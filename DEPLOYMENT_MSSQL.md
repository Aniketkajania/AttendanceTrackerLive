# Deploying Attendance Tracker with SQL Server (SSMS)

Target layout: **one Linux (or Windows) app server** running the API + recognition engine,
**SQL Server** on the same or another host, **nginx** serving the React build over HTTPS.

## 0. Architecture after the change
```
IN/OUT cameras --RTSP--> server_engine.py ----\
                                               >--> SQL Server (pyodbc) <--- main.py (FastAPI) <--- nginx <--- browser
enrollment_photos/, snapshots/  (shared disk) -/
```
Both Python programs must see the SAME `DATA_DIR` (photos + snapshots) and the same DB.

## 1. Create the database (SSMS)
1. Connect to your SQL Server in SSMS (needs sysadmin for the first run).
2. Open `schema_mssql.sql`, **change the password** in the `CREATE LOGIN attendance_app` line, press F5.
   It creates the database, 5 tables, indexes and a least-privilege login (`db_datareader` + `db_datawriter` only).
3. Confirm: `SELECT name FROM sys.tables;` shows users, cameras, attendance_logs, daily_attendance, admin_users.
4. SQL Server must accept TCP/IP: *SQL Server Configuration Manager -> Network Configuration -> TCP/IP = Enabled*
   (default port 1433), restart the service, and allow 1433 **only from the app server's IP** in the firewall.
   If the login fails, check *Server Properties -> Security -> SQL Server and Windows Authentication mode*.

## 2. Prepare the app server (Ubuntu 22.04/24.04 example)
```bash
sudo apt update && sudo apt install -y python3-venv python3-dev build-essential unixodbc-dev \
     libgl1 libglib2.0-0 ffmpeg nginx curl gnupg
# Microsoft ODBC Driver 18
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/msprod.gpg
curl -fsSL https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list | \
     sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt update && sudo ACCEPT_EULA=Y apt install -y msodbcsql18
sudo useradd -r -m -d /srv/attendance attendance
```
(Windows host: install "ODBC Driver 18 for SQL Server" from Microsoft; skip apt steps.)

## 3. Deploy the code
```bash
sudo -u attendance bash
cd /srv/attendance && git clone <your-repo> app && cd app      # or copy this folder
python3 -m venv ../venv && source ../venv/bin/activate
pip install -r requirements.txt                                 # GPU server: pip install onnxruntime-gpu instead of onnxruntime
mkdir -p /srv/attendance/data
cp .env.example .env && nano .env                               # fill in DB_*, JWT_SECRET, SMTP, DATA_DIR
chmod 600 .env
python database_setup.py                                        # must print [OK] ... all tables present
python create_admin.py                                          # first portal login (role: admin)
```

## 4. Build the frontend
```bash
cd frontend && npm ci && npm run build        # creates frontend/dist (nginx serves this; the Vite dev proxy is not used in production)
```

## 5. Run as services
```bash
sudo cp deploy/attendance-*.service /etc/systemd/system/
sudo cp deploy/nginx-attendance.conf /etc/nginx/sites-available/attendance
sudo ln -s /etc/nginx/sites-available/attendance /etc/nginx/sites-enabled/
# put your TLS cert at /etc/ssl/attendance/ (or run: sudo certbot --nginx)
sudo systemctl daemon-reload
sudo systemctl enable --now attendance-api attendance-engine
sudo nginx -t && sudo systemctl reload nginx
journalctl -u attendance-engine -f      # look for: [ENGINE] Using ..., [STREAM] <camera>: connected
```
The first start downloads the `antelopev2` model (~350 MB) to `/srv/attendance/.insightface` - make sure the server has internet once.

## 6. First-run checklist
1. Open `https://attendance.yourcompany.com`, log in with the admin you created.
2. **Cameras** page: add each camera (RTSP URL parts). The server must be able to reach the camera LAN
   (VPN / site-to-site if cameras are in other offices). Test: `ffprobe rtsp://user:pass@ip:554/path` from the server.
3. **Register Employee**: enroll one person, then in SSMS run
   `SELECT employee_id, LEN(face_embedding) FROM users;` to confirm the embedding stored.
4. Walk past the camera; within ~60 s of enrollment you should see a row in `daily_attendance`
   and a log line in `journalctl -u attendance-engine`.

## 7. What changed in the code (and why)
| File | Change |
|---|---|
| `db.py` (new) | pyodbc connection helper + `query/execute`; dict-style rows so existing code works unchanged |
| `schema_mssql.sql` (new) | T-SQL tables, constraints, indexes, app login |
| `config.py` | `DB_*` settings, absolute `PHOTOS_DIR/SNAPSHOTS_DIR` via `DATA_DIR`, `ALLOWED_ORIGINS`, `COOKIE_SECURE`, env-driven `SIMILARITY_THRESHOLD` and `SHOW_PREVIEW` |
| `main.py` | all `sqlite3` removed; `ON CONFLICT` -> `MERGE`; `LIMIT` -> `TOP`; CORS from env; Linux-safe webcam open; model providers chosen from what is installed; employee delete is now a **soft delete** |
| `server_engine.py` | uses `db.connect`; headless by default; `cv2.CAP_DSHOW` only on Windows; clean stop on `systemctl stop`; loads only active employees |
| `auth.py` / `users_api.py` / `create_admin.py` | SQL Server access; auth cookie gets `Secure` flag in production; `MERGE` for admin upsert |
| `database_setup.py` | now only a **non-destructive** connection/table check (old one dropped tables) |
| `portal_app.py` | removed (old Streamlit app, SQLite-only) |
| `requirements.txt`, `.env.example`, `deploy/` (new) | missing deps (`aiortc`, `av`, `pyodbc`), config template, systemd + nginx |

Data-type note: dates/times are still stored as text (`YYYY-MM-DD`, `YYYY-MM-DD HH:MM:SS`) exactly like before, so the
engine and React code need no changes. You can migrate to `DATE`/`DATETIME2` later as a separate task.

## 8. Things you must still decide / watch
* **Duplicate RTSP sessions.** The engine and the portal's live view (`main.py` WebRTC) each open the camera. Many IP cameras
  allow only 2-4 sessions. Use the camera's sub-stream for live view or limit live view to admins.
* **WebRTC live view through nginx/NAT** needs UDP reachability to the API host. If the video never starts, add a STUN/TURN
  server (e.g. coturn) in `RTCPeerConnection(RTCConfiguration(iceServers=[...]))` in `main.py` and `new RTCPeerConnection({iceServers:[...]})` in `Cameras.jsx`.
* **Camera passwords** are plain text in `cameras.password`. Restrict DB access, or encrypt with SQL Server Always Encrypted / a Fernet key in `.env`.
* **Face embeddings are biometric data.** Enable TDE on the database, encrypted backups, TLS (`DB_ENCRYPT=true`), and check DPDP/GDPR consent requirements.
* **Backups.** Schedule full + log backups for `AttendanceTracker` and back up `DATA_DIR` (photos/snapshots) with it.
* **Single engine instance only.** Cooldown is in memory; two engines would double-punch. Run exactly one `attendance-engine`.
* **Performance.** CPU-only handles a few cameras; use an NVIDIA GPU (`onnxruntime-gpu`) for more. Consider purging old snapshots (cron).
* **Threshold mismatch.** README says 0.48, code defaulted to 0.45. Now set `SIMILARITY_THRESHOLD` in `.env`; tune with real data.
* **Rotate secrets.** `database_setup.py` in the old repo seeded a camera with credentials in history; rotate any real camera password that was ever committed.
