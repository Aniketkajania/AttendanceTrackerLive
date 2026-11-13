"""CamSec-style operations. Requires migrations/001_camsec_operations.sql first.
All mutation routes enforce authorization independently of the UI.
"""
from datetime import date, datetime, timedelta
from typing import Optional
import csv
import io
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from db import query, execute

router = APIRouter(prefix="/api/operations", tags=["Operations"])


def permitted(request: Request, roles=("admin", "hr")):
    user = getattr(request.state, "user", None)
    if not user or user.get("role") not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


def exists(table, key, value):
    # Internal table names only (never user-controlled).
    return bool(query(f"SELECT TOP 1 1 AS present FROM {table} WHERE {key} = ?", (value,)))


class ShiftIn(BaseModel):
    shift_name: str = Field(min_length=1, max_length=100)
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    grace_minutes: int = Field(default=15, ge=0, le=180)


@router.get("/readiness")
def readiness(request: Request):
    """Read-only check for the optional operations schema.
    This endpoint does not create tables or mutate attendance.
    """
    permitted(request, ("admin",))
    needed = ["attendance_shifts", "employee_shifts", "attendance_areas",
              "attendance_visitors", "attendance_camera_areas"]
    rows = query("""
        SELECT name FROM sys.tables
        WHERE schema_id=SCHEMA_ID('dbo')
          AND name IN ('attendance_shifts','employee_shifts','attendance_areas',
                       'attendance_visitors','attendance_camera_areas')
    """)
    found = {r["name"] for r in rows}
    missing = [name for name in needed if name not in found]
    return {"ready":not missing, "missing_tables":missing,
            "setup_script":"migrations/003_operations_setup_no_leaves.sql"}


@router.get("/shifts")
def shifts(request: Request):
    permitted(request, ("admin", "hr", "viewer"))
    return query("SELECT id, shift_name, CONVERT(VARCHAR(5), start_time, 108) AS start_time, CONVERT(VARCHAR(5), end_time, 108) AS end_time, grace_minutes, is_active FROM attendance_shifts ORDER BY shift_name")


@router.post("/shifts", status_code=201)
def add_shift(item: ShiftIn, request: Request):
    permitted(request, ("admin",))
    try:
        execute("INSERT INTO attendance_shifts (shift_name,start_time,end_time,grace_minutes) VALUES (?,?,?,?)",
                (item.shift_name.strip(), item.start_time, item.end_time, item.grace_minutes))
    except Exception as exc:
        raise HTTPException(409, "Unable to create shift; check for duplicate name") from exc
    return {"ok": True}


class ShiftAssignment(BaseModel):
    employee_id: str
    shift_id: int


@router.get("/assignments")
def assignments(request: Request):
    permitted(request, ("admin", "hr", "viewer"))
    return query("""SELECT e.employee_id, u.person_name, e.shift_id, s.shift_name
                    FROM employee_shifts e JOIN users u ON u.employee_id=e.employee_id
                    JOIN attendance_shifts s ON s.id=e.shift_id ORDER BY u.person_name""")


@router.post("/assignments")
def assign_shift(item: ShiftAssignment, request: Request):
    permitted(request, ("admin", "hr"))
    if not exists("users", "employee_id", item.employee_id) or not exists("attendance_shifts", "id", item.shift_id):
        raise HTTPException(404, "Employee or shift not found")
    execute("""UPDATE employee_shifts SET shift_id=? WHERE employee_id=?;
               IF @@ROWCOUNT=0 INSERT INTO employee_shifts(employee_id,shift_id) VALUES (?,?)""",
            (item.shift_id, item.employee_id, item.employee_id, item.shift_id))
    return {"ok": True}


class AreaIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)


@router.get("/areas")
def areas(request: Request):
    permitted(request, ("admin", "hr", "viewer"))
    return query("SELECT id,name,location,description,is_active FROM attendance_areas ORDER BY location,name")


@router.post("/areas", status_code=201)
def create_area(item: AreaIn, request: Request):
    permitted(request, ("admin",))
    try:
        execute("INSERT INTO attendance_areas(name,location,description) VALUES (?,?,?)",
                (item.name.strip(), item.location.strip(), item.description.strip()))
    except Exception as exc:
        raise HTTPException(409, "Area name already exists") from exc
    return {"ok": True}


class VisitorIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    organization: str = Field(default="", max_length=200)
    host_employee_id: Optional[str] = None
    purpose: str = Field(default="", max_length=500)
    location: str = Field(min_length=1, max_length=100)


@router.get("/visitors")
def visitors(request: Request, date_filter: Optional[date] = None):
    permitted(request, ("admin", "hr"))
    sql = """SELECT TOP 500 id,full_name,organization,host_employee_id,purpose,location,
             CONVERT(VARCHAR(19),checked_in_at,120) AS checked_in_at,
             CONVERT(VARCHAR(19),checked_out_at,120) AS checked_out_at
             FROM attendance_visitors"""
    if date_filter:
        return query(sql+" WHERE checked_in_at >= ? AND checked_in_at < DATEADD(day,1,?) ORDER BY id DESC",
                     (date_filter, date_filter))
    return query(sql+" ORDER BY id DESC")


@router.post("/visitors", status_code=201)
def checkin_visitor(item: VisitorIn, request: Request):
    permitted(request)
    if item.host_employee_id and not exists("users", "employee_id", item.host_employee_id):
        raise HTTPException(404, "Host employee not found")
    execute("""INSERT INTO attendance_visitors(full_name,organization,host_employee_id,purpose,location)
               VALUES (?,?,?,?,?)""",
            (item.full_name.strip(), item.organization.strip(), item.host_employee_id or None,
             item.purpose.strip(), item.location.strip()))
    return {"ok": True}


@router.post("/visitors/{visitor_id}/checkout")
def checkout_visitor(visitor_id: int, request: Request):
    permitted(request)
    if not query("SELECT TOP 1 id FROM attendance_visitors WHERE id=? AND checked_out_at IS NULL", (visitor_id,)):
        raise HTTPException(409, "Visitor not found or already checked out")
    execute("UPDATE attendance_visitors SET checked_out_at=SYSDATETIME() WHERE id=? AND checked_out_at IS NULL",
            (visitor_id,))
    return {"ok": True}


@router.get("/overview")
def overview(request: Request, work_date: date):
    permitted(request, ("admin", "hr", "viewer"))
    attendance = query("""SELECT COUNT(*) AS present FROM daily_attendance WHERE work_date=?""",
                       (work_date.isoformat(),))
    staff = query("SELECT COUNT(*) AS total FROM users WHERE is_active=1")
    visitors = query("""SELECT COUNT(*) AS total FROM attendance_visitors
                        WHERE checked_in_at >= ? AND checked_in_at < DATEADD(day,1,?)""",
                     (work_date, work_date))
    return {"staff": staff[0]["total"], "present": attendance[0]["present"],
            "visitors": visitors[0]["total"],
            "not_recorded": max(0, staff[0]["total"]-attendance[0]["present"])}


# ---------- consolidated attendance reporting ----------
@router.get("/report-locations")
def report_locations(request: Request):
    permitted(request, ("admin", "hr", "viewer"))
    rows = query("SELECT DISTINCT base_location FROM dbo.users WHERE is_active=1 AND base_location IS NOT NULL ORDER BY base_location")
    return [x["base_location"] for x in rows]


@router.get("/reports/daily")
def daily_report(request: Request, work_date: date, location: Optional[str] = None):
    """Staff roster + scheduled shift + first/last punch.
    Overnight shifts need dedicated cross-date reconciliation; mark them explicitly,
    rather than asserting somebody was late based on clock time alone.
    """
    permitted(request, ("admin", "hr", "viewer"))
    rows = query("""
        SELECT u.employee_id, u.person_name, u.base_location,
               s.shift_name, CONVERT(VARCHAR(5),s.start_time,108) AS shift_start,
               CONVERT(VARCHAR(5),s.end_time,108) AS shift_end,
               s.grace_minutes,
               da.first_check_in,da.last_check_out,da.total_working_hours,
               da.current_status
        FROM dbo.users u
        LEFT JOIN dbo.employee_shifts es ON es.employee_id=u.employee_id
        LEFT JOIN dbo.attendance_shifts s ON s.id=es.shift_id AND s.is_active=1
        LEFT JOIN dbo.daily_attendance da ON da.employee_id=u.employee_id AND da.work_date=?
        WHERE u.is_active=1 AND (? IS NULL OR u.base_location=?)
        ORDER BY u.person_name
    """, (work_date.isoformat(),location,location))
    for row in rows:
        if row["first_check_in"]:
            if not row["shift_start"]:
                status = "PRESENT_UNASSIGNED_SHIFT"
            elif row["shift_end"] <= row["shift_start"]:
                status = "PRESENT_OVERNIGHT_REVIEW"
            else:
                scheduled = datetime.combine(work_date, datetime.strptime(row["shift_start"], "%H:%M").time())
                deadline = scheduled + timedelta(minutes=int(row["grace_minutes"] or 0))
                punch = datetime.strptime(row["first_check_in"], "%Y-%m-%d %H:%M:%S")
                status = "LATE" if punch > deadline else "ON_TIME"
        elif row["shift_start"]:
            status = "NO_PUNCH_SCHEDULED"
        else:
            status = "NO_PUNCH_UNASSIGNED_SHIFT"
        row["attendance_status"] = status
    return {"work_date":work_date.isoformat(), "location":location, "rows":rows,
            "summary":{"staff":len(rows),
                       "present":sum(bool(x["first_check_in"]) for x in rows),
                       "late":sum(x["attendance_status"]=="LATE" for x in rows),
                       "on_time":sum(x["attendance_status"]=="ON_TIME" for x in rows),
                       "not_recorded":sum(not bool(x["first_check_in"]) for x in rows),
                       "requires_review":sum(x["attendance_status"] in ("PRESENT_OVERNIGHT_REVIEW","NO_PUNCH_UNASSIGNED_SHIFT","PRESENT_UNASSIGNED_SHIFT") for x in rows)}}


@router.get("/reports/daily.csv")
def daily_report_csv(request: Request, work_date: date, location: Optional[str] = None):
    data = daily_report(request, work_date, location)
    fields = ["employee_id","person_name","base_location","shift_name","shift_start",
              "shift_end","first_check_in","last_check_out","total_working_hours",
              "current_status","attendance_status"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in data["rows"]:
        # Prefix spreadsheet formula-looking text to protect CSV exports opened in Excel.
        safe = {k: ("'" + v if isinstance(v,str) and v.lstrip().startswith(("=","+","-","@")) else v)
                for k,v in row.items()}
        writer.writerow(safe)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":f'attachment; filename="attendance_{work_date.isoformat()}.csv"'})


# ---------- area assignment ----------
class CameraAreaAssignment(BaseModel):
    camera_id: str = Field(min_length=1,max_length=50)
    area_id: int = Field(ge=1)


@router.get("/camera-areas")
def camera_areas(request: Request):
    permitted(request, ("admin","hr","viewer"))
    return query("""
        SELECT c.camera_id,c.camera_name,c.location,c.camera_role,
               ca.area_id,a.name AS area_name
        FROM dbo.cameras c
        LEFT JOIN dbo.attendance_camera_areas ca ON ca.camera_id=c.camera_id
        LEFT JOIN dbo.attendance_areas a ON a.id=ca.area_id
        WHERE c.is_active=1 ORDER BY c.location,c.camera_name
    """)


@router.post("/camera-areas")
def assign_camera_area(item: CameraAreaAssignment, request: Request):
    permitted(request, ("admin",))
    if not exists("cameras","camera_id",item.camera_id) or not exists("attendance_areas","id",item.area_id):
        raise HTTPException(404,"Camera or area not found")
    execute("""
        UPDATE dbo.attendance_camera_areas SET area_id=?,assigned_at=SYSDATETIME()
        WHERE camera_id=?;
        IF @@ROWCOUNT=0 INSERT INTO dbo.attendance_camera_areas(camera_id,area_id) VALUES (?,?)
    """,(item.area_id,item.camera_id,item.camera_id,item.area_id))
    return {"ok":True}


@router.get("/analytics/activity")
def attendance_activity(request: Request, work_date: date):
    """Verified punch activity, NOT anonymous people counting or camera footfall."""
    permitted(request, ("admin","hr","viewer"))
    hourly = query("""
        SELECT SUBSTRING(event_timestamp,12,2) AS hour,
               SUM(CASE WHEN event_type='IN' THEN 1 ELSE 0 END) AS arrivals,
               SUM(CASE WHEN event_type='OUT' THEN 1 ELSE 0 END) AS departures
        FROM dbo.attendance_logs WHERE work_date=?
        GROUP BY SUBSTRING(event_timestamp,12,2)
        ORDER BY hour
    """,(work_date.isoformat(),))
    by_camera = query("""
        SELECT a.camera_id, c.camera_name, a.event_type, COUNT(*) AS events
        FROM dbo.attendance_logs a
        LEFT JOIN dbo.cameras c ON c.camera_id=a.camera_id
        WHERE a.work_date=?
        GROUP BY a.camera_id,c.camera_name,a.event_type
        ORDER BY a.camera_id,a.event_type
    """,(work_date.isoformat(),))
    return {"work_date":work_date.isoformat(), "hourly":hourly, "by_camera":by_camera,
            "metric":"verified_attendance_events", "is_people_count":False}
