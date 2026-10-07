"""Streamlit pieces shared by every page: connection, cached analysis frame, GCSU branding, tables
that always show n, and the report filters. Metrics and charts never import from here."""
from __future__ import annotations

import base64
import dataclasses
from datetime import date
from html import escape

import pandas as pd
import streamlit as st

import config
import db
from metrics.common import Stat
from reports.context import ReportFilters, filters_text, fmt_date, load_frame, thresholds_note  # noqa: F401
from reports.pdf import batch_export, batch_zip, export_filename, pdf_bytes
from reports.tables import Col, build_table

CSS = f"""
<style>
:root {{ --navy: {config.NAVY}; --green: {config.GREEN}; --grey: {config.LIGHT_GREY};
         --low: {config.LOW_SAMPLE_GREY}; --lowtext: {config.LOW_SAMPLE_TEXT}; }}
.gc-header {{ background: var(--navy); color: white; border-radius: 6px; padding: 14px 20px;
              display: flex; align-items: center; gap: 22px; margin-bottom: 10px; flex-wrap: wrap; }}
.gc-mark {{ width: 78px; height: 78px; border-radius: 50%; border: 3px solid var(--green);
            display: flex; align-items: center; justify-content: center; text-align: center;
            font-weight: 800; font-size: 13px; line-height: 1.1; flex: none; }}
.gc-mark img {{ width: 78px; height: 78px; border-radius: 50%; }}
.gc-titles {{ flex: 1; min-width: 260px; border-left: 3px solid var(--green); padding-left: 16px; }}
.gc-title {{ font-size: 34px; font-weight: 900; letter-spacing: 1px; line-height: 1; }}
.gc-sub {{ font-size: 20px; font-weight: 800; color: #7FD39A; margin-top: 4px; }}
.gc-values {{ font-size: 10px; letter-spacing: 1px; color: #C9D3DF; margin-top: 6px; }}
.gc-player {{ text-align: right; min-width: 220px; margin-left: auto; }}
.gc-player .name {{ font-size: 22px; font-weight: 800; text-transform: uppercase; }}
.gc-player .season {{ color: #7FD39A; font-weight: 700; }}
.gc-player .dates {{ font-size: 12px; color: #C9D3DF; }}
.gc-grade {{ margin-top: 6px; border: 2px dashed #7FD39A; border-radius: 4px; padding: 4px 8px;
             font-size: 11px; color: #C9D3DF; display: inline-block; }}
.gc-section {{ background: var(--navy); color: white; border-radius: 4px; padding: 6px 12px; margin: 18px 0 8px;
               font-weight: 800; letter-spacing: .5px; display: flex; align-items: center; gap: 12px; }}
.gc-section .num {{ background: var(--green); padding: 1px 10px; border-radius: 3px; }}
.gc-section .note {{ margin-left: auto; font-size: 11px; font-weight: 500; color: #C9D3DF; }}
.gc-tiles {{ display: flex; background: var(--navy); border-radius: 6px; padding: 6px 0; flex-wrap: wrap; }}
.gc-tile {{ flex: 1; min-width: 92px; text-align: center; color: white; padding: 6px 4px;
            border-right: 1px solid var(--green); }}
.gc-tile:last-child {{ border-right: none; }}
.gc-tile .lab {{ font-size: 11px; font-weight: 700; color: #C9D3DF; text-transform: uppercase; }}
.gc-tile .val {{ font-size: 24px; font-weight: 800; }}
.gc-tile .n {{ font-size: 10px; color: #C9D3DF; }}
.gc-tile.low .val {{ color: #8A96A3; font-size: 18px; }}
.gc-scroll {{ overflow-x: auto; }}
table.gc {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
table.gc th {{ background: var(--navy); color: white; padding: 5px 6px; text-align: center; font-weight: 700; }}
table.gc th .hn {{ display: block; font-size: 10px; font-weight: 400; color: #C9D3DF; }}
table.gc td {{ padding: 4px 6px; text-align: center; border-bottom: 1px solid var(--grey); }}
table.gc td.lab {{ text-align: left; white-space: nowrap; font-weight: 600; }}
table.gc tr:nth-child(even) td {{ background: #F6F7F9; }}
table.gc tr.all td {{ background: var(--navy); color: white; font-weight: 700; }}
table.gc td .n {{ display: block; font-size: 10px; color: #6B7785; line-height: 1; }}
table.gc tr.all td .n {{ color: #C9D3DF; }}
table.gc td.low {{ color: var(--lowtext); background: #ECECEC !important; }}
table.gc td.low .v {{ font-size: 11px; }}
table.gc tr.all td.low {{ background: #3A4A60 !important; color: #AAB4C0; }}
.gc-dot {{ display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: 6px;
           vertical-align: -1px; }}
.gc-foot {{ font-size: 11px; color: #555; margin-top: 4px; }}
.gc-footer {{ background: var(--navy); color: white; text-align: center; padding: 14px; border-radius: 6px;
              margin-top: 22px; }}
.gc-footer .big {{ font-size: 22px; font-weight: 800; letter-spacing: 6px; }}
.gc-footer .vals {{ font-size: 10px; letter-spacing: 2px; color: #C9D3DF; margin-top: 4px; }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# --- Data ---------------------------------------------------------------------------------------

@st.cache_resource
def get_conn():
    return db.connect()


@st.cache_data(show_spinner="Crunching numbers…", max_entries=16)
def _frame(filter_values: tuple, version: tuple) -> pd.DataFrame:  # version is only a cache key
    return load_frame(get_conn(), ReportFilters(*filter_values))


def frame(f: ReportFilters) -> pd.DataFrame:
    """Analysis frame for the filters, cached until any pitch, game, rule or override changes."""
    conn = get_conn()
    return _frame(dataclasses.astuple(f), db.data_version(conn))


# --- Branding -----------------------------------------------------------------------------------

def _wordmark() -> str:
    if config.LOGO_PATH.exists():
        b64 = base64.b64encode(config.LOGO_PATH.read_bytes()).decode()
        return f'<div class="gc-mark"><img src="data:image/png;base64,{b64}" alt="GCSU logo"></div>'
    return '<div class="gc-mark">GCSU<br>BASEBALL</div>'


def header(report_kind: str, player: str | None = None, season: str = "", dates: str = "",
           extra: str = "") -> None:
    """Navy header band from the GCSU mockup. `report_kind` e.g. "Individual Pitcher Report"."""
    right = ""
    if player:
        right = (f'<div class="gc-player"><div class="name">{escape(player)}</div>'
                 f'<div class="season">{escape(season)}</div><div class="dates">{escape(dates)}</div>'
                 f'<div class="dates">{escape(extra)}</div>'
                 '<div class="gc-grade">Player Grade — pending coach definition</div></div>')
    st.markdown(
        f'<div class="gc-header">{_wordmark()}<div class="gc-titles">'
        f'<div class="gc-title">{config.APP_TITLE_CAPS}</div><div class="gc-sub">{escape(report_kind.upper())}</div>'
        f'<div class="gc-values">{config.FOOTER_VALUES}</div></div>{right}</div>', unsafe_allow_html=True)


def section(num: int, title: str, note: str = "") -> None:
    st.markdown(f'<div class="gc-section"><span class="num">{num:02d}</span>{escape(title.upper())}'
                f'<span class="note">{escape(note)}</span></div>', unsafe_allow_html=True)


def footer(note: str = "") -> None:
    st.markdown(f'<div class="gc-footer"><div class="big">GCSU BASEBALL</div>'
                f'<div class="vals">{config.FOOTER_VALUES}</div></div>', unsafe_allow_html=True)
    if note:
        st.caption(note)


# --- Stats as HTML ------------------------------------------------------------------------------

def pitch_label_html(code: str) -> str:
    if code == "All":
        return "All pitches"
    pt = config.PITCH_TYPES.get(code, config.PITCH_TYPES["OT"])
    return f'<span class="gc-dot" style="background:{pt["color"]}"></span>{escape(pt["label"])} ({code})'


def tiles(items: list[tuple[str, object]]) -> None:
    """Navy metric band. Values may be Stats (shown with n, greyed when low) or plain values."""
    cells = []
    for label, v in items:
        if isinstance(v, Stat):
            cls = " low" if v.low else ""
            cells.append(f'<div class="gc-tile{cls}"><div class="lab">{escape(label)}</div>'
                         f'<div class="val">{escape(v.text())}</div><div class="n">n={v.n}</div></div>')
        else:
            cells.append(f'<div class="gc-tile"><div class="lab">{escape(label)}</div>'
                         f'<div class="val">{escape(str(v))}</div><div class="n">&nbsp;</div></div>')
    st.markdown(f'<div class="gc-tiles">{"".join(cells)}</div>', unsafe_allow_html=True)


def stat_table(df: pd.DataFrame, cols: list[Col], row_label=pitch_label_html, label_header: str = "Pitch Type",
               count_key: str | None = None) -> str:
    """HTML rendering of `reports.tables.build_table` (n placement and greying live there)."""
    spec = build_table(df, cols, count_key)
    head = [f"<th>{escape(label_header)}</th>"] + [
        f'<th>{escape(h)}{f"<span class=hn>n={n}</span>" if n is not None else ""}</th>' for h, n in spec.headers]
    body = []
    for key, cells in spec.rows:
        tds = [f'<td class="lab">{row_label(key)}</td>']
        for cell in cells:
            n = f'<span class="n">n={cell.n}</span>' if cell.n is not None else ""
            cls = ' class="low"' if cell.low else ""
            tds.append(f'<td{cls}><span class="v">{escape(cell.text)}</span>{n}</td>')
        body.append(f'<tr class="{"all" if key == "All" else ""}">{"".join(tds)}</tr>')
    return (f'<div class="gc-scroll"><table class="gc"><thead><tr>{"".join(head)}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def show_table(html: str, foot: str = "") -> None:
    st.markdown(html, unsafe_allow_html=True)
    if foot:
        st.markdown(f'<div class="gc-foot">{escape(foot)}</div>', unsafe_allow_html=True)


# --- Filters ------------------------------------------------------------------------------------

def game_label(g: pd.Series) -> str:
    bits = [fmt_date(g["game_date"]), g["game_type"] or "type not set"]
    if g["opponent"]:
        bits.append(f"vs {g['opponent']}")
    if g["stadium"]:
        bits.append(g["stadium"])
    return " · ".join(bits)


def report_filters(conn) -> ReportFilters | None:
    """Sidebar filters shared by both report pages (widget keys persist across them)."""
    games = db.get_games(conn)
    if games.empty:
        st.info("No data yet. Load a TrackMan CSV on the **Load Data** page.")
        return None
    sb = st.sidebar
    sb.markdown("### Filters")
    mode = sb.radio("Report covers", ["Date range", "Single game"], key="f_mode", horizontal=True)
    if mode == "Single game":
        games = games.sort_values(["game_date", "game_id"], ascending=False)
        gid = sb.selectbox("Game", games["game_id"].tolist(), key="f_game",
                           format_func=lambda g: game_label(games.set_index("game_id").loc[g]))
        return ReportFilters(game_ids=(gid,))

    dates = [date.fromisoformat(d) for d in games["game_date"].dropna()]
    lo, hi = min(dates), max(dates)
    picked = sb.date_input("Dates", value=(lo, hi), min_value=lo, max_value=hi, key="f_dates", format="MM/DD/YYYY")
    d_from, d_to = (picked + (picked[0],))[:2] if isinstance(picked, tuple) and picked else (lo, hi)
    types = sb.multiselect("Game types", config.GAME_TYPES, key="f_types", placeholder="All game types")
    ha = sb.multiselect("Home / away", config.HOME_AWAY, key="f_ha", placeholder="Home, away and neutral")
    t_min = t_max = None
    if sb.checkbox("Filter by temperature", key="f_temp_on",
                   help="Games with no temperature entered are left out when this is on."):
        t_min, t_max = sb.slider("Temperature (°F)", 20, 110, (40, 90), key="f_temp")
    return ReportFilters(date_from=d_from.isoformat(), date_to=d_to.isoformat(), game_types=tuple(types),
                         home_away=tuple(ha), temp_min=t_min, temp_max=t_max)


# --- PDF export ---------------------------------------------------------------------------------

def pdf_controls(kind: str, report, df: pd.DataFrame, f: ReportFilters, roster_size: int) -> None:
    """Sidebar buttons: download this player's PDF, or save one PDF per player to exports/."""
    sb = st.sidebar
    sb.markdown("### PDF")
    note = filters_text(f)
    plural = "pitchers" if kind == "pitcher" else "hitters"
    if config.DEMO_MODE:
        _demo_pdf_controls(kind, report, df, f, note, plural, roster_size)
        return
    sb.download_button("Download this report", data=lambda: pdf_bytes(kind, report, note),
                       file_name=export_filename(kind, report.name, report.scope), mime="application/pdf",
                       icon=":material/picture_as_pdf:", type="primary", on_click="ignore")
    if sb.button(f"Save all {roster_size} {plural} to exports/", help="One PDF per player for the current "
                 "filters, saved in the exports folder. Re-exporting the same report overwrites it."):
        with st.spinner(f"Writing {roster_size} PDFs…"):
            paths = batch_export(df, kind, filters_note=note)
        sb.success(f"Saved {len(paths)} PDFs to {config.EXPORT_DIR}")


def _demo_pdf_controls(kind: str, report, df: pd.DataFrame, f: ReportFilters, note: str, plural: str,
                       roster_size: int) -> None:
    """Browser test version: build first, then download. stlite can't serve a download that is built
    when it's clicked, and there is no exports folder, so the whole team comes as one zip file."""
    sb = st.sidebar
    player_id = getattr(report, "pitcher_id", None) or getattr(report, "hitter_id", "")
    one_key = ("pdf", kind, player_id, dataclasses.astuple(f), db.data_version(get_conn()))
    all_key = ("zip", kind, dataclasses.astuple(f), db.data_version(get_conn()))
    made = st.session_state.setdefault("demo_pdfs", {})
    if one_key in made:
        sb.download_button("Save this report (PDF)", data=made[one_key], type="primary",
                           file_name=export_filename(kind, report.name, report.scope), mime="application/pdf",
                           icon=":material/picture_as_pdf:", on_click="ignore")
    elif sb.button("Make PDF of this report", type="primary", icon=":material/picture_as_pdf:"):
        with st.spinner("Making the PDF…"):
            made[one_key] = pdf_bytes(kind, report, note)
        st.rerun()
    if all_key in made:
        sb.download_button(f"Save all {roster_size} {plural} (.zip)", data=made[all_key],
                           file_name=f"gcsu_catalytics_{plural}.zip", mime="application/zip", on_click="ignore")
    elif sb.button(f"Make PDFs for all {roster_size} {plural}", help="One PDF per player for the current "
                   "filters, in one zip file. Takes about a second per player."):
        with st.spinner(f"Making {roster_size} PDFs…"):
            made[all_key] = batch_zip(df, kind, note)
        st.rerun()
