"""Assemble everything on one pitcher report (P1). Used by the app page and the PDF export."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from metrics import pitching, scores
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
    score: scores.ScoreSummary

    @property
    def throws_short(self) -> str:
        return {"Right": "RHP", "Left": "LHP"}.get(self.throws, self.throws or "")

    @property
    def grades(self) -> list[scores.ScoreSummary]:
        return [self.score]


def er_text(line: dict) -> str:
    return str(line["ER"]) if line["ER"] != "—" else "—*"


def runs_footnote(line: dict) -> str:
    """Where R and ER came from (shared by the app and the PDF)."""
    official = line["runs_official"]
    if official == "all":
        return "R and ER are official (box score): runs are charged to the pitcher who put the runner on."
    if official == "some":
        return ("* R is official (box score) for games with play-by-play loaded and TrackMan's runs scored while "
                "he pitched for the rest; ER needs the play-by-play for every game.")
    return ("* ER needs the game's official play-by-play (Game Context page). R = runs scored while this pitcher "
            "was on the mound (TrackMan).")


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
        score=scores.pitcher_scores(df, pitcher_id),
    )
