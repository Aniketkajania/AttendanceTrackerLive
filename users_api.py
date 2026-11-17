"""Admin-only user management. Must be included AFTER auth's middleware is registered."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from db import connect, IntegrityError
from auth import hash_pw

router = APIRouter(prefix="/api/users")
ROLES = {"admin", "hr", "viewer"}

def admin_only(request: Request):
    if request.state.user["role"] != "admin":
        raise HTTPException(403, "Only admins can manage users")

def db():
    return connect()

def other_admins(conn, username):
    return conn.execute("SELECT COUNT(*) AS n FROM admin_users WHERE role='admin' AND username <> ?", (username,)).fetchone()["n"]

class UserIn(BaseModel):
    username: str
    full_name: str
    role: str
    password: Optional[str] = None      # blank on edit = keep current password

def check(u: UserIn, creating: bool):
    if u.role not in ROLES:
        raise HTTPException(400, "Role must be admin, hr or viewer")
    if not u.full_name.strip():
        raise HTTPException(400, "Full name is required")
    if (creating or u.password) and (not u.password or len(u.password) < 8):
        raise HTTPException(400, "Password must be at least 8 characters")

@router.get("")
def list_users(request: Request):
    admin_only(request)
    conn = db()
    try:
        return conn.execute("SELECT username, full_name, role FROM admin_users ORDER BY role, username").fetchall()
    finally:
        conn.close()

@router.post("")
def create_user(u: UserIn, request: Request):
    admin_only(request)
    uname = u.username.strip().lower()
    if not uname or " " in uname:
        raise HTTPException(400, "Username is required and cannot contain spaces")
    check(u, creating=True)
    conn = db()
    try:
        if conn.execute("SELECT TOP 1 1 AS present FROM admin_users WHERE username=?", (uname,)).fetchone():
            raise HTTPException(409, f"Username '{uname}' already exists")
        conn.execute("INSERT INTO admin_users (username, password_hash, full_name, role) VALUES (?,?,?,?)",
                     (uname, hash_pw(u.password), u.full_name.strip(), u.role))
        conn.commit()
    except IntegrityError as exc:
        conn.rollback()
        raise HTTPException(409, f"Username '{uname}' already exists") from exc
    finally:
        conn.close()
    return {"ok": True}

@router.put("/{username}")
def update_user(username: str, u: UserIn, request: Request):
    admin_only(request)
    check(u, creating=False)
    conn = db()
    row = conn.execute("SELECT role FROM admin_users WHERE username=?", (username,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "User not found")
    if row["role"] == "admin" and u.role != "admin" and other_admins(conn, username) == 0:
        conn.close(); raise HTTPException(400, "You cannot demote the last admin")
    if u.password:
        conn.execute("UPDATE admin_users SET full_name=?, role=?, password_hash=? WHERE username=?",
                     (u.full_name.strip(), u.role, hash_pw(u.password), username))
    else:
        conn.execute("UPDATE admin_users SET full_name=?, role=? WHERE username=?",
                     (u.full_name.strip(), u.role, username))
    conn.commit(); conn.close()
    return {"ok": True}

@router.delete("/{username}")
def delete_user(username: str, request: Request):
    admin_only(request)
    if username == request.state.user["username"]:
        raise HTTPException(400, "You cannot delete your own account")
    conn = db()
    row = conn.execute("SELECT role FROM admin_users WHERE username=?", (username,)).fetchone()
    if row and row["role"] == "admin" and other_admins(conn, username) == 0:
        conn.close(); raise HTTPException(400, "You cannot delete the last admin")
    conn.execute("DELETE FROM admin_users WHERE username=?", (username,))
    conn.commit(); conn.close()
    return {"ok": True}