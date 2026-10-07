"""Pitcher Report page (P1)."""
from __future__ import annotations

import streamlit as st

import config
from charts import pitching as cp
from charts.zone import zone_heatmap
from metrics import pitching
from reports import pitcher as report
from reports.tables import PITCH_TYPE_COLS, PITCHER_SPLIT_COLS
from ui.common import (
    footer, frame, get_conn, header, pdf_controls, report_filters, section, show_table, stat_table, thresholds_note,
    tiles,
)


def render() -> None:
    conn = get_conn()
    f = report_filters(conn)
    if f is None:
        return
    df = frame(f)
    if df.empty:
        st.warning("No pitches match these filters.")
        return
    roster = pitching.list_pitchers(df)
    labels = {r.PitcherId: f"{r.Pitcher} ({r.PitcherThrows[:1]}HP) · {r.pitches} pitches"
              for r in roster.itertuples()}
    pid = st.sidebar.selectbox("Pitcher", list(labels), format_func=labels.get, key="pitcher_id")
    r = report.build(df, pid)
    if r is None:
        st.warning("This pitcher threw no pitches in the selected games.")
        return
    pdf_controls("pitcher", r, df, f, len(roster))

    header("Individual Pitcher Report", r.name, r.scope.season_text, r.scope.date_text,
           f"{r.throws_short} · {r.scope.games} game(s) · {r.scope.game_types_text}")
    if r.n_corrected:
        st.caption(f"{r.n_corrected} of this pitcher's pitches are re-typed by coach corrections "
                   "(Pitch Type Corrections page).")

    section(1, "Game Summary", f"{r.line['pitches']} pitches")
    L = r.line
    tiles([("IP", L["IP"]), ("PA", L["PA"]), ("H", L["H"]), ("R", L["R"]), ("ER", "—*"), ("BB", L["BB"]),
           ("K", L["K"]), ("HR", L["HR"]), ("Strike %", L["Strike %"]), ("1st-Pitch Strike %", L["First-Pitch Strike %"])])
    st.markdown('<div class="gc-foot">* TrackMan does not record earned runs. R = runs scored while this '
                "pitcher was on the mound. IP counts strikeouts plus outs on the play, including outs on the "
                "bases.</div>", unsafe_allow_html=True)

    section(2, "Pitch Type Metrics", "averages by pitch type")
    star = "* fewer than 10 pitches. " if any(s.low for s in r.table["Count"]) else ""
    show_table(stat_table(r.table, PITCH_TYPE_COLS, count_key="Count"),
               f"{star}Velo, spin, movement and release averages use the pitches counted in Count unless an n "
               "is shown. HB: + = third-base side (arm side for a RHP). Out % = PAs ending on the pitch with an "
               "out ÷ PAs ending on the pitch.")

    # Same sections, in the same order, as the PDF (reports/pdf.py).
    section(3, "Usage & Swing-and-Miss")
    c1, c2, c3 = st.columns(3)
    c1.pyplot(cp.usage_chart(r.usage))
    c2.pyplot(cp.rate_bars(r.table, "Whiff %", "Whiff % by pitch type",
                           f"fewer than {config.MIN_N['swings']} swings"))
    c3.pyplot(cp.rate_bars(r.table, "Chase %", "Chase % by pitch type",
                           f"fewer than {config.MIN_N['out_of_zone']} pitches outside the zone"))

    section(4, "Movement & Locations")
    c1, c2, c3 = st.columns(3)
    c1.pyplot(cp.movement_chart(r.movement))
    c2.pyplot(zone_heatmap(r.zone_baa, "Strike Zone BAA", config.ZONE_AVG_SCALE, "at-bats"))
    c3.pyplot(cp.whiff_locations_chart(r.whiffs))

    section(5, "Hitter Splits")
    show_table(stat_table(r.splits, PITCHER_SPLIT_COLS, row_label=str, label_header="Split"),
               "Hitter side is the batter who finished each plate appearance. GB % and FB % use TaggedHitType; "
               "FB % includes popups.")

    footer(thresholds_note())
