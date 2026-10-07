"""SQLite storage: raw pitches, game context, and pitch-type corrections.

Raw rows are stored exactly as read from the CSV (every column, as text) and are never updated.
Corrections and filters are applied at query time (rule 1). No UI code lives here.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS pitches (
    pitch_uid   TEXT PRIMARY KEY,
    game_id     TEXT NOT NULL,
    game_date   TEXT,            -- ISO date derived at load, used only for filtering
    source_file TEXT,
    loaded_at   TEXT,
    raw_json    TEXT NOT NULL    -- the full CSV row, every column as text, exactly as read
);
CREATE INDEX IF NOT EXISTS ix_pitches_game ON pitches(game_id);
CREATE INDEX IF NOT EXISTS ix_pitches_date ON pitches(game_date);

CREATE TABLE IF NOT EXISTS games (
    game_id           TEXT PRIMARY KEY,
    game_date         TEXT,
    stadium           TEXT,
    first_pitch_local TEXT,
    game_type         TEXT,
    opponent          TEXT,
    home_away         TEXT,
    temp_f            REAL,
    humidity_pct      REAL,
    wind_mph          REAL,
    wind_dir          TEXT,
    notes             TEXT,
    weather_source    TEXT,      -- e.g. "NWS station KMLJ"; NULL when entered by hand
    updated_at        TEXT
);

CREATE TABLE IF NOT EXISTS pitch_type_rules (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pitcher_id     TEXT NOT NULL,
    pitcher_name   TEXT,
    auto_type      TEXT NOT NULL,   -- pitch code, e.g. CH
    min_velo       REAL,            -- optional inclusive bound on RelSpeed
    max_velo       REAL,            -- optional inclusive bound on RelSpeed
    corrected_type TEXT NOT NULL,   -- pitch code, e.g. SI
    note           TEXT,
    created_at     TEXT
);

CREATE TABLE IF NOT EXISTS pitch_overrides (
    pitch_uid      TEXT PRIMARY KEY,
    corrected_type TEXT NOT NULL,
    note           TEXT,
    created_at     TEXT
);

CREATE TABLE IF NOT EXISTS loads (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file       TEXT,
    loaded_at         TEXT,
    rows_in_file      INTEGER,
    added             INTEGER,
    skipped_duplicate INTEGER,
    skipped_no_uid    INTEGER
);
"""

GAME_FIELDS = ["game_date", "stadium", "first_pitch_local", "game_type", "opponent", "home_away",
               "temp_f", "humidity_pct", "wind_mph", "wind_dir", "notes", "weather_source"]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (and create if needed) the database. Pass ":memory:" for a throwaway database."""
    path = config.DB_PATH if path is None else path
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# --- Pitches ------------------------------------------------------------------------------------

def insert_pitches(conn: sqlite3.Connection, rows: list[dict], source_file: str) -> tuple[int, int]:
    """Insert raw rows, skipping any PitchUID already stored. Returns (added, skipped)."""
    loaded_at = _now()
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO pitches (pitch_uid, game_id, game_date, source_file, loaded_at, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(r["pitch_uid"], r["game_id"], r["game_date"], source_file, loaded_at, json.dumps(r["raw"]))
         for r in rows],
    )
    conn.commit()
    added = conn.total_changes - before
    return added, len(rows) - added


def count_pitches(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM pitches").fetchone()[0]


def query_pitches(conn: sqlite3.Connection, date_from: str | None = None, date_to: str | None = None,
                  game_ids: list[str] | None = None, game_types: list[str] | None = None,
                  home_away: list[str] | None = None, temp_min: float | None = None,
                  temp_max: float | None = None) -> pd.DataFrame:
    """Return raw pitch rows (all text) matching the game filters, with game context attached.

    Context columns are prefixed `game_` so they never collide with TrackMan columns. A temperature
    filter excludes games with no temperature recorded.
    """
    where, params = [], []
    if date_from:
        where.append("p.game_date >= ?"); params.append(str(date_from))
    if date_to:
        where.append("p.game_date <= ?"); params.append(str(date_to))
    if game_ids:
        where.append(f"p.game_id IN ({','.join('?' * len(game_ids))})"); params += list(game_ids)
    if game_types:
        where.append(f"g.game_type IN ({','.join('?' * len(game_types))})"); params += list(game_types)
    if home_away:
        where.append(f"g.home_away IN ({','.join('?' * len(home_away))})"); params += list(home_away)
    if temp_min is not None:
        where.append("g.temp_f >= ?"); params.append(temp_min)
    if temp_max is not None:
        where.append("g.temp_f <= ?"); params.append(temp_max)
    sql = ("SELECT p.raw_json, g.game_type, g.home_away, g.opponent, g.temp_f "
           "FROM pitches p LEFT JOIN games g ON g.game_id = p.game_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([json.loads(r["raw_json"]) for r in rows])
    df["game_type"] = [r["game_type"] for r in rows]
    df["game_home_away"] = [r["home_away"] for r in rows]
    df["game_opponent"] = [r["opponent"] for r in rows]
    df["game_temp_f"] = [r["temp_f"] for r in rows]
    return df


# --- Games --------------------------------------------------------------------------------------

def insert_game_if_new(conn: sqlite3.Connection, game_id: str, fields: dict) -> bool:
    """Create the game row with pre-filled values. Never overwrites a game a coach already edited."""
    cols = ["game_id"] + [f for f in GAME_FIELDS if f in fields] + ["updated_at"]
    vals = [game_id] + [fields[f] for f in GAME_FIELDS if f in fields] + [_now()]
    cur = conn.execute(f"INSERT OR IGNORE INTO games ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
    conn.commit()
    return cur.rowcount == 1


def update_game(conn: sqlite3.Connection, game_id: str, fields: dict) -> None:
    fields = {k: v for k, v in fields.items() if k in GAME_FIELDS}
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = ?"
    conn.execute(f"UPDATE games SET {sets} WHERE game_id = ?", [*fields.values(), _now(), game_id])
    conn.commit()


def get_games(conn: sqlite3.Connection) -> pd.DataFrame:
    rows = conn.execute("SELECT * FROM games ORDER BY game_date, game_id").fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=["game_id", *GAME_FIELDS, "updated_at"])


# --- Pitch-type corrections ---------------------------------------------------------------------

def add_rule(conn: sqlite3.Connection, pitcher_id: str, pitcher_name: str, auto_type: str,
             corrected_type: str, min_velo: float | None = None, max_velo: float | None = None,
             note: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO pitch_type_rules (pitcher_id, pitcher_name, auto_type, min_velo, max_velo, "
        "corrected_type, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (str(pitcher_id), pitcher_name, auto_type, min_velo, max_velo, corrected_type, note, _now()))
    conn.commit()
    return cur.lastrowid


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    conn.execute("DELETE FROM pitch_type_rules WHERE id = ?", (rule_id,))
    conn.commit()


def get_rules(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM pitch_type_rules ORDER BY id").fetchall()]


def set_override(conn: sqlite3.Connection, pitch_uid: str, corrected_type: str, note: str | None = None) -> None:
    conn.execute("INSERT OR REPLACE INTO pitch_overrides (pitch_uid, corrected_type, note, created_at) "
                 "VALUES (?, ?, ?, ?)", (pitch_uid, corrected_type, note, _now()))
    conn.commit()


def delete_override(conn: sqlite3.Connection, pitch_uid: str) -> None:
    conn.execute("DELETE FROM pitch_overrides WHERE pitch_uid = ?", (pitch_uid,))
    conn.commit()


def get_overrides(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["pitch_uid"]: r["corrected_type"]
            for r in conn.execute("SELECT pitch_uid, corrected_type FROM pitch_overrides").fetchall()}


# --- Load log -----------------------------------------------------------------------------------

def log_load(conn: sqlite3.Connection, source_file: str, rows_in_file: int, added: int,
             skipped_duplicate: int, skipped_no_uid: int) -> None:
    conn.execute("INSERT INTO loads (source_file, loaded_at, rows_in_file, added, skipped_duplicate, "
                 "skipped_no_uid) VALUES (?, ?, ?, ?, ?, ?)",
                 (source_file, _now(), rows_in_file, added, skipped_duplicate, skipped_no_uid))
    conn.commit()


def get_loads(conn: sqlite3.Connection) -> pd.DataFrame:
    rows = conn.execute("SELECT * FROM loads ORDER BY id DESC").fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=["id", "source_file", "loaded_at", "rows_in_file",
                                                          "added", "skipped_duplicate", "skipped_no_uid"])


def game_pitch_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute("SELECT game_id, COUNT(*) FROM pitches GROUP BY game_id")}


def data_version(conn: sqlite3.Connection) -> tuple:
    """Changes whenever anything a report reads changes; the app uses it as a cache key."""
    q = lambda sql: conn.execute(sql).fetchone()  # noqa: E731
    return (q("SELECT COUNT(*), MAX(loaded_at) FROM pitches")[:],
            tuple(tuple(r) for r in conn.execute("SELECT * FROM games ORDER BY game_id")),
            tuple(tuple(r) for r in conn.execute("SELECT * FROM pitch_type_rules ORDER BY id")),
            tuple(tuple(r) for r in conn.execute("SELECT pitch_uid, corrected_type FROM pitch_overrides ORDER BY 1")))
