"""Team Pitchers and Team Hitters pages: the individual report run on a whole team, then a table
with one row per player. Same filters, sections and charts as the individual pages."""
from __future__ import annotations

import dataclasses
from html import escape

import pandas as pd
import streamlit as st

import config
import db
from reports import team
from reports.pdf import team_pdf_bytes, team_pdf_filename
from ui import hitter_page, pitcher_page
from ui.common import (
    filters_text, footer, frame, get_conn, report_filters, section, show_table, thresholds_note,
)

TEAM_SCORE_NOTE = ("Team scores are the average of every player's game scores: each pitcher's outing, or each "
                   "hitter's game, counts once. Each player's own score is in the table, and his game-by-game "
                   "breakdown is on his individual report.")


def _team_picker(df: pd.DataFrame, kind: str) -> str:
    codes = team.teams(df, kind)
    if len(codes) == 1:
        return codes[0]
    return st.sidebar.selectbox("Team", codes, format_func=team.team_label, key=f"team_{kind}",
                                help="GCSU, or the other team in an outside game.")


def _pdf_controls(kind: str, t, f) -> None:
    sb = st.sidebar
    sb.markdown("### PDF")
    note = filters_text(f)
    name = team_pdf_filename(kind, t)
    if not config.DEMO_MODE:
        sb.download_button("Download team report", data=lambda: team_pdf_bytes(kind, t, note), file_name=name,
                           mime="application/pdf", icon=":material/picture_as_pdf:", type="primary",
                           on_click="ignore", help="Page 1 is the report below; then the by-player table.")
        return
    # Browser test version: build first, then download (see ui.common._demo_pdf_controls).
    key = ("team", kind, t.team, dataclasses.astuple(f), db.data_version(get_conn()))
    made = st.session_state.setdefault("demo_pdfs", {})
    if key in made:
        sb.download_button("Save team report (PDF)", data=made[key], file_name=name, mime="application/pdf",
                           icon=":material/picture_as_pdf:", type="primary", on_click="ignore")
    elif sb.button("Make PDF of the team report", type="primary", icon=":material/picture_as_pdf:"):
        with st.spinner("Making the PDF…"):
            made[key] = team_pdf_bytes(kind, t, note)
        st.rerun()


def _roster(roster: pd.DataFrame, caption: str) -> None:
    """One row per player, in the app's table style (grey = below the minimum sample)."""
    shown, low = team.roster_text(roster), team.roster_low(roster)
    head = "".join(f"<th>{escape(c)}</th>" for c in shown.columns)
    body = []
    for i, row in enumerate(shown.itertuples(index=False)):
        tds = [f'<td class="lab">{escape(row[0])}</td>'] + [
            f'<td{" class=low" if low.iat[i, j] else ""}><span class="v">{escape(v)}</span></td>'
            for j, v in enumerate(row) if j]
        body.append(f"<tr>{''.join(tds)}</tr>")
    show_table(f'<div class="gc-scroll"><table class="gc"><thead><tr>{head}</tr></thead>'
               f'<tbody>{"".join(body)}</tbody></table></div>', caption)


def render_pitchers() -> None:
    f = report_filters(get_conn())
    if f is None:
        return
    df = frame(f)
    if df.empty:
        st.warning("No pitches match these filters.")
        return
    t = team.build_pitchers(df, _team_picker(df, "pitcher"))
    if t is None:
        st.warning("This team threw no pitches in the selected games.")
        return
    _pdf_controls("pitcher", t, f)
    pitcher_page.show(t.report, "Team Pitcher Report")
    section(6, "By Pitcher", f"{t.n_players} pitchers · best Pitcher Score first")
    _roster(t.roster, "Each row is that pitcher's numbers for the same games and filters. Grey = below the minimum "
                      "sample. " + TEAM_SCORE_NOTE)
    footer(thresholds_note())


def render_hitters() -> None:
    f = report_filters(get_conn())
    if f is None:
        return
    df = frame(f)
    if df.empty:
        st.warning("No pitches match these filters.")
        return
    t = team.build_hitters(df, _team_picker(df, "hitter"))
    if t is None:
        st.warning("This team had no plate appearances in the selected games.")
        return
    _pdf_controls("hitter", t, f)
    hitter_page.show(t.report, "Team Hitter Report", f"{t.n_players} hitters")
    section(5, "By Hitter", f"{t.n_players} hitters · best Hitter Score first")
    _roster(t.roster, "Each row is that hitter's numbers for the same games and filters. Grey = below the minimum "
                      "sample. " + TEAM_SCORE_NOTE)
    footer(thresholds_note())
