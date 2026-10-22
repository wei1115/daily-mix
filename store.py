# -*- coding: utf-8 -*-
"""SQLite storage: daily playlists, play history, enrichment cache."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "dailymix.db")
_lock = threading.Lock()


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init():
    with _lock, closing(_connect()) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS playlists (
            date       TEXT PRIMARY KEY,
            payload    TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS seen (
            key        TEXT PRIMARY KEY,
            artist     TEXT,
            title      TEXT,
            first_seen TEXT,
            last_seen  TEXT
        );
        CREATE TABLE IF NOT EXISTS cache (
            key        TEXT PRIMARY KEY,
            payload    TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)
        conn.commit()


def get_playlist(date: str):
    with _lock, closing(_connect()) as conn:
        row = conn.execute("SELECT payload FROM playlists WHERE date = ?", (date,)).fetchone()
    return json.loads(row["payload"]) if row else None


def save_playlist(date: str, payload: dict):
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO playlists(date, payload, created_at) VALUES(?,?,?) "
            "ON CONFLICT(date) DO UPDATE SET payload=excluded.payload, created_at=excluded.created_at",
            (date, json.dumps(payload, ensure_ascii=False), now))
        conn.commit()


def list_dates(limit: int = 30):
    with _lock, closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT date, created_at FROM playlists ORDER BY date DESC LIMIT ?", (limit,)).fetchall()
    return [{"date": r["date"], "created_at": r["created_at"]} for r in rows]


def seen_map(days: int = 30) -> dict[str, str]:
    """key -> last_seen date (YYYY-MM-DD), for per-source lookback windows."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with _lock, closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT key, last_seen FROM seen WHERE last_seen >= ?", (cutoff,)).fetchall()
    return {r["key"]: (r["last_seen"] or "")[:10] for r in rows}


def mark_seen(items):
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, closing(_connect()) as conn:
        for it in items:
            conn.execute(
                "INSERT INTO seen(key, artist, title, first_seen, last_seen) VALUES(?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen",
                (it["key"], it["artist"], it["title"], now, now))
        conn.commit()


def cache_get(key: str, max_age_days: int = 45):
    with _lock, closing(_connect()) as conn:
        row = conn.execute("SELECT payload, updated_at FROM cache WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    try:
        age = datetime.now() - datetime.fromisoformat(row["updated_at"])
    except ValueError:
        return None
    if age.days > max_age_days:
        return None
    try:
        return json.loads(row["payload"])
    except json.JSONDecodeError:
        return None


def cache_set(key: str, payload):
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO cache(key, payload, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (key, json.dumps(payload, ensure_ascii=False), now))
        conn.commit()


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

def prune_cache(max_age_days: int = 60) -> int:
    """Drop enrichment cache rows that have aged out; keeps the DB small."""
    cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat(timespec="seconds")
    with _lock, closing(_connect()) as conn:
        removed = conn.execute("DELETE FROM cache WHERE updated_at < ?", (cutoff,)).rowcount
        conn.commit()
    return removed


def db_stats() -> dict:
    size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    with _lock, closing(_connect()) as conn:
        playlists = conn.execute("SELECT COUNT(*) AS c FROM playlists").fetchone()["c"]
        seen = conn.execute("SELECT COUNT(*) AS c FROM seen").fetchone()["c"]
        cached = conn.execute("SELECT COUNT(*) AS c FROM cache").fetchone()["c"]
    return {"bytes": size, "playlists": playlists, "seen": seen, "cache": cached}


def clear_cache(keep_today: bool = True, seen_days: int = 30) -> dict:
    """Drop old playlists, the enrichment cache, and stale dedupe rows."""
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=seen_days)).strftime("%Y-%m-%d")

    with _lock, closing(_connect()) as conn:
        if keep_today:
            n_playlists = conn.execute(
                "DELETE FROM playlists WHERE date < ?", (today,)).rowcount
        else:
            n_playlists = conn.execute("DELETE FROM playlists").rowcount
        n_cache = conn.execute("DELETE FROM cache").rowcount
        n_seen = conn.execute("DELETE FROM seen WHERE last_seen < ?", (cutoff,)).rowcount
        conn.commit()

    # Reclaim disk space; harmless if it cannot run right now.
    try:
        with _lock, closing(_connect()) as conn:
            conn.isolation_level = None
            conn.execute("VACUUM")
    except sqlite3.Error:
        pass

    return {
        "playlists": n_playlists,
        "cache": n_cache,
        "seen": n_seen,
        "stats": db_stats(),
    }
