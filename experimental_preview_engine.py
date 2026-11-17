"""Standalone read-only face-recognition preview: no attendance writes or emails.
Run: python experimental_preview_engine.py --camera HO_IN
Or:  python experimental_preview_engine.py --camera HO_IN --detect-only
Press Q to close. Use a desktop session, not NSSM.
"""
import argparse
import json
import time
from collections import defaultdict, deque

import cv2
import numpy as np

import face_pipeline as fp

# Isolated experimental settings. No changes to production engine globals.
MIN_PX = 20
MIN_SCORE = 0.35
MIN_SHARP = 8.0
MAX_POSE = 2.2
SIM_THRESHOLD = 0.40  # Preview only, requires test-set calibration
RECHECK_SEC = 0.75


def sources(camera_id):
    from db import query
    from server_engine import build_camera_source
    rows = query("SELECT * FROM cameras WHERE camera_id=? AND is_active=1", (camera_id,))
    if not rows:
        raise RuntimeError("Camera not found or inactive: " + camera_id)
    return build_camera_source(rows[0])


def gallery():
    from db import query
    users = []
    for row in query("SELECT person_name,face_embedding FROM users WHERE is_active=1"):
        try:
            vector = np.asarray(json.loads(row["face_embedding"]), np.float32)
            if vector.shape != (512,) or not np.isfinite(vector).all():
                continue
            vector /= max(float(np.linalg.norm(vector)), 1e-8)
            users.append((row["person_name"], vector))
        except (ValueError, TypeError):
            pass
    return users, np.stack([v for _, v in users]) if users else np.empty((0, 512), np.float32)


def assess(frame, detection):
    x1, y1, x2, y2 = [int(x) for x in detection["bbox"]]
    h, w = frame.shape[:2]
    crop = frame[max(y1, 0):min(y2, h), max(x1, 0):min(x2, w)]
    px = min(x2-x1, y2-y1)
    if px < MIN_PX:
        return False, "TOO SMALL", px
    if detection["score"] < MIN_SCORE:
        return False, "LOW CONF", px
    if fp.sharpness(crop) < MIN_SHARP:
        return False, "BLURRY", px
    if detection["kps"] is None or abs(fp.yaw_proxy(detection["kps"])) > MAX_POSE:
        return False, "EXTREME SIDE", px
    return True, "READY", px


def run(args):
    if args.rtsp:
        from experimental_rtsp_preview import run_rtsp
        return run_rtsp(args)
    from server_engine import build_face_app
    # Read-only DB calls; never import an attendance writer or call event handlers.
    source = args.video if args.video else sources(args.camera)
    people, vectors = ([], np.empty((0, 512), np.float32)) if args.detect_only else gallery()
    print(f"[EXPERIMENT] preview only: {len(people)} enrolled templates; no SQL writes", flush=True)
    app = build_face_app()
    finder = fp.FaceFinder(app)
    tracker = fp.FaceTracker()
    # Tracking across slow frames is essential to get two confirmation votes.
    old_ttl, old_confirmed = fp.TRACK_TTL, fp.TRACK_TTL_CONFIRMED
    fp.TRACK_TTL = 2.0
    fp.TRACK_TTL_CONFIRMED = 2.0
    states = {}
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError("Could not open camera/video")
    last_report = time.monotonic()
    counts = defaultdict(int)
    camera = args.camera or "OFFLINE VIDEO"
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                if args.video:
                    break
                cap.release()
                time.sleep(2)
                cap = cv2.VideoCapture(source)
                continue
            started = time.perf_counter()
            now = time.time()
            # Full-frame pass plus one rotating high-resolution 2x2 tile.
            dets = finder.detect(frame, rois=None, tile_grid=(2, 2))
            pairs = tracker.update(dets, now)
            for track, det in pairs:
                state = states.setdefault(track.id, {"last": 0.0, "votes": deque(maxlen=4), "label": "DETECTED", "confirmed": False})
                usable, why, px = assess(frame, det)
                if not usable:
                    state["label"] = f"{why}: {px}px"
                    counts[why] += 1
                    continue
                if args.detect_only or not people:
                    state["label"] = f"FACE: {px}px"
                    counts["usable"] += 1
                    continue
                if now - state["last"] < RECHECK_SEC:
                    continue
                state["last"] = now
                emb = finder.embed(frame, det["kps"], det["bbox"], det["score"])
                scores = vectors @ emb
                idx = int(np.argmax(scores))
                best = float(scores[idx])
                second = float(np.partition(scores, -2)[-2]) if len(scores) > 1 else -1.0
                good = best >= SIM_THRESHOLD and (len(scores) < 2 or best-second >= 0.04)
                state["votes"].append(idx if good else None)
                votes = sum(v == idx for v in state["votes"]) if good else 0
                if good and votes >= 2:
                    state["label"] = f"TEST MATCH: {people[idx][0]} ({best:.2f})"
                    state["confirmed"] = True
                    counts["test_match"] += 1
                elif good:
                    state["label"] = f"CHECKING {votes}/2 ({best:.2f})"
                    counts["checking"] += 1
                else:
                    state["label"] = f"NO MATCH ({best:.2f})"
                    state["confirmed"] = False
                    counts["no_match"] += 1
            scale = min(1.0, 1280.0/frame.shape[1])
            view = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame.copy()
            for track in tracker.tracks:
                if now-track.last_seen > 0.6:
                    continue
                state = states.get(track.id, {})
                b = (track.bbox*scale).astype(int)
                color = (0, 255, 0) if state.get("confirmed") else (0, 165, 255)
                cv2.rectangle(view, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), color, 2)
                cv2.putText(view, state.get("label", "DETECTED"), (int(b[0]), max(25,int(b[1])-8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
            ms = (time.perf_counter()-started)*1000
            cv2.putText(view, f"EXPERIMENT ONLY - NO PUNCHES | {camera} | {ms:.0f}ms | Q quit",
                        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255,255,0), 2)
            cv2.imshow("Experimental Recognition - " + camera, view)
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                break
            if time.monotonic()-last_report >= 30:
                print(f"[EXPERIMENT STATS] {camera} scan_ms={ms:.0f} " + " ".join(f"{k}={v}" for k,v in counts.items()), flush=True)
                counts.clear()
                last_report = time.monotonic()
            if len(states) > 300:
                live = {t.id for t in tracker.tracks}
                states = {k:v for k,v in states.items() if k in live}
    finally:
        cap.release()
        cv2.destroyAllWindows()
        fp.TRACK_TTL, fp.TRACK_TTL_CONFIRMED = old_ttl, old_confirmed
        print("[EXPERIMENT] stopped. No attendance was written.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--camera", help="Active camera ID, e.g. HO_IN")
    group.add_argument("--video", help="Local consented test video")
    group.add_argument("--rtsp", action="store_true", help="Standalone RTSP detection: no SQL or employee records")
    parser.add_argument("--detect-only", action="store_true", help="Detect faces without identity matching")
    parser.add_argument("--host", help="RTSP camera IP or hostname (used with --rtsp)")
    parser.add_argument("--port", type=int, default=554, help="RTSP port")
    parser.add_argument("--path", default="Streaming/Channels/101", help="Camera RTSP path, without leading slash")
    parser.add_argument("--username", default="", help="RTSP login (password prompted securely)")
    args = parser.parse_args()
    if args.rtsp and not args.host:
        parser.error("--rtsp requires --host CAMERA_IP")
    if args.rtsp and (not 1 <= args.port <= 65535):
        parser.error("--port must be between 1 and 65535")
    if args.rtsp and args.detect_only:
        parser.error("--rtsp is already detection-only; omit --detect-only")
    run(args)
    raise SystemExit(0)

