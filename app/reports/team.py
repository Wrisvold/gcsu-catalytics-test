"""Assemble the Team Pitcher and Team Hitter reports. Used by the app pages and the PDF export.

A team report is the individual report run on every pitch one team threw (or saw), so its sections,
tables and charts are the same ones, drawn by the same code. Two things differ:

- **Scores** are the average of every player's game scores, weighted by plate appearances (batters
  faced for a pitcher), because the scoring sheet scores one player in one game (coach answer R1).
- A **by-player table** lists each player's main numbers and scores, best score first.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

import config
from metrics import hitting, pitching, scores
from metrics.common import Stat
from reports import hitter as hitter_report
from reports import pitcher as pitcher_report
from reports.context import display_name


@dataclass
class TeamScore(scores.ScoreSummary):
    """Every player-game score in the report, averaged with each weighted by its plate appearances."""
    weights: list[int] = field(default_factory=list)   # PA (batters faced) in each of `games`

    @property
    def average(self) -> float | None:
        total = sum(self.weights)
        if not self.games or not total:
            return super().average
        return sum(g.total * w for g, w in zip(self.games, self.weights)) / total

    @property
    def detail(self) -> str:
        n = len(self.games)
        if not n:
            return self.unavailable or "no games"
        return f"PA-weighted avg of {n} player-game{'s' if n != 1 else ''}"


def team_label(code: str) -> str:
    return "GCSU" if code == config.TEAM_CODE else code


def teams(df: pd.DataFrame, kind: str) -> list[str]:
    """Team codes in the frame, GCSU first."""
    col = "PitcherTeam" if kind == "pitcher" else "BatterTeam"
    found = sorted({t for t in df[col].dropna() if t})
    return sorted(found, key=lambda t: t != config.TEAM_CODE)


def _team_score(name: str, summaries: dict[str, scores.ScoreSummary], df: pd.DataFrame, id_col: str) -> TeamScore:
    """`summaries` maps player id -> his score; each of his games is weighted by his PA in it."""
    ends = df[df["pa_end"]]
    pa = ends.groupby([ends[id_col].astype(str), ends["GameID"].astype(str)]).size()
    games, weights = [], []
    for pid, s in summaries.items():
        for g in s.games:
            games.append(g)
            weights.append(int(pa.get((pid, str(g.game_id)), 0)))
    reason = next((s.unavailable for s in summaries.values() if s.unavailable), "")
    return TeamScore(name, games, "" if games else reason, weights)


@dataclass
class TeamPitcherReport:
    team: str
    report: pitcher_report.PitcherReport   # the individual layout, run on the whole staff
    roster: pd.DataFrame                   # one row per pitcher, best Pitcher Score first
    n_players: int


@dataclass
class TeamHitterReport:
    team: str
    report: hitter_report.HitterReport
    roster: pd.DataFrame
    n_players: int


def _sort(rows: list[dict], score_col: str) -> pd.DataFrame:
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    key = out[score_col].map(lambda s: -s.average if s.average is not None else float("inf"))
    return out.assign(_k=key).sort_values(["_k", "Player"]).drop(columns="_k").reset_index(drop=True)


def build_pitchers(df: pd.DataFrame, team: str = config.TEAM_CODE) -> TeamPitcherReport | None:
    """`df` is the filtered analysis frame for all players."""
    t = df[df["PitcherTeam"] == team]
    if t.empty:
        return None
    ids = [str(i) for i in pitching.list_pitchers(t)["PitcherId"]]
    rows, summaries = [], {}
    for pid in ids:
        p = pitching.for_pitcher(t, pid)
        score = summaries[pid] = scores.pitcher_scores(df, pid)
        L = pitching.performance_line(p)
        throws = p["PitcherThrows"].iloc[-1]
        rows.append({"Player": display_name(p["Pitcher"].iloc[-1]),
                     "T": {"Right": "R", "Left": "L"}.get(throws, ""), "G": int(p["GameID"].nunique()),
                     "IP": L["IP"], "PA": L["PA"], "H": L["H"], "R": L["R"], "ER": L["ER"], "BB": L["BB"],
                     "K": L["K"], "HR": L["HR"], "Pitches": L["pitches"], "Strike %": L["Strike %"],
                     "1st-Pitch Strike %": L["First-Pitch Strike %"], "Pitcher Score": score})
    staff = pitcher_report.assemble(t, team, f"{team_label(team)} Pitching Staff",
                                    f"{len(ids)} pitcher{'s' if len(ids) != 1 else ''}",
                                    _team_score("Pitcher Score", summaries, df, "PitcherId"))
    return TeamPitcherReport(team, staff, _sort(rows, "Pitcher Score"), len(ids))


def build_hitters(df: pd.DataFrame, team: str = config.TEAM_CODE) -> TeamHitterReport | None:
    t = df[df["BatterTeam"] == team]
    if t.empty:
        return None
    ids = [str(i) for i in hitting.list_hitters(t)["hitter_id"]]
    rows, hit_scores, clutch_scores = [], {}, {}
    for hid in ids:
        h = hitting.for_hitter(t, hid)
        score = hit_scores[hid] = scores.hitter_scores(df, hid)
        clutch = clutch_scores[hid] = scores.clutch_scores(df, hid)
        k = hitting.key_metrics(h)
        sides = {s for s in h["hitter_side"] if s in ("Right", "Left")}
        rows.append({"Player": display_name(h["hitter"].iloc[-1]),
                     "B": "S" if len(sides) == 2 else {"Right": "R", "Left": "L"}.get(next(iter(sides), ""), ""),
                     "G": int(h["GameID"].nunique()), "PA": k["PA"], "AB": k["AB"], "H": k["H"], "HR": k["HR"],
                     "BB": k["BB"], "K": k["K"], "RBI": "—" if k["RBI"] is None else k["RBI"],
                     "AVG": k["AVG"], "OBP": k["OBP"], "SLG": k["SLG"], "OPS": k["OPS"], "QAB %": k["QAB %"],
                     "Hard Hit %": k["Hard Hit %"], "Hitter Score": score, "Clutch Score": clutch})
    lineup = hitter_report.assemble(t, team, f"{team_label(team)} Hitters",
                                    _team_score("Hitter Score", hit_scores, df, "hitter_id"),
                                    _team_score("Clutch Score", clutch_scores, df, "hitter_id"))
    return TeamHitterReport(team, lineup, _sort(rows, "Hitter Score"), len(ids))


def roster_text(roster: pd.DataFrame) -> pd.DataFrame:
    """The by-player table as display strings (Stats and scores as their printed text)."""
    def cell(v):
        if isinstance(v, scores.ScoreSummary):
            return v.text
        if isinstance(v, Stat):
            return v.text()
        return str(v)
    return roster.apply(lambda col: col.map(cell))


def roster_low(roster: pd.DataFrame) -> pd.DataFrame:
    """True where a by-player cell is a Stat below its minimum sample (shown grey)."""
    return roster.apply(lambda col: col.map(lambda v: isinstance(v, Stat) and v.low))
