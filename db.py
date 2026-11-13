"""
Single place for all SQL Server access (pyodbc).
Every other module imports `connect` / `query` / `execute` from here, so switching
databases never touches business logic again.
"""
import pyodbc
from config import (DB_SERVER, DB_NAME, DB_USER, DB_PASSWORD,
                    DB_DRIVER, DB_ENCRYPT, DB_TRUST_CERT, DB_TRUSTED)

pyodbc.pooling = True          # ODBC driver-level connection pooling (cheap reconnects)
IntegrityError = pyodbc.IntegrityError


def _conn_str() -> str:
    parts = [
        f"DRIVER={{{DB_DRIVER}}}",
        f"SERVER={DB_SERVER}",
        f"DATABASE={DB_NAME}",
        f"Encrypt={'yes' if DB_ENCRYPT else 'no'}",
        f"TrustServerCertificate={'yes' if DB_TRUST_CERT else 'no'}",
        "Connection Timeout=15",
    ]
    if DB_TRUSTED:                         # Windows auth (only when the app runs on Windows)
        parts.append("Trusted_Connection=yes")
    else:
        parts += [f"UID={DB_USER}", f"PWD={{{DB_PASSWORD}}}"]
    return ";".join(parts)


class Row(dict):
    """dict that also supports row[0] so old `fetchone()[0]` code keeps working."""
    def __getitem__(self, k):
        return super().__getitem__(k) if isinstance(k, str) else list(self.values())[k]


class _Cursor:
    def __init__(self, cur):
        self._c = cur

    def execute(self, sql, params=()):
        self._c.execute(sql, params)
        return self

    def _cols(self):
        return [d[0] for d in self._c.description] if self._c.description else []

    def fetchone(self):
        r = self._c.fetchone()
        return Row(zip(self._cols(), r)) if r else None

    def fetchall(self):
        cols = self._cols()
        return [Row(zip(cols, r)) for r in self._c.fetchall()]

    @property
    def rowcount(self):
        return self._c.rowcount


class _Conn:
    def __init__(self):
        self._conn = pyodbc.connect(_conn_str(), autocommit=False)

    def cursor(self):
        return _Cursor(self._conn.cursor())

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def connect() -> _Conn:
    return _Conn()


def query(sql: str, params=()) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def execute(sql: str, params=()):
    conn = connect()
    try:
        conn.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
