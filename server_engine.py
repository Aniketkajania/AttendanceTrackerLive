"""
Multi-camera attendance engine - FAST version
=============================================

What changed vs. the old engine, and why
----------------------------------------
1. DECODING RUNS IN A SEPARATE ffmpeg PROCESS PER CAMERA.
   The old engine decoded RTSP inside this Python process, competing with the face models for
   CPU and the GIL. When the reader fell behind, packets were lost and ffmpeg printed
   "error while decoding MB ..." / "cabac decode of qscale diff failed". Now ffmpeg runs on its own,
   drops corrupt packets (+discardcorrupt), and hands us only DECODE_FPS frames per second.
   The aggressive "nobuffer" / "max_delay=0" options are gone (they cause the smeared frames).
   If ffmpeg is not installed the engine falls back to OpenCV automatically.

2. MOTION GATE. An empty gate costs almost nothing: the heavy detector only runs when the picture
   changes, when a face is being tracked, or once per IDLE_SCAN_SEC as a safety net.

3. LIGHT DETECTOR + HEAVY RECOGNIZER. Face finding uses the small SCRFD model (DETECTOR_PACK,
   default buffalo_s). Embeddings still come from FACE_MODEL (buffalo_l), so your enrolled
   vectors stay valid. Set DETECTOR_PACK=buffalo_l in .env to use the big detector again.

4. DATABASE + SNAPSHOT WRITES HAPPEN IN A BACKGROUND THREAD, so inference never waits on SQL Server.

5. ONNX sessions are created with thread spinning disabled and a capped thread count, which
   leaves CPU for the decoders.

6. A [STATS] line every 30 s shows decode fps, scan rate and ms per scan for each camera.

Optional .env knobs
-------------------
FACE_MODEL=buffalo_l        DETECTOR_PACK=buffalo_s       STREAM_BACKEND=auto|ffmpeg|opencv
DECODE_FPS=8                STREAM_MAX_WIDTH=1920         FFMPEG_HWACCEL=  (auto | cuda | d3d11va | qsv)
MOTION_GATE=1               ORT_THREADS=<n>               FFMPEG_BIN=C:\\path\\ffmpeg.exe
"""
import os

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"
# Used only by the OpenCV fallback reader. No nobuffer / max_delay: they let packets be dropped.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;discardcorrupt|stimeout;5000000"

import glob
import json
import platform
import queue
import shutil
import subprocess
import threading
import time
import types
from datetime import datetime
from urllib.parse import quote

import cv2
import numpy as np

import config as _cfg
from config import (
    SNAPSHOTS_DIR, SIMILARITY_THRESHOLD,
    COOLDOWN_SECONDS, DB_SYNC_INTERVAL, SHOW_PREVIEW as _SHOW_PREVIEW,
    ENGINE_DEVICE, GPU_MEM_LIMIT_MB,
)
from db import connect
from email_notifier import send_attendance_email_async
import face_pipeline as fp
from face_pipeline import (
    FaceFinder, FaceTracker, enhance_for_detection,
    CONFIRM_VOTES, STRONG_MARGIN, MATCH_MARGIN,
)

# Tracks survive a missed detection a little longer, because we now process ~8 frames/s, not 30.
fp.TRACK_TTL = float(os.getenv("UNCONFIRMED_TRACK_TTL", "2.0"))
fp.TRACK_TTL_CONFIRMED = float(os.getenv("CONFIRMED_TRACK_TTL", "2.5"))


# =====================================================================
# TUNING KNOBS
# =====================================================================
FACE_MODEL = getattr(_cfg, "FACE_MODEL", None) or os.getenv("FACE_MODEL", "buffalo_l")   # recognition (must match enrolment)
DETECTOR_PACK = os.getenv("DETECTOR_PACK", "buffalo_s")                                  # face finding (light = fast)

# ---- stream decoding ----
STREAM_BACKEND = os.getenv("STREAM_BACKEND", "auto").strip().lower()     # auto | ffmpeg | opencv
DECODE_FPS = float(os.getenv("DECODE_FPS", "8"))                         # frames/s handed to the engine
STREAM_MAX_WIDTH = int(os.getenv("STREAM_MAX_WIDTH", "1280"))            # larger frames are downscaled by ffmpeg
FFMPEG_HWACCEL = os.getenv("FFMPEG_HWACCEL", "").strip()                 # "", auto, cuda, d3d11va, qsv
STALL_SEC = 8.0                                                          # no frames for this long -> restart ffmpeg
RECONNECT_DELAY = 3.0

# ---- idle gating ----
MOTION_GATE = os.getenv("MOTION_GATE", "0").strip() == "1"
MOTION_SIZE = (320, 180)        # frame is shrunk to this for the motion check
MOTION_PIX_DELTA = 18           # grey-level change that counts as "moved"
MOTION_MIN_PIXELS = 30          # changed pixels (of 57,600) needed to wake the detector
IDLE_SCAN_SEC = 1.0             # safety scan interval when the scene looks static
BUSY_SEC = 1.5                  # keep scanning every frame this long after a face was last seen

# ---- engine ----
USE_INTEL_GPU = False
DET_SIZE = (640, 640)           # only used for model.prepare(); real detection sizes live in face_pipeline.py
INFER_EVERY = float(os.getenv("INFER_EVERY", "0.08"))
OVERLAY_TTL = 2.5
PREVIEW_MAX_WIDTH = 1280
SHOW_PREVIEW = _SHOW_PREVIEW
REVERIFY = 2.0                  # confirmed tracks are re-checked this often (seconds)
STATS_EVERY = 30                # seconds between [STATS] lines
MAX_FRAME_AGE = float(os.getenv("MAX_FRAME_AGE", "1.25"))
NEAR_RECOVERY_LIMIT = int(os.getenv("NEAR_RECOVERY_LIMIT", "1"))
ENABLE_ENHANCEMENT = os.getenv("ENABLE_ENHANCEMENT", "0").strip() == "1"
ORT_THREADS = int(os.getenv("ORT_THREADS", str(max(2, (os.cpu_count() or 4) // 2))))

CAMERA_ROIS: dict = {
    # "HO_IN": [(0.15, 0.05, 0.55, 0.85)]
}
TILE_GRID = None                # e.g. (3, 2)


# =====================================================================
# DB / CAMERA HELPERS
# =====================================================================
_tls = threading.local()


def get_db_connection():
    conn = connect()
    _tls.conn = conn            # remembered so a failed write can close it
    return conn


def build_camera_source(cam_row: dict):
    if cam_row["connection_type"] == "WEBCAM":
        return int(cam_row["webcam_index"] if cam_row["webcam_index"] is not None else 0)
    safe_user = quote(str(cam_row["username"] or ""), safe="")
    safe_pass = quote(str(cam_row["password"] or ""), safe="")
    ip = cam_row["ip_address"]
    port = cam_row["port"] or 554
    path = cam_row["rtsp_path"] or ""
    if path and not path.startswith("/"):
        path = "/" + path
    auth = f"{safe_user}:{safe_pass}@" if (safe_user and safe_pass) else ""
    return f"rtsp://{auth}{ip}:{port}{path}"


def mask_source(src):
    """Hide the password when printing an RTSP URL."""
    if isinstance(src, str) and "@" in src:
        return "rtsp://***@" + src.split("@", 1)[1]
    return src


# =====================================================================
# STREAM READERS
# =====================================================================
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _find_ffmpeg():
    exe = os.getenv("FFMPEG_BIN") or shutil.which("ffmpeg")
    if not exe:
        return None, None
    probe = os.getenv("FFPROBE_BIN")
    if not probe:
        d, base = os.path.split(exe)
        cand = os.path.join(d, base.replace("ffmpeg", "ffprobe")) if d else None
        probe = cand if (cand and os.path.exists(cand)) else shutil.which("ffprobe")
    return exe, probe


FFMPEG_BIN, FFPROBE_BIN = _find_ffmpeg()
USE_FFMPEG = STREAM_BACKEND in ("auto", "ffmpeg") and bool(FFMPEG_BIN and FFPROBE_BIN)


def backend_label():
    if USE_FFMPEG:
        return f"ffmpeg process ({FFMPEG_BIN})"
    if STREAM_BACKEND == "ffmpeg":
        return "opencv (STREAM_BACKEND=ffmpeg was requested but ffmpeg/ffprobe were not found)"
    return "opencv (ffmpeg/ffprobe not found - install ffmpeg for much better results)"


def _probe_size(url):
    """Ask ffprobe for the stream's width/height. Returns (w, h) or None if the camera is unreachable."""
    if not FFPROBE_BIN:
        return None
    cmd = [FFPROBE_BIN, "-v", "error"]
    if str(url).lower().startswith("rtsp"):
        cmd += ["-rtsp_transport", "tcp"]
    cmd += ["-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", url]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW).stdout
        line = out.strip().splitlines()[0].strip().strip(",")
        w, h = [int(x) for x in line.split(",")[:2]]
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


class FFmpegStream:
    """
    One ffmpeg process per camera. ffmpeg decodes everything, but only DECODE_FPS frames per second
    are converted to BGR and piped to us. A reader thread drains the pipe continuously and keeps only
    the newest frame, so ffmpeg is never blocked and the camera connection never backs up.
    """
    kind = "ffmpeg"

    def __init__(self, cam_config: dict):
        self.cam_config = cam_config
        self.camera_id = cam_config["camera_id"]
        self.source = build_camera_source(cam_config)
        self.latest_frame = None
        self.frame_ts = 0.0
        self.frames = 0
        self.lock = threading.Lock()
        self.running = True
        self.proc = None
        self.last_ok = 0.0
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._watchdog, daemon=True).start()

    # ---------- lifecycle ----------
    def _loop(self):
        while self.running:
            try:
                self._run_once()
            except Exception as e:
                print(f"[STREAM] {self.camera_id}: {type(e).__name__}: {e}")
            if self.running:
                time.sleep(RECONNECT_DELAY)

    def _run_once(self):
        size = _probe_size(self.source)
        if size is None:
            print(f"[STREAM] {self.camera_id}: cannot reach {mask_source(self.source)} "
                  f"- retrying in {RECONNECT_DELAY:.0f}s")
            return
        w, h = size
        ow = (min(w, STREAM_MAX_WIDTH) // 2) * 2
        oh = (int(round(h * ow / w)) // 2) * 2

        cmd = [FFMPEG_BIN, "-hide_banner", "-nostdin", "-loglevel", "error"]
        if str(self.source).lower().startswith("rtsp"):
            cmd += ["-rtsp_transport", "tcp"]
        cmd += ["-fflags", "+discardcorrupt", "-flags", "low_delay"]
        if FFMPEG_HWACCEL:
            cmd += ["-hwaccel", FFMPEG_HWACCEL]
        vf = f"fps={DECODE_FPS:g}"
        if (ow, oh) != (w, h):
            vf += f",scale={ow}:{oh}"
        cmd += ["-use_wallclock_as_timestamps", "1", "-i", self.source, "-an", "-sn", "-dn",
                "-vf", vf, "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]

        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0, creationflags=_NO_WINDOW)
        self.proc = proc
        self.last_ok = time.time()
        threading.Thread(target=self._drain_stderr, args=(proc,), daemon=True).start()
        print(f"[STREAM] {self.camera_id}: connected, camera {w}x{h} -> engine {ow}x{oh} @ {DECODE_FPS:g} fps "
              f"(if the camera size is small, point it at its MAIN stream)")

        nbytes = ow * oh * 3
        buf = bytearray(nbytes)
        view = memoryview(buf)
        try:
            while self.running:
                got = 0
                while got < nbytes:
                    n = proc.stdout.readinto(view[got:])
                    if not n:
                        return                      # ffmpeg exited or was killed -> reconnect
                    got += n
                frame = np.frombuffer(buf, np.uint8).reshape(oh, ow, 3).copy()
                now = time.time()
                with self.lock:
                    self.latest_frame = frame
                    self.frame_ts = now
                    self.frames += 1
                self.last_ok = now
        finally:
            self._terminate(proc)
            self.proc = None

    @staticmethod
    def _terminate(proc):
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=3)
        except Exception:
            pass
        try:
            proc.stdout.close()
        except Exception:
            pass

    def _drain_stderr(self, proc):
        """ffmpeg's warnings are counted and summarised instead of flooding the console."""
        count, window_start, last = 0, time.time(), ""
        try:
            for raw in iter(proc.stderr.readline, b""):
                count += 1
                last = raw.decode("utf-8", "ignore").strip()
                if time.time() - window_start > 30:
                    print(f"[STREAM] {self.camera_id}: decoder reported {count} warnings in 30s (last: {last[:90]})")
                    count, window_start = 0, time.time()
        except Exception:
            pass
        finally:
            if count:
                print(f"[STREAM] {self.camera_id}: decoder reported {count} warnings (last: {last[:90]})")
            try:
                proc.stderr.close()
            except Exception:
                pass

    def _watchdog(self):
        while self.running:
            time.sleep(2.0)
            proc = self.proc
            if proc is not None and proc.poll() is None and time.time() - self.last_ok > STALL_SEC:
                print(f"[STREAM] {self.camera_id}: no frames for {STALL_SEC:.0f}s, restarting")
                try:
                    proc.kill()
                except Exception:
                    pass
                self.last_ok = time.time()

    # ---------- API used by the engine ----------
    def get_latest_frame(self):
        with self.lock:
            if self.latest_frame is None:
                return None, 0.0
            return self.latest_frame, self.frame_ts      # never modified after publishing, so no copy

    def stop(self):
        self.running = False
        proc = self.proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass


class OpenCVStream:
    """Fallback reader (webcams, or when ffmpeg is not installed). Decodes in-process, so it is less robust."""
    kind = "opencv"

    def __init__(self, cam_config: dict):
        self.cam_config = cam_config
        self.camera_id = cam_config["camera_id"]
        self.source = build_camera_source(cam_config)
        self.latest_frame = None
        self.frame_ts = 0.0
        self.frames = 0
        self.lock = threading.Lock()
        self.running = True
        self._logged_size = False
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    def _open(self):
        if isinstance(self.source, int):
            cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW) if platform.system() == "Windows" else cv2.VideoCapture(self.source)
        else:
            cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def _reader_loop(self):
        cap, fails, last_retr = None, 0, 0.0
        period = 1.0 / max(DECODE_FPS, 0.5)
        while self.running:
            if cap is None:
                cap = self._open()
                if not cap.isOpened():
                    print(f"[STREAM] {self.camera_id}: cannot open {mask_source(self.source)} "
                          f"- retrying in {RECONNECT_DELAY:.0f}s")
                    cap.release()
                    cap = None
                    time.sleep(RECONNECT_DELAY)
                    continue
                print(f"[STREAM] {self.camera_id}: connected (opencv)")
                fails = 0

            # grab() keeps the stream moving; retrieve() (the costly colour conversion) only at DECODE_FPS
            if not cap.grab():
                fails += 1
                if fails > 100:
                    print(f"[STREAM] {self.camera_id}: stream lost, reconnecting")
                    cap.release()
                    cap = None
                    time.sleep(RECONNECT_DELAY)
                else:
                    time.sleep(0.02)
                continue
            fails = 0
            t = time.time()
            if t - last_retr < period:
                continue
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                continue
            last_retr = t
            h, w = frame.shape[:2]
            if not self._logged_size:
                print(f"[STREAM] {self.camera_id}: receiving {w}x{h}")
                self._logged_size = True
            if w > STREAM_MAX_WIDTH:
                frame = cv2.resize(frame, (STREAM_MAX_WIDTH, int(h * STREAM_MAX_WIDTH / w)), interpolation=cv2.INTER_AREA)
            with self.lock:
                self.latest_frame = frame
                self.frame_ts = t
                self.frames += 1

        if cap is not None:
            cap.release()

    def get_latest_frame(self):
        with self.lock:
            if self.latest_frame is None:
                return None, 0.0
            return self.latest_frame, self.frame_ts

    def stop(self):
        self.running = False


def make_stream(cam_config: dict):
    src = build_camera_source(cam_config)
    if isinstance(src, str) and USE_FFMPEG:
        return FFmpegStream(cam_config)
    return OpenCVStream(cam_config)


# =====================================================================
# SNAPSHOT + ATTENDANCE LOGIC (unchanged behaviour)
# =====================================================================
def save_gate_snapshot(frame, bbox, employee_id: str, location: str, tag: str) -> str:
    today_str = datetime.now().strftime("%Y-%m-%d")
    day_dir = os.path.join(SNAPSHOTS_DIR, today_str)
    os.makedirs(day_dir, exist_ok=True)

    h, w, _ = frame.shape
    x1, y1, x2, y2 = map(int, bbox)
    pad_w = int((x2 - x1) * 0.4)
    pad_h = int((y2 - y1) * 0.4)
    cx1, cy1 = max(0, x1 - pad_w), max(0, y1 - pad_h)
    cx2, cy2 = min(w, x2 + pad_w), min(h, y2 + pad_h)

    crop = frame[cy1:cy2, cx1:cx2].copy()
    ts_str = datetime.now().strftime("%H:%M:%S")
    cv2.putText(crop, f"{employee_id} | {location} {tag} | {ts_str}", (8, crop.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 0), 1, cv2.LINE_AA)

    filename = f"{employee_id}_{location}_{tag}_{datetime.now().strftime('%H%M%S')}.jpg"
    filepath = os.path.join(day_dir, filename)
    cv2.imwrite(filepath, crop, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return filepath


def process_strict_in_out_event(user: dict, cam_config: dict, confidence: float, frame, bbox):
    """
    Processes a verified face against strict camera_role ('IN' or 'OUT'):
    - Triggers email on FIRST CHECK-IN of the day.
    - Triggers email on EVERY valid CHECK-OUT ('OUT' camera).
    """
    emp_id = user["employee_id"]
    name = user["person_name"]
    email = user["email"]
    base_loc = user["base_location"]

    cam_id = cam_config["camera_id"]
    cam_loc = cam_config["location"]
    cam_role = cam_config["camera_role"]  # Strictly 'IN' or 'OUT'

    now_dt = datetime.now()
    work_date_str = now_dt.strftime("%Y-%m-%d")
    now_ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM daily_attendance
        WHERE employee_id = ? AND work_date = ?
    """, (emp_id, work_date_str))
    summary = cursor.fetchone()

    email_payload = None
    snapshot_path = None

    # ==========================================================
    # CASE 1: NO RECORD TODAY YET
    # ==========================================================
    if not summary:
        if cam_role == "IN":
            snapshot_path = save_gate_snapshot(frame, bbox, emp_id, cam_loc, "FIRST_IN")
            visited_str = cam_loc

            cursor.execute("""
                INSERT INTO daily_attendance (
                    employee_id, person_name, base_location, work_date,
                    first_check_in, first_check_in_camera, first_check_in_location, first_check_in_image,
                    current_status, current_location, visited_locations,
                    last_event_time, total_checks, out_of_office_hours, total_working_hours
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'IN', ?, ?, ?, 1, 0.0, 0.0)
            """, (emp_id, name, base_loc, work_date_str, now_ts_str, cam_id, cam_loc, snapshot_path,
                  cam_loc, visited_str, now_ts_str))

            print(f"\n[FIRST CHECK-IN] {name} ({emp_id}) at {cam_loc} ({cam_id}) | {now_ts_str}")

            email_payload = {
                "email": email,
                "person_name": name,
                "employee_id": emp_id,
                "event_title": "FIRST CHECK-IN",
                "event_type": "IN",
                "event_time": now_ts_str,
                "camera_id": cam_id,
                "camera_location": cam_loc,
                "first_check_in": now_ts_str,
                "first_check_in_location": cam_loc,
                "last_check_out": None,
                "visited_locations": visited_str,
                "total_checks": 1,
                "out_of_office_hours": 0.0,
                "total_working_hours": 0.0,
                "snapshot_path": snapshot_path
            }
        else:
            # Employee walked past OUT camera without checking IN first today
            snapshot_path = save_gate_snapshot(frame, bbox, emp_id, cam_loc, "UNMATCHED_OUT")
            visited_str = cam_loc
            cursor.execute("""
                INSERT INTO daily_attendance (
                    employee_id, person_name, base_location, work_date,
                    last_check_out, last_check_out_camera, last_check_out_location, last_check_out_image,
                    current_status, current_location, visited_locations,
                    last_event_time, total_checks, out_of_office_hours, total_working_hours
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OUT', ?, ?, ?, 1, 0.0, 0.0)
            """, (emp_id, name, base_loc, work_date_str, now_ts_str, cam_id, cam_loc, snapshot_path,
                  cam_loc, visited_str, now_ts_str))

            print(f"\n[CHECK-OUT (NO PRIOR IN)] {name} ({emp_id}) at {cam_loc} ({cam_id}) | {now_ts_str}")

            email_payload = {
                "email": email,
                "person_name": name,
                "employee_id": emp_id,
                "event_title": "CHECK-OUT",
                "event_type": "OUT",
                "event_time": now_ts_str,
                "camera_id": cam_id,
                "camera_location": cam_loc,
                "first_check_in": "Not Recorded",
                "first_check_in_location": "-",
                "last_check_out": f"{now_ts_str} ({cam_loc})",
                "visited_locations": visited_str,
                "total_checks": 1,
                "out_of_office_hours": 0.0,
                "total_working_hours": 0.0,
                "snapshot_path": snapshot_path
            }

    # ==========================================================
    # CASE 2: RECORD ALREADY EXISTS FOR TODAY
    # ==========================================================
    else:
        prev_status = summary["current_status"]
        last_time_dt = datetime.strptime(summary["last_event_time"], "%Y-%m-%d %H:%M:%S")
        delta_hours = max(0.0, (now_dt - last_time_dt).total_seconds() / 3600.0)

        total_checks = summary["total_checks"] + 1
        work_hrs = float(summary["total_working_hours"])
        ooo_hrs = float(summary["out_of_office_hours"])

        # Update visited_locations breadcrumb if roaming to a new site
        visited_list = [loc.strip() for loc in (summary["visited_locations"] or "").split("->") if loc.strip()]
        if not visited_list or visited_list[-1] != cam_loc:
            visited_list.append(cam_loc)
        visited_str = " -> ".join(visited_list)

        if cam_role == "OUT":
            # ----------------------------------------------------
            # CHECK-OUT CAMERA TRIGGERED
            # ----------------------------------------------------
            snapshot_path = save_gate_snapshot(frame, bbox, emp_id, cam_loc, "LAST_OUT")

            if prev_status == "IN":
                work_hrs = round(work_hrs + delta_hours, 4)

            cursor.execute("""
                UPDATE daily_attendance SET
                    last_check_out = ?,
                    last_check_out_camera = ?,
                    last_check_out_location = ?,
                    last_check_out_image = ?,
                    current_status = 'OUT',
                    current_location = ?,
                    visited_locations = ?,
                    last_event_time = ?,
                    total_checks = ?,
                    total_working_hours = ?
                WHERE employee_id = ? AND work_date = ?
            """, (now_ts_str, cam_id, cam_loc, snapshot_path, cam_loc, visited_str,
                  now_ts_str, total_checks, work_hrs, emp_id, work_date_str))

            print(f"\n[CHECK-OUT] {name} ({emp_id}) exited at {cam_loc} ({cam_id}) | Total Work: {work_hrs:.2f} hrs")

            # ALWAYS trigger email on every OUT event
            email_payload = {
                "email": email,
                "person_name": name,
                "employee_id": emp_id,
                "event_title": "CHECK-OUT",
                "event_type": "OUT",
                "event_time": now_ts_str,
                "camera_id": cam_id,
                "camera_location": cam_loc,
                "first_check_in": summary["first_check_in"] or "Not Recorded",
                "first_check_in_location": summary["first_check_in_location"] or "-",
                "last_check_out": f"{now_ts_str} ({cam_loc})",
                "visited_locations": visited_str,
                "total_checks": total_checks,
                "out_of_office_hours": ooo_hrs,
                "total_working_hours": work_hrs,
                "snapshot_path": snapshot_path
            }

        elif cam_role == "IN":
            # ----------------------------------------------------
            # CHECK-IN CAMERA TRIGGERED (RE-ENTRY OR TERMINAL VISIT)
            # ----------------------------------------------------
            snapshot_path = save_gate_snapshot(frame, bbox, emp_id, cam_loc, "RE_IN")

            if prev_status == "OUT":
                ooo_hrs = round(ooo_hrs + delta_hours, 4)

            # Backfill first_check_in only if their very first punch today was an unmatched OUT
            first_in = summary["first_check_in"] or now_ts_str
            first_in_cam = summary["first_check_in_camera"] or cam_id
            first_in_loc = summary["first_check_in_location"] or cam_loc
            first_in_img = summary["first_check_in_image"] or snapshot_path

            cursor.execute("""
                UPDATE daily_attendance SET
                    first_check_in = ?,
                    first_check_in_camera = ?,
                    first_check_in_location = ?,
                    first_check_in_image = ?,
                    current_status = 'IN',
                    current_location = ?,
                    visited_locations = ?,
                    last_event_time = ?,
                    total_checks = ?,
                    out_of_office_hours = ?
                WHERE employee_id = ? AND work_date = ?
            """, (first_in, first_in_cam, first_in_loc, first_in_img, cam_loc, visited_str,
                  now_ts_str, total_checks, ooo_hrs, emp_id, work_date_str))

            print(f"\n[RE-ENTRY IN] {name} ({emp_id}) entered {cam_loc} ({cam_id}) | Out-of-Office: {ooo_hrs:.2f} hrs")
            # Note: No email on intermediate re-entries; only on First IN and Every OUT.

    # Always append to immutable attendance_logs table
    cursor.execute("""
        INSERT INTO attendance_logs (
            employee_id, person_name, camera_id, camera_location,
            work_date, event_type, event_timestamp, confidence_score, snapshot_image
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (emp_id, name, cam_id, cam_loc, work_date_str, cam_role, now_ts_str, round(confidence, 4), snapshot_path))

    conn.commit()
    conn.close()

    if email_payload:
        send_attendance_email_async(email_payload)


class EventWriter(threading.Thread):
    """Records punches (SQL + snapshot + email) off the inference thread, so recognition never waits on the DB."""

    def __init__(self, events: "queue.Queue"):
        super().__init__(daemon=True)
        self.events = events
        self.running = True

    def run(self):
        while self.running or not self.events.empty():
            try:
                item = self.events.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                process_strict_in_out_event(*item)
            except Exception as e:
                print(f"[EVENTS] failed to record a punch: {type(e).__name__}: {e}")
                conn = getattr(_tls, "conn", None)      # do not leak the half-used connection
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    def stop(self):
        self.running = False


def load_users_and_cameras():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT employee_id, person_name, email, base_location, face_embedding FROM users WHERE is_active = 1")
    users = []
    for r in cursor.fetchall():
        users.append({
            "employee_id": r["employee_id"],
            "person_name": r["person_name"],
            "email": r["email"],
            "base_location": r["base_location"],
            "embedding": np.array(json.loads(r["face_embedding"]), dtype=np.float32)
        })

    cursor.execute("SELECT * FROM cameras WHERE is_active = 1")
    cameras = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return users, cameras


def make_user_state(users: list):
    """Pack users + a stacked embedding matrix so matching is a single matrix multiply."""
    matrix = np.stack([u["embedding"] for u in users]) if users else np.zeros((0, 512), dtype=np.float32)
    return {"users": users, "matrix": matrix}


# =====================================================================
# FACE MODELS  (light detector + FACE_MODEL recognizer, CUDA / DirectML / CPU)
# =====================================================================
def _model_dir(pack: str) -> str:
    from insightface.utils.storage import ensure_available
    return ensure_available("models", pack, root="~/.insightface")


def _pick_onnx(pack_dir: str, prefixes: tuple) -> str:
    for f in sorted(glob.glob(os.path.join(pack_dir, "*.onnx"))):
        if os.path.basename(f).lower().startswith(prefixes):
            return f
    raise RuntimeError(f"no model starting with {prefixes} in {pack_dir}")


def _make_session(path: str, providers):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.log_severity_level = 3
    so.intra_op_num_threads = ORT_THREADS
    try:
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")   # no busy-waiting between calls
    except Exception:
        pass
    return ort.InferenceSession(path, sess_options=so, providers=providers)


def _load_onnx(path: str, providers, kind: str):
    from insightface.model_zoo import model_zoo
    try:
        from insightface.model_zoo.scrfd import SCRFD
        from insightface.model_zoo.arcface_onnx import ArcFaceONNX
        sess = _make_session(path, providers)
        return (SCRFD if kind == "detection" else ArcFaceONNX)(model_file=path, session=sess)
    except Exception as e:
        print(f"[ENGINE] tuned session failed for {os.path.basename(path)} ({type(e).__name__}: {e}); using default loader")
        return model_zoo.get_model(path, providers=providers)


def load_models(providers, ctx_id):
    from insightface.app.common import Face

    try:
        det_path = _pick_onnx(_model_dir(DETECTOR_PACK), ("det_", "scrfd"))
    except Exception as e:
        print(f"[ENGINE] detector pack '{DETECTOR_PACK}' unavailable ({e}); using the {FACE_MODEL} detector")
        det_path = _pick_onnx(_model_dir(FACE_MODEL), ("det_", "scrfd"))
    rec_path = _pick_onnx(_model_dir(FACE_MODEL), ("w600k", "glintr", "arcface"))

    det = _load_onnx(det_path, providers, "detection")
    rec = _load_onnx(rec_path, providers, "recognition")
    if getattr(det, "taskname", "") != "detection" or getattr(rec, "taskname", "") != "recognition":
        raise RuntimeError("unexpected model type was loaded")

    det.prepare(ctx_id, input_size=DET_SIZE, det_thresh=0.5)
    rec.prepare(ctx_id)

    # warm-up pass so the first real face is not slow
    kps = np.array([[260, 200], [380, 200], [320, 260], [285, 320], [355, 320]], np.float32)
    rec.get(np.zeros((480, 640, 3), np.uint8), Face(bbox=np.zeros(4, np.float32), kps=kps, det_score=1.0))
    print(f"[ENGINE] detector: {os.path.basename(det_path)} | recognizer: {os.path.basename(rec_path)}")
    return types.SimpleNamespace(models={"detection": det, "recognition": rec})


def build_face_app():
    import onnxruntime as ort
    available = ort.get_available_providers()
    print(f"[ENGINE] ONNX Runtime providers available: {available}")

    attempts = []
    if ENGINE_DEVICE != "cpu":
        if "CUDAExecutionProvider" in available:
            cuda_opts = {
                "gpu_mem_limit": GPU_MEM_LIMIT_MB * 1024 * 1024,
                "arena_extend_strategy": "kSameAsRequested",
                "cudnn_conv_algo_search": "HEURISTIC",
            }
            attempts.append(([("CUDAExecutionProvider", cuda_opts), "CPUExecutionProvider"], 0,
                             f"NVIDIA CUDA (limit {GPU_MEM_LIMIT_MB} MB)"))
        if USE_INTEL_GPU and "DmlExecutionProvider" in available:
            attempts.append((["DmlExecutionProvider", "CPUExecutionProvider"], 0, "DirectML (Intel/AMD GPU)"))
    if ENGINE_DEVICE != "gpu":
        attempts.append((["CPUExecutionProvider"], -1, f"CPU ({ORT_THREADS} threads)"))

    last_err = None
    for providers, ctx_id, label in attempts:
        try:
            print(f"[ENGINE] Loading detector={DETECTOR_PACK} + recognizer={FACE_MODEL} on {label}...")
            app = load_models(providers, ctx_id)
            print(f"[ENGINE] Using {label}.")
            return app
        except Exception as e:
            last_err = e
            print(f"[ENGINE] {label} failed ({type(e).__name__}: {e}). Falling back...")
    raise RuntimeError(f"Could not initialise the face models: {last_err}")


# =====================================================================
# RECOGNITION WORKER (runs separately from the preview loop)
# =====================================================================
class InferenceWorker(threading.Thread):
    """
    Per camera, per new frame:
        motion gate -> (enhance if dark) -> detect -> track -> quality-gate ->
        embed (raw frame) -> fuse over frames -> vote -> queue the punch for the EventWriter.
    """
    def __init__(self, face_app, streams: dict, state_holder: dict, events: "queue.Queue"):
        super().__init__(daemon=True)
        self.finder = FaceFinder(face_app)
        self.finder.warmup()
        self.streams = streams
        self.state_holder = state_holder
        self.events = events
        self.trackers = {}
        self.overlays = {}
        self.overlay_lock = threading.Lock()
        self.cooldown_tracker = {}        # (employee_id, camera_role) -> last event epoch
        self.last_frame_ts = {}
        self.last_infer = {}
        self.prev_small = {}              # camera_id -> previous small grey frame (motion gate)
        self.last_full = {}               # camera_id -> time of the last full scan
        self.stats = {}                   # camera_id -> {"seen", "scanned", "ms"}
        self.timing = {}
        self.running = True

    # ---------- preview side ----------
    def get_overlays(self, cid):
        with self.overlay_lock:
            item = self.overlays.get(cid)
        if not item:
            return []
        ts, tracks = item
        now = time.time()
        if now - ts > OVERLAY_TTL:
            return []
        out = []
        for bbox, vel, last_seen, color, label in tracks:
            b = bbox + vel * min(max(now - last_seen, 0.0), 0.4)
            out.append((int(b[0]), int(b[1]), int(b[2]), int(b[3]), color, label))
        return out

    def pop_stats(self):
        out, self.stats = self.stats, {}
        return out

    # ---------- worker loop ----------
    def run(self):
        while self.running:
            did_work = False
            streams = sorted(list(self.streams.items()), key=lambda item: self.last_infer.get(item[0], 0.0))
            for cid, stream in streams:
                now = time.time()
                if now - self.last_infer.get(cid, 0.0) < INFER_EVERY:
                    continue
                frame, fts = stream.get_latest_frame()
                if frame is None or fts == self.last_frame_ts.get(cid) or now - fts > MAX_FRAME_AGE:
                    continue
                self.last_frame_ts[cid] = fts
                self.last_infer[cid] = now

                t0 = time.time()
                ran = False
                try:
                    ran = self._analyze(frame, stream.cam_config, cid, now)
                except Exception as e:
                    print(f"[INFER] {cid} error: {type(e).__name__}: {e}")
                dt = time.time() - t0

                st = self.stats.setdefault(cid, {"seen": 0, "scanned": 0, "ms": 0.0, "frame_age_ms": 0.0})
                st["seen"] += 1
                st["frame_age_ms"] += max(0.0, now - fts) * 1000.0
                if ran:
                    st["scanned"] += 1
                    st["ms"] += dt * 1000.0
                    if dt > 0.6:
                        print(f"[SLOW] {cid}: one scan took {dt:.2f}s")
                did_work = True
            if not did_work:
                time.sleep(0.005)

    # ---------- motion gate ----------
    def _motion(self, cid, gray):
        small = cv2.GaussianBlur(gray, (5, 5), 0)
        prev = self.prev_small.get(cid)
        self.prev_small[cid] = small
        if prev is None or prev.shape != small.shape:
            return True
        diff = cv2.absdiff(small, prev)
        return int(np.count_nonzero(diff > MOTION_PIX_DELTA)) > MOTION_MIN_PIXELS

    # ---------- one frame ----------
    def _analyze(self, frame, cam_cfg, cid, now):
        """Returns True if a full detection pass ran, False if the frame was skipped as idle."""
        state = self.state_holder["state"]
        users, matrix = state["users"], state["matrix"]
        cam_role = cam_cfg["camera_role"]
        tracker = self.trackers.setdefault(cid, FaceTracker())

        gray = cv2.cvtColor(cv2.resize(frame, MOTION_SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)

        if MOTION_GATE:
            moving = self._motion(cid, gray)
            busy = any(now - t.last_seen < BUSY_SEC for t in tracker.tracks)
            if not moving and not busy and now - self.last_full.get(cid, 0.0) < IDLE_SCAN_SEC:
                tracker.update([], now)                 # just expires old tracks
                self._publish(cid, tracker, cam_role, now)
                return False
        self.last_full[cid] = now

        # enhancement (LAB conversion) only when the scene really is dark / blown out / flat
        if ENABLE_ENHANCEMENT:
            mean, std = float(gray.mean()), float(gray.std())
            det_frame = frame if (95 <= mean <= 165 and std >= 40) else enhance_for_detection(frame)
        else:
            det_frame = frame
        detect_start = time.perf_counter()
        dets = self.finder.detect(det_frame, rois=CAMERA_ROIS.get(cid), tile_grid=TILE_GRID)
        tm = self.timing.setdefault(cid, {"detect_ms": 0.0, "embed_ms": 0.0, "embeds": 0, "detects": 0})
        tm["detect_ms"] += (time.perf_counter() - detect_start) * 1000
        tm["detects"] += 1

        for track, det in tracker.update(dets, now):
            self._process(track, det, frame, cam_cfg, users, matrix, now)

        # faces we were following but the full pass missed: look right where they were
        recovery_attempts = 0
        for t in tracker.tracks:
            if t.matched_now or recovery_attempts >= NEAR_RECOVERY_LIMIT:
                continue
            recovery_attempts += 1
            d = self.finder.detect_near(det_frame, t.display_box(now))
            if d is not None:
                t.update(d["bbox"], now)
                self._process(t, d, frame, cam_cfg, users, matrix, now)

        self._publish(cid, tracker, cam_role, now)
        return True

    def _publish(self, cid, tracker, cam_role, now):
        if not SHOW_PREVIEW:                            # overlays are only needed for the preview window
            return
        snapshot = []
        for t in tracker.tracks:
            self._refresh_label(t, cam_role, now)
            snapshot.append((t.bbox.copy(), t.vel.copy(), t.last_seen, t.color, t.label))
        with self.overlay_lock:
            self.overlays[cid] = (time.time(), snapshot)

    # ---------- identity for one tracked face ----------
    def _process(self, track, det, frame, cam_cfg, users, matrix, now):
        # confirmed and checked recently: nothing to do (skip even the quality check)
        if track.confirmed_id is not None and (now - track.last_verify) < REVERIFY:
            return

        ok, reason, m, q = self.finder.assess(frame, det["bbox"], det["kps"], det["score"])
        if not ok:
            if track.confirmed_id is None:
                track.label, track.color = "Unknown", (0, 0, 255)
            return

        if not len(users):
            track.label, track.color = "Unknown", (0, 0, 255)
            return

        embed_start = time.perf_counter()
        emb = self.finder.embed(frame, det["kps"], det["bbox"], det["score"])
        tm = self.timing.setdefault(cam_cfg["camera_id"], {"detect_ms": 0.0, "embed_ms": 0.0, "embeds": 0, "detects": 0})
        tm["embed_ms"] += (time.perf_counter() - embed_start) * 1000
        tm["embeds"] += 1
        track.embs.append((emb, q))
        track.good_samples += 1
        track.last_verify = now

        if q > track.best_q:
            track.best_q, track.best_frame, track.best_bbox = q, frame, det["bbox"].copy()

        fused = track.fused_embedding()
        scores = matrix @ fused
        order = np.argsort(scores)[::-1]
        s1 = float(scores[order[0]])
        s2 = float(scores[order[1]]) if len(order) > 1 else -1.0
        best = users[int(order[0])]
        margin_ok = (len(order) < 2) or ((s1 - s2) >= MATCH_MARGIN)
        matched = (s1 >= SIMILARITY_THRESHOLD) and margin_ok

        # ---- already confirmed: re-verification ----
        if track.confirmed_id is not None:
            if matched and best["employee_id"] == track.confirmed_id:
                track.disagree = 0
                track.confirmed_score = s1
                self._record(track, best, cam_cfg, s1, frame, det["bbox"], now)
            else:
                track.disagree += 1
                if track.disagree >= 2:
                    track.reset_identity()
                    track.label, track.color = "Unknown", (0, 0, 255)
            return

        # ---- not confirmed yet: vote over frames ----
        track.votes.append(best["employee_id"] if matched else None)
        cnt = sum(1 for v in track.votes if v == best["employee_id"]) if matched else 0
        strong = matched and s1 >= SIMILARITY_THRESHOLD + STRONG_MARGIN

        if matched and (cnt >= CONFIRM_VOTES or strong):
            track.confirmed_id = best["employee_id"]
            track.confirmed_name = best["person_name"]
            track.confirmed_score = s1
            track.disagree = 0
            self._record(track, best, cam_cfg, s1, track.best_frame, track.best_bbox, now)
            track.label, track.color = f"{best['person_name']} ({s1:.2f})", (0, 255, 0)
        elif matched:
            track.label, track.color = f"{best['person_name']} ({s1:.2f})", (0, 255, 0)
        else:
            track.label, track.color = f"Unknown ({s1:.2f})", (0, 0, 255)

    def _record(self, track, user, cam_cfg, score, frame, bbox, now):
        key = (user["employee_id"], cam_cfg["camera_role"])
        if now - self.cooldown_tracker.get(key, 0.0) > COOLDOWN_SECONDS:
            self.cooldown_tracker[key] = now
            track.recorded_at = now
            try:
                self.events.put_nowait((user, dict(cam_cfg), score, frame, np.array(bbox, copy=True)))
            except queue.Full:
                self.cooldown_tracker.pop(key, None)    # allow a retry on the next sighting
                print("[EVENTS] queue full, punch not recorded (will retry on next sighting)")

    def _refresh_label(self, track, cam_role, now):
        """Overrides any cooldown or system text to strictly show Name (Score)."""
        if track.confirmed_id is None:
            return
        track.color, track.label = (0, 255, 0), f"{track.confirmed_name} ({track.confirmed_score:.2f})"

    def stop(self):
        self.running = False


# =====================================================================
# PREVIEW
# =====================================================================
def render_preview(frame, boxes, cid, cam_cfg):
    """Shrink the frame to fit the screen, THEN draw (so text stays sharp and boxes scale correctly)."""
    h, w = frame.shape[:2]
    scale = 1.0 if w <= PREVIEW_MAX_WIDTH else PREVIEW_MAX_WIDTH / w
    disp = frame.copy() if scale == 1.0 else cv2.resize(frame, (int(w * scale), int(h * scale)))

    for (x1, y1, x2, y2, color, label) in boxes:
        sx1, sy1, sx2, sy2 = int(x1 * scale), int(y1 * scale), int(x2 * scale), int(y2 * scale)
        cv2.rectangle(disp, (sx1, sy1), (sx2, sy2), color, 2)
        cv2.putText(disp, label, (sx1, max(25, sy1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

    cv2.putText(disp, f"{cid} | Loc: {cam_cfg['location']} | Role: {cam_cfg['camera_role']}", (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2, cv2.LINE_AA)
    return disp


# =====================================================================
# MAIN
# =====================================================================
def main():
    import signal
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    cv2.setNumThreads(2)            # OpenCV's own thread pool must not fight the models for cores

    print(f"[ENGINE] recognizer={FACE_MODEL}  detector={DETECTOR_PACK}  motion gate={'on' if MOTION_GATE else 'off'}")
    print(f"[ENGINE] stream backend: {backend_label()}")
    face_app = build_face_app()

    users, active_cameras = load_users_and_cameras()
    print(f"[ENGINE] Loaded {len(users)} employee(s) and {len(active_cameras)} active camera(s).")
    state_holder = {"state": make_user_state(users)}

    events: "queue.Queue" = queue.Queue(maxsize=200)
    writer = EventWriter(events)
    writer.start()

    stream_threads: dict = {}
    for cam in active_cameras:
        cid = cam["camera_id"]
        stream_threads[cid] = make_stream(cam)
        print(f"[STREAM STARTED] {cid} ({cam['location']} - Role: {cam['camera_role']})")

    worker = InferenceWorker(face_app, stream_threads, state_holder, events)
    worker.start()

    last_db_sync = time.time()
    last_stats = time.time()
    prev_frames: dict = {}
    open_windows: set = set()

    print("\n[RUNNING] Multi-Camera Attendance Engine is live. Press 'q' in a preview window (or Ctrl+C) to stop.\n")

    try:
        while True:
            now_epoch = time.time()

            # Periodically sync new employees or camera changes from DB without restarting
            if (now_epoch - last_db_sync) > DB_SYNC_INTERVAL:
                last_db_sync = now_epoch
                try:
                    users, latest_cameras = load_users_and_cameras()
                except Exception as e:
                    print(f"[ENGINE] DB sync failed ({type(e).__name__}: {e}); keeping current data, will retry")
                else:
                    state_holder["state"] = make_user_state(users)
                    latest_ids = {c["camera_id"] for c in latest_cameras}

                    for cam in latest_cameras:
                        cid = cam["camera_id"]
                        if cid not in stream_threads:
                            stream_threads[cid] = make_stream(cam)
                            print(f"[STREAM ADDED] {cid} ({cam['location']} - Role: {cam['camera_role']})")
                        elif build_camera_source(cam) != stream_threads[cid].source:
                            stream_threads[cid].stop()
                            stream_threads[cid] = make_stream(cam)
                            print(f"[STREAM RESTARTED] {cid} (connection details changed)")
                        else:
                            stream_threads[cid].cam_config = cam

                    for cid in list(stream_threads.keys()):
                        if cid not in latest_ids:
                            stream_threads[cid].stop()
                            del stream_threads[cid]
                            if cid in open_windows:
                                cv2.destroyWindow(f"Camera Feed - {cid}")
                                open_windows.discard(cid)
                            print(f"[STREAM STOPPED] {cid}")

            # Health line: decode fps, scan rate and cost per scan
            if (now_epoch - last_stats) > STATS_EVERY:
                dt = now_epoch - last_stats
                last_stats = now_epoch
                st = worker.pop_stats()
                timing = worker.timing
                worker.timing = {}
                parts = []
                for cid, s in list(stream_threads.items()):
                    fr = s.frames
                    fps_in = (fr - prev_frames.get(cid, 0)) / dt
                    prev_frames[cid] = fr
                    w = st.get(cid, {"seen": 0, "scanned": 0, "ms": 0.0})
                    avg = w["ms"] / w["scanned"] if w["scanned"] else 0.0
                    age = w.get("frame_age_ms", 0.0) / w["seen"] if w["seen"] else 0.0
                    tm = timing.get(cid, {})
                    detect_avg = tm.get("detect_ms", 0.0) / max(1, tm.get("detects", 0))
                    embed_avg = tm.get("embed_ms", 0.0) / max(1, tm.get("embeds", 0))
                    parts.append(f"{cid}: in {fps_in:.1f} fps | scanned {w['scanned'] / dt:.1f}/s of {w['seen'] / dt:.1f}/s | {avg:.0f} ms/scan | {age:.0f} ms frame age | detect {detect_avg:.0f} ms | embed {embed_avg:.0f} ms ({tm.get('embeds', 0)} faces)")
                if parts:
                    print("[STATS] " + "   ||   ".join(parts))

            # Preview only - recognition happens in the worker thread, so this never blocks on the model
            if SHOW_PREVIEW:
                for cid, stream in list(stream_threads.items()):
                    frame, _ = stream.get_latest_frame()
                    if frame is None:
                        continue
                    win = f"Camera Feed - {cid}"
                    if cid not in open_windows:
                        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
                        open_windows.add(cid)
                    cv2.imshow(win, render_preview(frame, worker.get_overlays(cid), cid, stream.cam_config))

                if cv2.waitKey(30) & 0xFF == ord("q"):
                    break
            else:
                time.sleep(0.25)

    except KeyboardInterrupt:
        print("\n[ENGINE] Stopping server engine...")
    finally:
        worker.stop()
        for stream in stream_threads.values():
            stream.stop()
        writer.stop()
        writer.join(timeout=5)          # let queued punches finish writing
        cv2.destroyAllWindows()
        print("[ENGINE] Cleanly exited.")


if __name__ == "__main__":
    main()