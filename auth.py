"""Login + role protection. One middleware guards every /api, /snapshots and /photos request."""
import time
import bcrypt, jwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from config import JWT_SECRET, COOKIE_SECURE
from db import connect

ALGO, TTL = "HS256", 12 * 3600          # login lasts 12 hours
router = APIRouter()

# (method, exact path, roles allowed). Everything else only needs a valid login.
RULES = [
    ("GET",  "/api/cameras",   {"admin"}),
    ("POST", "/api/cameras",   {"admin"}),
    ("POST", "/api/employees", {"admin", "hr"}),
]

def init_auth():
    """Tables are created by schema_mssql.sql. Nothing to do at startup (kept for compatibility)."""
    return None

def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def read_token(token):
    try:
        d = jwt.decode(token, JWT_SECRET, algorithms=[ALGO])
        return {"username": d["sub"], "full_name": d["name"], "role": d["role"]}
    except Exception:
        return None

async def auth_middleware(request: Request, call_next):
    path = request.url.path
    guarded = path.startswith(("/api/", "/snapshots/", "/photos/"))
    if not guarded or path == "/api/auth/login" or request.method == "OPTIONS":
        return await call_next(request)
    user = read_token(request.cookies.get("token"))
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    for method, p, roles in RULES:
        if request.method == method and path == p and user["role"] not in roles:
            return JSONResponse({"detail": "Your role cannot do this"}, status_code=403)
    request.state.user = user
    return await call_next(request)

class LoginIn(BaseModel):
    username: str
    password: str

@router.post("/api/auth/login")
def login(body: LoginIn, response: Response):
    conn = connect()
    row = conn.execute("SELECT * FROM admin_users WHERE username = ?", (body.username.strip().lower(),)).fetchone()
    conn.close()
    if not row or not bcrypt.checkpw(body.password.encode(), row["password_hash"].encode()):
        time.sleep(1)                       # slows down password guessing
        raise HTTPException(401, "Wrong username or password")
    token = jwt.encode({"sub": row["username"], "name": row["full_name"], "role": row["role"],
                        "exp": int(time.time()) + TTL}, JWT_SECRET, algorithm=ALGO)
    # HttpOnly cookie: <img> tags and the Excel link are authenticated automatically
    response.set_cookie("token", token, httponly=True, samesite="lax", secure=COOKIE_SECURE, max_age=TTL)
    return {"username": row["username"], "full_name": row["full_name"], "role": row["role"]}

@router.get("/api/auth/me")
def me(request: Request):
    return request.state.user

@router.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("token")
    return {"ok": True}