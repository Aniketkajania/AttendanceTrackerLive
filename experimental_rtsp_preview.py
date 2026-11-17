"""Isolated RTSP detection preview. Does not import SQL, config or server_engine.

Reads RTSP and draws face detections only. No identity recognition, snapshots,
attendance events or persistent logs. Run on an authorized workstation.
"""
import getpass
import glob
import os
import threading
import time
from urllib.parse import quote

import cv2
import numpy as np

from face_pipeline import FaceTracker, sharpness, yaw_proxy


class LatestCamera:
    """Decode on a dedicated thread so AI processing never blocks RTSP capture."""
    def __init__(self, uri):
        self.uri = uri
        self.lock = threading.Lock()
        self.frame = None
        self.timestamp = 0.0
        self.running = True
        self.connected = False
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def _read_loop(self):
        while self.running:
            # OpenCV uses FFmpeg when available in the wheel.
            cap = cv2.VideoCapture(self.uri, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                cap.release()
                print("[RTSP] Camera unavailable; retrying without logging credentials", flush=True)
                time.sleep(2)
                continue
            self.connected = True
            print("[RTSP] Connected", flush=True)
            try:
                while self.running:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    with self.lock:
                        self.frame, self.timestamp = frame, time.monotonic()
            finally:
                cap.release()
                self.connected = False
            if self.running:
                time.sleep(1)

    def latest(self):
        with self.lock:
            return self.frame, self.timestamp

    def stop(self):
        self.running = False
        self.thread.join(timeout=3)


def make_uri(host, port, path, username):
    # Prompt for password rather than putting it in shell history or git.
    password = getpass.getpass("Camera RTSP password: ") if username else ""
    auth = (quote(username, safe="") + ":" + quote(password, safe="") + "@") if username else ""
    return f"rtsp://{auth}{host}:{port}/{path.lstrip('/')}"


def load_detector():
    from insightface.model_zoo import get_model
    from insightface.utils.storage import ensure_available

    pack = os.getenv("EXPERIMENT_DETECTOR_PACK", "buffalo_s")
    if not pack.replace("_", "").isalnum():
        raise ValueError("Invalid detector pack name")
    folder = ensure_available("models", pack, root=os.path.expanduser("~/.insightface"))
    candidates = sorted(glob.glob(os.path.join(folder, "det_*.onnx")))
    if not candidates:
        candidates = sorted(glob.glob(os.path.join(folder, "scrfd*.onnx")))
    if not candidates:
        raise RuntimeError("No SCRFD detector in model pack: " + pack)
    detector = get_model(candidates[0], providers=["CPUExecutionProvider"])
    detector.prepare(ctx_id=-1, input_size=(960, 544), det_thresh=0.35)
    print(f"[MODEL] Detection only: {os.path.basename(candidates[0])}", flush=True)
    return detector


def score_quality(frame, bbox, kps, confidence):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = np.asarray(bbox, dtype=int)
    side = min(x2-x1, y2-y1)
    if side < 20:
        return "SMALL"
    if confidence < 0.35:
        return "LOW CONF"
    crop = frame[max(0,y1):min(h,y2), max(0,x1):min(w,x2)]
    if crop.size == 0 or sharpness(crop) < 8.0:
        return "BLUR"
    if kps is None or abs(yaw_proxy(kps)) > 2.2:
        return "SIDE"
    return "USABLE"


def run_rtsp(args):
    uri = make_uri(args.host, args.port, args.path, args.username)
    print("[EXPERIMENT] No SQL connection, no identity matching, no attendance writes", flush=True)
    detector = load_detector()
    camera = LatestCamera(uri)
    tracker = FaceTracker()
    import face_pipeline as fp
    previous_ttl = fp.TRACK_TTL
    fp.TRACK_TTL = 2.0
    states = {}
    latest_inferred = 0.0
    inference_ms = 0.0
    scans = 0
    scanning = False
    lock = threading.Lock()
    running = threading.Event()
    running.set()

    def inference_loop():
        nonlocal latest_inferred, inference_ms, scans, scanning, states
        last_ts = 0.0
        while running.is_set():
            frame, ts = camera.latest()
            if frame is None or ts == last_ts:
                time.sleep(0.01)
                continue
            last_ts = ts
            scanning = True
            start = time.perf_counter()
            try:
                # Keep native pixels; use full-frame detection and tiled passes
                # in the original experimental engine when evaluating tiny faces.
                boxes, points = detector.detect(frame, input_size=(960, 544), max_num=0)
                dets = []
                for i, box in enumerate(boxes):
                    b = np.asarray(box[:4], np.float32)
                    if min(b[2]-b[0], b[3]-b[1]) < 14:
                        continue
                    kp = points[i] if points is not None else None
                    dets.append({"bbox": b, "kps": kp, "score": float(box[4])})
                now = time.monotonic()
                with lock:
                    pairs = tracker.update(dets, now)
                    for track, det in pairs:
                        states[track.id] = score_quality(frame, det["bbox"], det["kps"], det["score"])
                    live = {t.id for t in tracker.tracks}
                    states = {k: v for k, v in states.items() if k in live}
                    latest_inferred = now
                    scans += 1
            except Exception as exc:
                print("[EXPERIMENT] Detection error: " + type(exc).__name__ + ": " + str(exc), flush=True)
                time.sleep(0.3)
            finally:
                inference_ms = (time.perf_counter()-start)*1000
                scanning = False

    worker = threading.Thread(target=inference_loop, daemon=True)
    worker.start()
    last_report = time.monotonic()
    last_scans = 0
    try:
        while True:
            frame, ts = camera.latest()
            if frame is None:
                canvas = np.zeros((480, 850, 3), dtype=np.uint8)
                cv2.putText(canvas, "Waiting for RTSP feed ...", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)
            else:
                canvas = frame.copy()
            scale = min(1.0, 1280.0/canvas.shape[1])
            if scale < 1:
                canvas = cv2.resize(canvas, None, fx=scale, fy=scale)
            now = time.monotonic()
            with lock:
                overlays = [(t.id, t.bbox.copy(), t.last_seen, states.get(t.id, "DETECTED")) for t in tracker.tracks]
            for track_id, bbox, last_seen, label in overlays:
                if now-last_seen > 0.7:
                    continue
                b = (bbox*scale).astype(int)
                color = (0, 255, 0) if label == "USABLE" else (0, 165, 255)
                cv2.rectangle(canvas, tuple(b[:2]), tuple(b[2:]), color, 2)
                cv2.putText(canvas, f"#{track_id} {label}", (int(b[0]), max(45,int(b[1])-8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            age_ms = (now-ts)*1000 if ts else 0
            info = f"DETECTION ONLY | preview age {age_ms:.0f}ms | scan {inference_ms:.0f}ms | Q quit"
            cv2.putText(canvas, info, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,0), 2)
            cv2.imshow("Experimental RTSP - No Database", canvas)
            if cv2.waitKey(30) & 0xFF in (ord("q"),ord("Q")):
                break
            if now-last_report >= 30:
                print(f"[EXPERIMENT STATS] scans={scans-last_scans} / 30s; latest_detection_ms={inference_ms:.0f}; frame_age_ms={age_ms:.0f}", flush=True)
                last_report, last_scans = now, scans
    finally:
        running.clear()
        camera.stop()
        worker.join(timeout=3)
        fp.TRACK_TTL = previous_ttl
        cv2.destroyAllWindows()
        print("[EXPERIMENT] Closed. No attendance records created.", flush=True)
