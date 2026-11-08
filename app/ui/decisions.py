"""Clickable Swing Decisions chart for the app (coaches, Nov 2026: "click one of the pitches and see what
the pitch metrics on that take/swing/chase was"). The PDF keeps the matplotlib chart (charts.hitting),
since paper can't be clicked; this one draws the same points, colors and zone with Altair so a click on a
pitch shows its details underneath."""
from __future__ import annotations

from html import escape

import altair as alt
import pandas as pd
import streamlit as st

import config
from charts.base import pitch_label
from metrics.hitting import SWING_DECISIONS
from reports.context import display_name, fmt_date

WIDTH, HEIGHT = 248, 310  # px; 4 ft x 5 ft window, so the zone keeps its shape
SELECTION = "pick"


def _fmt(v, spec: str, unit: str = "") -> str:
    return "—" if v is None or pd.isna(v) else f"{v:{spec}}{unit}"


def _chart_frame(points: pd.DataFrame) -> pd.DataFrame:
    """Points with the fields the Altair chart encodes: fill and stroke colors (takes are hollow), a
    shape (chases are crosses) and the tooltip text."""
    d = points.copy()
    color = d["decision"].map(config.DECISION_COLORS)
    filled = d["decision"].str.startswith("Swing") | (d["decision"] == "Chase")
    d["stroke"] = color
    d["fill"] = color.where(filled, "transparent")
    d["shape"] = (d["decision"] == "Chase").map({True: "cross", False: "circle"})
    d["pitch"] = d["pitch_type"].map(pitch_label)
    d["velo"] = d["RelSpeed"].map(lambda v: _fmt(v, ".1f", " mph"))
    (x0, x1), (y0, y1) = config.LOC_PLOT_X, config.LOC_PLOT_Y
    d["x"] = d["plot_x"].clip(x0, x1)
    d["y"] = d["plot_y"].clip(y0, y1)
    return d[["PitchUID", "x", "y", "stroke", "fill", "shape", "pitch", "count", "velo", "decision", "result"]]


def decisions_chart(points: pd.DataFrame) -> alt.LayerChart:
    """Strike zone, home plate and every pitch, catcher's view; click selects one pitch."""
    hw, lo, hi = config.ZONE_HALF_WIDTH_FT, config.ZONE_BOTTOM_FT, config.ZONE_TOP_FT
    xs = alt.Scale(domain=list(config.LOC_PLOT_X), nice=False)
    ys = alt.Scale(domain=list(config.LOC_PLOT_Y), nice=False)
    no_axis = alt.Axis(labels=False, ticks=False, title=None, grid=False, domain=False)
    zone = alt.Chart(pd.DataFrame({"x": [-hw], "x2": [hw], "y": [lo], "y2": [hi]})).mark_rect(
        fill="transparent", stroke=config.NAVY, strokeWidth=2).encode(
        x=alt.X("x:Q", scale=xs, axis=no_axis), x2="x2", y=alt.Y("y:Q", scale=ys, axis=no_axis), y2="y2")
    p = 17 / 24
    plate = alt.Chart(pd.DataFrame({"x": [-p, p, p, 0, -p, -p], "y": [0.45, 0.45, 0.33, 0.15, 0.33, 0.45],
                                    "o": range(6)})).mark_line(color=config.NAVY, strokeWidth=1.2).encode(
        x=alt.X("x:Q", scale=xs), y=alt.Y("y:Q", scale=ys), order="o")
    pick = alt.selection_point(name=SELECTION, fields=["PitchUID"], on="click", empty=True)
    dots = alt.Chart(_chart_frame(points)).mark_point(size=70, strokeWidth=1.6, opacity=1).encode(
        x=alt.X("x:Q", scale=xs), y=alt.Y("y:Q", scale=ys),
        fill=alt.Fill("fill:N", scale=None), stroke=alt.Stroke("stroke:N", scale=None),
        shape=alt.Shape("shape:N", scale=None),
        size=alt.condition(pick, alt.value(110), alt.value(45)),
        opacity=alt.condition(pick, alt.value(1.0), alt.value(0.3)),
        tooltip=[alt.Tooltip("pitch:N", title="Pitch"), alt.Tooltip("count:N", title="Count"),
                 alt.Tooltip("velo:N", title="Velo"), alt.Tooltip("decision:N", title="Decision"),
                 alt.Tooltip("result:N", title="Result")],
    ).add_params(pick)
    return (zone + plate + dots).properties(width=WIDTH, height=HEIGHT).configure_view(stroke=None)


def _legend(counts: dict[str, int]) -> str:
    items = []
    for d in SWING_DECISIONS:
        color = config.DECISION_COLORS[d]
        filled = d.startswith("Swing") or d == "Chase"
        mark = "✕" if d == "Chase" else "●" if filled else "○"
        items.append(f'<span style="color:{color};font-weight:700">{mark}</span> {escape(d)} ({counts.get(d, 0)})')
    return '<div class="gc-foot">' + " &nbsp; ".join(items) + "</div>"


def _details(row: pd.Series) -> str:
    """One pitch's numbers, as the panel under the chart shows them."""
    hand = {"Right": "RHP", "Left": "LHP"}.get(row["PitcherThrows"], "")
    opp = f" vs {row['game_opponent']}" if isinstance(row["game_opponent"], str) and row["game_opponent"] else ""
    inning = f"Inning {int(row['Inning'])}" if pd.notna(row["Inning"]) else ""
    bip = ""
    if pd.notna(row["ev"]) or pd.notna(row["la"]):
        bip = f" · Exit velo **{_fmt(row['ev'], '.1f', ' mph')}** · Launch angle **{_fmt(row['la'], '.0f', '°')}**"
    height_in = row["PlateLocHeight"] * 12 if pd.notna(row["PlateLocHeight"]) else None
    return (f"**{pitch_label(row['pitch_type'])}** · {row['decision']} · **{row['result']}**  \n"
            f"Count **{row['count'] or '—'}** · {fmt_date(row['game_date'])}{opp} · {inning} · "
            f"{display_name(row['Pitcher'] or '')} ({hand})  \n"
            f"Velo **{_fmt(row['RelSpeed'], '.1f', ' mph')}** · Spin **{_fmt(row['SpinRate'], ',.0f', ' rpm')}** · "
            f"IVB **{_fmt(row['InducedVertBreak'], '.1f', ' in')}** · HB **{_fmt(row['HorzBreak'], '.1f', ' in')}** · "
            f"Height **{_fmt(height_in, '.0f', ' in')}** above the ground{bip}")


DETAIL_COLUMNS = {"pitch": "Pitch", "count": "Count", "decision": "Decision", "result": "Result",
                  "velo": "Velo (mph)", "spin": "Spin (rpm)", "ivb": "IVB (in)", "hb": "HB (in)",
                  "ev": "EV (mph)", "la": "LA (°)", "date": "Date", "inning": "Inn", "pitcher": "Pitcher"}


def pitch_table(points: pd.DataFrame) -> pd.DataFrame:
    """Every pitch on the chart as table rows, for the list under it."""
    return pd.DataFrame({
        "pitch": points["pitch_type"].map(pitch_label), "count": points["count"], "decision": points["decision"],
        "result": points["result"], "velo": points["RelSpeed"].round(1), "spin": points["SpinRate"].round(0),
        "ivb": points["InducedVertBreak"].round(1), "hb": points["HorzBreak"].round(1),
        "ev": points["ev"].round(1), "la": points["la"].round(0),
        "date": points["game_date"].map(fmt_date), "inning": points["Inning"],
        "pitcher": points["Pitcher"].fillna("").map(display_name),
    }).rename(columns=DETAIL_COLUMNS)


def render(container, points: pd.DataFrame, counts: dict[str, int], key: str) -> None:
    """The chart in `container` (a column), the clicked pitch's details under it, and a list of every
    pitch on the chart, filterable by decision."""
    with container:
        st.markdown('<div style="font-weight:800;color:%s;font-size:14px">SWING DECISIONS</div>'
                    '<div class="gc-foot">Catcher\'s view · %d pitches · filled = swing · '
                    '<b>click a pitch for its numbers</b></div>' % (config.NAVY, len(points)),
                    unsafe_allow_html=True)
        if points.empty:
            st.caption("No tracked pitches.")
            return
        event = st.altair_chart(decisions_chart(points), on_select="rerun", selection_mode=SELECTION,
                                key=f"{key}_chart", width="content")
        st.markdown(_legend(counts), unsafe_allow_html=True)
        picked = (event.selection.get(SELECTION) or []) if event else []
        uid = picked[0].get("PitchUID") if picked else None
        row = points[points["PitchUID"] == uid]
        if not row.empty:
            st.info(_details(row.iloc[0]))
        else:
            st.caption("Click a pitch to see its velo, spin, movement and result. Double-click to clear.")
        with st.expander("Every pitch on this chart"):
            only = st.selectbox("Show", ["All pitches", *SWING_DECISIONS], key=f"{key}_only")
            shown = points if only == "All pitches" else points[points["decision"] == only]
            st.dataframe(pitch_table(shown), hide_index=True)
