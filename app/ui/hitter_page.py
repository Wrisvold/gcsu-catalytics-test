"""Hitter Report page (P2)."""
from __future__ import annotations

from html import escape

import streamlit as st

import config
from charts import hitting as ch
from charts.zone import zone_heatmap
from metrics import hitting
from reports import hitter as report
from reports.context import fmt_date, pbp_note
from reports.tables import BREAKDOWN_COLS, HITTER_SPLIT_COLS
from ui import decisions
from ui.common import (
    SCORES_NOTE, footer, frame, get_conn, header, pdf_controls, pitch_label_html, report_filters, score_breakdown,
    section, show_table, stat_table, thresholds_note, tiles,
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
    all_seq = _filter_at_bats(r)  # before the PDF buttons, so this report's PDF lists the same at-bats
    pdf_controls("hitter", r, df, f, len(roster))
    show(r)
    show_page2(r, all_seq)

    section(7, "Scores", "1–100, from the coaches' scoring sheet")
    score_breakdown(r.grades)
    st.caption(SCORES_NOTE)

    footer(thresholds_note())


def show(r: report.HitterReport, title: str = "Individual Hitter Report", who: str | None = None) -> None:
    """Header and sections 1–4, for one hitter or (team page) a whole lineup."""
    header(title, r.name, r.scope.season_text, r.scope.date_text,
           f"{who or 'Bats ' + r.bats_short} · {r.scope.games} game(s) · {r.scope.game_types_text}", r.grades)
    if note := pbp_note(r.scope):
        st.caption(note)

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
    decisions.render(c3, r.decisions, r.decision_counts, key=f"decisions_{r.hitter_id}")
    c1, c2, c3 = st.columns(3)
    c1.pyplot(zone_heatmap(r.zone_ev, "Strike Zone Exit Velo", config.ZONE_EV_SCALE, "balls in play"))
    c2.pyplot(zone_heatmap(r.zone_avg, "Strike Zone AVG", config.ZONE_AVG_SCALE, "at-bats"))
    c3.pyplot(ch.chase_map_chart(r.chase, r.sides))

    section(4, "Splits: Pitcher Hand & Velo Tier")
    show_table(stat_table(r.splits, HITTER_SPLIT_COLS, row_label=str, label_header="Split"), report.SPLITS_NOTE)


def _code_html(code: str, color: str) -> str:
    return f'<b style="color:{color}">{escape(code)}</b>'


def _at_bat_keys(r: report.HitterReport) -> tuple[str, str]:
    return f"ab_teams_{r.hitter_id}", f"ab_dates_{r.hitter_id}"


def _filter_at_bats(r: report.HitterReport):
    """Apply the at-bat list's Team and Date filters (widgets drawn in section 6, read here from the
    session first) to `r.sequences`. Returns the full list, for the filters' choices."""
    all_seq = r.sequences
    choices = (report.sequence_teams(all_seq), report.sequence_dates(all_seq))
    picked = []
    for key, options in zip(_at_bat_keys(r), choices):
        kept = [v for v in st.session_state.get(key, []) if v in options]  # drop picks the date range removed
        st.session_state[key] = kept
        picked.append(kept)
    r.sequences, r.sequence_filter = report.filter_sequences(all_seq, *picked)
    return all_seq


def show_page2(r: report.HitterReport, all_seq=None) -> None:
    """Sections 5 and 6 (page 2 of the PDF): the pitch mix in each count, then every plate appearance
    pitch by pitch, with Team and Date filters when `all_seq` (the unfiltered list) is given."""
    section(5, "Pitch Mix by Count", "% of pitches seen in each count")
    types, mix = report.count_mix_rows(r.count_mix)
    if mix:
        head = "<th>Count</th><th>Pitches</th>" + "".join(
            f"<th>{pitch_label_html(t)}</th>" for t in types)
        body = "".join(
            f'<tr class="{"grp" if not label[0].isdigit() else ""}"><td class="lab">{escape(label)}</td>'
            + "".join(f"<td>{escape(v)}</td>" for v in vals) + "</tr>" for label, vals in mix)
        show_table(f'<div class="gc-scroll"><table class="gc"><thead><tr>{head}</tr></thead>'
                   f'<tbody>{body}</tbody></table></div>', report.COUNT_MIX_NOTE)
    else:
        st.caption("No pitches with a count.")

    section(6, "At-Bat Sequences", f"{len(r.sequences)} plate appearances"
            + (f" of {len(all_seq)}" if all_seq is not None and len(all_seq) != len(r.sequences) else ""))
    if all_seq is not None and not all_seq.empty:
        team_key, date_key = _at_bat_keys(r)
        c1, c2 = st.columns(2)
        c1.multiselect("Team", report.sequence_teams(all_seq), key=team_key, placeholder="All teams",
                       help="Only at-bats against these teams: GCSU, or the opponent entered on Game "
                            "Context (TrackMan's team code when none is entered).")
        c2.multiselect("Date", report.sequence_dates(all_seq), key=date_key, format_func=fmt_date,
                       placeholder="All dates", help="Only at-bats from these games.")
        st.caption("Leave both empty for every at-bat. This report's PDF lists the same at-bats; the team print "
                   "file always lists them all.")
    rows = report.sequence_rows(r.sequences)
    if rows:
        head = "".join(f"<th>{h}</th>" for h in rows[0])
        body = "".join(
            "<tr>" + "".join(
                f'<td style="text-align:left">{report.colored_sequence(escape(v), _code_html)}</td>' if k == "Sequence"
                else f'<td class="lab">{escape(v)}</td>' if k == "Pitcher" else f"<td>{escape(v)}</td>"
                for k, v in row.items()) + "</tr>" for row in rows)
        show_table(f'<div class="gc-scroll"><table class="gc"><thead><tr>{head}</tr></thead>'
                   f'<tbody>{body}</tbody></table></div>', report.SEQUENCE_NOTE)
    else:
        st.caption("No plate appearances.")
