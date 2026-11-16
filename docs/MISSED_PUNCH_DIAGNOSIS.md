# Diagnosing registered employees shown as Unknown

The attendance recognition process is **server_engine.py**, NOT the IIS React frontend or the FastAPI `main.py` service. A preview rendering correctly does not prove that the recognition process has detected, matched or recorded a punch.

## New read-only diagnostics
After pulling this branch and restarting the **recognition engine in a controlled maintenance window** (do not restart it during attendance rush), watch the console or engine log:
- `[MATCH_REJECT] ... reason=quality_too_small`: the detected face is too small; verify camera distance, lens and actual recognition-stream pixels
- `quality_blurry`: motion blur, low shutter speed, poor lighting or compression
- `quality_side_face`: steep face angle; review camera placement and enrollment angles
- `quality_low_conf`: low detector confidence
- `low_similarity`: a valid face embedding was generated but did not reach the face-match threshold. This can indicate poor enrollment images, different camera angle/lighting, or a mismatched recognition model
- `ambiguous_identity`: best candidate is too close to second best; **do not remove the margin check** because that risks recording a wrong employee
- `waiting_for_confirmation`: match is promising but a second observation is needed; if the employee leaves quickly, investigate scan rate and number of cameras competing for CPU
- `no_active_enrollments`: engine has no active identities loaded. Check database connectivity and whether the employee is active.
- `[RECOGNITION] ... attendance=queued`: recognition succeeded and was queued; **this does NOT mean SQL committed**
- `[EVENTS] committed ...`: SQL transaction was committed; recognition event time is retained even if writer processing was delayed
- `[EVENTS] failed to record a punch`: SQL writing failed and requires investigation. The connection now rolls back and closes cleanly; failed punches are **not yet durably retried**.
- `[STATS] ... scanned .../s | detect ...ms | embed ...ms | rejections ...`: 30-second aggregate statistics per camera

Scores and image-quality measurements are diagnostics, not a substitute for validation on genuinely labeled employee images. Logs intentionally contain no face photos or embedding vectors.

## Safe investigation of one missed employee
1. Record the camera ID and approximate time of one missed event. Do not publish their face photo, full name or employee ID in debugging messages.
2. Check the recognition engine's `[STATS]` for that camera: decoded input FPS, scanned FPS, frame age, detection and embedding milliseconds.
3. Check the `[MATCH_REJECT]` reason during the encounter.
4. If `low_similarity` dominates: verify the engine says `recognizer: ...` for the same buffalo_l model family as the enrollment API, then re-enroll the affected employee with **well-lit, sharp front and neutral photos**; optional real camera frames can help when acquired with permission.
5. If `waiting_for_confirmation` dominates: compare time in view with scan rate. Consider camera placement and CPU/GPU scaling rather than weakening identity confirmation thresholds.
6. If quality gates dominate: adjust capture setup (distance, angle, lighting/shutter speed) and verify the recognition feed is the main stream, not the preview substream.
7. If `attendance=queued` but no SQL row: check `[EVENTS]` and SQL availability, queue fullness, and punch cooldown. Do not infer successful write from a green overlay.
8. If `DETECTION_PROFILE=fast` is set in the recognition engine environment, test `quality` in an isolated checkout or maintenance window and measure scan throughput. `quality` uses larger detector inputs, which can become *slower* on a four-core CPU. Do not automatically switch production profiles without testing.

## Safeguards
- Keep `SIMILARITY_THRESHOLD`, `MATCH_MARGIN`, `CONFIRM_VOTES` and `COOLDOWN_SECONDS` unchanged until actual rejection reasons are observed.
- Never make an Unknown face automatically punch as the nearest employee.
- SQL connection cleanup and timestamp preservation are reliability hardening, **not** a guarantee against lost events in outages. Durable retry plus idempotency is a separate stage.
- Do not restart `AttendanceTrackerAPI` in place of the recognition engine: its startup is independent.
- Continuous on-disk diagnostic retention may reveal sensitive behavioral patterns. Restrict access and retention of any redirected engine logs.
