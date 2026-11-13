# Test deployment checklist — operations features

This branch is **not** live. CI verifies that the React frontend builds, Python compiles, and mocked operations API tests pass. A live SQL Server and real cameras are not available to the GitHub runner.

## Preconditions
1. Back up the existing database, and create a **TEST database** with the current core tables `users`, `cameras`, `daily_attendance`, `attendance_logs` and `admin_users`.
2. Point an **isolated backend** at the TEST database. Do not start another `server_engine.py` against the production attendance database.
3. In SSMS, switch to the TEST database and run **only** `migrations/003_operations_setup_no_leaves.sql` to set up shifts, visitors, areas and camera mappings. It is idempotent and doesn't delete core records. Avoid rerunning `001_camsec_operations.sql` just to add these tables because that script creates a legacy leave module that is no longer used.
4. Start the test FastAPI API on an available port, e.g. `uvicorn main:app --host 127.0.0.1 --port 8001`. Configure Vite's proxy to target that port for an isolated test, and run `npm run dev` inside `frontend`. Do not stop IIS or NSSM production services.

## Quick diagnostics
Log in as **admin** to the TEST API and open `/api/operations/readiness`. Expected response:
```json
{"ready":true,"missing_tables":[],"setup_script":"migrations/003_operations_setup_no_leaves.sql"}
```
This uses only a read-only SQL query. A missing-table response means the SQL migration was not applied to the database used by the test API.

## Manual smoke tests (test records only)
1. **Shift Management:** create a 09:00-18:00 shift; assign it to a test employee; reload and confirm assignment.
2. **Visitors:** register a test visitor; confirm visible in list; check them out; verify timestamp and that a repeat checkout is blocked.
3. **Area Selection:** create an area, map an existing test camera; reload; confirm mapping.
4. **Daily Reports:** select a date/location; verify roster against known test records; export CSV; confirm spreadsheet-safe names and statuses.
5. **Analytics:** verify counts against `daily_attendance` and `attendance_logs`; activity counts are **accepted punches**, not physical footfall.
6. **Roles:** viewer must not create shifts or camera mappings; HR may manage visitors and employee-shift assignments but cannot create a shift.
7. **Regression:** check live attendance, face enrollment, audit logs, camera management and Excel export.
8. **UI:** resize the browser to confirm Area Selection remains scrollable above the fixed profile card.

## Boundaries
- `Not recorded` and `NO_PUNCH_SCHEDULED` do not prove absence.
- Overnight shifts are flagged for review; payroll calculations are not fully implemented.
- SQL Server-specific behavior (constraints and commits) must be verified on a test SQL Server.
- Person counting, unknown-person alerts, multi-camera re-identification and 50-camera throughput remain separate, **unimplemented** capabilities.
- **Never merge/deploy** before actual SQL and functional tests and explicit approval from system owners.
