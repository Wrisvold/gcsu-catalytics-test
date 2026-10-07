"""Hitter-report metrics (P2). Every function takes an analysis frame from `common.prepare()`,
already filtered to one hitter (and date range / game types), and returns numbers with their n.
Hitters are identified by `hitter_id`: the batter on the last pitch of each PA (AUDIT.md section 4).
Definitions are mirrored in METRICS.md.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import config
from metrics.common import (
    CHASE_REGIONS, Stat, ZoneGrid, avg_stat, babip_stat, batting_counts, chase_pct, hard_hit_pct,
    max_stat, mean_stat, obp_stat, pitch_type_order, rate, ratio, slg_stat, whiff_pct, woba_stat,
    zone_grid,
)


def list_hitters(df: pd.DataFrame) -> pd.DataFrame:
    """One row per hitter: id, name, side(s), team, pitches seen, PA."""
    if df.empty:
        return pd.DataFrame(columns=["hitter_id", "hitter", "side", "BatterTeam", "pitches", "PA"])
    g = df.groupby("hitter_id").agg(
        hitter=("hitter", "last"),
        side=("hitter_side", lambda s: "/".join(sorted({v for v in s if v}))),
        BatterTeam=("BatterTeam", "last"), pitches=("PitchUID", "size"), PA=("pa_end", "sum"))
    return g.reset_index().sort_values("hitter").reset_index(drop=True)


def for_hitter(df: pd.DataFrame, hitter_id: str) -> pd.DataFrame:
    return df[df["hitter_id"] == str(hitter_id)]


def key_metrics(df: pd.DataFrame) -> dict:
    """PA, AVG, OBP, SLG, wOBA (MLB weights), Hard Hit %, Avg / Max Exit Velo, Avg Launch Angle.

    **Avg Exit Velo / Max Exit Velo**: mean / max ExitSpeed over balls in play with a trusted exit
    velo (ev_ok). Min n: MIN_N['bip'].
    **Avg Launch Angle**: mean Angle over balls in play with a trusted angle (la_ok). Min n: MIN_N['bip'].
    """
    c = batting_counts(df)
    return {
        "PA": c["PA"], "AB": c["AB"], "H": c["H"], "2B": c["2B"], "3B": c["3B"], "HR": c["HR"],
        "BB": c["BB"] + c["IBB"], "HBP": c["HBP"], "K": c["K"],
        "AVG": avg_stat(c), "OBP": obp_stat(c), "SLG": slg_stat(c), "wOBA": woba_stat(c),
        "Hard Hit %": hard_hit_pct(df),
        "Avg Exit Velo": mean_stat(df["ev"], "bip", "mph"),
        "Max Exit Velo": max_stat(df["ev"], "bip", "mph"),
        "Avg Launch Angle": mean_stat(df["la"], "bip", "deg"),
    }


def _breakdown_row(sub: pd.DataFrame, total: int) -> dict:
    return {
        "Pitches": Stat(len(sub), len(sub), config.MIN_N["pitches"], "count"),
        "Seen %": Stat(100.0 * len(sub) / total if total else None, total, 0, "pct"),
        "Swing %": rate(sub["is_swing"], pd.Series(True, index=sub.index), "pitches"),
        "Whiff %": whiff_pct(sub),
        "Chase %": chase_pct(sub),
        "Avg Exit Velo": mean_stat(sub["ev"], "bip", "mph"),
        "Avg Launch Angle": mean_stat(sub["la"], "bip", "deg"),
    }


def pitch_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """One row per pitch type faced, plus "All".

    **Seen %**: pitches of the type ÷ all pitches seen.
    **Swing %**: swings ÷ pitches of the type. Min n: MIN_N['pitches'].
    **Whiff %**, **Chase %**: see common definitions.
    **Avg Exit Velo / Avg Launch Angle** by pitch: over balls in play off that pitch type (ev_ok / la_ok).
    """
    total = len(df)
    rows, index = [], []
    for code in pitch_type_order(df["pitch_type"]):
        rows.append(_breakdown_row(df[df["pitch_type"] == code], total))
        index.append(code)
    if total:
        rows.append(_breakdown_row(df, total))
        index.append("All")
    out = pd.DataFrame(rows, index=index)
    out.index.name = "pitch_type"
    return out


def zone_avg(df: pd.DataFrame) -> ZoneGrid:
    """**Strike-zone batting average** (3x3, catcher's view): hits ÷ at-bats by the zone cell of the
    at-bat's final pitch. Min n per cell: MIN_N['zone_cell_ab']."""
    abs_ = df[df["pa_end"] & df["is_ab"]]
    return zone_grid(abs_, lambda cell: ratio(int(cell["is_hit"].sum()), len(cell), "zone_cell_ab"))


def zone_ev(df: pd.DataFrame) -> ZoneGrid:
    """**Strike-zone average exit velo** (3x3, catcher's view): mean ExitSpeed of balls in play
    (ev_ok) by the zone cell of the pitch. Min n per cell: MIN_N['zone_cell_bip']."""
    bip = df[df["ev_ok"]]
    return zone_grid(bip, lambda cell: mean_stat(cell["ev"], "zone_cell_bip", "mph"))


@dataclass
class SprayData:
    points: pd.DataFrame   # x, y (ft; x < 0 = left field), result, hit_type, on_arc
    n_bip: int
    n_missing: int         # balls in play left off: no Bearing or no Distance
    n_on_arc: int          # ground balls drawn on the fixed infield arc


def spray_points(df: pd.DataFrame) -> SprayData:
    """**Spray chart**: balls in play at Bearing (0° = center field, negative = left field) and
    Distance. Ground balls are drawn at their bearing on a fixed arc of SPRAY_GROUND_BALL_ARC_FT,
    because TrackMan's Distance for a ground ball is the first bounce (ASSUMPTIONS.md A4). Balls with
    no Bearing or no Distance are left off and counted."""
    bip = df[df["is_bip"]]
    have = bip["Bearing"].notna() & bip["Distance"].notna()
    pts = bip[have]
    on_arc = pts["TaggedHitType"] == "GroundBall"
    r = pts["Distance"].where(~on_arc, config.SPRAY_GROUND_BALL_ARC_FT)
    theta = np.radians(pts["Bearing"])
    result = pts["outcome"].where(pts["outcome"].isin(list(config.RESULT_COLORS)), "Other")
    points = pd.DataFrame({"x": r * np.sin(theta), "y": r * np.cos(theta), "result": result,
                           "hit_type": pts["TaggedHitType"], "on_arc": on_arc, "PitchUID": pts["PitchUID"]})
    return SprayData(points.reset_index(drop=True), len(bip), int((~have).sum()), int(on_arc.sum()))


@dataclass
class ContactData:
    points: pd.DataFrame   # x (ft, inside/pull side negative after mirroring), y (ft toward pitcher), ev, out_front
    out_front_ev: Stat
    deep_ev: Stat
    n: int


def contact_points(df: pd.DataFrame) -> ContactData:
    """**Contact point**: top-down view of ContactPositionX (toward the pitcher) and ContactPositionZ
    (side) for balls in play. Left-handed hitters are mirrored so the inside / pull side is on the left
    for everyone. **Out front** = ContactPositionX > CONTACT_OUT_FRONT_FT (in front of the plate's
    front edge, ASSUMPTIONS.md A7); otherwise **deep**. Avg exit velo for each group uses ev_ok balls.
    Min n: MIN_N['contact_group']."""
    bip = df[df["is_bip"] & df["ContactPositionX"].notna() & df["ContactPositionZ"].notna()]
    mirror = np.where(bip["hitter_side"] == "Left", -1.0, 1.0)
    x = bip["ContactPositionZ"] * config.CONTACT_Z_TO_CATCHER_X * mirror
    out_front = bip["ContactPositionX"] > config.CONTACT_OUT_FRONT_FT
    pts = pd.DataFrame({"x": x, "y": bip["ContactPositionX"], "ev": bip["ev"], "out_front": out_front,
                        "PitchUID": bip["PitchUID"]})
    return ContactData(pts.reset_index(drop=True),
                       mean_stat(bip.loc[out_front, "ev"], "contact_group", "mph"),
                       mean_stat(bip.loc[~out_front, "ev"], "contact_group", "mph"),
                       len(bip))


@dataclass
class ChaseMap:
    points: pd.DataFrame        # every chase: plot_x, plot_y (catcher's view), pitch_type, chase_region
    regions: dict[str, Stat]    # chase % in each region outside the zone


def chase_map(df: pd.DataFrame) -> ChaseMap:
    """**Chase map**: every swing at a pitch outside the zone, plus **chase % by region**: chases in
    the region ÷ pitches in the region. Regions are up, down, inside and away relative to the hitter; a
    pitch outside a corner belongs to the side it misses by more. Min n: MIN_N['chase_region']."""
    pts = df.loc[df["is_chase"], ["PitchUID", "plot_x", "plot_y", "pitch_type", "chase_region"]]
    regions = {r: rate(df["is_chase"], df["chase_region"] == r, "chase_region") for r in CHASE_REGIONS}
    return ChaseMap(pts.reset_index(drop=True), regions)


SWING_DECISIONS = ["Swing, in zone", "Take, in zone", "Chase", "Take, out of zone"]


def swing_decisions(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """**Swing decisions**: every pitch with a tracked location, labelled swing or take, in or out of
    the zone. Returns the points (catcher's view) and the count in each category."""
    t = df[df["loc_tracked"]]
    decision = np.select([t["is_swing"] & t["in_zone"], ~t["is_swing"] & t["in_zone"],
                          t["is_swing"] & t["out_zone"]], SWING_DECISIONS[:3], default=SWING_DECISIONS[3])
    pts = pd.DataFrame({"PitchUID": t["PitchUID"], "plot_x": t["plot_x"], "plot_y": t["plot_y"],
                        "pitch_type": t["pitch_type"], "decision": decision}).reset_index(drop=True)
    return pts, {d: int((pts["decision"] == d).sum()) for d in SWING_DECISIONS}


def pitcher_splits(df: pd.DataFrame) -> pd.DataFrame:
    """vs RHP and vs LHP (PitcherThrows): AVG, Max EV, Avg EV, HH %, Whiff %, Chase %, BABIP."""
    out = {}
    for name, hand in [("vs RHP", "Right"), ("vs LHP", "Left")]:
        sub = df[df["PitcherThrows"] == hand]
        c = batting_counts(sub)
        out[name] = {"PA": c["PA"], "AVG": avg_stat(c),
                     "Max EV": max_stat(sub["ev"], "bip", "mph"), "Avg EV": mean_stat(sub["ev"], "bip", "mph"),
                     "HH %": hard_hit_pct(sub), "Whiff %": whiff_pct(sub), "Chase %": chase_pct(sub),
                     "BABIP": babip_stat(c)}
    return pd.DataFrame(out).T
