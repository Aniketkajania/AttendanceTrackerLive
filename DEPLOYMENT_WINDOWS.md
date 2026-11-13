# Windows SQL Server: what is different

Works with the code you already have (`schema_mssql.sql`, `db.py`, `.env`). Only the setup around it changes.
Pick **Option A** (app on the same Windows server, simplest) or **Option B** (app on a separate Linux box; follow `DEPLOYMENT_MSSQL.md` for the app side and use Section 1 below for the database side).

## 1. Prepare SQL Server on Windows (both options)
1. **Mixed-mode authentication.** Run `deploy/windows/sqlserver_windows_setup.sql` (first query). If it returns 1, switch to
   *SQL Server and Windows Authentication* (SSMS > Server Properties > Security) and restart the *SQL Server (MSSQLSERVER)* service.
2. **Enable TCP/IP with a fixed port** (needed unless the app runs on the same machine):
   *SQL Server Configuration Manager > SQL Server Network Configuration > Protocols for <instance> > TCP/IP = Enabled*.
   Open TCP/IP > **IP Addresses** tab > scroll to **IPAll**: clear *TCP Dynamic Ports*, set *TCP Port* = `1433`. Restart the SQL service.
   (Express / named instances use a random dynamic port by default; this is the usual reason for "cannot connect".)
3. **Windows Firewall** (elevated PowerShell), only for the app server's IP:
   `New-NetFirewallRule -DisplayName "SQL 1433 from app" -Direction Inbound -Protocol TCP -LocalPort 1433 -RemoteAddress <APP_SERVER_IP> -Action Allow`
4. **Run `schema_mssql.sql`** in SSMS (change the password on the `CREATE LOGIN` line first).
5. **Connection string in `.env`:**
   * Default instance: `DB_SERVER=10.0.0.20,1433`
   * Named instance with fixed port (recommended): `DB_SERVER=10.0.0.20,1433`
   * Named instance via SQL Browser (`DB_SERVER=10.0.0.20\SQLEXPRESS`): needs the *SQL Server Browser* service running and UDP 1434 open. Avoid; use the fixed port.
   * Certificate: a fresh Windows SQL Server uses a self-signed cert, so set `DB_ENCRYPT=true` and `DB_TRUST_CERT=true`.
     To remove the need for that, install a CA-signed certificate (Configuration Manager > Protocols > Properties > Certificate tab).
6. **Test from the app machine:** `Test-NetConnection 10.0.0.20 -Port 1433` must say `TcpTestSucceeded : True`, then `python database_setup.py`.

## 2. Option A: everything on the Windows server
1. Install: Python 3.10+, Node 18+, Git, **ODBC Driver 18 for SQL Server** (Microsoft download), NSSM, Caddy (or IIS), and the VC++ Redistributable.
   For an NVIDIA GPU also install the CUDA/cuDNN versions that match your `onnxruntime-gpu`.
2. Copy the project to `C:\attendance\app`, copy `.env.example` to `.env` and set:
   ```
   DB_SERVER=localhost,1433
   DB_USER=attendance_app
   DB_PASSWORD=...
   DB_TRUST_CERT=true
   DATA_DIR=C:\attendance\data
   COOKIE_SECURE=true
   ALLOWED_ORIGINS=https://attendance.yourcompany.com
   ```
   *Optional Windows authentication:* set `DB_TRUSTED=true` (leave `DB_USER/PASSWORD` blank), create a Windows service account, and in SSMS run
   `CREATE LOGIN [DOMAIN\svc_attendance] FROM WINDOWS; USE AttendanceTracker; CREATE USER [DOMAIN\svc_attendance] FOR LOGIN [DOMAIN\svc_attendance]; ALTER ROLE db_datareader ADD MEMBER [DOMAIN\svc_attendance]; ALTER ROLE db_datawriter ADD MEMBER [DOMAIN\svc_attendance];`
   then run both services under that account (commented line in the script). This removes the DB password from `.env`.
3. `python database_setup.py` then `python create_admin.py`.
4. `cd frontend; npm ci; npm run build`
5. Run `deploy\windows\install_services.ps1` as Administrator (creates the `AttendanceAPI` and `AttendanceEngine` services, auto-start, auto-restart, logs in `C:\attendance\logs`).
6. Web server: use `deploy\windows\Caddyfile` (serves `frontend\dist`, proxies `/api`, `/snapshots`, `/photos` to port 8000, handles HTTPS).
   Open 443 in Windows Firewall. IIS + ARR works too, but Caddy needs one file.
7. Check: `Get-Content C:\attendance\logs\engine.log -Wait` should show `[ENGINE] Using ...` and `[STREAM] <camera>: connected`.

## 3. Windows-specific cautions
* **Do not run the engine in a logged-in desktop session.** Services run headless; leave `SHOW_PREVIEW=false`.
* **Windows Update reboots** will stop everything; the services auto-start, but set active hours / maintenance window.
* **Long paths / spaces:** keep the project and `DATA_DIR` on a short path without spaces (`C:\attendance`).
* **Antivirus** scanning `snapshots\` can slow writes; exclude `C:\attendance\data`.
* **Backups:** SQL Express has no SQL Agent. Use Task Scheduler + `sqlcmd -S localhost -Q "BACKUP DATABASE AttendanceTracker TO DISK='D:\Backups\AT.bak' WITH COMPRESSION, CHECKSUM, INIT"`, and copy `C:\attendance\data` too.
* **SQL Express limits:** 10 GB per database, 1 GB RAM for the engine. Fine for embeddings + logs for a long time; snapshot images live on disk, not in the DB.
* **Resources:** the face model and SQL Server will compete for RAM on one box; cap SQL Server's *max server memory* (Server Properties > Memory) to leave ~4-6 GB for the engine.
