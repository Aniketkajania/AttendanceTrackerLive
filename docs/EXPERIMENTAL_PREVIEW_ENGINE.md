# Experimental preview engine (no attendance writes)

This is a **separate test entrypoint**: `experimental_preview_engine.py`. It is **not** used by `AttendanceTrackerEngine` (NSSM), FastAPI, or IIS. It reads active camera configuration and existing enrollment vectors using **SQL SELECT** only, and never writes attendance logs, alters the current engine, saves video/images, or sends messages.

## Run in a Windows desktop session

```powershell
cd C:\AttendanceTracker_mssql\at_mssql
git pull origin feature/camsec-capabilities
& ".\.venv\Scripts\Python.exe" experimental_preview_engine.py --camera HO_IN
```

Press **Q** in the OpenCV preview to quit; or Ctrl+C in its terminal. For face detection only (does not generate identity embeddings), add `--detect-only`. To test a consented offline video, pass `--video C:\path\to\test.mp4` instead of `--camera HO_IN`.

**Do not install this experimental engine as a Windows service.** It requires an interactive desktop for the preview. Start with **one camera at a time** in a controlled off-peak window: it will add camera stream and CPU load while your current production service continues independently.

## What is experimental

- Entire frame scanned without an entrance-only ROI, plus one high-detail 2×2 tile per frame (rotating through all four areas).
- Experimental gate for testing distant/moderate side poses: minimum face side 20px, detector confidence 0.35, sharpness 8 and pose proxy absolute value ≤2.2. These are **not** safe thresholds for production without validation.
- Reuse the currently enrolled `buffalo_l` embedding gallery from SQL (read-only). Displays `TEST MATCH` only after two matching samples with a 0.40 score threshold and distinct-candidate margin. A green test label is **not** evidence of a safe production identity threshold.
- Displays face-size/blur/pose failure reasons; 30-second console summary. No photographs, videos, attendance events, or unknown-face identities are persisted.

This first experimental version does **not yet** build separate embedding templates from all four enrollment pictures or compare a different detector/model. Test detection, angled pose and baseline recognition first; evaluate any new model and multi-template gallery offline before considering production integration.

For a proper evaluation, test consenting registered volunteers walking normally under various positions, and unregistered people, tracking correct identifications, false matches, missed faces, and frame-by-frame quality. Tiny or heavily occluded faces may remain impossible to identify reliably.
