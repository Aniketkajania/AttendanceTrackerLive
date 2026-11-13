-- Operations schema setup: no leave-management tables, no destructive DDL.
-- IMPORTANT: Select the intended TEST database in SSMS before executing.
-- Existing core schema (users, cameras, daily_attendance, attendance_logs) must already exist.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.users', N'U') IS NULL OR OBJECT_ID(N'dbo.cameras', N'U') IS NULL
    THROW 51001, 'Core AttendanceTracker tables missing. Apply schema_mssql.sql to a TEST database first.', 1;

IF OBJECT_ID(N'dbo.attendance_shifts', N'U') IS NULL
BEGIN
  CREATE TABLE dbo.attendance_shifts (
    id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    shift_name NVARCHAR(100) NOT NULL UNIQUE,
    start_time TIME(0) NOT NULL,
    end_time TIME(0) NOT NULL,
    grace_minutes INT NOT NULL DEFAULT(15),
    is_active BIT NOT NULL DEFAULT(1),
    CONSTRAINT CK_shift_grace CHECK (grace_minutes BETWEEN 0 AND 180)
  );
END;

IF OBJECT_ID(N'dbo.employee_shifts', N'U') IS NULL
BEGIN
  CREATE TABLE dbo.employee_shifts (
    employee_id NVARCHAR(50) NOT NULL PRIMARY KEY,
    shift_id INT NOT NULL,
    CONSTRAINT FK_employee_shifts_user FOREIGN KEY (employee_id) REFERENCES dbo.users(employee_id),
    CONSTRAINT FK_employee_shifts_shift FOREIGN KEY (shift_id) REFERENCES dbo.attendance_shifts(id)
  );
END;

IF OBJECT_ID(N'dbo.attendance_areas', N'U') IS NULL
BEGIN
  CREATE TABLE dbo.attendance_areas (
    id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    name NVARCHAR(100) NOT NULL UNIQUE,
    location NVARCHAR(100) NOT NULL,
    description NVARCHAR(300) NULL,
    is_active BIT NOT NULL DEFAULT(1)
  );
END;

IF OBJECT_ID(N'dbo.attendance_visitors', N'U') IS NULL
BEGIN
  CREATE TABLE dbo.attendance_visitors (
    id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    full_name NVARCHAR(200) NOT NULL,
    organization NVARCHAR(200) NULL,
    host_employee_id NVARCHAR(50) NULL,
    purpose NVARCHAR(500) NULL,
    location NVARCHAR(100) NOT NULL,
    checked_in_at DATETIME2(0) NOT NULL DEFAULT(SYSDATETIME()),
    checked_out_at DATETIME2(0) NULL,
    CONSTRAINT FK_attendance_visitors_user FOREIGN KEY(host_employee_id) REFERENCES dbo.users(employee_id)
  );
END;

IF OBJECT_ID(N'dbo.attendance_camera_areas', N'U') IS NULL
BEGIN
  CREATE TABLE dbo.attendance_camera_areas (
    camera_id NVARCHAR(50) NOT NULL PRIMARY KEY,
    area_id INT NOT NULL,
    assigned_at DATETIME2(0) NOT NULL DEFAULT(SYSDATETIME()),
    CONSTRAINT FK_attendance_camera_areas_camera FOREIGN KEY (camera_id) REFERENCES dbo.cameras(camera_id),
    CONSTRAINT FK_attendance_camera_areas_area FOREIGN KEY (area_id) REFERENCES dbo.attendance_areas(id)
  );
END;

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.attendance_camera_areas') AND name='IX_attendance_camera_areas_area')
  CREATE INDEX IX_attendance_camera_areas_area ON dbo.attendance_camera_areas(area_id);

COMMIT TRANSACTION;
-- Deliberately does not create/drop leave requests or touch core attendance records.
