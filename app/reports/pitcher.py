"""Assemble everything on one pitcher report (P1). Used by the app page and the PDF export."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from metrics import pitching
from metrics.common import ZoneGrid
from reports.context import Scope, display_name, scope_of


@dataclass
class PitcherReport:
    pitcher_id: str
    name: str
    throws: str
    scope: Scope
    line: dict
    table: pd.DataFrame        # pitch-type table, Stats, one row per type plus "All"
    usage: pd.DataFrame        # usage % by type (rows) for All / vs LHH / vs RHH (columns)
    movement: pd.DataFrame
    zone_baa: ZoneGrid
    whiffs: pd.DataFrame
    splits: pd.DataFrame
    n_corrected: int           # pitches whose type a coach correction changed

    @property
    def throws_short(self) -> str:
        return {"Right": "RHP", "Left": "LHP"}.get(self.throws, self.throws or "")


def build(df: pd.DataFrame, pitcher_id: str) -> PitcherReport | None:
    """`df` is the filtered analysis frame for all players; returns None if he threw no pitches."""
    p = pitching.for_pitcher(df, pitcher_id)
    if p.empty:
        return None
    return PitcherReport(
        pitcher_id=str(pitcher_id),
        name=display_name(p["Pitcher"].iloc[-1]),
        throws=p["PitcherThrows"].iloc[-1],
        scope=scope_of(p),
        line=pitching.performance_line(p),
        table=pitching.pitch_type_table(p),
        usage=pitching.usage_by_side(p),
        movement=pitching.movement_points(p),
        zone_baa=pitching.zone_baa(p),
        whiffs=pitching.whiff_locations(p),
        splits=pitching.hitter_splits(p),
        n_corrected=int(p["pitch_type_corrected"].sum()),
    )
