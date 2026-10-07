"""Load TrackMan CSV exports into SQLite.

Validates required columns, skips PitchUIDs already stored (so loading a file twice adds nothing),
and pre-fills a game-context row for each GameID. Rows are stored as text exactly as read.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

import pandas as pd

import config
import db
from metrics.common import parse_game_date

# Columns the metrics need. A file missing any of these is rejected with the list of what's missing.
REQUIRED_COLUMNS = [
    "PitchNo", "Date", "PAofInning", "PitchofPA",
    "Pitcher", "PitcherId", "PitcherThrows", "PitcherTeam",
    "Batter", "BatterId", "BatterSide", "BatterTeam",
    "Inning", "Top/Bottom", "Outs", "Balls", "Strikes",
    "AutoPitchType", "PitchCall", "KorBB", "TaggedHitType", "PlayResult", "OutsOnPlay", "RunsScored",
    "RelSpeed", "SpinRate", "InducedVertBreak", "HorzBreak", "RelHeight", "Extension",
    "PlateLocHeight", "PlateLocSide",
    "ExitSpeed", "Angle", "Distance", "Bearing", "HitLaunchConfidence",
    "ContactPositionX", "ContactPositionY", "ContactPositionZ",
    "GameID", "Stadium", "PitchUID",
]


class IngestError(ValueError):
    pass


@dataclass
class IngestResult:
    source: str
    rows_in_file: int
    added: int
    skipped_duplicate: int
    skipped_no_uid: int
    game_ids: list[str] = field(default_factory=list)
    new_game_ids: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.source}: {self.rows_in_file} rows read, {self.added} added, "
                f"{self.skipped_duplicate} skipped as duplicates, {self.skipped_no_uid} skipped with no PitchUID.")


def read_trackman_csv(source: str | Path | IO) -> pd.DataFrame:
    """Read every column as text, keeping blanks as empty strings, so nothing is reinterpreted."""
    return pd.read_csv(source, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def missing_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in REQUIRED_COLUMNS if c not in df.columns]


def game_defaults(game: pd.DataFrame) -> dict:
    """What the CSV itself tells us about a game. Everything else is left for the coach."""
    dates = [d for d in (parse_game_date(l, d) for l, d in
                         zip(game.get("LocalDateTime", pd.Series([""] * len(game))), game["Date"])) if d]
    out: dict = {"game_date": min(dates) if dates else None,
                 "stadium": next((s for s in game["Stadium"] if s), None)}
    if "LocalDateTime" in game:
        times = sorted(t for t in game["LocalDateTime"] if t)
        out["first_pitch_local"] = times[0] if times else None
    intrasquad = bool((game["PitcherTeam"] == game["BatterTeam"]).all())
    if intrasquad:
        out["game_type"] = "Intrasquad"
    if "HomeTeam" in game and "AwayTeam" in game:
        home, away = game["HomeTeam"].iloc[0], game["AwayTeam"].iloc[0]
        if home == config.TEAM_CODE:
            out["home_away"] = "Home"
            if not intrasquad and away:
                out["opponent"] = away
        elif away == config.TEAM_CODE:
            out["home_away"] = "Away"
            if not intrasquad and home:
                out["opponent"] = home
    return out


def load_csv(conn: sqlite3.Connection, source: str | Path | IO, source_name: str | None = None) -> IngestResult:
    """Validate a TrackMan CSV and add its new pitches. Raises IngestError if columns are missing."""
    name = source_name or (Path(source).name if isinstance(source, (str, Path)) else "upload.csv")
    df = read_trackman_csv(source)
    missing = missing_columns(df)
    if missing:
        raise IngestError(f"{name} is missing required TrackMan columns: {', '.join(missing)}")

    has_uid = df["PitchUID"].str.strip() != ""
    no_uid = int((~has_uid).sum())
    df = df[has_uid]
    in_file_dupes = int(df["PitchUID"].duplicated().sum())
    df = df.drop_duplicates("PitchUID")

    local = df["LocalDateTime"] if "LocalDateTime" in df else pd.Series([""] * len(df), index=df.index)
    rows = [{"pitch_uid": rec["PitchUID"], "game_id": rec["GameID"],
             "game_date": parse_game_date(loc, rec["Date"]), "raw": rec}
            for rec, loc in zip(df.to_dict("records"), local)]
    added, skipped = db.insert_pitches(conn, rows, name)

    game_ids = sorted(df["GameID"].unique().tolist())
    new_games = [gid for gid in game_ids
                 if db.insert_game_if_new(conn, gid, game_defaults(df[df["GameID"] == gid]))]

    result = IngestResult(name, len(has_uid), added, skipped + in_file_dupes, no_uid, game_ids, new_games)
    db.log_load(conn, name, result.rows_in_file, added, result.skipped_duplicate, no_uid)
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("Usage: python ingest.py <trackman.csv> [more.csv ...]")
    connection = db.connect()
    for p in sys.argv[1:]:
        print(load_csv(connection, p).summary())
    print(f"Database now holds {db.count_pitches(connection)} pitches ({config.DB_PATH}).")
