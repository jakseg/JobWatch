"""SQLite database layer for JobWatch (encrypted via SQLCipher)."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlcipher3 import dbapi2 as sqlcipher

DB_PATH = Path("data/jobwatch.db")


def _get_key() -> str:
    key = os.environ.get("DB_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("DB_ENCRYPTION_KEY environment variable is not set")
    return key


def _dict_factory(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def get_connection() -> sqlcipher.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlcipher.connect(str(DB_PATH))
    conn.row_factory = _dict_factory
    key = _get_key().replace("'", "''")
    conn.execute(f"PRAGMA key='{key}'")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id       INTEGER PRIMARY KEY,
                username      TEXT,
                notify_hour   INTEGER DEFAULT 7,
                notify_minute INTEGER DEFAULT 0,
                created_at    TEXT    NOT NULL,
                is_active     INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS companies (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
                name       TEXT    NOT NULL,
                url        TEXT    NOT NULL,
                keywords   TEXT    DEFAULT '',
                is_paused  INTEGER DEFAULT 0,
                created_at TEXT    NOT NULL,
                UNIQUE(chat_id, url)
            );

            CREATE TABLE IF NOT EXISTS state (
                company_id   INTEGER PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
                lines        TEXT    DEFAULT '[]',
                last_checked TEXT,
                version      INTEGER DEFAULT 2
            );
        """)
        conn.commit()
    finally:
        conn.close()


# --- Users ---

def get_user(chat_id: int) -> dict | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    finally:
        conn.close()


def get_or_create_user(chat_id: int, username: str | None = None) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if row is not None:
            return row

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO users (chat_id, username, created_at) VALUES (?, ?, ?)",
            (chat_id, username, now),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    finally:
        conn.close()


def update_notify_time(chat_id: int, hour: int, minute: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET notify_hour = ?, notify_minute = ? WHERE chat_id = ?",
            (hour, minute, chat_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_active_users() -> list[dict]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE is_active = 1"
        ).fetchall()
    finally:
        conn.close()


# --- Companies ---

def add_company(chat_id: int, name: str, url: str, keywords: list[str]) -> int:
    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "INSERT INTO companies (chat_id, name, url, keywords, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, name, url, ",".join(keywords), now),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def remove_company(chat_id: int, company_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM companies WHERE id = ? AND chat_id = ?",
            (company_id, chat_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def list_companies(chat_id: int) -> list[dict]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM companies WHERE chat_id = ? ORDER BY name",
            (chat_id,),
        ).fetchall()
    finally:
        conn.close()


def get_companies_for_check(chat_id: int) -> list[dict]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM companies WHERE chat_id = ? AND is_paused = 0 ORDER BY name",
            (chat_id,),
        ).fetchall()
    finally:
        conn.close()


def set_company_paused(company_id: int, paused: bool) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE companies SET is_paused = ? WHERE id = ?",
            (1 if paused else 0, company_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_keywords(company_id: int, keywords: list[str]) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE companies SET keywords = ? WHERE id = ?",
            (",".join(keywords), company_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- Stats (anonymized) ---

def get_stats() -> dict:
    conn = get_connection()
    try:
        total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        active_users = conn.execute("SELECT COUNT(*) as c FROM users WHERE is_active = 1").fetchone()["c"]
        total_companies = conn.execute("SELECT COUNT(*) as c FROM companies").fetchone()["c"]
        active_companies = conn.execute("SELECT COUNT(*) as c FROM companies WHERE is_paused = 0").fetchone()["c"]
        paused_companies = total_companies - active_companies
        companies_with_keywords = conn.execute(
            "SELECT COUNT(*) as c FROM companies WHERE keywords != ''"
        ).fetchone()["c"]
        checked = conn.execute("SELECT COUNT(*) as c FROM state WHERE last_checked IS NOT NULL").fetchone()["c"]
        # Top 5 most tracked company names (anonymized — no user data)
        top_companies = conn.execute(
            "SELECT name, COUNT(*) as c FROM companies GROUP BY LOWER(name) ORDER BY c DESC LIMIT 5"
        ).fetchall()
        # Average companies per user
        avg_per_user = round(total_companies / total_users, 1) if total_users > 0 else 0
        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_companies": total_companies,
            "active_companies": active_companies,
            "paused_companies": paused_companies,
            "companies_with_keywords": companies_with_keywords,
            "checked_companies": checked,
            "avg_companies_per_user": avg_per_user,
            "top_companies": top_companies,
        }
    finally:
        conn.close()


# --- State ---

def get_stored_lines(company_id: int) -> set[str] | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT lines FROM state WHERE company_id = ?", (company_id,)
        ).fetchone()
        if row is None:
            return None
        return set(json.loads(row["lines"]))
    finally:
        conn.close()


def save_lines(company_id: int, lines: set[str]) -> None:
    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        lines_json = json.dumps(sorted(lines), ensure_ascii=False)
        conn.execute(
            "INSERT OR REPLACE INTO state (company_id, lines, last_checked, version) "
            "VALUES (?, ?, ?, 2)",
            (company_id, lines_json, now),
        )
        conn.commit()
    finally:
        conn.close()
