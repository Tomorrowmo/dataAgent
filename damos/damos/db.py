"""日记数据层：SQLite（标准库 sqlite3），所有读写按 owner_sub（OIDC sub）归属。"""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("DIARY_DB", os.path.join(os.path.dirname(__file__), "diary.db"))


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_sub TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_entries_owner ON entries(owner_sub)")


def list_entries(owner_sub):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM entries WHERE owner_sub=? ORDER BY updated_at DESC",
            (owner_sub,),
        ).fetchall()


def get_entry(entry_id, owner_sub):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM entries WHERE id=? AND owner_sub=?",
            (entry_id, owner_sub),
        ).fetchone()


def create_entry(owner_sub, title, content):
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO entries (owner_sub, title, content, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (owner_sub, title, content, now, now),
        )
        return cur.lastrowid


def update_entry(entry_id, owner_sub, title, content):
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            "UPDATE entries SET title=?, content=?, updated_at=? WHERE id=? AND owner_sub=?",
            (title, content, now, entry_id, owner_sub),
        )
        return cur.rowcount > 0


def delete_entry(entry_id, owner_sub):
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM entries WHERE id=? AND owner_sub=?",
            (entry_id, owner_sub),
        )
        return cur.rowcount > 0
