"""
face_pipeline.py  -  detection / enhancement / tracking helpers for server_engine.py

Put this file next to server_engine.py. It has NO dependency on your DB/config code.

What it fixes
-------------
1. DETECTION SCALE.  A 16:9 CCTV frame was squashed into a 640x640 detector input, so a
   60 px face became ~20 px and was missed or flagged "Too Small".  We now detect at
   960x544 (aspect-correct) and can add native-resolution ROI / rotating-tile passes.
2. IMAGE ENHANCEMENT (measured).  Gamma + CLAHE is applied to the DETECTION frame only when
   the scene is dark / flat.  Embeddings are always computed from the RAW frame (same domain
   as the enrolment photos).  Sharpening / denoising / up-scaling a face crop was
   benchmarked and did NOT improve recognition, so it is deliberately not used.
3. QUALITY GATES that are scale-independent (blur is measured on a normalised crop) and
   that understand head pose (side faces are not sent to the matcher).
4. TRACKING.  Faces are tracked across frames, so boxes never flicker, and identity is
   decided from several frames (fused embedding + voting) instead of a single noisy one.
"""
from __future__ import annotations

from collections import deque
import os

import cv2
import numpy as np
from insightface.app.common import Face

# =====================================================================
# TUNING KNOBS
# =====================================================================
# Detector input sizes. MUST be multiples of 32. Keep this set small and FIXED:
# GPU providers (DirectML/OpenVINO) re-compile the model for every new input shape.
# CPU fast detector profile: smaller input, less work, but may miss distant small faces.
DETECTION_PROFILE = os.getenv("DETECTION_PROFILE", "quality").strip().lower()
if DETECTION_PROFILE == "fast":
    FULL_SIZES = {"wide": (640, 384), "std": (640, 480), "tall": (512, 512)}
else:
    FULL_SIZES = {"wide": (960, 544), "std": (800, 608), "tall": (640, 640)}
ROI_DET_SIZE = (640, 640)       # native-resolution crops (ROIs / tiles)
DET_THRESH = 0.40               # raw detector threshold (low on purpose; quality gates filter later)
MIN_DET_PX = 14                 # ignore detections smaller than this (noise)
NMS_IOU = 0.40

# # ---- quality gates (a face must pass ALL of these before it is matched) ----
# MIN_FACE_PX = 40                # shortest side of the face box (old code: 70x50 -> rejected your desk face)
# MIN_DET_SCORE = 0.50
# MIN_SHARPNESS = 12.0            # Laplacian variance on a 96x96 normalised crop (sharp ~30, blurred ~8)
# MAX_YAW = 0.75                  # |nose offset| / eye distance. frontal ~0, 45deg ~0.5, profile >1.5

# ---- quality gates (a face must pass ALL of these before it is matched) ----
MIN_FACE_PX = 25                # Lowered from 40 to catch distant faces
MIN_DET_SCORE = 0.35            # Lowered from 0.50 to accept less confident top-down views
MIN_SHARPNESS = 8.0             # Lowered from 12.0 to tolerate 15fps motion blur
MAX_YAW = 1.2                   # Increased from 0.75 to allow steep side/top profiles
# ---- tracking / identity ----
TRACK_TTL = 0.3                 # seconds an un-detected track stays on screen (label keeps showing)
TRACK_TTL_CONFIRMED = 0.3
NEAR_DET_SIZE = (320, 320)      # track-guided re-detection window
NEAR_DET_THRESH = 0.25          # much lower than DET_THRESH: we already know a face should be here
TRACK_IOU = 0.15
EMB_BUFFER = 8                  # embeddings fused per track
CONFIRM_VOTES = 2               # same identity this many times (of the last VOTE_WINDOW) -> confirmed
VOTE_WINDOW = 5
STRONG_MARGIN = 0.10            # score >= threshold + this confirms on the first vote
MATCH_MARGIN = 0.04             # best score must beat 2nd best user by this (only if >1 user enrolled)
REVERIFY_SEC = 2.0              # confirmed tracks are re-checked this often (saves CPU)
UNKNOWN_AFTER = 3               # good samples without a match before showing "Unknown"


# =====================================================================
# IMAGE ENHANCEMENT
# =====================================================================
def enhance_for_detection(frame: np.ndarray) -> np.ndarray:
    """
    Auto-gamma + CLAHE on luminance, applied ONLY when the scene is dark, blown-out or flat
    (otherwise the frame is returned untouched - it costs ~100 ms at 1080p and measured no gain
    on well-lit frames).  Used for FINDING faces; embeddings use the raw frame.
    """
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    mean, std = float(l.mean()), float(l.std())
    if 95 <= mean <= 165 and std >= 40:
        return frame

    if mean < 95 or mean > 165:
        gamma = np.clip(np.log(118.0 / 255.0) / np.log(max(mean, 1.0) / 255.0), 0.6, 1.6)
        l = cv2.LUT(l, (np.linspace(0, 1, 256) ** gamma * 255).astype(np.uint8))
    l = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


# =====================================================================
# SMALL GEOMETRY HELPERS
# =====================================================================
def iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def nms(dets: list, thr: float = NMS_IOU) -> list:
    dets = sorted(dets, key=lambda d: d["score"], reverse=True)
    keep = []
    for d in dets:
        if all(iou(d["bbox"], k["bbox"]) < thr for k in keep):
            keep.append(d)
    return keep


def yaw_proxy(kps) -> float:
    """~0 frontal, grows as the head turns. Nose offset from the eye midpoint / eye distance."""
    if kps is None:
        return 0.0
    le, re, nose = kps[0], kps[1], kps[2]
    eye_dist = float(np.linalg.norm(re - le))
    if eye_dist < 1e-3:
        return 9.0
    return float((nose[0] - (le[0] + re[0]) / 2.0) / eye_dist)


def sharpness(crop: np.ndarray, n: int = 96) -> float:
    """Scale-independent blur metric (the old code measured raw crops, so it depended on face size)."""
    if crop.size == 0:
        return 0.0
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    interp = cv2.INTER_AREA if g.shape[0] > n else cv2.INTER_CUBIC
    g = cv2.resize(g, (n, n), interpolation=interp)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def _pick_full_size(w: int, h: int):
    ar = w / float(h)
    return FULL_SIZES["wide"] if ar >= 1.6 else FULL_SIZES["std"] if ar >= 1.2 else FULL_SIZES["tall"]


# =====================================================================
# DETECTOR + RECOGNISER WRAPPER
# =====================================================================
class FaceFinder:
    def __init__(self, face_app):
        self.det = face_app.models["detection"]
        self.rec = face_app.models["recognition"]
        self.det.det_thresh = DET_THRESH
        self._tile_i = 0

    def warmup(self):
        """Run every fixed detector shape once so the first real frame is not slow (GPU providers compile per shape)."""
        sizes = set(FULL_SIZES.values()) | {ROI_DET_SIZE, NEAR_DET_SIZE}
        if os.getenv("QUALITY_SCAN_INTERVAL", "0") not in ("0", "0.0"):
            sizes |= {(960, 544), (800, 608), (640, 640)}
        for (w, h) in sizes:
            self._raw(np.zeros((h, w, 3), np.uint8), (w, h))

    # ---------- raw SCRFD call ----------
    def _raw(self, img, size, offset=(0, 0), thr=None):
        old = self.det.det_thresh
        if thr is not None:
            self.det.det_thresh = thr
        try:
            b, k = self.det.detect(img, input_size=size, max_num=0, metric="default")
        finally:
            self.det.det_thresh = old
        out = []
        ox, oy = offset
        for i in range(len(b)):
            bb = b[i][:4].astype(np.float32) + np.array([ox, oy, ox, oy], np.float32)
            kp = None
            if k is not None:
                kp = k[i].astype(np.float32) + np.array([ox, oy], np.float32)
            if min(bb[2] - bb[0], bb[3] - bb[1]) >= MIN_DET_PX:
                out.append({"bbox": bb, "score": float(b[i][4]), "kps": kp})
        return out

    # ---------- multi-pass detection ----------
    def detect(self, frame, rois=None, tile_grid=None, high_accuracy=False):
        """
        frame     : (enhanced) full-resolution BGR frame
        rois      : optional list of normalised (x1,y1,x2,y2) regions scanned at native resolution
        tile_grid : optional (cols, rows). ONE tile is scanned per call (round-robin), so every
                    part of the frame is covered at high resolution every cols*rows cycles.
        """
        h, w = frame.shape[:2]
        size = ({"wide": (960, 544), "std": (800, 608), "tall": (640, 640)}["wide" if w / float(h) >= 1.6 else "std" if w / float(h) >= 1.2 else "tall"]) if high_accuracy else _pick_full_size(w, h)
        dets = self._raw(frame, size)

        regions = []
        for r in rois or []:
            regions.append((int(r[0] * w), int(r[1] * h), int(r[2] * w), int(r[3] * h)))
        if tile_grid:
            cols, rows = tile_grid
            idx = self._tile_i % (cols * rows)
            self._tile_i += 1
            c, r = idx % cols, idx // cols
            tw, th = w / cols, h / rows
            ov = 0.15  # overlap so faces on tile borders are not cut
            regions.append((int(max(0, (c - ov) * tw)), int(max(0, (r - ov) * th)),
                            int(min(w, (c + 1 + ov) * tw)), int(min(h, (r + 1 + ov) * th))))

        for (x1, y1, x2, y2) in regions:
            if x2 - x1 > 32 and y2 - y1 > 32:
                dets += self._raw(frame[y1:y2, x1:x2], ROI_DET_SIZE, offset=(x1, y1))
        return nms(dets)

    # ---------- track-guided re-detection ----------
    def detect_near(self, frame, bbox):
        """
        Look for a face again in a native-resolution window around where a tracked face was last
        seen, with a low threshold. This is what keeps small / side-on faces detected on EVERY
        cycle instead of flickering in and out when the detector score dips below its threshold.
        """
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = [float(v) for v in bbox]
        bw, bh = x2 - x1, y2 - y1
        half = max(bw, bh) * 1.2 + 20
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        rx1, ry1 = int(max(0, cx - half)), int(max(0, cy - half))
        rx2, ry2 = int(min(w, cx + half)), int(min(h, cy + half))
        if rx2 - rx1 < 32 or ry2 - ry1 < 32:
            return None
        found = self._raw(frame[ry1:ry2, rx1:rx2], NEAR_DET_SIZE, offset=(rx1, ry1), thr=NEAR_DET_THRESH)
        best = None
        for d in found:
            ov = iou(d["bbox"], (x1, y1, x2, y2))
            if ov > 0.25 and (best is None or ov > best[0]):
                best = (ov, d)
        return best[1] if best else None

    # ---------- recognition ----------
    def embed(self, raw_frame, kps, bbox=None, score=1.0):
        """Embedding from the RAW frame + detector landmarks (aligned/normalised by insightface)."""
        f = Face(bbox=np.zeros(4, np.float32) if bbox is None else bbox, kps=kps, det_score=score)
        self.rec.get(raw_frame, f)
        return f.normed_embedding.astype(np.float32)

    # ---------- quality gate ----------
    @staticmethod
    def assess(raw_frame, bbox, kps, score):
        """Return (ok, reason, metrics, quality 0..1)."""
        x1, y1, x2, y2 = [int(v) for v in bbox]
        side = min(x2 - x1, y2 - y1)
        yaw = yaw_proxy(kps)
        h, w = raw_frame.shape[:2]
        crop = raw_frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        sh = sharpness(crop)
        metrics = {"px": side, "yaw": yaw, "sharp": sh, "score": score}

        if score < MIN_DET_SCORE:
            return False, "Low Conf", metrics, 0.0
        if side < MIN_FACE_PX:
            return False, "Too Small", metrics, 0.0
        if abs(yaw) > MAX_YAW:
            return False, "Side Face", metrics, 0.0
        if sh < MIN_SHARPNESS:
            return False, "Blurry", metrics, 0.0

        q = (min(1.0, score)
             * min(1.0, side / 110.0)
             * (1.0 - min(abs(yaw), MAX_YAW) / (MAX_YAW * 1.5))
             * min(1.0, sh / 30.0))
        return True, "ok", metrics, float(max(q, 0.05))


# =====================================================================
# TRACKER
# =====================================================================
class Track:
    _next_id = 1

    def __init__(self, bbox, now):
        self.id = Track._next_id
        Track._next_id += 1
        self.bbox = np.array(bbox, np.float32)
        self.vel = np.zeros(4, np.float32)
        self.last_seen = now
        self.created = now
        self.matched_now = False
        # identity state
        self.embs = deque(maxlen=EMB_BUFFER)      # (embedding, quality)
        self.votes = deque(maxlen=VOTE_WINDOW)
        self.good_samples = 0
        self.reasons = deque(maxlen=7)            # recent rejection reasons -> stable on-screen label
        self.confirmed_id = None                  # employee_id once identity is confirmed
        self.confirmed_name = ""
        self.confirmed_score = 0.0
        self.recorded_at = 0.0
        self.last_verify = 0.0
        self.disagree = 0
        self.best_q = 0.0
        self.best_frame = None                    # raw frame at best quality (used for the snapshot)
        self.best_bbox = None
        # display
        self.label = "Unknown"
        self.color = (0, 0, 255)

    def update(self, bbox, now):
        bbox = np.asarray(bbox, np.float32)
        dt = max(now - self.last_seen, 1e-3)
        self.vel = 0.5 * self.vel + 0.5 * (bbox - self.bbox) / dt
        self.bbox = 0.6 * bbox + 0.4 * self.bbox      # light smoothing, removes jitter
        self.last_seen = now
        self.matched_now = True

    def display_box(self, now):
        missed = now - self.last_seen
        return self.bbox + self.vel * min(missed, 0.4) if missed > 0 else self.bbox

    def fused_embedding(self):
        if not self.embs:
            return None
        e = sum(q * v for v, q in self.embs)
        n = np.linalg.norm(e)
        return e / n if n > 0 else None

    def reset_identity(self):
        self.embs.clear()
        self.votes.clear()
        self.good_samples = 0
        self.confirmed_id = None
        self.confirmed_name = ""
        self.disagree = 0
        self.best_q = 0.0


class FaceTracker:
    def __init__(self):
        self.tracks: list[Track] = []

    def update(self, dets: list, now: float):
        """Match detections to tracks. Returns list of (track, det)."""
        for t in self.tracks:
            t.matched_now = False

        pairs = []
        for ti, t in enumerate(self.tracks):
            pb = t.display_box(now)
            tw, th = pb[2] - pb[0], pb[3] - pb[1]
            tc = np.array([(pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2])
            for di, d in enumerate(dets):
                s = iou(pb, d["bbox"])
                if s < TRACK_IOU:  # fast movers: fall back to centre distance
                    dc = np.array([(d["bbox"][0] + d["bbox"][2]) / 2, (d["bbox"][1] + d["bbox"][3]) / 2])
                    dist = float(np.linalg.norm(tc - dc)) / max(tw, th, 1.0)
                    s = 0.1 * (1.0 - dist) if dist < 0.9 else 0.0
                if s > 0:
                    pairs.append((s, ti, di))
        pairs.sort(reverse=True)

        used_t, used_d, result = set(), set(), []
        for s, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            self.tracks[ti].update(dets[di]["bbox"], now)
            result.append((self.tracks[ti], dets[di]))

        for di, d in enumerate(dets):
            if di not in used_d:
                t = Track(d["bbox"], now)
                t.matched_now = True
                self.tracks.append(t)
                result.append((t, d))

        self.tracks = [
            t for t in self.tracks
            if now - t.last_seen <= (TRACK_TTL_CONFIRMED if t.confirmed_id is not None else TRACK_TTL)
        ]
        return result