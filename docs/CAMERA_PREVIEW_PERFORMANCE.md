# Camera preview performance — development branch

This changes **browser camera previews** in `frontend/src/pages/Cameras.jsx` and `main.py`. It does NOT alter `server_engine.py`, face-recognition models, enrollment, or SQL schema.

## Behavior
- The camera wall **automatically starts previews** for cameras visible in the browser viewport. No Start Preview click is needed. When scrolling, active streams switch to on-screen cameras.
- A maximum of **two browser WebRTC previews** are active in this tab on the present CPU server. If three cards are simultaneously visible, the third indicates it is queued until one of the first two leaves the viewport; expanding a card gives it priority.
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
1. Pull development branch in a **test checkout**. The newest change is only to React, so Vite can hot-reload it; restart the test FastAPI process only if it is not already running the earlier preview backend optimizations.
2. Leave the production IIS/NSSM and attendance engine running unchanged. Avoid testing simultaneous high-resolution feeds if the server CPU is already overloaded.
3. Open Camera Wall: the first visible feeds start automatically. Confirm that there is no overlapping hover badge or Start Preview button.
4. Check that the first visible camera shows video or a visible error within ~12s. Check frame age and reconnect count.
5. With three visible cards, verify that only two auto-play and the third is queued. Scroll until a different card enters the viewport; the streams should switch without clicking a Start Preview button.
6. Navigate away from Camera Wall; after the idle interval, background RTSP preview workers should stop.
7. Compare CPU and memory use before and after, and observe actual attendance engine scan FPS. A shared decode pipeline or dedicated media gateway is still needed for large fleets.

## Limitations
- This is a **resource-limited auto-preview grid**, not a true 50-simultaneous-live-stream CCTV wall. For all 50 tiles to update simultaneously, use camera substreams plus a dedicated streaming gateway/NVR and validate network, browser decoding and hardware limits.
- The server still opens a second camera RTSP connection separate from `server_engine.py` while a browser preview is active.
- It still uses CPU decoding and aiortc encoding; the browser limit applies per tab, not as a fleet-wide admission control.
- A camera's read timeout, substream support, initial keyframe wait and WebRTC connectivity vary by installation.
- Camera health is reported **on preview demand**, not a continuous fleet-wide monitoring/alert service.
- No claim of 50+ simultaneous live previews or verified latency before actual server tests.
