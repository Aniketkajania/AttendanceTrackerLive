"""
Connection check for SQL Server.  Run:  python database_setup.py

The tables are created by schema_mssql.sql (run it once in SSMS).
This script NEVER drops or alters anything; it only verifies that the app can reach the
database and that every expected table exists, and (optionally) seeds nothing.
"""
from db import connect
from config import DB_SERVER, DB_NAME

EXPECTED = ["users", "cameras", "attendance_logs", "daily_attendance", "admin_users"]

def main():
    print(f"Connecting to {DB_SERVER} / {DB_NAME} ...")
    conn = connect()
    present = {r["TABLE_NAME"] for r in conn.execute(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'").fetchall()}
    conn.close()
    missing = [t for t in EXPECTED if t not in present]
    if missing:
        raise SystemExit(f"[FAIL] Missing tables: {missing}. Run schema_mssql.sql in SSMS first.")
    print("[OK] Connected, all tables present:", ", ".join(EXPECTED))

if __name__ == "__main__":
    main()
