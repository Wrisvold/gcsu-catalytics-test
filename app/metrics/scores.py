"""Pitcher Score, Hitter Score and Clutch Score (1-100), from the coaches' scoring sheet (Oct 2026).

Each game is scored on its own and a report shows the average of its games. Within a game:

1. Each part (Strike %, QAB %, ...) earns its points in a straight line from its floor (0 points) to
   its goal (all its points), capped at both ends. Parts with no data in that game are left out and
   the remaining parts are scaled up to 100.
2. Bonuses and penalties are added (each counted per occurrence). Pitcher Score bonuses add up to at
   most PITCHER_BONUS_CAP (+15) per game; penalties have no cap.
3. The total is rounded and held between SCORE_RANGE (1 and 100).

Parts, goals, floors and point values live in config.py; definitions are in METRICS.md section 5.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

import config
from metrics.common import (
    Stat, batting_counts, chase_pct, hard_hit_pct, obp_stat, rate, slg_stat, whiff_pct,
)


@dataclass
class ScorePart:
    key: str
    label: str
    points: float          # most it can earn
    value: Stat | None     # the stat it's built on; None when there's no data in the game
    earned: float | None   # points earned; None = left out

    @property
    def value_text(self) -> str:
        return "—" if self.value is None else self.value.text()


@dataclass
class Adjustment:
    key: str
    label: str
    count: int
    each: int

    @property
    def total(self) -> int:
        return self.count * self.each


@dataclass
class GameScore:
    game_id: str
    game_date: str | None
    opponent: str
    parts: list[ScorePart]
    adjustments: list[Adjustment]
    base: float              # parts only, scaled to 100
    total: int               # base + adjustments, rounded, within SCORE_RANGE
    notes: list[str] = field(default_factory=list)


@dataclass
class ScoreSummary:
    name: str                # "Pitcher Score", "Hitter Score", "Clutch Score"
    games: list[GameScore]
    unavailable: str = ""    # why a score couldn't be given, when there are no games

    @property
    def average(self) -> float | None:
        return sum(g.total for g in self.games) / len(self.games) if self.games else None

    @property
    def text(self) -> str:
        return "—" if self.average is None else f"{self.average:.0f}"

    @property
    def detail(self) -> str:
        n = len(self.games)
        if not n:
            return self.unavailable or "no games"
        return "1 game" if n == 1 else f"avg of {n} games"


def part_points(value: float | None, points: float, floor: float, goal: float) -> float | None:
    """Linear from floor (0) to goal (all points), capped. Works for lower-is-better (floor > goal)."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or goal == floor:
        return None
    return points * min(1.0, max(0.0, (value - floor) / (goal - floor)))


def _score(parts_spec: list, values: dict[str, Stat | None], adj_spec: dict, counts: dict[str, int],
           game_id: str, game_date, opponent: str, notes: list[str], bonus_cap: int | None = None) -> GameScore | None:
    parts = []
    for key, label, points, floor, goal in parts_spec:
        v = values.get(key)
        earned = part_points(v.value if v is not None else None, points, floor, goal)
        parts.append(ScorePart(key, label, points, v if earned is not None else None, earned))
    available = [p for p in parts if p.earned is not None]
    if not available:
        return None
    base = 100.0 * sum(p.earned for p in available) / sum(p.points for p in available)
    adjustments = [Adjustment(k, label, int(counts.get(k, 0)), each) for k, (label, each) in adj_spec.items()]
    bonus = sum(a.total for a in adjustments if a.total > 0)
    if bonus_cap is not None and bonus > bonus_cap:
        adjustments.append(Adjustment("bonus_cap", f"Bonus cap (+{bonus_cap} max)", 1, bonus_cap - bonus))
    lo, hi = config.SCORE_RANGE
    total = int(min(hi, max(lo, round(base + sum(a.total for a in adjustments)))))
    return GameScore(game_id, game_date, opponent, parts, adjustments, base, total, notes)


def _game_info(g: pd.DataFrame) -> tuple[str, str | None, str]:
    opp = g["game_opponent"].iloc[0] if "game_opponent" in g else None
    return str(g["GameID"].iloc[0]), g["game_date"].iloc[0], opp if isinstance(opp, str) else ""


def _games(df: pd.DataFrame):
    for gid in dict.fromkeys(df["GameID"]):
        yield df[df["GameID"] == gid]


def _count_02(df: pd.DataFrame) -> pd.Series:
    return (df["Balls"] == 0) & (df["Strikes"] == 2)


# --- Pitcher Score ------------------------------------------------------------------------------

def _pitcher_innings(game: pd.DataFrame, pitcher_id: str) -> dict[str, int]:
    """Full innings this pitcher threw by himself: every pitch of the half-inning, and its three outs."""
    out = {"inning_12": 0, "inning_15": 0, "one_two_three": 0}
    for _, half in game.groupby(["Inning", "Top/Bottom"], sort=False):
        if not (half["PitcherId"].astype(str) == str(pitcher_id)).all():
            continue
        ends = half[half["pa_end"]]
        outs = int(half["outs_on_pitch"].sum())
        if outs != 3:
            continue
        n = len(half)
        if n <= 12:
            out["inning_12"] += 1
        elif n <= 15:
            out["inning_15"] += 1
        if len(ends) == 3 and ends["is_pa_out"].all():
            out["one_two_three"] += 1
    return out


def pitcher_game_score(game: pd.DataFrame, pitcher_id: str) -> GameScore | None:
    """`game` is the full analysis frame for one game (every pitcher), so whole innings can be seen."""
    p = game[game["PitcherId"].astype(str) == str(pitcher_id)]
    if p.empty:
        return None
    ends = p[p["pa_end"]]
    c = batting_counts(p)
    one_one = (p["Balls"] == 1) & (p["Strikes"] == 1)
    one_one_win = (p["is_strike"] & ~p["is_bip"]) | (p["is_bip"] & p["is_pa_out"])
    notes = []
    if p["off_line"].all():
        runs = int(p["off_R"].sum())
        if "off_er" in p and not p["off_er"].all():
            notes.append("Runs Allowed charged from the coach play-by-play sheet")
    else:
        runs = int(p["RunsScored"].fillna(0).sum())
        notes.append("Runs Allowed from TrackMan (no official line for this game)")
    values = {
        "strike_pct": rate(p["is_strike"], pd.Series(True, index=p.index), None),
        "one_one_win_pct": rate(one_one_win, one_one, None),
        "first_pitch_strike_pct": rate(p["is_strike"], p["is_first_pitch"], None),
        "whiff_pct": whiff_pct(p),
        "chase_pct": chase_pct(p),
        "k_minus_bb_pct": Stat(100.0 * (c["K"] - c["BB"] - c["IBB"]) / c["PA"] if c["PA"] else None, c["PA"]),
        "runs_allowed": Stat(float(runs), len(p), 0, "count"),
    }
    bb = ends["is_bb"]
    counts = {
        "bb_4_pitch": int((bb & (ends["pa_pitches"] == 4)).sum()),
        "bb_5_pitch": int((bb & (ends["pa_pitches"] == 5)).sum()),
        "hit_0_2": int((ends["is_hit"] & _count_02(ends)).sum()),
        "bb_after_0_2": int((bb & ends["pa_was_0_2"]).sum()),
        "hbp_0_2": int((ends["is_hbp"] & _count_02(ends)).sum()),
        "out_3_pitches": int((ends["is_pa_out"] & (ends["pa_pitches"] <= 3)).sum()),
        "out_4_pitches": int((ends["is_pa_out"] & (ends["pa_pitches"] == 4)).sum()),
        **_pitcher_innings(game, pitcher_id),
    }
    return _score(config.PITCHER_SCORE_PARTS, values, config.PITCHER_SCORE_ADJUSTMENTS, counts,
                  *_game_info(p), notes, config.PITCHER_BONUS_CAP)


def pitcher_scores(df: pd.DataFrame, pitcher_id: str) -> ScoreSummary:
    """`df` is the filtered analysis frame for all players."""
    mine = set(df.loc[df["PitcherId"].astype(str) == str(pitcher_id), "GameID"])
    games = [pitcher_game_score(g, pitcher_id) for g in _games(df[df["GameID"].isin(mine)])]
    return ScoreSummary("Pitcher Score", [g for g in games if g])


# --- Hitter Score -------------------------------------------------------------------------------

def _k_split(ends: pd.DataFrame, situation: pd.Series) -> tuple[int, int]:
    k = ends["is_k"] & situation
    looking = k & (ends["PitchCall"] == "StrikeCalled")
    return int(looking.sum()), int((k & ~looking).sum())


def hitter_game_score(h: pd.DataFrame) -> GameScore | None:
    """`h` is one hitter's pitches in one game."""
    ends = h[h["pa_end"]]
    if ends.empty:
        return None
    notes = []
    if ends["gs_known"].all():
        rbi = Stat(float(ends["gs_rbi"].sum()), len(ends), 0, "count")
    else:
        rbi = None
        notes.append("RBIs left out and RISP strikeouts not split out (no play-by-play for this game)")
    kl, ks = _k_split(ends, ~ends["risp"])
    kl_risp, ks_risp = _k_split(ends, ends["risp"])
    values = {"hard_hit_pct": hard_hit_pct(h), "qab_pct": rate(h["is_qab"], h["pa_end"], None),
              "chase_pct": chase_pct(h), "rbi": rbi}
    counts = {
        "k_looking": kl, "k_swinging": ks, "k_looking_risp": kl_risp, "k_swinging_risp": ks_risp,
        "hbp": int(ends["is_hbp"].sum()),
        "hard_hit_0_2": int((ends["is_hard_hit"] & _count_02(ends)).sum()),
        "hard_hit_1_2": int((ends["is_hard_hit"] & (ends["Balls"] == 1) & (ends["Strikes"] == 2)).sum()),
        "bb_after_0_2": int((ends["is_bb"] & ends["pa_was_0_2"]).sum()),
    }
    return _score(config.HITTER_SCORE_PARTS, values, config.HITTER_SCORE_ADJUSTMENTS, counts, *_game_info(h), notes)


def hitter_scores(df: pd.DataFrame, hitter_id: str) -> ScoreSummary:
    h = df[df["hitter_id"] == str(hitter_id)]
    games = [hitter_game_score(g) for g in _games(h)]
    return ScoreSummary("Hitter Score", [g for g in games if g])


# --- Clutch Score -------------------------------------------------------------------------------

def _rbi_bonuses(ends: pd.DataFrame) -> dict[str, int]:
    """Walk-off hit, go-ahead RBI, game-tying RBI: each PA earns only the biggest of the three.
    Two-out RBI is counted on top."""
    rbi = ends["gs_rbi"] > 0
    before = ends["gs_bat_score"] - ends["gs_fld_score"]
    after = ends["gs_bat_after"] - ends["gs_fld_after"]
    sched = pd.to_numeric(ends.get("game_innings", pd.Series(index=ends.index, dtype=float)),
                          errors="coerce").fillna(config.SCHEDULED_INNINGS)
    walk_off = (ends["is_hit"] & (ends["Top/Bottom"] == "Bottom") & (ends["Inning"] >= sched)
                & (before <= 0) & (after > 0))
    go_ahead = rbi & (before <= 0) & (after > 0) & ~walk_off
    tying = rbi & (before < 0) & (after == 0)
    return {"walk_off_hit": int(walk_off.sum()), "go_ahead_rbi": int(go_ahead.sum()),
            "tying_rbi": int(tying.sum()), "two_out_rbi": int((rbi & (ends["gs_outs"] == 2)).sum())}


def clutch_game_score(h: pd.DataFrame) -> GameScore | None:
    """`h` is one hitter's pitches in one game. Scored only from plate appearances in high-leverage
    spots, so it needs the play-by-play; a game without one, or with no HL plate appearance, is
    skipped. Bonuses (walk-off, go-ahead, tying, two-out RBI) count on any plate appearance."""
    ends = h[h["pa_end"] & h["gs_known"]]
    hl = h[h["high_leverage"]]
    hl_ends = hl[hl["pa_end"]]
    if hl_ends.empty:
        return None
    c = batting_counts(hl)
    risp_ends = hl_ends[hl_ends["risp"]]
    looking = hl_ends["is_k"] & (hl_ends["PitchCall"] == "StrikeCalled")
    values = {
        "hl_hard_hit_pct": hard_hit_pct(hl),
        "hl_qab_pct": rate(hl["is_qab"], hl["pa_end"], None),
        "hl_obp": obp_stat(c),
        "hl_slg": slg_stat(c),
        "risp_rbi": Stat(float(risp_ends["gs_rbi"].sum()), len(risp_ends), 0, "count") if len(risp_ends) else None,
    }
    counts = {"hl_k": int((hl_ends["is_k"] & ~looking).sum()), "hl_k_looking": int(looking.sum()),
              "hl_dp": int(hl_ends["gs_dp"].sum()), **_rbi_bonuses(ends)}
    return _score(config.CLUTCH_SCORE_PARTS, values, config.CLUTCH_SCORE_ADJUSTMENTS, counts, *_game_info(h),
                  [f"{len(hl_ends)} high-leverage PA"])


def clutch_scores(df: pd.DataFrame, hitter_id: str) -> ScoreSummary:
    h = df[df["hitter_id"] == str(hitter_id)]
    games = [clutch_game_score(g) for g in _games(h)]
    games = [g for g in games if g]
    reason = ""
    if not games:
        reason = ("needs play-by-play" if not h["gs_known"].any() else "no high-leverage PA")
    return ScoreSummary("Clutch Score", games, reason)
