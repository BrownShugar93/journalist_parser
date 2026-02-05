import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

DB_PATH = Path(__file__).with_name("app.db")


def _connect():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                access_until TEXT,
                daily_runs_date TEXT,
                daily_runs_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email.lower(),))
        return cur.fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return cur.fetchone()
    finally:
        conn.close()


def create_user(email: str, password_hash: str, password_salt: str) -> int:
    conn = _connect()
    try:
        cur = conn.cursor()
        created_at = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO users (email, password_hash, password_salt, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (email.lower(), password_hash, password_salt, created_at),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def set_access_until(user_id: int, access_until: Optional[datetime]):
    conn = _connect()
    try:
        cur = conn.cursor()
        value = access_until.isoformat() if access_until else None
        cur.execute("UPDATE users SET access_until = ? WHERE id = ?", (value, user_id))
        conn.commit()
    finally:
        conn.close()


def update_daily_runs(user_id: int, today_str: str, new_count: int):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET daily_runs_date = ?, daily_runs_count = ? WHERE id = ?",
            (today_str, new_count, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def store_session(token: str, user_id: int, expires_at: datetime):
    conn = _connect()
    try:
        cur = conn.cursor()
        created_at = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO sessions (token, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, expires_at.isoformat(), created_at),
        )
        conn.commit()
    finally:
        conn.close()


def get_session(token: str) -> Optional[sqlite3.Row]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM sessions WHERE token = ?", (token,))
        return cur.fetchone()
    finally:
        conn.close()


def delete_session(token: str):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def reset_daily_runs_if_needed(user_id: int, today_str: str) -> Tuple[str, int]:
    user = get_user_by_id(user_id)
    if not user:
        return today_str, 0
    if user["daily_runs_date"] != today_str:
        update_daily_runs(user_id, today_str, 0)
        return today_str, 0
    return user["daily_runs_date"] or today_str, int(user["daily_runs_count"] or 0)
