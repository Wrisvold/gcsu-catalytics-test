"""Line official plate appearances up with TrackMan's, and official pitching lines with TrackMan pitchers.

Plate appearances are matched within each half-inning. When both sources have the same number, they
pair in order (the batting order makes this reliable even when TrackMan spells a name differently).
Otherwise they are aligned by order and batter name, and whatever doesn't pair is listed. Pitching
lines pair with the TrackMan pitcher of the same team whose name is closest.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pbp.boxscore import BoxScore, PitcherLine
from pbp.plays import PlateAppearance, name_similarity, replay

MIN_NAME_SIMILARITY = 0.5   # to pair two plate appearances when the counts differ
MIN_PITCHER_SIMILARITY = 0.75

_HIT = {"1B", "2B", "3B", "HR"}


def _kind(code: str | None) -> str:
    """Coarse outcome used to spot disagreements between TrackMan and the official scoring."""
    if code in _HIT:
        return "hit"
    if code in ("BB", "IBB"):
        return "walk"
    if code in ("HBP", "K", "CI"):
        return code
    return "other"


_PLAIN = {"1B": "single", "2B": "double", "3B": "triple", "HR": "home run", "BB": "walk", "IBB": "walk",
          "HBP": "hit by pitch", "K": "strikeout", "ROE": "reached on error", "FC": "fielder's choice",
          "SF": "sacrifice fly", "SH": "sacrifice bunt", "Out": "out", "CI": "catcher's interference",
          "InPlayUnknown": "ball in play"}


@dataclass
class GameMatch:
    game_id: str
    pa_state: pd.DataFrame                     # one row per matched TrackMan pa_id
    pitcher_lines: dict[str, PitcherLine]      # TrackMan PitcherId -> official line
    tm_pas: int = 0
    official_pas: int = 0
    matched: int = 0
    unmatched_tm: list[str] = field(default_factory=list)
    unmatched_official: list[str] = field(default_factory=list)
    disagreements: list[str] = field(default_factory=list)
    unmatched_pitchers: list[str] = field(default_factory=list)
    replay_warnings: list[str] = field(default_factory=list)
    pairs: dict[int, int] = field(default_factory=dict)   # official PA (index in replay().pas) -> TrackMan pa_id

    @property
    def ok(self) -> bool:
        return self.matched == self.tm_pas == self.official_pas and not self.replay_warnings


def _align(tm: list[str], off: list[str]) -> list[tuple[int, int]]:
    if len(tm) == len(off):
        return list(zip(range(len(tm)), range(len(off))))
    n, m = len(tm), len(off)
    sim = [[name_similarity(a, b) for b in off] for a in tm]
    best = np.zeros((n + 1, m + 1))
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            pair = best[i - 1, j - 1] + sim[i - 1][j - 1] if sim[i - 1][j - 1] >= MIN_NAME_SIMILARITY else -1
            best[i, j] = max(best[i - 1, j], best[i, j - 1], pair)
    pairs, i, j = [], n, m
    while i and j:
        s = sim[i - 1][j - 1]
        if s >= MIN_NAME_SIMILARITY and best[i, j] == best[i - 1, j - 1] + s:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif best[i, j] == best[i - 1, j]:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def _state_row(pa_id: int, p: PlateAppearance) -> dict:
    return {"pa_id": pa_id, "gs_on1": p.on1 is not None, "gs_on2": p.on2 is not None, "gs_on3": p.on3 is not None,
            "gs_runners": p.runners_on, "gs_outs": p.outs_before, "gs_bat_score": p.bat_before,
            "gs_fld_score": p.fld_before, "gs_bat_after": p.bat_after, "gs_fld_after": p.fld_after,
            "gs_rbi": p.rbi, "gs_dp": p.dp, "gs_advanced": p.advanced, "gs_code": p.code,
            "gs_outs_on_play": p.outs_on_play}


def match_game(game: pd.DataFrame, box: BoxScore) -> GameMatch:
    """`game` is one game's analysis frame (after PA grouping and outcomes)."""
    from pbp.sheet import is_coach

    gid = str(game["GameID"].iloc[0])
    rep = replay(box)
    kind = "coach sheet" if is_coach(box.source) else "official"
    ends = game[game["pa_end"]]
    official: dict[tuple[int, str], list[PlateAppearance]] = {}
    index = {id(p): n for n, p in enumerate(rep.pas)}
    for p in rep.pas:
        official.setdefault((p.inning, p.half), []).append(p)

    rows, out = [], GameMatch(gid, pd.DataFrame(), {}, len(ends), len(rep.pas), replay_warnings=rep.warnings)
    halves = sorted(set(official) | {(int(i), str(t)) for i, t in zip(ends["Inning"], ends["Top/Bottom"])},
                    key=lambda k: (k[0], k[1] != "Top"))
    for inning, half in halves:
        tm = ends[(ends["Inning"] == inning) & (ends["Top/Bottom"] == half)]
        off = official.get((inning, half), [])
        tm_names = tm["hitter"].tolist()
        pairs = _align(tm_names, [p.batter for p in off])
        where = f"{half} {inning}"
        for i, j in pairs:
            t, p = tm.iloc[i], off[j]
            rows.append(_state_row(int(t["pa_id"]), p))
            out.pairs[index[id(p)]] = int(t["pa_id"])
            if name_similarity(t["hitter"], p.batter) < MIN_NAME_SIMILARITY:
                out.disagreements.append(f"{where}: TrackMan batter {t['hitter']} paired by order with "
                                         f"{p.batter}")
            if _kind(t["outcome"]) != _kind(p.code):
                out.disagreements.append(f"{where}: {p.batter} — TrackMan {_PLAIN.get(t['outcome'], t['outcome'])}, "
                                         f"{kind} {_PLAIN.get(p.code, p.code)} (\"{p.text}\")")
        paired_tm = {i for i, _ in pairs}
        paired_off = {j for _, j in pairs}
        out.unmatched_tm += [f"{where}: {n}" for i, n in enumerate(tm_names) if i not in paired_tm]
        out.unmatched_official += [f"{where}: {p.batter}" for j, p in enumerate(off) if j not in paired_off]
    out.matched = len(rows)
    out.pa_state = pd.DataFrame(rows)

    # Pitchers: those who threw in the top half pitch for the home team.
    side = game.groupby("PitcherId").agg(name=("Pitcher", "last"),
                                         top=("Top/Bottom", lambda s: (s == "Top").mean() >= 0.5))
    lines = {True: [p for p in box.pitching if p.team == box.home],
             False: [p for p in box.pitching if p.team == box.away]}
    for is_home in (True, False):
        candidates = [(name_similarity(r["name"], line.name), pid, k)
                      for pid, r in side[side["top"] == is_home].iterrows()
                      for k, line in enumerate(lines[is_home])]
        used_pid, used_line = set(), set()
        for s, pid, k in sorted(candidates, reverse=True):
            if s >= MIN_PITCHER_SIMILARITY and pid not in used_pid and k not in used_line:
                out.pitcher_lines[str(pid)] = lines[is_home][k]
                used_pid.add(pid)
                used_line.add(k)
        out.unmatched_pitchers += [line.name for k, line in enumerate(lines[is_home]) if k not in used_line]
    return out
