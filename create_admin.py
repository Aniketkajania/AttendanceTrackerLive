"""Run:  python create_admin.py   (creates or resets a portal login)"""
import getpass
from auth import init_auth, hash_pw
from db import connect

init_auth()
username = input("Username: ").strip().lower()
full_name = input("Full name: ").strip()
role = input("Role (admin / hr / viewer): ").strip().lower()
assert role in ("admin", "hr", "viewer"), "Role must be admin, hr or viewer"
pw = getpass.getpass("Password (min 8 chars): ")
assert len(pw) >= 8, "Password too short"

conn = connect()
conn.execute("""MERGE dbo.admin_users WITH (HOLDLOCK) AS t
    USING (SELECT ? AS username, ? AS password_hash, ? AS full_name, ? AS role) AS s
    ON t.username = s.username
    WHEN MATCHED THEN UPDATE SET password_hash=s.password_hash, full_name=s.full_name, role=s.role
    WHEN NOT MATCHED THEN INSERT (username, password_hash, full_name, role)
         VALUES (s.username, s.password_hash, s.full_name, s.role);""",
    (username, hash_pw(pw), full_name, role))
conn.commit(); conn.close()
print(f"Saved login '{username}' with role '{role}'.")