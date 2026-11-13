# CamSec-style capability matrix — development branch only

This is a **CamSec-inspired implementation**, not CamSec AI Pro source code or a claim of feature parity. CamSec publishes modular attendance, visitors, security alerts, traffic and HR workflows; exact commercial behavior remains proprietary.

| Feature | Current development status | Notes |
|---|---|---|
| CCTV RTSP / webcam setup | Existing | Test per camera; ffmpeg absent on current Windows server |
| Live face detection and recognition | Existing + experimental optimizations | CPU-limited; measure false matches and misses before rollout |
| Employee face enrollment | Existing + image quality check | Up to four photos, server extraction |
| Attendance IN/OUT audit and Excel | Existing | Existing gate-role-based punch semantics |
| Employee account roles | Existing | Admin, HR, viewer; custom permission builder not implemented |
| Shifts and assignments | Backend/UI implemented | SQL migration 001 required |
| Leave requests and approvals | Backend/UI implemented | SQL migration 001 required |
| Visitor register and checkout | Backend/UI implemented | SQL migration 001 required; manual only |
| Areas | Backend/UI implemented | SQL migration 001 required |
| Camera-to-area mapping | Newly implemented | SQL migration 002 required; administrative only |
| Analytics overview | Implemented | Derived from existing attendance/leave/visitor tables |
| Hourly and per-camera activity | Newly implemented | Verified punches only, NOT anonymous people counting |
| Shift-aware daily roster and CSV | Newly implemented | Overnight/unassigned schedules flagged for review |
| Anonymous people counting and genuine footfall | NOT implemented | Requires person detector + tracker + validated line-crossing algorithm |
| Unknown person alerts / intrusion detection | NOT implemented | Requires explicit event definitions, privacy controls, calibration |
| Multi-camera cross-camera identity tracking | NOT implemented | Separate high-risk and compute-intensive capability |
| Real-time alert delivery and mobile app | NOT implemented | Requires notification infrastructure |
| Dedicated GPU/50+ concurrent cameras | NOT deployed | Benchmark on suitable hardware before expanding |
| Night shift payroll-grade rules/holidays/overtime | NOT implemented | Daily report intentionally marks overnight shifts for review |
| Production validation | NOT completed | GitHub CI only checks syntax/build; actual SQL and CCTV test pending |

## SQL migration and safe testing
- Use a **separate test checkout and cloned SQL database**. Both migrations are additive but have never been verified against your specific schema on the Windows server.
- Run `migrations/001_camsec_operations.sql` first (it uses `USE AttendanceTracker`; change or remove that line for your TEST database), followed by `migrations/002_camera_area_mapping.sql` in the correct database context.
- Existing attendance recorder continues to write to SQL. Do not start a second `server_engine.py` attached to production SQL, or duplicate attendance events/emails may result.
- Deploy only after snapshot and DB backups, role checks and approval from camera/biometric data custodians.

## New endpoints
- `GET /api/operations/reports/daily?work_date=YYYY-MM-DD[&location=...]`
- `GET /api/operations/reports/daily.csv?work_date=YYYY-MM-DD[&location=...]`
- `GET /api/operations/analytics/activity?work_date=YYYY-MM-DD`
- `GET /api/operations/camera-areas`
- `POST /api/operations/camera-areas` (admin only)

The UI keeps the existing Gateway Distriparks corporate design.

**Accuracy caveats:** 'Absent estimate' is not a payroll decision. The shift report handles straightforward day shifts; overnight crossings, holidays and flexible shifts need separate reconciliation. A camera event counter is not equivalent to unique people counting.
