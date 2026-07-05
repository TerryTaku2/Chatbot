import os

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Modules that import this before app.py calls load_dotenv() itself need their
# own .env load to find DATABASE_URL at import time.
load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

# Timestamp columns are stored as TEXT in the exact format SQLite's
# CURRENT_TIMESTAMP used to produce ('YYYY-MM-DD HH:MM:SS', UTC, no tz).
# Application code across both the chatbot and the accommodation blueprint
# parses these with datetime.fromisoformat() and does string slicing on them,
# so we deliberately avoid native TIMESTAMP columns (which psycopg2 would hand
# back as datetime objects) to keep that code working unchanged.
NOW_SQL = "to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"


class _CompatCursor:
    """Wraps a psycopg2 cursor to accept SQLite-style '?' placeholders and
    bare CURRENT_TIMESTAMP literals, and to behave like sqlite3.Row (supports
    both row['col'] and row[0])."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        query = query.replace("?", "%s").replace("CURRENT_TIMESTAMP", NOW_SQL)
        self._cursor.execute(query, params or ())
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _CompatConnection:
    """Wraps a psycopg2 connection to mimic the sqlite3 connection API used
    throughout db.py / db_ttech.py (conn.execute(...), dict+index-accessible
    rows)."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return _CompatCursor(
            self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        )

    def execute(self, query, params=None):
        cur = self.cursor()
        cur.execute(query, params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_connection(search_path=None):
    """search_path, if given, is a comma-separated schema list, e.g. 'ttech,public'."""
    options = f"-c search_path={search_path}" if search_path else None
    conn = psycopg2.connect(DATABASE_URL, options=options)
    return _CompatConnection(conn)
