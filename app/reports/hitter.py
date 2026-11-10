"""Assemble everything on one hitter report (P2). Used by the app page and the PDF export."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import config
from metrics import hitting, scores
from metrics.common import ZoneGrid
from reports.context import Scope, display_name, fmt_date, scope_of


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
    sequences: pd.DataFrame    # page 2: one row per PA, every pitch as count + type
    count_mix: pd.DataFrame    # page 2: pitch-type % in each count
    score: scores.ScoreSummary
    clutch: scores.ScoreSummary
    sequence_filter: str = ""  # page 2: which at-bats are listed, when the coach filtered them

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


SEQUENCE_NOTE = ("Each pitch is the count before it, then the pitch type (FB = four-seam or sinker, CT = cutter, "
                 "SL slider, ST sweeper, CU curveball, CH changeup, FS splitter, KN knuckleball, OT other). PA = his "
                 "trip to the plate in that game (1 = first). Result uses the official scoring where the "
                 "play-by-play is loaded.")
COUNT_MIX_NOTE = ("% of the pitches he saw in each count that were each pitch type (each row adds to 100%). The "
                  "count is balls-strikes before the pitch. Even includes 0-0; two strikes includes 3-2.")


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
    return assemble(h, str(hitter_id), display_name(h["hitter"].iloc[-1]),
                    scores.hitter_scores(df, hitter_id), scores.clutch_scores(df, hitter_id))


def assemble(h: pd.DataFrame, hitter_id: str, name: str, score: scores.ScoreSummary,
             clutch: scores.ScoreSummary) -> HitterReport:
    """The report for the pitches in `h` (one hitter's, or a whole lineup's for the team report)."""
    points, counts = hitting.swing_decisions(h)
    return HitterReport(
        hitter_id=hitter_id,
        name=name,
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
        sequences=hitting.at_bat_sequences(h),
        count_mix=hitting.pitch_mix_by_count(h),
        score=score,
        clutch=clutch,
    )


# --- Page 2: at-bat sequences and pitch mix by count ---------------------------------------------

def colored_sequence(seq: str, color_tag) -> str:
    """The sequence text with each pitch code shown as it reads in the sequences (config.SEQUENCE_CODES:
    FB for four-seams and sinkers, CT for cutters) and wrapped by `color_tag(label, color)` (HTML for the
    app, ReportLab markup for the PDF). "0-0 SI, 0-1 SL" -> "0-0 <FB>, 0-1 <SL>"."""
    out = []
    for item in seq.split(", ") if seq else []:
        count, _, code = item.rpartition(" ")
        label = config.SEQUENCE_CODES.get(code, code)
        color_code = config.SEQUENCE_COLOR_OF.get(code, code)
        pt = config.PITCH_TYPES.get(color_code, config.PITCH_TYPES["OT"])
        out.append(f"{count} {color_tag(label, pt['color'])}".strip())
    return ", ".join(out)


def sequence_teams(seq: pd.DataFrame) -> list[str]:
    """The pitching teams in the at-bat list, for its Team filter."""
    return sorted({t for t in seq["team"] if t}) if not seq.empty else []


def sequence_dates(seq: pd.DataFrame) -> list[str]:
    """The game dates in the at-bat list (ISO), newest first, for its Date filter."""
    return sorted({d for d in seq["game_date"] if d}, reverse=True) if not seq.empty else []


def filter_sequences(seq: pd.DataFrame, teams=(), dates=()) -> tuple[pd.DataFrame, str]:
    """The at-bats against `teams` on `dates` (empty = all), and a note saying what was picked ("" for
    every at-bat). PA numbers keep counting within each game, so a filtered list still says which trip
    each one was."""
    out = seq
    parts = []
    if teams:
        out = out[out["team"].isin(teams)]
        parts.append("vs " + ", ".join(teams))
    if dates:
        out = out[out["game_date"].isin(dates)]
        parts.append("on " + ", ".join(fmt_date(d) for d in sorted(dates)))
    note = f"Only at-bats {' '.join(parts)}." if parts else ""
    return out, note


def sequence_rows(seq: pd.DataFrame) -> list[dict]:
    """At-bat sequences as display text, one dict per PA: Date, Opp, PA, Inn, Pitcher, Sequence, Result."""
    rows = []
    for r in seq.itertuples(index=False):
        hand = f" ({r.throws}HP)" if r.throws in ("R", "L") else ""
        d = pd.Timestamp(r.game_date) if r.game_date else None
        rows.append({"Date": f"{d.month}/{d.day}" if d is not None else "—", "Opp": r.team or "—",
                     "PA": str(r.pa_no), "Inn": "" if pd.isna(r.Inning) else str(int(r.Inning)),
                     "Pitcher": display_name(r.pitcher or "") + hand, "Sequence": r.sequence,
                     "Result": r.result or "—"})
    return rows


def count_mix_rows(mix: pd.DataFrame) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Pitch mix by count as text: (pitch-type codes in column order, [(row label, ["n", "40%", ...])])."""
    types = [c for c in mix.columns if c != "Pitches"]
    rows = [(label, [str(int(r["Pitches"]))] + [f"{r[t]:.0f}%" if r[t] else "–" for t in types])
            for label, r in mix.iterrows()]
    return types, rows
