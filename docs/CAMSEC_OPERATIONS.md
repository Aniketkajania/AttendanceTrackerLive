# CamSec-inspired features (existing Gateway visual design preserved)

This branch does **not** copy the CamSec UI. It retains the Gateway Distriparks React sidebar, light palette, login, existing employee enrollment, camera configuration, attendance and audit pages.

## Implemented in this branch
- Attendance analytics with daily staff, present, estimated absent, visitor, and approved-leave counts.
- Visitor register and checkout workflow.
- Shift definitions and employee shift assignment.
- Leave requests and HR/admin approval or rejection.
- Office area definitions.
- Access restrictions: HR/admin manage visitors and leave; admin creates shifts and areas; admin/HR assign shifts.
- Face detection precheck: `POST /api/face/detect` (admin/HR, JPEG/PNG multipart field `image`, 8 MB maximum); UI shows face quality and confirms at least one usable frontal photo. This is photo enrollment QA, not continuous camera event recognition.
- Camera API preview processing reduced to maximum 960px width, no added 33ms sleep after capture; camera diagnostics endpoint at `GET /api/cameras/{camera_id}/metrics`.

Detection checks may take multiple seconds on CPU-only Windows Server. A green CI build is not proof that InsightFace can load on the user's Windows installation.

These additions are **not** a complete equivalent of CamSec's proprietary product: visual people-counting, visitor facial recognition, liveness, shift-driven attendance calculations, area-to-camera association, granular custom roles, PDF reporting and full device-performance validation are not implemented. Do not advertise those features as delivered.

## Safe deployment
1. BACK UP your SQL Server database and current application directory.
2. Review and run `migrations/001_camsec_operations.sql` in SSMS against the intended database. This additive migration does not drop existing tables.
3. Update backend code and restart the FastAPI application (run in the existing venv). Do **not** run `database_setup.py` on your production database.
4. Build the frontend with `cd frontend && npm ci && npm run build`. Deploy `frontend/dist` using your existing IIS setup.
5. For RTSP performance, collect 30–60 seconds of `/api/cameras/{id}/metrics` and server CPU/GPU measurements before and after deployment. The engine's independent ffmpeg/InsightFace loop is separate from the API's OpenCV/WebRTC stream; both can consume resources. Camera credentials must never be logged.

## Known workflow limitations
- A leave request entered here requires admin or HR login; no employee self-service authentication exists.
- A shift assignment does not yet affect attendance lateness or midnight rollover calculations.
- "Absent estimate" counts approved leave but does not account for holidays or unassigned shifts.
- A camera preview worker is shared by sessions but aiortc still encodes a track for each viewer; high viewer counts may need an SFU or forwarded stream.
- SQL Server must have the migration applied before the new operations endpoints work.
