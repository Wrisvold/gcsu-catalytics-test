"""Report filters and the query-time analysis frame shared by the app and the PDF export.

No UI code lives here. `load_frame()` reads raw rows from SQLite, then applies coach pitch-type
corrections and every derived column through `metrics.common.prepare()` (rule 1).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

import pandas as pd

import config
import db
from metrics.common import prepare


@dataclass(frozen=True)
class ReportFilters:
    """Game-level filters. Empty tuples and None mean "no filter"."""
    date_from: str | None = None
    date_to: str | None = None
    game_ids: tuple[str, ...] = ()
    game_types: tuple[str, ...] = ()
    home_away: tuple[str, ...] = ()
    temp_min: float | None = None
    temp_max: float | None = None


def load_frame(conn: sqlite3.Connection, f: ReportFilters) -> pd.DataFrame:
    """Analysis frame for every pitch in the games that pass the filters, corrections applied."""
    raw = db.query_pitches(conn, f.date_from, f.date_to, list(f.game_ids) or None,
                           list(f.game_types) or None, list(f.home_away) or None, f.temp_min, f.temp_max)
    return prepare(raw, db.get_rules(conn), db.get_overrides(conn))


def display_name(trackman_name: str) -> str:
    """TrackMan stores "Last, First"; reports print "First Last"."""
    if "," in trackman_name:
        last, first = (p.strip() for p in trackman_name.split(",", 1))
        return f"{first} {last}".strip()
    return trackman_name.strip()


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


@dataclass
class Scope:
    """What a report covers, printed in its header and footer."""
    first_date: str | None
    last_date: str | None
    games: int
    game_types: list[str]

    @property
    def date_text(self) -> str:
        if self.first_date == self.last_date:
            return fmt_date(self.first_date)
        return f"{fmt_date(self.first_date)} – {fmt_date(self.last_date)}"

    @property
    def game_types_text(self) -> str:
        return ", ".join(self.game_types) if self.game_types else "Game type not set"

    @property
    def season_text(self) -> str:
        """"Fall 2026" style label from the first date (Aug–Dec = Fall, Jan–Jul = Spring)."""
        if not self.first_date:
            return ""
        d = date.fromisoformat(self.first_date)
        return f"{'Fall' if d.month >= 8 else 'Spring'} {d.year}"


def scope_of(df: pd.DataFrame) -> Scope:
    if df.empty:
        return Scope(None, None, 0, [])
    dates = df["game_date"].dropna()
    types = sorted({t for t in df.get("game_type", []) if isinstance(t, str) and t})
    return Scope(dates.min() if len(dates) else None, dates.max() if len(dates) else None,
                 int(df["GameID"].nunique()), types)


def filters_text(f: ReportFilters) -> str:
    """Filters beyond the date range, for report footers. Empty when there are none."""
    bits = []
    if f.home_away:
        bits.append("/".join(f.home_away))
    if f.temp_min is not None or f.temp_max is not None:
        lo = "" if f.temp_min is None else f"{f.temp_min:g}"
        hi = "" if f.temp_max is None else f"{f.temp_max:g}"
        bits.append(f"{lo}–{hi} °F")
    return ("Filters: " + ", ".join(bits) + ".") if bits else ""


def thresholds_note() -> str:
    m = config.MIN_N
    return (f"Greyed values are below their minimum sample: {m['pitches']} pitches, {m['swings']} swings, "
            f"{m['out_of_zone']} pitches outside the zone, {m['pa']} PA, {m['ab']} AB, {m['bip']} balls in play, "
            f"{m['zone_cell_ab']} per zone square. Definitions: METRICS.md. {config.DATA_SOURCE_NOTE}")
