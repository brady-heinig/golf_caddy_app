"""SQLite shot history for the AI Golf Caddie."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_DB = Path(__file__).resolve().parent / "shots.db"


def _migrate_shots_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(shots)").fetchall()}
    if "proximity_ft" not in cols:
        conn.execute("ALTER TABLE shots ADD COLUMN proximity_ft INTEGER")
        conn.commit()


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Create tables if they don't exist. Return open connection."""
    path = str(_DEFAULT_DB if db_path is None else db_path)
    # Streamlit reruns may use different threads; SQLite default would raise.
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS shots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at   TEXT NOT NULL,
            course_id   TEXT NOT NULL,
            hole        INTEGER NOT NULL,
            shot_number INTEGER NOT NULL,
            club        TEXT NOT NULL,
            distance_to_pin_before INTEGER,
            distance_achieved      INTEGER,
            lie         TEXT,
            shot_shape  TEXT,
            result      TEXT,
            notes       TEXT,
            proximity_ft INTEGER
        );

        CREATE TABLE IF NOT EXISTS courses (
            course_id   TEXT PRIMARY KEY,
            name        TEXT,
            raw_json    TEXT,
            updated_at  TEXT
        );
        """
    )
    conn.commit()
    _migrate_shots_columns(conn)
    return conn


def log_shot(
    conn,
    course_id,
    hole,
    shot_number,
    club,
    distance_to_pin_before,
    lie,
    shot_shape,
    result=None,
    distance_achieved=None,
    notes=None,
    proximity_ft: int | None = None,
) -> int:
    """Insert one shot row. Return new row id."""
    logged_at = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        INSERT INTO shots (
            logged_at, course_id, hole, shot_number, club,
            distance_to_pin_before, lie, shot_shape, result,
            distance_achieved, notes, proximity_ft
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            logged_at,
            course_id,
            hole,
            shot_number,
            club,
            distance_to_pin_before,
            lie,
            shot_shape,
            result,
            distance_achieved,
            notes,
            proximity_ft,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_shots_at_distance(
    conn, distance_yards: int, tolerance: int = 15, limit: int = 20
) -> list[dict]:
    """
    Return the most recent `limit` shots where
    distance_to_pin_before is within ±tolerance of distance_yards.
    Order by logged_at DESC.
    """
    lo = distance_yards - tolerance
    hi = distance_yards + tolerance
    cur = conn.execute(
        """
        SELECT club, distance_to_pin_before, lie, shot_shape, result, logged_at, proximity_ft
        FROM shots
        WHERE distance_to_pin_before IS NOT NULL
          AND distance_to_pin_before BETWEEN ? AND ?
        ORDER BY logged_at DESC
        LIMIT ?
        """,
        (lo, hi, limit),
    )
    rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_shots_for_hole(
    conn, course_id: str, hole: int, limit: int = 10
) -> list[dict]:
    """Return recent shots for a specific hole."""
    cur = conn.execute(
        """
        SELECT club, distance_to_pin_before, lie, shot_shape, result, logged_at, proximity_ft
        FROM shots
        WHERE course_id = ? AND hole = ?
        ORDER BY logged_at DESC
        LIMIT ?
        """,
        (course_id, hole, limit),
    )
    return [dict(r) for r in cur.fetchall()]


def get_club_stats(conn, club: str) -> dict:
    """
    Return a summary dict for a club:
    { average_distance, shot_count, result_breakdown: {green: n, fairway: n, ...} }
    """
    cur = conn.execute(
        """
        SELECT distance_achieved, distance_to_pin_before, result
        FROM shots
        WHERE club = ?
        """,
        (club,),
    )
    rows = cur.fetchall()
    distances: list[float] = []
    breakdown: dict[str, int] = {}
    for r in rows:
        d = r["distance_achieved"]
        if d is not None and d > 0:
            distances.append(float(d))
        elif r["distance_to_pin_before"] is not None:
            distances.append(float(r["distance_to_pin_before"]))
        res = (r["result"] or "unknown").lower().strip()
        breakdown[res] = breakdown.get(res, 0) + 1
    shot_count = len(rows)
    avg = sum(distances) / len(distances) if distances else 0.0
    return {
        "average_distance": avg,
        "shot_count": shot_count,
        "result_breakdown": breakdown,
    }


def format_history_for_prompt(shots: list[dict]) -> str:
    """
    Convert a list of shot dicts into a compact multi-line string
    suitable for injection into the Claude prompt.
    """
    lines: list[str] = []
    for s in shots:
        club = s.get("club") or "?"
        d = s.get("distance_to_pin_before")
        dist_s = f"{d} yds" if d is not None else "? yds"
        lie = s.get("lie") or "?"
        shape = s.get("shot_shape") or "?"
        result = s.get("result") or "?"
        px = s.get("proximity_ft")
        px_s = f" | {px} ft to hole" if px is not None else ""
        lines.append(f"  - {club} | {dist_s} | {lie} | {shape} → {result}{px_s}")
    return "\n".join(lines)
