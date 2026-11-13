-- Run in SSMS on the Windows SQL Server BEFORE schema_mssql.sql.

-- 1) Must return 0, otherwise the SQL login 'attendance_app' cannot connect.
SELECT SERVERPROPERTY('IsIntegratedSecurityOnly') AS WindowsAuthOnly;   -- 0 = mixed mode (good), 1 = fix below
-- Fix: SSMS > right-click server > Properties > Security > "SQL Server and Windows Authentication mode" > OK, then restart the SQL Server service.

-- 2) Check the port you are listening on (should be 1433)
SELECT local_tcp_port FROM sys.dm_exec_connections WHERE session_id = @@SPID;

-- 3) After the app is live: nightly backup (SQL Server Express has no SQL Agent -> schedule this with Windows Task Scheduler + sqlcmd)
-- BACKUP DATABASE AttendanceTracker TO DISK = N'D:\Backups\AttendanceTracker.bak' WITH COMPRESSION, CHECKSUM, INIT;
