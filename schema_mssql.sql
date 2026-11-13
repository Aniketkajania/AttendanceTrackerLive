/* =====================================================================
   Attendance Tracker - SQL Server schema (idempotent: safe to re-run)
   Run in SSMS while connected to your SQL Server instance.
   ===================================================================== */
IF DB_ID(N'AttendanceTracker') IS NULL CREATE DATABASE AttendanceTracker;
GO
USE AttendanceTracker;
GO

/* 1. Employees + face embedding (512 floats as JSON) */
IF OBJECT_ID(N'dbo.users', N'U') IS NULL
CREATE TABLE dbo.users (
    id                  INT IDENTITY(1,1) PRIMARY KEY,
    employee_id         NVARCHAR(50)   NOT NULL,
    person_name         NVARCHAR(200)  NOT NULL,
    email               NVARCHAR(320)  NOT NULL,
    base_location       NVARCHAR(100)  NOT NULL,
    enrolled_photo_path NVARCHAR(500)  NULL,
    face_embedding      NVARCHAR(MAX)  NOT NULL,
    is_active           BIT            NOT NULL CONSTRAINT DF_users_active DEFAULT 1,
    created_at          DATETIME2(0)   NOT NULL CONSTRAINT DF_users_created DEFAULT SYSDATETIME(),
    CONSTRAINT UQ_users_employee UNIQUE (employee_id),
    CONSTRAINT UQ_users_email    UNIQUE (email)
);
GO

/* 2. Cameras (strict IN / OUT) */
IF OBJECT_ID(N'dbo.cameras', N'U') IS NULL
CREATE TABLE dbo.cameras (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    camera_id       NVARCHAR(50)  NOT NULL,
    camera_name     NVARCHAR(200) NOT NULL,
    location        NVARCHAR(100) NOT NULL,
    camera_role     NVARCHAR(3)   NOT NULL CONSTRAINT CK_cam_role CHECK (camera_role IN ('IN','OUT')),
    connection_type NVARCHAR(10)  NOT NULL CONSTRAINT CK_cam_conn CHECK (connection_type IN ('RTSP','WEBCAM')),
    webcam_index    INT           NULL CONSTRAINT DF_cam_idx DEFAULT 0,
    ip_address      NVARCHAR(100) NULL,
    port            INT           NULL CONSTRAINT DF_cam_port DEFAULT 554,
    username        NVARCHAR(100) NULL,
    password        NVARCHAR(200) NULL,
    rtsp_path       NVARCHAR(300) NULL,
    is_active       BIT           NOT NULL CONSTRAINT DF_cam_active DEFAULT 1,
    created_at      DATETIME2(0)  NOT NULL CONSTRAINT DF_cam_created DEFAULT SYSDATETIME(),
    CONSTRAINT UQ_cameras_camera_id UNIQUE (camera_id)
);
GO

/* 3. Raw audit log (every accepted punch) */
IF OBJECT_ID(N'dbo.attendance_logs', N'U') IS NULL
CREATE TABLE dbo.attendance_logs (
    log_id           BIGINT IDENTITY(1,1) PRIMARY KEY,
    employee_id      NVARCHAR(50)  NOT NULL,
    person_name      NVARCHAR(200) NOT NULL,
    camera_id        NVARCHAR(50)  NOT NULL,
    camera_location  NVARCHAR(100) NOT NULL,
    work_date        NVARCHAR(10)  NOT NULL,       -- 'YYYY-MM-DD'
    event_type       NVARCHAR(3)   NOT NULL CONSTRAINT CK_log_evt CHECK (event_type IN ('IN','OUT')),
    event_timestamp  NVARCHAR(19)  NOT NULL,       -- 'YYYY-MM-DD HH:MM:SS'
    confidence_score FLOAT         NULL,
    snapshot_image   NVARCHAR(500) NULL,
    CONSTRAINT FK_log_user   FOREIGN KEY (employee_id) REFERENCES dbo.users(employee_id),
    CONSTRAINT FK_log_camera FOREIGN KEY (camera_id)   REFERENCES dbo.cameras(camera_id)
);
CREATE INDEX IX_logs_emp_date ON dbo.attendance_logs (employee_id, work_date);
CREATE INDEX IX_logs_camera   ON dbo.attendance_logs (camera_id, log_id DESC);
GO

/* 4. One summary row per employee per day */
IF OBJECT_ID(N'dbo.daily_attendance', N'U') IS NULL
CREATE TABLE dbo.daily_attendance (
    id                      INT IDENTITY(1,1) PRIMARY KEY,
    employee_id             NVARCHAR(50)  NOT NULL,
    person_name             NVARCHAR(200) NOT NULL,
    base_location           NVARCHAR(100) NOT NULL,
    work_date               NVARCHAR(10)  NOT NULL,
    first_check_in          NVARCHAR(19)  NULL,
    first_check_in_camera   NVARCHAR(50)  NULL,
    first_check_in_location NVARCHAR(100) NULL,
    first_check_in_image    NVARCHAR(500) NULL,
    last_check_out          NVARCHAR(19)  NULL,
    last_check_out_camera   NVARCHAR(50)  NULL,
    last_check_out_location NVARCHAR(100) NULL,
    last_check_out_image    NVARCHAR(500) NULL,
    current_status          NVARCHAR(3)   NOT NULL CONSTRAINT CK_da_status CHECK (current_status IN ('IN','OUT')),
    current_location        NVARCHAR(100) NOT NULL,
    visited_locations       NVARCHAR(500) NOT NULL,
    last_event_time         NVARCHAR(19)  NOT NULL,
    total_checks            INT           NOT NULL CONSTRAINT DF_da_checks DEFAULT 1,
    out_of_office_hours     FLOAT         NOT NULL CONSTRAINT DF_da_ooo DEFAULT 0,
    total_working_hours     FLOAT         NOT NULL CONSTRAINT DF_da_work DEFAULT 0,
    CONSTRAINT FK_da_user FOREIGN KEY (employee_id) REFERENCES dbo.users(employee_id),
    CONSTRAINT UQ_da_emp_date UNIQUE (employee_id, work_date)
);
CREATE INDEX IX_da_date ON dbo.daily_attendance (work_date) INCLUDE (employee_id, current_status);
GO

/* 5. Portal logins */
IF OBJECT_ID(N'dbo.admin_users', N'U') IS NULL
CREATE TABLE dbo.admin_users (
    username      NVARCHAR(100) NOT NULL PRIMARY KEY,
    password_hash NVARCHAR(200) NOT NULL,
    full_name     NVARCHAR(200) NOT NULL,
    role          NVARCHAR(10)  NOT NULL CONSTRAINT CK_admin_role CHECK (role IN ('admin','hr','viewer'))
);
GO

/* 6. Least-privilege login for the app (change the password!) */
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'attendance_app')
    CREATE LOGIN attendance_app WITH PASSWORD = N'CHANGE_ME_Str0ng!Passw0rd', CHECK_POLICY = ON;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'attendance_app')
    CREATE USER attendance_app FOR LOGIN attendance_app;
ALTER ROLE db_datareader ADD MEMBER attendance_app;
ALTER ROLE db_datawriter ADD MEMBER attendance_app;
GO
