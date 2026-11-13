"""User Access regressions: mock SQL and password hashing, no live database."""
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException

db_stub = types.ModuleType("db")
db_stub.connect = lambda: None
db_stub.IntegrityError = type("IntegrityError", (Exception,), {})
sys.modules["db"] = db_stub
auth_stub = types.ModuleType("auth")
auth_stub.hash_pw = lambda _: "fake-bcrypt-hash"
sys.modules["auth"] = auth_stub
import users_api


class FakeConn:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.sql = []
        self.closed = False
        self.committed = False

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def request(role="admin"):
    return SimpleNamespace(state=SimpleNamespace(user={"role": role, "username": "admin"}))


class TestUsersAPI(unittest.TestCase):
    def test_list_users_uses_fetchall_and_closes_connection(self):
        conn = FakeConn(rows=[{"username": "admin", "role": "admin", "full_name": "Administrator"}])
        with patch.object(users_api, "db", return_value=conn):
            rows = users_api.list_users(request())
        self.assertEqual(rows[0]["username"], "admin")
        self.assertTrue(conn.closed)

    def test_list_users_denies_nonadmins(self):
        with self.assertRaises(HTTPException) as ctx:
            users_api.list_users(request("viewer"))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_duplicate_username_returns_409(self):
        conn = FakeConn(rows=[{"present": 1}])
        user = users_api.UserIn(username="admin", full_name="Administrator",
                                role="viewer", password="TestPassword123!")
        with patch.object(users_api, "db", return_value=conn):
            with self.assertRaises(HTTPException) as ctx:
                users_api.create_user(user, request())
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertFalse(conn.committed)
        self.assertTrue(conn.closed)

    def test_new_user_insert_commits(self):
        conn = FakeConn()
        user = users_api.UserIn(username="sample.viewer", full_name="Sample Viewer",
                                role="viewer", password="TestPassword123!")
        with patch.object(users_api, "db", return_value=conn):
            self.assertEqual(users_api.create_user(user, request()), {"ok": True})
        self.assertTrue(conn.committed)
        self.assertTrue(conn.closed)
        self.assertTrue(any("INSERT INTO admin_users" in sql for sql, _ in conn.sql))


if __name__ == "__main__":
    unittest.main()
