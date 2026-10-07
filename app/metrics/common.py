"""Shared definitions and the query-time preparation step.

`prepare()` turns raw stored rows (all text) into an analysis frame: typed numbers, final pitch type
after coach corrections, plate-appearance grouping, zone flags and outcome flags. The raw rows are
never modified; everything here is derived on read (rule 1). Each definition below is mirrored in
METRICS.md.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

import config

NUMERIC_COLUMNS = [
    "PitchNo", "PAofInning", "PitchofPA", "Inning", "Outs", "Balls", "Strikes", "OutsOnPlay",
    "RunsScored", "RelSpeed", "SpinRate", "InducedVertBreak", "HorzBreak", "RelHeight", "RelSide",
    "Extension", "PlateLocHeight", "PlateLocSide", "ExitSpeed", "Angle", "Direction", "Distance",
    "Bearing", "ContactPositionX", "ContactPositionY", "ContactPositionZ",
]

BATTED_BALL_TYPES = ["GroundBall", "LineDrive", "FlyBall", "Popup"]
CHASE_REGIONS = ["up", "down", "inside", "away"]


# --- Stat: a value that always carries its n (rule 3) ------------------------------------------

@dataclass(frozen=True)
class Stat:
    """A displayed number with the sample size behind it.

    `n` is the denominator (rates) or the count of values averaged. `low` is True when n is below the
    configured minimum, and the UI greys the value out instead of hiding it (Section 4b).
    """
    value: float | None
    n: int
    min_n: int = 0
    kind: str = "pct"  # pct | avg | mph | deg | in | ft | rpm | count

    @property
    def low(self) -> bool:
        return self.n < self.min_n

    def text(self) -> str:
        v = self.value
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "—"
        if self.kind == "pct":
            return f"{v:.1f}%"
        if self.kind == "avg":
            s = f"{v:.3f}"
            return s[1:] if s.startswith("0.") else s
        if self.kind == "rpm":
            return f"{v:,.0f}"
        if self.kind == "count":
            return f"{v:.0f}"
        if self.kind == "deg":
            return f"{v:.1f}°"
        return f"{v:.1f}"

    def __str__(self) -> str:
        return f"{self.text()} (n={self.n})"


def _min(key: str | None) -> int:
    return config.MIN_N[key] if key else 0


def rate(num_mask: pd.Series, den_mask: pd.Series, min_key: str | None) -> Stat:
    """Percentage of `den_mask` rows that also satisfy `num_mask`."""
    den = int(den_mask.sum())
    num = int((num_mask & den_mask).sum())
    return Stat(100.0 * num / den if den else None, den, _min(min_key), "pct")


def ratio(num: float, den: float, min_key: str | None, kind: str = "avg") -> Stat:
    return Stat(num / den if den else None, int(den), _min(min_key), kind)


def mean_stat(values: pd.Series, min_key: str | None, kind: str) -> Stat:
    v = values.dropna()
    return Stat(float(v.mean()) if len(v) else None, len(v), _min(min_key), kind)


def max_stat(values: pd.Series, min_key: str | None, kind: str) -> Stat:
    v = values.dropna()
    return Stat(float(v.max()) if len(v) else None, len(v), _min(min_key), kind)


_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")


def parse_game_date(local_datetime: str, date: str) -> str | None:
    """ISO date for a pitch. Prefers LocalDateTime; accepts Date as YYYY-MM-DD or M/D/YYYY.

    Files re-saved in Excel turn Date into M/D/YYYY and lose the hour in Time (AUDIT.md section 6),
    which is why Time is never used.
    """
    for text in (local_datetime or "", date or ""):
        if m := _ISO_DATE.match(text):
            y, mo, d = m.groups()
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        if m := _US_DATE.match(text):
            mo, d, y = m.groups()
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None


def format_ip(outs: int) -> str:
    """Innings pitched in baseball notation: 7 outs -> "2.1"."""
    return f"{outs // 3}.{outs % 3}"


# --- Pitch types --------------------------------------------------------------------------------

def _norm(text) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


_AUTO_MAP = {_norm(k): v for k, v in config.AUTO_PITCH_TYPE_MAP.items()}


def auto_code(text) -> str:
    """AutoPitchType text -> pitch code (FF, SI, ...). Unknown or blank -> OT."""
    if text is None or (isinstance(text, float) and math.isnan(text)) or text is pd.NA:
        return "OT"
    return _AUTO_MAP.get(_norm(text), "OT")


def apply_pitch_types(df: pd.DataFrame, rules: list[dict] | None, overrides: dict[str, str] | None) -> None:
    """Set `auto_type` (from AutoPitchType) and `pitch_type` (after coach corrections).

    Order: plain rules (no velocity range) first, then velocity-ranged rules, each group in the order
    created; a later match overwrites an earlier one. Per-pitch overrides always win. A rule matches
    on PitcherId and auto type; a velocity bound is inclusive and a pitch with no RelSpeed never
    matches a ranged rule.
    """
    df["auto_type"] = df["AutoPitchType"].map(auto_code)
    df["pitch_type"] = df["auto_type"]
    rules = sorted(rules or [], key=lambda r: (r.get("min_velo") is not None or r.get("max_velo") is not None,
                                               r.get("id") or 0))
    pid = df["PitcherId"].astype(str)
    for r in rules:
        m = (pid == str(r["pitcher_id"])) & (df["auto_type"] == r["auto_type"])
        if r.get("min_velo") is not None:
            m &= df["RelSpeed"] >= float(r["min_velo"])
        if r.get("max_velo") is not None:
            m &= df["RelSpeed"] <= float(r["max_velo"])
        df.loc[m.fillna(False), "pitch_type"] = r["corrected_type"]
    if overrides:
        ov = df["PitchUID"].map(overrides)
        df.loc[ov.notna(), "pitch_type"] = ov[ov.notna()]
    df["pitch_type_corrected"] = df["pitch_type"] != df["auto_type"]


# --- Plate appearances (rules 14, 15, 16) -------------------------------------------------------

def is_pa_end(df: pd.DataFrame) -> pd.Series:
    """**Plate appearance end** (rule 14): KorBB is Strikeout or Walk, or PitchCall is InPlay,
    HitByPitch, or CatchersInterference."""
    return (df["KorBB"].isin(["Strikeout", "Walk"])
            | df["PitchCall"].isin(["InPlay", "HitByPitch", "CatchersInterference"])).fillna(False)


def add_pa_columns(df: pd.DataFrame) -> None:
    """Group pitches into plate appearances and credit each PA to the batter on its last pitch.

    A new PA starts when (GameID, Inning, Top/Bottom, PAofInning) changes or after a PA-ending pitch.
    `hitter`, `hitter_id` and `hitter_side` come from the PA's last pitch, which repairs the three
    pitches in the sample file where the operator left the pitcher's name in the Batter field
    (AUDIT.md section 4). The raw Batter columns are untouched.
    """
    df["pa_end"] = is_pa_end(df)
    key = df[["GameID", "Inning", "Top/Bottom", "PAofInning"]].astype(str)
    changed = (key != key.shift()).any(axis=1)
    after_end = df["pa_end"].shift(fill_value=False).astype(bool)
    df["pa_id"] = (changed | after_end).cumsum()
    grp = df.groupby("pa_id", sort=False)
    df["is_first_pitch"] = grp.cumcount() == 0
    for src, dst in [("Batter", "hitter"), ("BatterId", "hitter_id"), ("BatterSide", "hitter_side")]:
        df[dst] = grp[src].transform("last")
    df["hitter_id"] = df["hitter_id"].astype(str)
    df["batter_reassigned"] = (df["Batter"] != df["hitter"]).fillna(False)


_PLAY_RESULT = {"single": "1B", "double": "2B", "triple": "3B", "homerun": "HR", "error": "ROE",
                "fielderschoice": "FC", "out": "Out", "sacrifice": "SAC"}


def pa_outcomes(df: pd.DataFrame) -> pd.Series:
    """Outcome code for each PA-ending pitch (None elsewhere): K, BB, IBB, HBP, CI, 1B, 2B, 3B, HR,
    ROE, FC, SF, SH, Out, or InPlayUnknown (an in-play pitch with no recognised PlayResult; counted as
    an at-bat, not a hit). `Sacrifice` is a bunt (SH) when TaggedHitType is Bunt, otherwise a fly (SF)."""
    korbb, call = df["KorBB"], df["PitchCall"]
    in_play = df["PlayResult"].map(_norm).map(_PLAY_RESULT).fillna("InPlayUnknown")
    in_play = in_play.where(in_play != "SAC", np.where(df["TaggedHitType"] == "Bunt", "SH", "SF"))
    codes = np.select(
        [~df["pa_end"], korbb == "Strikeout", (korbb == "Walk") & (call == "BallIntentional"),
         korbb == "Walk", call == "HitByPitch", call == "CatchersInterference"],
        [None, "K", "IBB", "BB", "HBP", "CI"],
        default=in_play.to_numpy(dtype=object))
    return pd.Series(codes, index=df.index, dtype=object)


HIT_CODES = {"1B": 1, "2B": 2, "3B": 3, "HR": 4}
NON_AB_CODES = {"BB", "IBB", "HBP", "CI", "SF", "SH"}


def add_pa_outcomes(df: pd.DataFrame) -> None:
    """Outcome flags on PA-ending pitches (all False elsewhere).

    **At-bat** (rule 15): a PA end that is not BB, IBB, HBP, sacrifice (SF/SH) or catcher's
    interference. Reached on error counts as an at-bat but not a hit.
    **Hit** (rule 16): PlayResult Single, Double, Triple or HomeRun.
    **Out on the PA** (for Out %): strikeout, or OutsOnPlay > 0 on the PA-ending pitch.
    """
    df["outcome"] = pa_outcomes(df)
    o = df["outcome"]
    df["is_ab"] = o.notna() & ~o.isin(NON_AB_CODES)
    df["is_hit"] = o.isin(HIT_CODES)
    df["total_bases"] = o.map(HIT_CODES).fillna(0).astype(int)
    for code in ["K", "BB", "IBB", "HBP", "SF", "SH", "HR", "1B", "2B", "3B", "ROE", "CI"]:
        df[f"is_{code.lower()}"] = o == code
    df["is_pa_out"] = df["pa_end"] & ((o == "K") | (df["OutsOnPlay"].fillna(0) > 0))


# --- Location (rules 10, 13) --------------------------------------------------------------------

def add_location_columns(df: pd.DataFrame) -> None:
    """**Strike zone** (rule 10): |PlateLocSide| <= ZONE_HALF_WIDTH_FT and ZONE_BOTTOM_FT <=
    PlateLocHeight <= ZONE_TOP_FT. Pitches with no location are neither in nor out of the zone.

    `plot_x` / `plot_y` are catcher's-view chart coordinates (first-base side on the right).
    `zone_cell` numbers the 3x3 grid 1-9 left to right, top to bottom, in that view.
    `chase_region` (out-of-zone pitches only) is up, down, inside or away relative to the hitter: the
    side on which the pitch is furthest outside the zone.
    """
    side, height = df["PlateLocSide"], df["PlateLocHeight"]
    hw, lo, hi, g = config.ZONE_HALF_WIDTH_FT, config.ZONE_BOTTOM_FT, config.ZONE_TOP_FT, config.ZONE_GRID
    df["loc_tracked"] = side.notna() & height.notna()
    df["in_zone"] = df["loc_tracked"] & (side.abs() <= hw) & height.between(lo, hi)
    df["out_zone"] = df["loc_tracked"] & ~df["in_zone"]
    df["plot_x"] = side * config.PLATE_SIDE_TO_CATCHER_X
    df["plot_y"] = height

    col = np.floor((df["plot_x"] + hw) / (2 * hw / g)).clip(0, g - 1)
    row = np.floor((hi - height) / ((hi - lo) / g)).clip(0, g - 1)
    df["zone_cell"] = (row * g + col + 1).where(df["in_zone"]).astype("Int64")

    # Hitter-relative horizontal coordinate: positive = toward the hitter (inside).
    # A RHH stands on the catcher's left (negative plot_x); a LHH on the catcher's right.
    toward = np.where(df["hitter_side"] == "Right", -1.0, np.where(df["hitter_side"] == "Left", 1.0, np.nan))
    inside_coord = df["plot_x"] * toward
    excess = np.column_stack([height - hi, lo - height, inside_coord - hw, -inside_coord - hw])  # CHASE_REGIONS order
    excess = np.where(np.isnan(excess), -np.inf, excess)
    region = pd.Series(np.array(CHASE_REGIONS, dtype=object)[excess.argmax(axis=1)], index=df.index)
    region = region.where(df["out_zone"], None)
    # Unknown batter side: only up/down can be decided.
    no_side = df["out_zone"] & np.isnan(toward)
    region[no_side] = np.where(height[no_side] > hi, "up", np.where(height[no_side] < lo, "down", None))
    df["chase_region"] = region


# --- Pitch outcomes (rules 11, 12, 13) ----------------------------------------------------------

def add_pitch_outcomes(df: pd.DataFrame) -> None:
    """**Swing** (rule 11): StrikeSwinging, any Foul* value, or InPlay.
    **Whiff**: PitchCall == StrikeSwinging.
    **Strike** (rule 12): StrikeCalled, StrikeSwinging, any Foul* value, or InPlay.
    **Chase** (rule 13): a swing at a pitch outside the zone.
    """
    call = df["PitchCall"].fillna("")
    foul = call.str.startswith("Foul")
    df["is_whiff"] = call == "StrikeSwinging"
    df["is_swing"] = df["is_whiff"] | foul | (call == "InPlay")
    df["is_strike"] = (call == "StrikeCalled") | df["is_swing"]
    df["is_chase"] = df["is_swing"] & df["out_zone"]
    df["is_take"] = df["loc_tracked"] & ~df["is_swing"]


# --- Batted balls (rules 17, 18) ----------------------------------------------------------------

def add_batted_ball_columns(df: pd.DataFrame) -> None:
    """**Ball in play**: PitchCall == InPlay. Batted-ball metrics use balls in play only.
    `ev_ok` / `la_ok`: a ball in play with ExitSpeed / Angle recorded and HitLaunchConfidence not in
    EXCLUDED_LAUNCH_CONFIDENCE.
    **Hard hit** (rule 18): ev_ok and ExitSpeed >= HARD_HIT_MPH.
    """
    df["is_bip"] = df["PitchCall"] == "InPlay"
    trusted = ~df["HitLaunchConfidence"].isin(config.EXCLUDED_LAUNCH_CONFIDENCE)
    df["ev_ok"] = df["is_bip"] & df["ExitSpeed"].notna() & trusted
    df["la_ok"] = df["is_bip"] & df["Angle"].notna() & trusted
    df["is_hard_hit"] = df["ev_ok"] & (df["ExitSpeed"] >= config.HARD_HIT_MPH)
    df["ev"] = df["ExitSpeed"].where(df["ev_ok"])
    df["la"] = df["Angle"].where(df["la_ok"])
    tagged = df["is_bip"] & df["TaggedHitType"].isin(BATTED_BALL_TYPES)
    df["has_hit_type"] = tagged
    df["is_gb"] = tagged & (df["TaggedHitType"] == "GroundBall")
    df["is_fb"] = tagged & df["TaggedHitType"].isin(["FlyBall", "Popup"])


# --- Preparation --------------------------------------------------------------------------------

def prepare(raw: pd.DataFrame, rules: list[dict] | None = None,
            overrides: dict[str, str] | None = None) -> pd.DataFrame:
    """Raw stored rows -> analysis frame. Pure: returns a new frame, never alters `raw`."""
    if raw.empty:
        return raw.copy()
    df = raw.copy()
    for c in NUMERIC_COLUMNS:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Text columns: missing is "" (never NA), so comparisons are always plain True/False.
    for c in df.columns:
        if c not in NUMERIC_COLUMNS and (df[c].dtype == object or pd.api.types.is_string_dtype(df[c])):
            df[c] = df[c].fillna("").astype(str)
    df = df.copy()  # one contiguous block before adding columns (avoids pandas fragmentation warnings)
    local = df["LocalDateTime"] if "LocalDateTime" in df else pd.Series([""] * len(df), index=df.index)
    df["game_date"] = [parse_game_date(l, d) for l, d in zip(local, df["Date"])]
    df = df.sort_values(["game_date", "GameID", "PitchNo"], kind="stable").reset_index(drop=True)

    apply_pitch_types(df, rules, overrides)
    add_pa_columns(df)
    add_location_columns(df)
    add_pitch_outcomes(df)
    add_batted_ball_columns(df)
    add_pa_outcomes(df)
    return df.copy()


# --- Batting line shared by hitter reports and pitcher splits ------------------------------------

def batting_counts(df: pd.DataFrame) -> dict[str, int]:
    ends = df[df["pa_end"]]
    c = {k: int(ends[f"is_{k.lower()}"].sum()) for k in
         ["K", "BB", "IBB", "HBP", "SF", "SH", "HR", "1B", "2B", "3B", "ROE", "CI"]}
    c.update(PA=len(ends), AB=int(ends["is_ab"].sum()), H=int(ends["is_hit"].sum()),
             TB=int(ends["total_bases"].sum()))
    return c


def avg_stat(c: dict, min_key: str = "ab") -> Stat:
    """**AVG / BAA**: H ÷ AB."""
    return ratio(c["H"], c["AB"], min_key)


def obp_stat(c: dict) -> Stat:
    """**OBP**: (H + BB + IBB + HBP) ÷ (AB + BB + IBB + HBP + SF)."""
    den = c["AB"] + c["BB"] + c["IBB"] + c["HBP"] + c["SF"]
    return Stat((c["H"] + c["BB"] + c["IBB"] + c["HBP"]) / den if den else None, den, _min("pa"), "avg")


def slg_stat(c: dict) -> Stat:
    """**SLG**: total bases ÷ AB."""
    return ratio(c["TB"], c["AB"], "ab")


def woba_stat(c: dict) -> Stat:
    """**wOBA (MLB weights)**: (wBB·BB + wHBP·HBP + w1B·1B + w2B·2B + w3B·3B + wHR·HR) ÷
    (AB + BB + SF + HBP). Intentional walks are left out of both. Weights: config.WOBA_WEIGHTS."""
    w = config.WOBA_WEIGHTS
    num = (w["BB"] * c["BB"] + w["HBP"] * c["HBP"] + w["1B"] * c["1B"] + w["2B"] * c["2B"]
           + w["3B"] * c["3B"] + w["HR"] * c["HR"])
    den = c["AB"] + c["BB"] + c["SF"] + c["HBP"]
    return Stat(num / den if den else None, den, _min("pa"), "avg")


def babip_stat(c: dict) -> Stat:
    """**BABIP**: (H − HR) ÷ (AB − K − HR + SF)."""
    den = c["AB"] - c["K"] - c["HR"] + c["SF"]
    return Stat((c["H"] - c["HR"]) / den if den > 0 else None, max(den, 0), _min("babip"), "avg")


def k_pct(c: dict) -> Stat:
    """**K %**: strikeouts ÷ PA."""
    return Stat(100.0 * c["K"] / c["PA"] if c["PA"] else None, c["PA"], _min("pa"), "pct")


def bb_pct(c: dict) -> Stat:
    """**BB %**: walks (including intentional) ÷ PA."""
    return Stat(100.0 * (c["BB"] + c["IBB"]) / c["PA"] if c["PA"] else None, c["PA"], _min("pa"), "pct")


def hard_hit_pct(df: pd.DataFrame) -> Stat:
    """**Hard Hit %**: hard-hit balls ÷ balls in play with a tracked (ev_ok) exit velo."""
    return rate(df["is_hard_hit"], df["ev_ok"], "bip")


def gb_pct(df: pd.DataFrame) -> Stat:
    """**GB %**: TaggedHitType GroundBall ÷ balls in play tagged GroundBall, LineDrive, FlyBall or Popup."""
    return rate(df["is_gb"], df["has_hit_type"], "bip")


def fb_pct(df: pd.DataFrame) -> Stat:
    """**FB %**: TaggedHitType FlyBall or Popup ÷ the same denominator as GB %."""
    return rate(df["is_fb"], df["has_hit_type"], "bip")


def whiff_pct(df: pd.DataFrame) -> Stat:
    """**Whiff %**: whiffs ÷ swings. Min n: MIN_N['swings']."""
    return rate(df["is_whiff"], df["is_swing"], "swings")


def chase_pct(df: pd.DataFrame) -> Stat:
    """**Chase %**: swings at pitches outside the zone ÷ pitches outside the zone."""
    return rate(df["is_chase"], df["out_zone"], "out_of_zone")


def pitch_type_order(codes) -> list[str]:
    present = set(codes)
    return [c for c in config.PITCH_TYPES if c in present]


@dataclass
class ZoneGrid:
    """3x3 grid of Stats in catcher's view, rows top to bottom, columns left to right."""
    cells: list[list[Stat]]
    n_outside: int     # events outside the zone (not drawn in the grid)
    n_untracked: int   # events with no pitch location


def zone_grid(events: pd.DataFrame, cell_stat) -> ZoneGrid:
    g = config.ZONE_GRID
    cells = [[cell_stat(events[events["zone_cell"] == r * g + c + 1]) for c in range(g)] for r in range(g)]
    return ZoneGrid(cells, int(events["out_zone"].sum()), int((~events["loc_tracked"]).sum()))
