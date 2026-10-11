"""Assemble everything on one hitter report (P2). Used by the app page and the PDF export."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import config
from metrics import hitting, scores
from metrics.common import ZoneGrid
from reports.context import Scope, display_name, scope_of


@dataclass
class HitterReport:
    hitter_id: str
    name: str
    sides: list[str]           # "Right", "Left", or both for a switch hitter
    team: str
    scope: Scope
    key: dict
    breakdown: pd.DataFrame    # pitch breakdown, Stats, one row per type faced plus "All"
    spray: hitting.SprayData
    contact: hitting.ContactData
    zone_avg: ZoneGrid
    zone_ev: ZoneGrid
    chase: hitting.ChaseMap
    decisions: pd.DataFrame
    decision_counts: dict[str, int]
    splits: pd.DataFrame       # vs RHP / LHP, then by pitcher velo tier
    score: scores.ScoreSummary
    clutch: scores.ScoreSummary

    @property
    def grades(self) -> list[scores.ScoreSummary]:
        return [self.score, self.clutch]

    @property
    def bats_short(self) -> str:
        s = set(self.sides)
        if s == {"Right", "Left"}:
            return "S"
        return {"Right": "R", "Left": "L"}.get(next(iter(s), ""), "")


SPLITS_NOTE = ("Velo tier = the pitcher's average fastball velo (four-seam and sinker) over the games in this "
               "report. HH %, Avg EV and Max EV use tracked balls in play. BABIP = (H − HR) ÷ (AB − K − HR + SF).")


def key_note(k: dict) -> str:
    rbi = f" · {k['RBI']} RBI" if k["RBI"] is not None else ""
    return f"{k['PA']} PA · {k['AB']} AB · {k['H']} H · {k['BB']} BB · {k['K']} K{rbi}"


def key_footnote(k: dict) -> str:
    qab = ("QAB = hard-hit ball, BB, HBP, hit, RBI, 4+ pitches with two strikes, 8+ pitches, or a runner moved up "
           "with nobody out (the last three not on a strikeout).")
    if not k["qab_full"]:
        qab += " RBI and runner moves need the play-by-play, so they aren't counted in games without it."
    return (f"wOBA uses 2025 MLB weights (FanGraphs). Exit velo, launch angle and Hard Hit % use balls in play "
            f"only; Hard Hit = {config.HARD_HIT_MPH:g} mph or harder; n = tracked balls in play. {qab}")


def build(df: pd.DataFrame, hitter_id: str) -> HitterReport | None:
    """`df` is the filtered analysis frame for all players; returns None if he saw no pitches."""
    h = hitting.for_hitter(df, hitter_id)
    if h.empty:
        return None
    points, counts = hitting.swing_decisions(h)
    return HitterReport(
        hitter_id=str(hitter_id),
        name=display_name(h["hitter"].iloc[-1]),
        sides=sorted({s for s in h["hitter_side"] if s in ("Right", "Left")}, reverse=True),
        team=h["BatterTeam"].iloc[-1],
        scope=scope_of(h),
        key=hitting.key_metrics(h),
        breakdown=hitting.pitch_breakdown(h),
        spray=hitting.spray_points(h),
        contact=hitting.contact_points(h),
        zone_avg=hitting.zone_avg(h),
        zone_ev=hitting.zone_ev(h),
        chase=hitting.chase_map(h),
        decisions=points,
        decision_counts=counts,
        splits=hitting.pitcher_splits(h),
        score=scores.hitter_scores(df, hitter_id),
        clutch=scores.clutch_scores(df, hitter_id),
    )
