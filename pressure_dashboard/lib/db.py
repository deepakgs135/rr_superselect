"""Small read-only SQLite accessors used by page scripts."""

from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
DB_PATH = APP_DIR / "data" / "processed" / "analytics.sqlite3"
QUALITY_PATH = APP_DIR / "data" / "validation" / "quality.json"


def _ensure_bowling_columns() -> None:
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(deliveries)").fetchall()}
        changed = False
        if "current_rpo" not in cols:
            conn.execute("ALTER TABLE deliveries ADD COLUMN current_rpo REAL")
            changed = True
        if "bowling_pressure" not in cols:
            conn.execute("ALTER TABLE deliveries ADD COLUMN bowling_pressure INTEGER DEFAULT 0")
            changed = True
        if changed:
            conn.executescript(
                """
                UPDATE deliveries
                SET current_rpo = CASE
                    WHEN state_known = 1 AND scheduled_balls IS NOT NULL AND balls_remaining IS NOT NULL AND scheduled_balls > balls_remaining
                    THEN score_before * 6.0 / (scheduled_balls - balls_remaining)
                    ELSE NULL
                END;
                UPDATE deliveries
                SET bowling_pressure = CASE
                    WHEN state_known = 1 AND wickets_lost <= 2 AND (
                        (balls_remaining > 0 AND balls_remaining <= 30 AND rrr >= 9.0)
                        OR (balls_remaining <= 108 AND current_rpo > 11.0)
                    )
                    THEN 1 ELSE 0
                END;
                DROP VIEW IF EXISTS chase_states;
                CREATE VIEW chase_states AS SELECT * FROM deliveries WHERE innings = 2;
                CREATE INDEX IF NOT EXISTS idx_delivery_bowling_pressure ON deliveries(bowling_pressure, match_id);
                """
            )
            conn.commit()
    finally:
        conn.close()


@lru_cache(maxsize=256)
def _cached_query(
    sql: str,
    params: tuple[Any, ...],
    database_mtime: int,
) -> tuple[tuple[tuple[str, Any], ...], ...]:
    if not DB_PATH.exists():
        return ()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    try:
        rows = conn.execute(sql, params).fetchall()
        return tuple(tuple(dict(row).items()) for row in rows)
    except sqlite3.OperationalError as exc:
        if "no such column" in str(exc).lower():
            conn.close()
            _ensure_bowling_columns()
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            rows = conn.execute(sql, params).fetchall()
            return tuple(tuple(dict(row).items()) for row in rows)
        raise
    finally:
        conn.close()


def query(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    return [
        dict(row)
        for row in _cached_query(sql, tuple(params), DB_PATH.stat().st_mtime_ns)
    ]


@lru_cache(maxsize=4)
def _cached_quality(path: str, modified: int) -> str:
    return Path(path).read_text(encoding="utf-8")


def quality_report() -> dict[str, Any]:
    if not QUALITY_PATH.exists():
        return {}
    return json.loads(
        _cached_quality(str(QUALITY_PATH), QUALITY_PATH.stat().st_mtime_ns)
    )


def database_ready() -> bool:
    return DB_PATH.exists()
