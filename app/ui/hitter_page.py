"""Hitter Report page (P2)."""
from __future__ import annotations

import streamlit as st

import config
from charts import hitting as ch
from charts.zone import zone_heatmap
from metrics import hitting
from reports import hitter as report
from reports.tables import BREAKDOWN_COLS, HITTER_SPLIT_COLS
from ui.common import (
    SCORES_NOTE, footer, frame, get_conn, header, pdf_controls, report_filters, score_breakdown, section, show_table,
    stat_table, thresholds_note, tiles,
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
    roster = hitting.list_hitters(df)
    labels = {r.hitter_id: f"{r.hitter} ({r.side or '?'}) · {r.PA} PA" for r in roster.itertuples()}
    hid = st.sidebar.selectbox("Hitter", list(labels), format_func=labels.get, key="hitter_id")
    r = report.build(df, hid)
    if r is None:
        st.warning("This hitter saw no pitches in the selected games.")
        return
    pdf_controls("hitter", r, df, f, len(roster))
    show(r)

    section(5, "Scores", "1–100, from the coaches' scoring sheet")
    score_breakdown(r.grades)
    st.caption(SCORES_NOTE)

    footer(thresholds_note())


def show(r: report.HitterReport, title: str = "Individual Hitter Report", who: str | None = None) -> None:
    """Header and sections 1–4, for one hitter or (team page) a whole lineup."""
    header(title, r.name, r.scope.season_text, r.scope.date_text,
           f"{who or 'Bats ' + r.bats_short} · {r.scope.games} game(s) · {r.scope.game_types_text}", r.grades)

    k = r.key
    section(1, "Key Performance Metrics", report.key_note(k))
    tiles([("PA", k["PA"]), ("AVG", k["AVG"]), ("OBP", k["OBP"]), ("SLG", k["SLG"]), ("OPS", k["OPS"]),
           ("wOBA (MLB wts)", k["wOBA"]), ("QAB %", k["QAB %"]), ("Hard Hit %", k["Hard Hit %"]),
           ("Avg Exit Velo", k["Avg Exit Velo"]), ("Max Exit Velo", k["Max Exit Velo"]),
           ("Avg Launch Angle", k["Avg Launch Angle"])])
    st.markdown(f'<div class="gc-foot">{report.key_footnote(k)}</div>', unsafe_allow_html=True)

    section(2, "Pitch Breakdown", "Seen % = % of pitches seen")
    star = "* fewer than 10 pitches. " if any(s.low for s in r.breakdown["Pitches"]) else ""
    show_table(stat_table(r.breakdown, BREAKDOWN_COLS, count_key="Pitches"),
               f"{star}Avg EV and Avg LA by pitch use balls in play off that pitch type.")

    section(3, "Contact & Decisions")
    c1, c2, c3 = st.columns(3)
    c1.pyplot(ch.contact_chart(r.contact))
    c2.pyplot(ch.spray_chart(r.spray))
    c3.pyplot(ch.swing_decisions_chart(r.decisions, r.decision_counts))
    c1, c2, c3 = st.columns(3)
    c1.pyplot(zone_heatmap(r.zone_ev, "Strike Zone Exit Velo", config.ZONE_EV_SCALE, "balls in play"))
    c2.pyplot(zone_heatmap(r.zone_avg, "Strike Zone AVG", config.ZONE_AVG_SCALE, "at-bats"))
    c3.pyplot(ch.chase_map_chart(r.chase, r.sides))

    section(4, "Splits: Pitcher Hand & Velo Tier")
    show_table(stat_table(r.splits, HITTER_SPLIT_COLS, row_label=str, label_header="Split"), report.SPLITS_NOTE)
