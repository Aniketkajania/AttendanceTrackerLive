# Camera preview performance — development branch

This changes **browser camera previews** in `frontend/src/pages/Cameras.jsx` and `main.py`. It does NOT alter `server_engine.py`, face-recognition models, enrollment, or SQL schema.

## Behavior
- The camera wall starts **zero video streams** on opening the page. Press **Start live preview** or click a card to open it.
- A maximum of **two browser WebRTC previews** are active in this tab; opening a third closes the oldest preview.
- Startup shows **Connecting...**, fails visibly after **12 seconds**, and offers **Retry stream**.
- The FastAPI preview worker delivers at most **10 FPS** and downscales frames to max **640 px width** by default. A camera's main RTSP video still has to be decoded, so a real camera substream can further improve CPU load.
- Preview workers auto-stop after **30 seconds** without frame requests, freeing their RTSP connection; currently open pages may maintain their own worker.
- Preview card metrics from `GET /api/cameras/{camera_id}/metrics` report `connected`, `frame_age_ms`, `status`, and `reconnects`. **Enabled in the database does not imply online.**
- OpenCV FFmpeg mode requests a five-second connect/read timeout where supported. RTSP connection establishment may still take longer on particular driver builds.

## Optional environment settings for test API
```cmd
set PREVIEW_MAX_WIDTH=640
set PREVIEW_FPS=10
set PREVIEW_IDLE_SECONDS=30
```
Optional only for a homogeneous group of cameras with an explicitly verified low-resolution stream path:
```cmd
set PREVIEW_RTSP_PATH=/Streaming/Channels/102
```
**DO NOT** set `PREVIEW_RTSP_PATH` unless every camera on that API server supports that exact route. For mixed camera models, leave it unset and use the existing stored RTSP paths. No camera DB or attendance model settings are changed.

## Safe test
1. Pull development branch in a **test checkout** and restart only its FastAPI process; Vite reloads the React code.
2. Leave the production IIS/NSSM and attendance engine running unchanged. Avoid testing simultaneous high-resolution feeds if the server CPU is already overloaded.
3. Open Camera Wall: no RTSP worker should start until Start live preview is clicked.
4. Open one camera: it should show video or a visible error within ~12s. Check frame age and reconnect count.
5. Open a second camera. Verify both are responsive. Open third: oldest browser preview should pause.
6. Stop previews; wait >30s; status should transition to idle and the RTSP workers should stop.
7. Compare CPU and memory use before and after, and observe actual attendance engine scan FPS. A shared decode pipeline or dedicated media gateway is still needed for large fleets.

## Limitations
- The server still opens a second camera RTSP connection separate from `server_engine.py` while a browser preview is active.
- It still uses CPU decoding and aiortc encoding; the browser limit applies per tab, not as a fleet-wide admission control.
- A camera's read timeout, substream support, initial keyframe wait and WebRTC connectivity vary by installation.
- Camera health is reported **on preview demand**, not a continuous fleet-wide monitoring/alert service.
- No claim of 50+ simultaneous live previews or verified latency before actual server tests.
