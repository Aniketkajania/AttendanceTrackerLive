# Live recognition performance notes (server_engine.py)

The FastAPI face-detection endpoint is not the live recognition engine. The live recognizer is started separately with `python server_engine.py`.

## Changes in this branch
- Raised unconfirmed track expiry from 0.5 to 2.0 seconds and confirmed track expiry from 0.5 to 2.5 seconds. On a CPU-only multi-camera machine, scans can take long enough to lose identity and fail the two-vote confirmation.
- Each iteration prioritizes the camera that was scanned least recently rather than always putting the first configured camera first. Inference is still single-threaded; this makes scheduling fairer but does not multiply CPU throughput.
- Rejects incoming frames older than 1.25 seconds so attendance is not based on outdated frames.
- Motion gating now defaults OFF, because a stationary person should be detected promptly, not on a periodic idle scan.
- Conditional frame enhancement defaults OFF to save expensive full-frame color conversions; turn it on if your entrance is genuinely underexposed.
- Near-track recovery runs at most once per scanned frame by default instead of once for every missed face.
- Default decode input width is now 1280px instead of 1920px; output face size decreases, so test recognition accuracy at your actual gate distance.
- Logs a 30-second [STATS] line per camera containing input fps, scans per second, milliseconds per scan and average decoded-frame age.

## Configurable test settings (set in a test environment, not the production service)
```env
DECODE_FPS=8
STREAM_MAX_WIDTH=1280
INFER_EVERY=0.08
UNCONFIRMED_TRACK_TTL=2.0
CONFIRMED_TRACK_TTL=2.5
MAX_FRAME_AGE=1.25
MOTION_GATE=0
ENABLE_ENHANCEMENT=0
NEAR_RECOVERY_LIMIT=1
SHOW_PREVIEW=0
```

The safest production tuning keeps the face quality/match thresholds, tracking confirmation votes and recognition model unchanged until validation proves new values are safe.

## Verify safely
Do not run a second live engine pointing at the production attendance database. The independent engine will write real attendance logs and send emails. Prefer a cloned test SQL database with nonproduction cameras and SMTP_ENABLED=false.
Capture [STATS] output for at least 2 minutes while people enter. Collect the camera count, CPU use, frame age, average scan time, detection-to-attendance latency and missed detections. If frame age is large, inspect network/decoder; if scan ms is high, inspect ONNX provider, CPU and resolution. Runtime acceleration depends on the actual Windows Server model and ONNX provider availability.

The new changes are a measured optimization starting point, not a promise of immediate recognition on any hardware. The single inference worker is still a throughput limit under high camera counts; deeper per-camera inference scheduling may require a hardware benchmark, model replication or dedicated inference service.

## Measuring recognition latency (latest test branch)
A new `[RECOGNITION]` log line is printed once, when a track is confirmed. Its `detected_to_confirm` value starts at the **first detected face track**, not the moment a person enters the camera's view. `first_embedding_to_confirm` starts after the first successful embedding extraction. `attendance=queued` means the event was placed on the writer queue; it does **not** mean SQL has committed it. `attendance=not_queued_or_cooldown` commonly indicates the existing attendance cooldown, and may be expected.

The normal `[STATS]` output adds the number of confirmed tracks and average detect-to-confirm duration for each camera during its reporting interval. The detector and embedding timings are also reported.

For an honest end-to-end latency benchmark, record the moment a test participant first appears on camera separately, and measure through SQL commit with a safe test database. Run controlled trials with consenting participants: walking quickly, slowly, near and far, and looking away. Repeatedly verify correct identities and misses. Do not lower similarity thresholds to improve apparent latency.
