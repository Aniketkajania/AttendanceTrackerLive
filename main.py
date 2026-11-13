"""
FastAPI backend for the Attendance Portal.
Place this file in the project root, next to config.py, and run:
    uvicorn main:app --reload --port 8000
Docs UI: http://localhost:8000/docs
"""
import io
import os

# Must be set before the first cv2.VideoCapture is opened: TCP transport, low latency, drop corrupt packets
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                      "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0|stimeout;5000000")

import time
import json
import asyncio
from typing import Optional
from urllib.parse import quote

import cv2
import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

import platform
from config import PHOTOS_DIR, SNAPSHOTS_DIR, LOCATIONS, ALLOWED_ORIGINS, API_USE_GPU
from db import connect, query, execute, IntegrityError
from auth import router as auth_router, auth_middleware, init_auth
from users_api import router as users_router
from operations_api import router as operations_router
from face_pipeline import yaw_proxy

app = FastAPI(title="Attendance API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(auth_middleware)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(operations_router)
init_auth()

app.mount("/snapshots", StaticFiles(directory=SNAPSHOTS_DIR), name="snapshots")
app.mount("/photos", StaticFiles(directory=PHOTOS_DIR), name="photos")

# ---------- helpers ----------
def to_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    p = path.replace("\\", "/")
    i = p.rfind("/snapshots/")
    if i == -1:
        return None
    return quote(p[i:], safe="/")

_face_app = None

def get_face_model():
    global _face_app
    if _face_app is None:
        from insightface.app import FaceAnalysis
        import onnxruntime as ort
        # Enrolment is occasional, so the API uses the CPU by default and leaves all VRAM to the engine.
        use_gpu = API_USE_GPU and "CUDAExecutionProvider" in ort.get_available_providers()
        _face_app = FaceAnalysis(
            name="buffalo_l",
            allowed_modules=["detection", "recognition"],   # same modules as server_engine.py
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"] if use_gpu else ["CPUExecutionProvider"],
        )
        _face_app.prepare(ctx_id=0 if use_gpu else -1, det_size=(640, 640))
    return _face_app

def _enroll_quality(face, img_shape):
    """Reject enrolment photos that would poison the master embedding. Returns (ok, reason)."""
    x1, y1, x2, y2 = face.bbox
    side = min(x2 - x1, y2 - y1)
    if getattr(face, "det_score", 1.0) < 0.6:
        return False, "low detection confidence"
    if side < 80:
        return False, f"face too small ({int(side)}px, need >= 80px)"
    if abs(yaw_proxy(face.kps)) > 0.5:
        return False, "face is turned too far to the side"
    return True, ""

def _attendance_rows(date: str, location: Optional[str], search: Optional[str]):
    sql, p = "SELECT * FROM daily_attendance WHERE work_date = ?", [date]
    if location and location != "All Locations":
        sql += " AND (base_location=? OR current_location=? OR visited_locations LIKE ?)"
        p += [location, location, f"%{location}%"]
    if search:
        sql += " AND (employee_id LIKE ? OR person_name LIKE ?)"
        p += [f"%{search}%", f"%{search}%"]
    rows = query(sql + " ORDER BY id DESC", tuple(p))
    for r in rows:
        r["first_check_in_image_url"] = to_url(r.get("first_check_in_image"))
        r["last_check_out_image_url"] = to_url(r.get("last_check_out_image"))
    return rows

# ---------- general ----------
@app.get("/api/locations")
def locations():
    return LOCATIONS

# ---------- tab 1: live attendance ----------
@app.get("/api/attendance")
def attendance(date: str, location: Optional[str] = None, search: Optional[str] = None):
    rows = _attendance_rows(date, location, search)
    stats = {
        "total_present": len(rows),
        "currently_in": sum(r["current_status"] == "IN" for r in rows),
        "checked_out": sum(r["current_status"] == "OUT" for r in rows),
        "roaming": sum("->" in (r["visited_locations"] or "") for r in rows),
    }
    return {"stats": stats, "rows": rows}

@app.get("/api/attendance/export")
def attendance_export(date: str, location: Optional[str] = None, search: Optional[str] = None):
    rows = _attendance_rows(date, location, search)
    cols = [
        "employee_id", "person_name", "current_status", "first_check_in",
        "first_check_in_location", "last_check_out", "last_check_out_location",
        "total_checks", "out_of_office_hours", "total_working_hours", "visited_locations",
    ]
    df = pd.DataFrame(rows, columns=cols)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Daily_Attendance")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Attendance_{date}.xlsx"'},
    )

# ---------- tab 2: audit logs ----------
@app.get("/api/logs")
def logs(search: Optional[str] = None, limit: int = 200):
    sql, p = "SELECT TOP (?) * FROM attendance_logs", [min(max(limit, 1), 1000)]
    if search:
        sql += " WHERE employee_id LIKE ? OR person_name LIKE ?"
        p += [f"%{search}%", f"%{search}%"]
    rows = query(sql + " ORDER BY log_id DESC", tuple(p))
    for r in rows:
        r["snapshot_url"] = to_url(r.get("snapshot_image"))
    return rows

# ---------- tab 3: employees ----------
@app.get("/api/employees")
def employees():
    rows = query(
        "SELECT employee_id, person_name, email, base_location, CONVERT(varchar(19), created_at, 120) AS created_at "
        "FROM users WHERE is_active = 1 ORDER BY id DESC"
    )
    for r in rows:
        front = os.path.join(PHOTOS_DIR, r["employee_id"], "front.jpg")
        r["photo_url"] = f"/photos/{r['employee_id']}/front.jpg" if os.path.exists(front) else None
    return rows

@app.post("/api/employees")
def enroll_employee(
    employee_id: str = Form(...),
    person_name: str = Form(...),
    email: str = Form(...),
    base_location: str = Form(...),
    front: UploadFile = File(...),
    left: UploadFile = File(...),
    right: UploadFile = File(...),
    neutral: UploadFile = File(...),
    # OPTIONAL: 1-3 frames captured from the real CCTV camera(s). Biggest single accuracy gain,
    # because it closes the gap between phone photos and wide-angle camera footage.
    extra: list[UploadFile] = File(default=[]),
):
    emp_id = employee_id.strip().upper()
    face_app = get_face_model()
    emp_dir = os.path.join(PHOTOS_DIR, emp_id)
    os.makedirs(emp_dir, exist_ok=True)

    uploads = {"front.jpg": front, "left.jpg": left, "right.jpg": right, "neutral.jpg": neutral}
    for i, ef in enumerate(extra or [], start=1):
        uploads[f"cctv_{i}.jpg"] = ef
    vecs, warnings = [], []
    area = lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])

    for fname, ufile in uploads.items():
        arr = np.frombuffer(ufile.file.read(), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        faces = face_app.get(img) if img is not None else []
        if not faces:
            warnings.append(f"No face detected in {fname}, skipped.")
            continue
        primary = max(faces, key=area)
        cv2.imwrite(os.path.join(emp_dir, fname), img)
        
        # Only frontal photos (front, neutral, CCTV frames) feed the master vector; left/right would blur it.
        if fname in ["front.jpg", "neutral.jpg"] or fname.startswith("cctv_"):
            ok_q, why = _enroll_quality(primary, img.shape)
            if ok_q:
                vecs.append(primary.normed_embedding)
            else:
                warnings.append(f"{fname} not used for matching: {why}.")

    if not vecs:
        raise HTTPException(400, "Could not extract a valid face from any uploaded image.")

    mean_v = np.mean(vecs, axis=0)
    master = [round(float(x), 6) for x in mean_v / np.linalg.norm(mean_v)]

    try:
        execute(
            """
            MERGE dbo.users WITH (HOLDLOCK) AS t
            USING (SELECT ? AS employee_id, ? AS person_name, ? AS email, ? AS base_location,
                          ? AS enrolled_photo_path, ? AS face_embedding) AS s
            ON t.employee_id = s.employee_id
            WHEN MATCHED THEN UPDATE SET person_name=s.person_name, email=s.email,
                base_location=s.base_location, enrolled_photo_path=s.enrolled_photo_path,
                face_embedding=s.face_embedding, is_active=1
            WHEN NOT MATCHED THEN INSERT (employee_id, person_name, email, base_location,
                enrolled_photo_path, face_embedding)
                VALUES (s.employee_id, s.person_name, s.email, s.base_location,
                        s.enrolled_photo_path, s.face_embedding);
            """,
            (emp_id, person_name.strip(), email.strip(), base_location, emp_dir, json.dumps(master)),
        )
    except IntegrityError as e:
        raise HTTPException(409, f"Duplicate value (email already used?): {e}")

    return {"ok": True, "employee_id": emp_id, "vectors_used": len(vecs), "warnings": warnings}

# ---------- tab 4: cameras ----------
class CameraIn(BaseModel):
    camera_id: str
    camera_name: str
    location: str
    camera_role: str
    connection_type: str
    webcam_index: int = 0
    ip_address: Optional[str] = None
    port: int = 554
    username: Optional[str] = None
    password: Optional[str] = None 
    rtsp_path: Optional[str] = None
    is_active: bool = True

@app.get("/api/cameras")
def cameras():
    return query(
        "SELECT camera_id, camera_name, location, camera_role, connection_type, webcam_index, "
        "ip_address, port, username, rtsp_path, CAST(is_active AS int) AS is_active FROM cameras ORDER BY id"
    )

@app.get("/api/cameras/{camera_id}/preview")
def get_camera_preview(camera_id: str):
    conn = connect()
    row = conn.execute(
        "SELECT TOP 1 snapshot_image FROM attendance_logs WHERE camera_id = ? ORDER BY log_id DESC",
        (camera_id,)
    ).fetchone()
    conn.close()

    if row and row["snapshot_image"] and os.path.exists(row["snapshot_image"]):
        return FileResponse(row["snapshot_image"], media_type="image/jpeg")

    raise HTTPException(status_code=404, detail="No preview frame available yet")
    
@app.post("/api/cameras")
def save_camera(c: CameraIn):
    if c.camera_role not in ("IN", "OUT") or c.connection_type not in ("RTSP", "WEBCAM"):
        raise HTTPException(400, "Invalid camera_role or connection_type")
    cam_id = c.camera_id.strip().upper()

    password = c.password
    if not password:
        old = query("SELECT password FROM cameras WHERE camera_id = ?", (cam_id,))
        password = old[0]["password"] if old else None

    execute(
        """
        MERGE dbo.cameras WITH (HOLDLOCK) AS t
        USING (SELECT ? AS camera_id, ? AS camera_name, ? AS location, ? AS camera_role,
                      ? AS connection_type, ? AS webcam_index, ? AS ip_address, ? AS port,
                      ? AS username, ? AS password, ? AS rtsp_path, ? AS is_active) AS s
        ON t.camera_id = s.camera_id
        WHEN MATCHED THEN UPDATE SET camera_name=s.camera_name, location=s.location,
            camera_role=s.camera_role, connection_type=s.connection_type,
            webcam_index=s.webcam_index, ip_address=s.ip_address, port=s.port,
            username=s.username, password=s.password, rtsp_path=s.rtsp_path, is_active=s.is_active
        WHEN NOT MATCHED THEN INSERT (camera_id, camera_name, location, camera_role, connection_type,
            webcam_index, ip_address, port, username, password, rtsp_path, is_active)
            VALUES (s.camera_id, s.camera_name, s.location, s.camera_role, s.connection_type,
            s.webcam_index, s.ip_address, s.port, s.username, s.password, s.rtsp_path, s.is_active);
        """,
        (cam_id, c.camera_name, c.location, c.camera_role, c.connection_type, c.webcam_index,
         c.ip_address, c.port, c.username, password, c.rtsp_path, int(c.is_active)),
    )
    return {"ok": True, "camera_id": cam_id}

# ---------- Native WebRTC (WHEP) Endpoint ----------
pcs = set()
import threading
from aiortc import VideoStreamTrack
from av import VideoFrame

# Global registry for resilient camera threads
CAM_WORKERS = {}

class CameraWorker:
    def __init__(self, camera_config: dict):
        self.config = camera_config
        self.camera_id = camera_config["camera_id"]
        self.latest_frame = None
        self.running = True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _open_capture(self):
        conn_type = self.config.get("connection_type", "WEBCAM")
        if conn_type == "WEBCAM":
            src = int(self.config.get("webcam_index") or 0)
            cap = cv2.VideoCapture(src, cv2.CAP_DSHOW) if platform.system() == "Windows" else cv2.VideoCapture(src)
        else:
            ip = self.config.get("ip_address")
            port = self.config.get("port") or 554
            user = self.config.get("username") or ""
            pwd = self.config.get("password") or ""
            path = self.config.get("rtsp_path") or ""
            if path and not path.startswith("/"):
                path = "/" + path
            src = f"rtsp://{user}:{pwd}@{ip}:{port}{path}" if user and pwd else f"rtsp://{ip}:{port}{path}"
            cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _capture_loop(self):
        cap = self._open_capture()
        failures = 0

        while self.running:
            if not cap.grab():
                failures += 1
                time.sleep(0.02)
                if failures >= 50:  # Auto-reconnect on stream drop
                    cap.release()
                    time.sleep(0.5)
                    cap = self._open_capture()
                    failures = 0
                continue

            failures = 0
            success, frame = cap.retrieve()
            if success and frame is not None:
                # Resize if > 720p to save WebRTC bandwidth
                h, w = frame.shape[:2]
                if w > 1280:
                    frame = cv2.resize(frame, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_AREA)
                
                with self.lock:
                    self.latest_frame = frame
            time.sleep(0.033)  # ~30 FPS

        cap.release()

    def get_frame(self):
        with self.lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None


class ResilientVideoStreamTrack(VideoStreamTrack):
    """A custom WebRTC track that pulls frames from the robust OpenCV worker"""
    def __init__(self, worker: CameraWorker):
        super().__init__()
        self.worker = worker

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        
        # Non-blocking wait for the next frame
        frame = self.worker.get_frame()
        while frame is None:
            await asyncio.sleep(0.01)
            frame = self.worker.get_frame()

        # Convert OpenCV BGR array to WebRTC VideoFrame
        av_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        av_frame.pts = pts
        av_frame.time_base = time_base
        return av_frame


# ---------- Native WebRTC (WHEP) Endpoint ----------
pcs = set()

@app.post("/api/cameras/{camera_id}/whep")
async def webrtc_offer(camera_id: str, request: Request):
    conn = connect()
    cam = conn.execute("SELECT * FROM cameras WHERE camera_id = ?", (camera_id,)).fetchone()
    conn.close()

    if not cam or not cam["is_active"]:
        raise HTTPException(status_code=404, detail="Camera offline or not found")

    # Start the persistent background thread if it isn't running
    if camera_id not in CAM_WORKERS or not CAM_WORKERS[camera_id].running:
        CAM_WORKERS[camera_id] = CameraWorker(dict(cam))

    offer_sdp = await request.body()
    offer = RTCSessionDescription(sdp=offer_sdp.decode("utf-8"), type="offer")

    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState in ["failed", "closed"]:
            pcs.discard(pc)

    # Attach our custom resilient stream track
    video_track = ResilientVideoStreamTrack(CAM_WORKERS[camera_id])
    pc.addTrack(video_track)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return Response(content=pc.localDescription.sdp, media_type="application/sdp")

@app.on_event("shutdown")
async def on_shutdown():
    for worker in CAM_WORKERS.values():
        worker.running = False
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)

@app.delete("/api/employees/{employee_id}")
def delete_employee(employee_id: str):
    emp_id = employee_id.strip().upper()
    try:
        # Soft delete: attendance history keeps pointing at this employee (FK), the engine stops matching them.
        execute("UPDATE users SET is_active = 0 WHERE employee_id = ?", (emp_id,))
        return {"ok": True, "message": f"Deactivated {emp_id}"}
    except Exception as e:
        raise HTTPException(500, str(e))