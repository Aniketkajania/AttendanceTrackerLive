"""CamSec-style operations. Requires migrations/001_camsec_operations.sql first.
All mutation routes enforce authorization independently of the UI.
"""
from datetime import date
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Request
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


class LeaveIn(BaseModel):
    employee_id: str
    start_date: date
    end_date: date
    leave_type: Literal["CASUAL", "SICK", "EARNED", "UNPAID", "OTHER"]
    reason: str = Field(default="", max_length=1000)


@router.get("/leaves")
def leaves(request: Request, status: Optional[str] = None):
    permitted(request, ("admin", "hr"))
    if status and status not in ("PENDING", "APPROVED", "REJECTED"):
        raise HTTPException(422, "Invalid status")
    sql = """SELECT l.id,l.employee_id,u.person_name,CONVERT(VARCHAR(10),l.start_date,23) AS start_date,
            CONVERT(VARCHAR(10),l.end_date,23) AS end_date,l.leave_type,l.reason,l.status,l.reviewed_by
            FROM attendance_leave_requests l JOIN users u ON u.employee_id=l.employee_id"""
    if status:
        return query(sql+" WHERE l.status=? ORDER BY l.id DESC", (status,))
    return query(sql+" ORDER BY l.id DESC")


@router.post("/leaves", status_code=201)
def create_leave(item: LeaveIn, request: Request):
    permitted(request)
    if item.end_date < item.start_date:
        raise HTTPException(422, "End date cannot precede start date")
    if not exists("users", "employee_id", item.employee_id):
        raise HTTPException(404, "Employee not found")
    overlap = query("""SELECT TOP 1 id FROM attendance_leave_requests WHERE employee_id=? AND status <> 'REJECTED'
                     AND start_date<=? AND end_date>=?""", (item.employee_id, item.end_date, item.start_date))
    if overlap:
        raise HTTPException(409, "Overlapping leave request already exists")
    execute("INSERT INTO attendance_leave_requests (employee_id,start_date,end_date,leave_type,reason) VALUES (?,?,?,?,?)",
            (item.employee_id, item.start_date, item.end_date, item.leave_type, item.reason.strip()))
    return {"ok": True}


class ReviewIn(BaseModel):
    status: Literal["APPROVED", "REJECTED"]


@router.post("/leaves/{leave_id}/review")
def review_leave(leave_id: int, item: ReviewIn, request: Request):
    user = permitted(request, ("admin", "hr"))
    changed = query("SELECT id FROM attendance_leave_requests WHERE id=? AND status='PENDING'", (leave_id,))
    if not changed:
        raise HTTPException(409, "Request not found or already reviewed")
    execute("""UPDATE attendance_leave_requests SET status=?,reviewed_by=?,reviewed_at=SYSDATETIME()
               WHERE id=? AND status='PENDING'""", (item.status, user["username"], leave_id))
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
    leaves = query("""SELECT COUNT(*) AS total FROM attendance_leave_requests
                      WHERE status='APPROVED' AND start_date<=? AND end_date>=?""",
                   (work_date, work_date))
    return {"staff": staff[0]["total"], "present": attendance[0]["present"],
            "visitors": visitors[0]["total"], "on_leave": leaves[0]["total"],
            "absent_estimate": max(0, staff[0]["total"]-attendance[0]["present"]-leaves[0]["total"])}
