-- CamSec-inspired operations: additive SQL Server migration.
-- Run once in SSMS against AttendanceTracker. Does NOT drop existing data.
USE AttendanceTracker;
GO
IF OBJECT_ID('dbo.attendance_shifts','U') IS NULL
CREATE TABLE dbo.attendance_shifts (
 id INT IDENTITY(1,1) PRIMARY KEY,
 shift_name NVARCHAR(100) NOT NULL UNIQUE,
 start_time TIME(0) NOT NULL,
 end_time TIME(0) NOT NULL,
 grace_minutes INT NOT NULL DEFAULT 15,
 is_active BIT NOT NULL DEFAULT 1,
 CONSTRAINT CK_shift_grace CHECK (grace_minutes BETWEEN 0 AND 180)
);
GO
IF OBJECT_ID('dbo.employee_shifts','U') IS NULL
CREATE TABLE dbo.employee_shifts (
 employee_id NVARCHAR(50) NOT NULL PRIMARY KEY REFERENCES dbo.users(employee_id),
 shift_id INT NOT NULL REFERENCES dbo.attendance_shifts(id)
);
GO
IF OBJECT_ID('dbo.attendance_leave_requests','U') IS NULL
CREATE TABLE dbo.attendance_leave_requests (
 id INT IDENTITY(1,1) PRIMARY KEY,
 employee_id NVARCHAR(50) NOT NULL REFERENCES dbo.users(employee_id),
 start_date DATE NOT NULL,
 end_date DATE NOT NULL,
 leave_type NVARCHAR(30) NOT NULL,
 reason NVARCHAR(1000) NULL,
 status NVARCHAR(12) NOT NULL DEFAULT 'PENDING',
 reviewed_by NVARCHAR(100) NULL,
 reviewed_at DATETIME2(0) NULL,
 created_at DATETIME2(0) NOT NULL DEFAULT SYSDATETIME(),
 CONSTRAINT CK_leave_dates CHECK (end_date >= start_date),
 CONSTRAINT CK_leave_status CHECK (status IN ('PENDING','APPROVED','REJECTED'))
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.attendance_leave_requests') AND name='IX_attendance_leave_dates')
CREATE INDEX IX_attendance_leave_dates ON dbo.attendance_leave_requests(employee_id,start_date,end_date);
GO
IF OBJECT_ID('dbo.attendance_areas','U') IS NULL
CREATE TABLE dbo.attendance_areas (
 id INT IDENTITY(1,1) PRIMARY KEY,
 name NVARCHAR(100) NOT NULL UNIQUE,
 location NVARCHAR(100) NOT NULL,
 description NVARCHAR(300) NULL,
 is_active BIT NOT NULL DEFAULT 1
);
GO
IF OBJECT_ID('dbo.attendance_visitors','U') IS NULL
CREATE TABLE dbo.attendance_visitors (
 id INT IDENTITY(1,1) PRIMARY KEY,
 full_name NVARCHAR(200) NOT NULL,
 organization NVARCHAR(200) NULL,
 host_employee_id NVARCHAR(50) NULL REFERENCES dbo.users(employee_id),
 purpose NVARCHAR(500) NULL,
 location NVARCHAR(100) NOT NULL,
 checked_in_at DATETIME2(0) NOT NULL DEFAULT SYSDATETIME(),
 checked_out_at DATETIME2(0) NULL
);
GO