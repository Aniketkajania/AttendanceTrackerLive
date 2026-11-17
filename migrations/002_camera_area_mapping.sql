-- Phase 2: optional explicit camera-to-area mapping.
-- Safe additive migration; review/backup first, run against a TEST DB initially.
-- Use your current database (do not hardcode USE AttendanceTracker in the test script).
IF OBJECT_ID(N'dbo.attendance_camera_areas', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.attendance_camera_areas (
        camera_id NVARCHAR(50) NOT NULL,
        area_id INT NOT NULL,
        assigned_at DATETIME2(0) NOT NULL DEFAULT SYSDATETIME(),
        CONSTRAINT PK_attendance_camera_areas PRIMARY KEY(camera_id),
        CONSTRAINT FK_attendance_camera_areas_camera FOREIGN KEY(camera_id) REFERENCES dbo.cameras(camera_id),
        CONSTRAINT FK_attendance_camera_areas_area FOREIGN KEY(area_id) REFERENCES dbo.attendance_areas(id)
    );
END;
GO
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID(N'dbo.attendance_camera_areas')
      AND name = N'IX_attendance_camera_areas_area'
)
    CREATE INDEX IX_attendance_camera_areas_area ON dbo.attendance_camera_areas(area_id);
GO
