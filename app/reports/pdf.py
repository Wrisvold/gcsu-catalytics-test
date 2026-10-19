"""One-page, letter-size PDF reports (P4), laid out like the GCSU mockup.

The PDF draws the same report objects (`reports.pitcher`, `reports.hitter`), the same table cells
(`reports.tables`) and the same matplotlib figures (`charts`) as the app, so the two always agree.

Command line, against the app's database:
    python -m reports.pdf pitchers [--from 2026-10-01] [--to 2026-10-31] [--game-type Intrasquad] [--player Smith]
    python -m reports.pdf hitters  [same options]
"""
from __future__ import annotations

import argparse
import io
import re
import zipfile
from datetime import date
from pathlib import Path

import matplotlib
import pandas as pd
from matplotlib.figure import Figure
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle

import config
from charts import hitting as ch
from charts import pitching as cp
from charts.zone import zone_heatmap
from metrics import hitting, pitching
from metrics.common import Stat
from reports import hitter as hitter_report
from reports import pitcher as pitcher_report
from reports import team as team_report
from reports.context import ReportFilters, Scope, fmt_date, pbp_note, thresholds_note
from reports.tables import (
    BREAKDOWN_COLS, HITTER_SPLIT_COLS, PITCH_TYPE_COLS, PITCHER_SPLIT_COLS, Col, build_table,
)

PAGE_W, PAGE_H = letter
MARGIN = 20
CONTENT_W = PAGE_W - 2 * MARGIN
GAP = 5
CHART_DPI = 220

NAVY, GREEN = HexColor(config.NAVY), HexColor(config.GREEN)
PALE_GREEN, PALE_TEXT = HexColor("#7FD39A"), HexColor("#C9D3DF")
LOW_BG, LOW_TEXT = HexColor("#ECECEC"), HexColor(config.LOW_SAMPLE_TEXT)
ZEBRA, RULE = HexColor("#F6F7F9"), HexColor(config.LIGHT_GREY)

# DejaVu ships with matplotlib: same typeface as the charts, and full Unicode (°, −, ÷, ●).
_TTF = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
FONT, BOLD = "DejaVuSans", "DejaVuSans-Bold"
if FONT not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(FONT, str(_TTF / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(BOLD, str(_TTF / "DejaVuSans-Bold.ttf")))

NOTE = ParagraphStyle("note", fontName=FONT, fontSize=5.8, leading=7, textColor=HexColor("#555555"))
CELL = ParagraphStyle("cell", fontName=FONT, fontSize=6.3, leading=7.2, alignment=1)
LABEL = ParagraphStyle("label", parent=CELL, fontName=BOLD, alignment=0)
HEAD = ParagraphStyle("head", parent=CELL, fontName=BOLD, textColor=white, fontSize=6)


# --- Drawing primitives -------------------------------------------------------------------------

def _header(c: Canvas, top: float, kind: str, name: str, season: str, dates: str, extra: str,
            grades: list | None = None) -> float:
    h = 70
    x, y = MARGIN, top - h
    c.setFillColor(NAVY)
    c.roundRect(x, y, CONTENT_W, h, 4, stroke=0, fill=1)
    cx, cy = x + 36, y + h / 2
    if config.LOGO_PATH.exists():
        c.drawImage(ImageReader(str(config.LOGO_PATH)), cx - 27, cy - 27, 54, 54, mask="auto",
                    preserveAspectRatio=True)
    else:
        c.setStrokeColor(GREEN)
        c.setLineWidth(2)
        c.circle(cx, cy, 26, stroke=1, fill=0)
        c.setFillColor(white)
        c.setFont(BOLD, 7.5)
        c.drawCentredString(cx, cy + 1.5, "GCSU")
        c.drawCentredString(cx, cy - 7.5, "BASEBALL")
    c.setStrokeColor(GREEN)
    c.setLineWidth(2.5)
    c.line(x + 72, y + 9, x + 72, y + h - 9)
    c.setFillColor(white)
    c.setFont(BOLD, 23)
    c.drawString(x + 82, y + h - 29, config.APP_TITLE_CAPS)
    c.setFillColor(PALE_GREEN)
    c.setFont(BOLD, 12.5)
    c.drawString(x + 82, y + h - 45, kind.upper())

    rx = x + CONTENT_W - 10
    c.setFillColor(white)
    c.setFont(BOLD, 13)
    c.drawRightString(rx, y + h - 19, name.upper())
    c.setFillColor(PALE_GREEN)
    c.setFont(BOLD, 9)
    c.drawRightString(rx, y + h - 30, season)
    c.setFillColor(PALE_TEXT)
    c.setFont(FONT, 6.8)
    c.drawRightString(rx, y + h - 40, dates)
    c.drawRightString(rx, y + h - 49, extra)
    # Score boxes, right to left: "PITCHER SCORE 84 1 game"
    bx = rx
    for s in reversed(grades or []):
        label, value, detail = s.name.upper(), s.text, s.detail
        w = (pdfmetrics.stringWidth(label, BOLD, 5.6) + pdfmetrics.stringWidth(value, BOLD, 11)
             + pdfmetrics.stringWidth(detail, FONT, 5.2) + 16)
        c.setStrokeColor(PALE_GREEN)
        c.setLineWidth(0.8)
        c.roundRect(bx - w, y + 4, w, 15, 2, stroke=1, fill=0)
        tx = bx - w + 4
        c.setFillColor(PALE_TEXT)
        c.setFont(BOLD, 5.6)
        c.drawString(tx, y + 9, label)
        tx += pdfmetrics.stringWidth(label, BOLD, 5.6) + 4
        c.setFillColor(white)
        c.setFont(BOLD, 11)
        c.drawString(tx, y + 7.5, value)
        tx += pdfmetrics.stringWidth(value, BOLD, 11) + 4
        c.setFillColor(PALE_TEXT)
        c.setFont(FONT, 5.2)
        c.drawString(tx, y + 9, detail)
        bx -= w + 4
    # The values line, unless the score boxes reach under it (it's in the footer band anyway).
    if x + 82 + pdfmetrics.stringWidth(config.FOOTER_VALUES, FONT, 5.6) < bx - 4:
        c.setFillColor(PALE_TEXT)
        c.setFont(FONT, 5.6)
        c.drawString(x + 82, y + h - 58, config.FOOTER_VALUES)
    return y


def _section(c: Canvas, top: float, num: int, title: str, note: str = "") -> float:
    h = 14
    y = top - h
    c.setFillColor(NAVY)
    c.roundRect(MARGIN, y, CONTENT_W, h, 2, stroke=0, fill=1)
    c.setFillColor(GREEN)
    c.rect(MARGIN, y, 22, h, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont(BOLD, 8)
    c.drawCentredString(MARGIN + 11, y + 4, f"{num:02d}")
    c.drawString(MARGIN + 29, y + 4, title.upper())
    if note:
        c.setFillColor(PALE_TEXT)
        c.setFont(FONT, 6)
        c.drawRightString(MARGIN + CONTENT_W - 6, y + 4.5, note)
    return y


def _tiles(c: Canvas, top: float, items: list[tuple[str, object]]) -> float:
    h = 36
    y = top - h
    c.setFillColor(NAVY)
    c.roundRect(MARGIN, y, CONTENT_W, h, 3, stroke=0, fill=1)
    w = CONTENT_W / len(items)
    for i, (label, v) in enumerate(items):
        cx = MARGIN + w * (i + 0.5)
        if i:
            c.setStrokeColor(GREEN)
            c.setLineWidth(0.6)
            c.line(MARGIN + w * i, y + 5, MARGIN + w * i, y + h - 5)
        c.setFillColor(PALE_TEXT)
        text = label.upper().replace("WOBA", "wOBA")
        size = 5.6
        while size > 4 and pdfmetrics.stringWidth(text, BOLD, size) > w - 4:
            size -= 0.2
        c.setFont(BOLD, size)
        c.drawCentredString(cx, y + h - 9, text)
        stat = isinstance(v, Stat)
        low = stat and v.low
        c.setFillColor(HexColor("#8A96A3") if low else white)
        c.setFont(BOLD, 10 if low else 13)
        c.drawCentredString(cx, y + 11.5, v.text() if stat else str(v))
        if stat:
            c.setFillColor(PALE_TEXT)
            c.setFont(FONT, 5.3)
            c.drawCentredString(cx, y + 4, f"n={v.n}")
    return y


def _height(flowable) -> float:
    return flowable.wrap(CONTENT_W, PAGE_H)[1]


def _draw(c: Canvas, top: float, flowable) -> float:
    h = _height(flowable)
    flowable.drawOn(c, MARGIN, top - h)
    return top - h


def _paragraph(c: Canvas, top: float, text: str, style: ParagraphStyle = NOTE) -> float:
    return _draw(c, top, Paragraph(text, style)) if text else top


def _pitch_label(code: str) -> str:
    if code == "All":
        return "All pitches"
    pt = config.PITCH_TYPES.get(code, config.PITCH_TYPES["OT"])
    return f'<font color="{pt["color"]}">●</font> {pt["label"]} ({code})'


def _table(df: pd.DataFrame, cols: list[Col], count_key: str | None = None, label_header: str = "Pitch Type",
           row_label=_pitch_label, label_w: float = 82) -> Table:
    spec = build_table(df, cols, count_key)
    pad = 1.6 if len(spec.rows) <= 5 else 0.6  # tall tables (many pitch types or splits) pack tighter
    head = [Paragraph(label_header, HEAD)] + [
        Paragraph(h + (f'<br/><font size="5" color="{config.LIGHT_GREY}">n={n}</font>' if n is not None else ""), HEAD)
        for h, n in spec.headers]
    data, style = [head], [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
    ]
    for r, (key, cells) in enumerate(spec.rows, start=1):
        total = key == "All"
        ink = "white" if total else config.NAVY
        row = [Paragraph(f'<font color="{ink}">{row_label(key)}</font>', LABEL)]
        for col, cell in enumerate(cells, start=1):
            color = ("#AAB4C0" if total else config.LOW_SAMPLE_TEXT) if cell.low else ink
            n_color = "#C9D3DF" if total else "#6B7785"
            size = 5.6 if cell.low else 6.3
            n = f'<br/><font size="4.8" color="{n_color}">n={cell.n}</font>' if cell.n is not None else ""
            row.append(Paragraph(f'<font color="{color}" size="{size}">{cell.text}</font>{n}', CELL))
            if cell.low:
                style.append(("BACKGROUND", (col, r), (col, r), HexColor("#3A4A60") if total else LOW_BG))
        if total:
            style.insert(0, ("BACKGROUND", (0, r), (-1, r), NAVY))
        elif r % 2 == 0:
            style.insert(0, ("BACKGROUND", (0, r), (-1, r), ZEBRA))
        data.append(row)
    widths = [label_w] + [(CONTENT_W - label_w) / len(cols)] * len(cols)
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle(style))
    return t


def _figure(c: Canvas, fig: Figure, x: float, top: float, w: float, h: float) -> None:
    """Draw a matplotlib figure scaled to fit the cell, centered, keeping its aspect."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=CHART_DPI, bbox_inches="tight", pad_inches=0.02, facecolor="white")
    buf.seek(0)
    img = ImageReader(buf)
    iw, ih = img.getSize()
    scale = min(w / iw, h / ih)
    dw, dh = iw * scale, ih * scale
    c.drawImage(img, x + (w - dw) / 2, top - dh, dw, dh)


def _chart_row(c: Canvas, top: float, h: float, makers: list) -> float:
    """Three charts side by side. Each maker takes (width_in, height_in) and returns a Figure."""
    w = (CONTENT_W - 2 * GAP) / 3
    for i, make in enumerate(makers):
        _figure(c, make(w / 72, h / 72), MARGIN + i * (w + GAP), top, w, h)
    return top - h


def _footer(c: Canvas, note: str) -> float:
    """Navy values band at the bottom, with the sample-size / source note above it. Returns its top."""
    h = 26
    c.setFillColor(NAVY)
    c.roundRect(MARGIN, MARGIN, CONTENT_W, h, 3, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont(BOLD, 11)
    c.drawCentredString(PAGE_W / 2, MARGIN + 13, "G C S U   B A S E B A L L")
    c.setFillColor(PALE_TEXT)
    c.setFont(FONT, 5.4)
    c.drawCentredString(PAGE_W / 2, MARGIN + 5, config.FOOTER_VALUES)
    p = Paragraph(note, NOTE)
    _, ph = p.wrap(CONTENT_W, 100)
    p.drawOn(c, MARGIN, MARGIN + h + 3)
    return MARGIN + h + 3 + ph + 3


def footer_note(scope: Scope, filters_note: str = "") -> str:
    """Date range, game types, minimum-n thresholds and "Data: TrackMan." for every PDF footer, and a
    note when any game's play-by-play is a coach sheet."""
    parts = [f"Dates: {scope.date_text}.", f"Game types: {scope.game_types_text}.", filters_note,
             pbp_note(scope), thresholds_note(), f"Printed {fmt_date(date.today().isoformat())}."]
    return " ".join(p for p in parts if p)


# --- Pages --------------------------------------------------------------------------------------

def _draw_pitcher(c: Canvas, r: pitcher_report.PitcherReport, filters_note: str,
                  title: str = "Individual Pitcher Report") -> float:
    bottom = _footer(c, footer_note(r.scope, filters_note))
    y = _header(c, PAGE_H - MARGIN, title, r.name, r.scope.season_text, r.scope.date_text,
                f"{r.throws_short} · {r.scope.games} game(s) · {r.scope.game_types_text}", r.grades) - GAP
    L = r.line
    y = _section(c, y, 1, "Game Summary", f"{L['pitches']} pitches") - 2
    y = _tiles(c, y, [("IP", L["IP"]), ("PA", L["PA"]), ("H", L["H"]), ("R", L["R"]),
                      ("ER", pitcher_report.er_text(L)),
                      ("BB", L["BB"]), ("K", L["K"]), ("HR", L["HR"]), ("Strike %", L["Strike %"]),
                      ("1st-Pitch Strike %", L["First-Pitch Strike %"])]) - 1.5
    corrected = (f" {r.n_corrected} pitch(es) re-typed by coach pitch-type corrections." if r.n_corrected else "")
    y = _paragraph(c, y, pitcher_report.runs_footnote(L) + " IP = strikeouts + outs on the play, including outs "
                         "on the bases. Pitcher Score: see the app for the game-by-game breakdown." + corrected) - GAP

    y = _section(c, y, 2, "Pitch Type Metrics", "averages by pitch type") - 2
    y = _draw(c, y, _table(r.table, PITCH_TYPE_COLS, count_key="Count")) - 1.5
    star = f"* fewer than {config.MIN_N['pitches']} pitches. " if any(s.low for s in r.table["Count"]) else ""
    y = _paragraph(c, y, f"{star}Velo, spin, movement and release averages use the pitches in Count unless an n "
                         "is shown. HB + = third-base side (arm side for a RHP). Out % = PAs ending on the pitch "
                         "with an out ÷ PAs ending on the pitch.") - GAP

    # Hitter splits sit at the bottom; measure them first so the charts get the rest.
    splits = _table(r.splits, PITCHER_SPLIT_COLS, label_header="Split", row_label=str, label_w=60)
    splits_note = Paragraph("Hitter side = the batter who finished each plate appearance. GB % and FB % use "
                            "TaggedHitType; FB % includes popups.", NOTE)
    splits_h = 14 + 2 + _height(splits) + 1.5 + _height(splits_note)
    room = max(180.0, y - bottom - splits_h - 2 * (14 + 2) - 3 * GAP)
    h1, h2 = room * 0.42, room * 0.58

    y = _section(c, y, 3, "Usage & Swing-and-Miss") - 2
    y = _chart_row(c, y, h1, [
        lambda w, h: cp.usage_chart(r.usage, w, h),
        lambda w, h: cp.rate_bars(r.table, "Whiff %", "Whiff % by pitch type",
                                  f"fewer than {config.MIN_N['swings']} swings", w, h),
        lambda w, h: cp.rate_bars(r.table, "Chase %", "Chase % by pitch type",
                                  f"fewer than {config.MIN_N['out_of_zone']} pitches outside the zone", w, h),
    ]) - GAP
    y = _section(c, y, 4, "Movement & Locations") - 2
    y = _chart_row(c, y, h2, [
        lambda w, h: cp.movement_chart(r.movement, width_in=w, height_in=h),
        lambda w, h: zone_heatmap(r.zone_baa, "Strike Zone BAA", config.ZONE_AVG_SCALE, "at-bats", w, h),
        lambda w, h: cp.whiff_locations_chart(r.whiffs, w, h),
    ]) - GAP
    y = _section(c, y, 5, "Hitter Splits") - 2
    y = _draw(c, y, splits) - 1.5
    return _draw(c, y, splits_note) - bottom


def _draw_hitter(c: Canvas, r: hitter_report.HitterReport, filters_note: str,
                 title: str = "Individual Hitter Report", who: str | None = None) -> float:
    bottom = _footer(c, footer_note(r.scope, filters_note))
    who = who or f"Bats {r.bats_short}"
    y = _header(c, PAGE_H - MARGIN, title, r.name, r.scope.season_text, r.scope.date_text,
                f"{who} · {r.scope.games} game(s) · {r.scope.game_types_text}", r.grades) - GAP
    k = r.key
    y = _section(c, y, 1, "Key Performance Metrics", hitter_report.key_note(k)) - 2
    y = _tiles(c, y, [("PA", k["PA"]), ("AVG", k["AVG"]), ("OBP", k["OBP"]), ("SLG", k["SLG"]), ("OPS", k["OPS"]),
                      ("wOBA (MLB wts)", k["wOBA"]), ("QAB %", k["QAB %"]), ("Hard Hit %", k["Hard Hit %"]),
                      ("Avg Exit Velo", k["Avg Exit Velo"]), ("Max Exit Velo", k["Max Exit Velo"]),
                      ("Avg Launch Angle", k["Avg Launch Angle"])]) - 1.5
    y = _paragraph(c, y, hitter_report.key_footnote(k) + " Hitter and Clutch Scores: see the app for the "
                         "game-by-game breakdown.") - GAP

    y = _section(c, y, 2, "Pitch Breakdown", "Seen % = % of pitches seen") - 2
    y = _draw(c, y, _table(r.breakdown, BREAKDOWN_COLS, count_key="Pitches")) - 1.5
    star = f"* fewer than {config.MIN_N['pitches']} pitches. " if any(s.low for s in r.breakdown["Pitches"]) else ""
    y = _paragraph(c, y, f"{star}Avg EV and Avg LA by pitch use balls in play off that pitch type.") - GAP

    splits = _table(r.splits, HITTER_SPLIT_COLS, label_header="Split", row_label=str, label_w=86)
    splits_note = Paragraph(hitter_report.SPLITS_NOTE, NOTE)
    splits_h = 14 + 2 + _height(splits) + 1.5 + _height(splits_note)
    room = max(150.0, y - bottom - splits_h - (14 + 2) - 3 * GAP)  # 150: only the busiest case gets this low
    h1 = h2 = room / 2

    y = _section(c, y, 3, "Contact & Decisions") - 2
    y = _chart_row(c, y, h1, [
        lambda w, h: ch.contact_chart(r.contact, w, h),
        lambda w, h: ch.spray_chart(r.spray, w, h),
        lambda w, h: ch.swing_decisions_chart(r.decisions, r.decision_counts, w, h),
    ]) - GAP
    y = _chart_row(c, y, h2, [
        lambda w, h: zone_heatmap(r.zone_ev, "Strike Zone Exit Velo", config.ZONE_EV_SCALE, "balls in play", w, h),
        lambda w, h: zone_heatmap(r.zone_avg, "Strike Zone AVG", config.ZONE_AVG_SCALE, "at-bats", w, h),
        lambda w, h: ch.chase_map_chart(r.chase, r.sides, w, h),
    ]) - GAP
    y = _section(c, y, 4, "Splits: Pitcher Hand & Velo Tier") - 2
    y = _draw(c, y, splits) - 1.5
    return _draw(c, y, splits_note) - bottom


# --- Team reports -------------------------------------------------------------------------------

ROSTER_CELL = ParagraphStyle("roster", parent=CELL, fontSize=6.6, leading=7.6)
ROSTER_NOTE = ("Each row is that player's numbers for the same games and filters. A player's score is his "
               "average over his games; the team score in the header is the average of every player's game "
               "scores. Grey = below the minimum sample.")


def _roster_table(roster: pd.DataFrame, label_w: float = 92) -> Table:
    shown = team_report.roster_text(roster)
    cols = list(shown.columns)
    data = [[Paragraph(h, HEAD) for h in cols]]
    low = team_report.roster_low(roster)
    data += [[Paragraph(v if j == 0 or not low.iat[i, j] else f'<font color="{config.LOW_SAMPLE_TEXT}">{v}</font>',
                        LABEL if j == 0 else ROSTER_CELL) for j, v in enumerate(row)]
             for i, row in enumerate(shown.itertuples(index=False))]
    style = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 1.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
             ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
             ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE)]
    style += [("BACKGROUND", (0, r), (-1, r), ZEBRA) for r in range(2, len(data), 2)]
    # Rates and scores get more room than small counts, so "100.0%" stays on one line.
    weight = [0.6 if h in ("T", "B", "G") else 1.45 if "%" in h else 1.0 for h in cols[1:]]
    unit = (CONTENT_W - label_w) / sum(weight)
    t = Table(data, colWidths=[label_w] + [w * unit for w in weight], repeatRows=1)
    t.setStyle(TableStyle(style))
    return t


def _draw_roster(c: Canvas, r, filters_note: str, title: str, extra: str, num: int, heading: str,
                 roster: pd.DataFrame, note: str) -> None:
    """The by-player table on as many pages as it needs, each with the report's header and footer."""
    rest = [_roster_table(roster)]
    while rest:
        bottom = _footer(c, footer_note(r.scope, filters_note))
        y = _header(c, PAGE_H - MARGIN, title, r.name, r.scope.season_text, r.scope.date_text, extra,
                    r.grades) - GAP
        y = _section(c, y, num, heading, f"{len(roster)} players") - 2
        para = Paragraph(note, NOTE)
        room = y - bottom - _height(para) - 4
        table = rest.pop()
        pieces = table.split(CONTENT_W, room) if _height(table) > room else [table]
        y = _draw(c, y, pieces[0]) - 2
        if len(pieces) > 1:
            rest.append(pieces[1])
            c.showPage()
        else:
            _draw(c, y, para)


def _draw_team_pitchers(c: Canvas, t: team_report.TeamPitcherReport, filters_note: str) -> float:
    r, title = t.report, "Team Pitcher Report"
    slack = _draw_pitcher(c, r, filters_note, title)
    c.showPage()
    _draw_roster(c, r, filters_note, title, f"{r.throws_short} · {r.scope.games} game(s) · {r.scope.game_types_text}",
                 6, "By Pitcher", t.roster, ROSTER_NOTE + " Best Pitcher Score first.")
    return slack


def _draw_team_hitters(c: Canvas, t: team_report.TeamHitterReport, filters_note: str) -> float:
    r, title = t.report, "Team Hitter Report"
    who = f"{t.n_players} hitter{'s' if t.n_players != 1 else ''}"
    slack = _draw_hitter(c, r, filters_note, title, who)
    c.showPage()
    _draw_roster(c, r, filters_note, title, f"{who} · {r.scope.games} game(s) · {r.scope.game_types_text}",
                 5, "By Hitter", t.roster, ROSTER_NOTE + " Best Hitter Score first.")
    return slack


def team_pdf_bytes(kind: str, t, filters_note: str = "") -> bytes:
    """The team report: the individual layout run on the whole team, then the by-player table."""
    buf = io.BytesIO()
    draw = _draw_team_pitchers if kind == "pitcher" else _draw_team_hitters
    _render([(draw, t)], f"{t.report.name}, team report", buf, filters_note)
    return buf.getvalue()


def team_pdf_filename(kind: str, t) -> str:
    """e.g. team_pitchers_GCSU_2026-10-23.pdf."""
    s = t.report.scope
    dates = s.first_date if s.first_date == s.last_date else f"{s.first_date}_to_{s.last_date}"
    who = re.sub(r"[^A-Za-z0-9]+", "_", team_report.team_label(t.team)).strip("_")
    return f"team_{'pitchers' if kind == 'pitcher' else 'hitters'}_{who}_{dates}.pdf"


def _render(pages: list, title: str, out, filters_note: str) -> list[float]:
    """Draw (draw, report) pages into one PDF. Returns the room left above each footer in points
    (negative = overlap)."""
    c = Canvas(out, pagesize=letter, pageCompression=1)
    c.setTitle(f"{config.APP_TITLE} — {title}")
    c.setAuthor(config.APP_TITLE)
    c.setCreator(config.APP_TITLE)
    slack = []
    for draw, report in pages:
        slack.append(draw(c, report, filters_note))
        c.showPage()
    c.save()
    return slack


def pitcher_pdf(r: pitcher_report.PitcherReport, out, filters_note: str = "") -> float:
    """Write one pitcher's one-page report to `out` (a path or a binary file object)."""
    return _render([(_draw_pitcher, r)], f"{r.name}, pitcher report", out, filters_note)[0]


def hitter_pdf(r: hitter_report.HitterReport, out, filters_note: str = "") -> float:
    """Write one hitter's one-page report to `out` (a path or a binary file object)."""
    return _render([(_draw_hitter, r)], f"{r.name}, hitter report", out, filters_note)[0]


def pdf_bytes(kind: str, report, filters_note: str = "") -> bytes:
    buf = io.BytesIO()
    (pitcher_pdf if kind == "pitcher" else hitter_pdf)(report, buf, filters_note)
    return buf.getvalue()


def export_filename(kind: str, name: str, scope: Scope) -> str:
    """e.g. pitcher_Pat_Smith_2026-10-03.pdf, or ..._2026-09-11_to_2026-09-25.pdf for a range."""
    who = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "player"
    dates = scope.first_date if scope.first_date == scope.last_date else f"{scope.first_date}_to_{scope.last_date}"
    return f"{kind}_{who}_{dates}.pdf"


def _kind(kind: str):
    """(roster, build, write, draw) for kind "pitcher" or "hitter"."""
    if kind == "pitcher":
        return pitching.list_pitchers, "PitcherId", "PitcherTeam", pitcher_report.build, pitcher_pdf, _draw_pitcher
    return hitting.list_hitters, "hitter_id", "BatterTeam", hitter_report.build, hitter_pdf, _draw_hitter


def roster_ids(df: pd.DataFrame, kind: str, gcsu_only: bool = False) -> list[str]:
    """Every pitcher or hitter in the filtered frame, by TrackMan name (Last, First). With `gcsu_only`,
    only players who pitched or batted for GCSU (config.TEAM_CODE), leaving out the other team."""
    list_fn, id_col, team_col, *_ = _kind(kind)
    if gcsu_only:
        df = df[df[team_col] == config.TEAM_CODE]
    return [str(i) for i in list_fn(df)[id_col]]


def has_other_teams(df: pd.DataFrame, kind: str) -> bool:
    """True when the frame has pitchers (or hitters) who aren't GCSU, i.e. an outside game."""
    team_col = _kind(kind)[2]
    return bool((df[team_col] != config.TEAM_CODE).any())


def batch_export(df: pd.DataFrame, kind: str, out_dir: Path | None = None, filters_note: str = "",
                 ids: list[str] | None = None) -> list[Path]:
    """One PDF per pitcher (kind="pitcher") or hitter (kind="hitter") in the filtered frame, or only
    the given ids. Files go to exports/ and are overwritten when the same report is exported again."""
    out_dir = Path(out_dir or config.EXPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    *_, build, write, _ = _kind(kind)
    ids = roster_ids(df, kind) if ids is None else ids
    paths = []
    for pid in ids:
        r = build(df, pid)
        if r is None:
            continue
        path = out_dir / export_filename(kind, r.name, r.scope)
        write(r, str(path), filters_note)
        paths.append(path)
    return paths


def batch_zip(df: pd.DataFrame, kind: str, filters_note: str = "") -> bytes:
    """The same one-PDF-per-player export as batch_export, returned as one zip file in memory."""
    *_, build, write, _ = _kind(kind)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for pid in roster_ids(df, kind):
            r = build(df, pid)
            if r is not None:
                pdf = io.BytesIO()
                write(r, pdf, filters_note)
                z.writestr(export_filename(kind, r.name, r.scope), pdf.getvalue())
    return buf.getvalue()


def batch_pdf(df: pd.DataFrame, kind: str, filters_note: str = "", gcsu_only: bool = True,
              ids: list[str] | None = None) -> bytes:
    """Every player's one-page report in a single PDF, one page each in name order, ready to print
    in one go. GCSU players only by default, so an outside game doesn't print the other team."""
    *_, build, _, draw = _kind(kind)
    ids = roster_ids(df, kind, gcsu_only) if ids is None else ids
    pages = [(draw, r) for r in (build(df, pid) for pid in ids) if r is not None]
    buf = io.BytesIO()
    plural = "pitchers" if kind == "pitcher" else "hitters"
    _render(pages, f"all {plural}", buf, filters_note)
    return buf.getvalue()


def batch_pdf_filename(kind: str, df: pd.DataFrame) -> str:
    """e.g. all_pitchers_2026-10-23.pdf, or all_hitters_2026-10-01_to_2026-10-31.pdf."""
    dates = sorted(d for d in df["game_date"].dropna().astype(str)) if "game_date" in df else []
    span = "" if not dates else f"_{dates[0]}" if dates[0] == dates[-1] else f"_{dates[0]}_to_{dates[-1]}"
    return f"all_{'pitchers' if kind == 'pitcher' else 'hitters'}{span}.pdf"


def main(argv: list[str] | None = None) -> None:
    import db
    from reports.context import load_frame

    ap = argparse.ArgumentParser(description="Export one-page GCSU Catalytics PDFs to exports/.")
    ap.add_argument("kind", choices=["pitchers", "hitters"])
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    ap.add_argument("--game-type", action="append", default=[], choices=config.GAME_TYPES)
    ap.add_argument("--player", help="only players whose TrackMan name contains this text")
    ap.add_argument("--out", type=Path, default=config.EXPORT_DIR)
    a = ap.parse_args(argv)
    df = load_frame(db.connect(), ReportFilters(a.date_from, a.date_to, game_types=tuple(a.game_type)))
    if df.empty:
        raise SystemExit("No pitches match those filters.")
    kind = a.kind[:-1]
    ids = None
    if a.player:
        roster = pitching.list_pitchers(df) if kind == "pitcher" else hitting.list_hitters(df)
        id_col, name_col = ("PitcherId", "Pitcher") if kind == "pitcher" else ("hitter_id", "hitter")
        ids = roster.loc[roster[name_col].str.contains(a.player, case=False, regex=False), id_col].tolist()
        if not ids:
            raise SystemExit(f"No {a.kind} match '{a.player}'.")
    paths = batch_export(df, kind, a.out, ids=ids)
    for p in paths:
        print(p)
    print(f"{len(paths)} PDF(s) written to {a.out}")


if __name__ == "__main__":
    main()
