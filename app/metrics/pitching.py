"""Pitcher-report metrics (P1). Every function takes an analysis frame from `common.prepare()`,
already filtered to one pitcher (and date range / game types), and returns numbers with their n.
Definitions are mirrored in METRICS.md.
"""
from __future__ import annotations

import pandas as pd

import config
from metrics.common import (
    Stat, ZoneGrid, avg_stat, babip_stat, batting_counts, bb_pct, chase_pct, fb_pct, format_ip, gb_pct,
    hard_hit_pct, k_pct, max_stat, mean_stat, pitch_type_order, rate, ratio, whiff_pct, zone_grid,
)


def list_pitchers(df: pd.DataFrame) -> pd.DataFrame:
    """One row per pitcher: id, name, throws, pitch count, PA faced."""
    if df.empty:
        return pd.DataFrame(columns=["PitcherId", "Pitcher", "PitcherThrows", "pitches", "PA"])
    g = df.groupby("PitcherId").agg(Pitcher=("Pitcher", "last"), PitcherThrows=("PitcherThrows", "last"),
                                    pitches=("PitchUID", "size"), PA=("pa_end", "sum"))
    return g.reset_index().sort_values("Pitcher").reset_index(drop=True)


def for_pitcher(df: pd.DataFrame, pitcher_id: str) -> pd.DataFrame:
    return df[df["PitcherId"] == str(pitcher_id)]


def outs_recorded(df: pd.DataFrame) -> int:
    """**Outs recorded**: strikeouts + the sum of OutsOnPlay over every pitch thrown (including
    baserunning outs on pitches that did not end a PA). OutsOnPlay does not include strikeouts in
    TrackMan data (AUDIT.md section 5)."""
    return int(df.loc[df["pa_end"], "is_k"].sum() + df["OutsOnPlay"].fillna(0).sum())


def performance_line(df: pd.DataFrame) -> dict:
    """IP, PA, H, R, ER, BB, K, HR, HBP, Strike %, First-Pitch Strike %.

    **IP**: outs recorded ÷ 3, shown in baseball notation (3.1 = 3⅓).
    **R**: sum of RunsScored on this pitcher's pitches (runs scored while he was pitching; TrackMan
    does not track inherited runners).
    **ER**: not available in TrackMan; shown as "—".
    **Strike %**: strikes (rule 12) ÷ pitches. Min n: MIN_N['pitches'].
    **First-Pitch Strike %**: strikes on the first pitch of a PA ÷ PAs this pitcher threw the first
    pitch of. Min n: MIN_N['first_pitches'].
    """
    c = batting_counts(df)
    outs = outs_recorded(df)
    return {
        "IP": format_ip(outs), "outs": outs, "PA": c["PA"], "H": c["H"],
        "R": int(df["RunsScored"].fillna(0).sum()), "ER": "—",
        "BB": c["BB"] + c["IBB"], "K": c["K"], "HR": c["HR"], "HBP": c["HBP"],
        "Strike %": rate(df["is_strike"], pd.Series(True, index=df.index), "pitches"),
        "First-Pitch Strike %": rate(df["is_strike"], df["is_first_pitch"], "first_pitches"),
        "pitches": len(df),
    }


def _type_row(sub: pd.DataFrame, total: int, ended: pd.DataFrame) -> dict:
    return {
        "Count": Stat(len(sub), len(sub), config.MIN_N["pitches"], "count"),
        "Usage %": Stat(100.0 * len(sub) / total if total else None, total, 0, "pct"),
        "Avg Velo": mean_stat(sub["RelSpeed"], None, "mph"),
        "Max Velo": max_stat(sub["RelSpeed"], None, "mph"),
        "Avg Spin": mean_stat(sub["SpinRate"], None, "rpm"),
        "Max Spin": max_stat(sub["SpinRate"], None, "rpm"),
        "IVB": mean_stat(sub["InducedVertBreak"], None, "in"),
        "HB": mean_stat(sub["HorzBreak"], None, "in"),
        "Extension": mean_stat(sub["Extension"], None, "ft"),
        "Rel Height": mean_stat(sub["RelHeight"], None, "ft"),
        "Strike %": rate(sub["is_strike"], pd.Series(True, index=sub.index), "pitches"),
        "Whiff %": whiff_pct(sub),
        "Chase %": chase_pct(sub),
        "Out %": rate(ended["is_pa_out"], ended["pa_end"], "pa_ended"),
    }


def pitch_type_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per pitch type (final type after corrections), plus an "All" row.

    **Count / Usage %**: pitches of the type ÷ all pitches. Rows with fewer than MIN_N['pitches']
    pitches get an asterisk on the count ("* fewer than 10 pitches").
    **Avg / Max Velo** (RelSpeed), **Avg / Max Spin** (SpinRate), **IVB** (InducedVertBreak),
    **HB** (HorzBreak), **Extension**, **Rel Height** (RelHeight): averages (and maxima) over the
    pitches of that type with a value.
    **Strike %**, **Whiff %**, **Chase %**: see common definitions.
    **Out %**: PAs that ended on this pitch type with an out (strikeout, or OutsOnPlay > 0) ÷ all PAs
    that ended on this pitch type. Min n: MIN_N['pa_ended']. (ASSUMPTIONS.md A9)
    In the "All" row the movement columns are left blank; averaging them across pitch types means
    nothing.
    """
    total = len(df)
    rows, index = [], []
    for code in pitch_type_order(df["pitch_type"]):
        sub = df[df["pitch_type"] == code]
        rows.append(_type_row(sub, total, sub[sub["pa_end"]]))
        index.append(code)
    if total:
        all_row = _type_row(df, total, df[df["pa_end"]])
        for k in ["Avg Velo", "Max Velo", "Avg Spin", "Max Spin", "IVB", "HB", "Extension", "Rel Height"]:
            all_row[k] = Stat(None, 0, 0, all_row[k].kind)
        rows.append(all_row)
        index.append("All")
    out = pd.DataFrame(rows, index=index)
    out.index.name = "pitch_type"
    return out


def usage_by_side(df: pd.DataFrame) -> pd.DataFrame:
    """**Usage %** overall and split by hitter side: pitches of the type ÷ all pitches in that split.
    n = pitches in the split. Hitter side comes from the PA's final batter (AUDIT.md section 4)."""
    splits = {"All": df, "vs LHH": df[df["hitter_side"] == "Left"], "vs RHH": df[df["hitter_side"] == "Right"]}
    out = {}
    for name, sub in splits.items():
        total = len(sub)
        out[name] = {code: Stat(100.0 * (sub["pitch_type"] == code).sum() / total if total else None,
                                total, config.MIN_N["pitches"], "pct")
                     for code in pitch_type_order(df["pitch_type"])}
    return pd.DataFrame(out)


def movement_points(df: pd.DataFrame) -> pd.DataFrame:
    """Pitch-break chart data: HorzBreak, InducedVertBreak and final pitch type for each pitch."""
    return df.loc[df["HorzBreak"].notna() & df["InducedVertBreak"].notna(),
                  ["PitchUID", "pitch_type", "auto_type", "HorzBreak", "InducedVertBreak", "RelSpeed", "SpinRate"]]


def zone_baa(df: pd.DataFrame) -> ZoneGrid:
    """**Strike-zone BAA** (3x3, catcher's view): hits ÷ at-bats, grouped by the zone cell of the
    pitch that ended the at-bat. At-bats ending outside the zone are counted in the footnote, not the
    grid. Min n per cell: MIN_N['zone_cell_ab']."""
    abs_ = df[df["pa_end"] & df["is_ab"]]
    return zone_grid(abs_, lambda cell: ratio(int(cell["is_hit"].sum()), len(cell), "zone_cell_ab"))


def whiff_locations(df: pd.DataFrame) -> pd.DataFrame:
    """Every whiff with a tracked location, in catcher's-view coordinates, with its pitch type."""
    return df.loc[df["is_whiff"] & df["loc_tracked"], ["PitchUID", "plot_x", "plot_y", "pitch_type"]]


def hitter_splits(df: pd.DataFrame) -> pd.DataFrame:
    """vs RHH and vs LHH: BAA, K %, BB %, GB %, FB %, HH %, BABIP (definitions in common)."""
    out = {}
    for name, side in [("vs RHH", "Right"), ("vs LHH", "Left")]:
        sub = df[df["hitter_side"] == side]
        c = batting_counts(sub)
        out[name] = {"PA": c["PA"], "BAA": avg_stat(c), "K %": k_pct(c), "BB %": bb_pct(c),
                     "GB %": gb_pct(sub), "FB %": fb_pct(sub), "HH %": hard_hit_pct(sub),
                     "BABIP": babip_stat(c)}
    return pd.DataFrame(out).T
