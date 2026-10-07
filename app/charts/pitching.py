"""Pitcher-report charts (P1): usage, pitch movement, whiff/chase bars, whiff locations."""
from __future__ import annotations

import pandas as pd
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

import config
from charts.base import (
    LABEL_SIZE, SMALL_SIZE, clip_to_window, draw_zone, empty_message, fit_scale, location_axes,
    new_figure, pitch_color, title,
)


def usage_chart(usage: pd.DataFrame, width_in: float = 3.6, height_in: float = 2.0) -> Figure:
    """100% stacked bars of usage %, one bar each for All, vs LHH and vs RHH. A split with fewer than
    MIN_N['pitches'] pitches is drawn faded and marked with an asterisk."""
    fig, ax = new_figure(width_in, height_in)
    splits = list(usage.columns)
    labels = []
    for i, split in enumerate(splits):
        y = len(splits) - 1 - i
        left = 0.0
        stats = usage[split]
        n = next((s.n for s in stats), 0)
        low = n < config.MIN_N["pitches"]
        for code, s in stats.items():
            w = s.value or 0.0
            if w <= 0:
                continue
            ax.barh(y, w, left=left, color=pitch_color(code), alpha=0.45 if low else 1.0,
                    edgecolor="white", lw=0.6, height=0.7)
            if w >= 9:
                ax.text(left + w / 2, y, f"{code}\n{w:.0f}%", ha="center", va="center", fontsize=SMALL_SIZE,
                        color="white", fontweight="bold")
            left += w
        if n == 0:
            ax.text(50, y, "no pitches", ha="center", va="center", fontsize=SMALL_SIZE, color="#555555")
        labels.append((y, f"{split}{'*' if low and n else ''}\nn={n}"))
    ax.set_yticks([y for y, _ in labels], [t for _, t in labels], fontsize=SMALL_SIZE)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100%"], fontsize=SMALL_SIZE)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    title(ax, "Pitch Usage", "Overall and by hitter side")
    if any(next((s.n for s in usage[c]), 0) < config.MIN_N["pitches"] for c in splits):
        ax.set_xlabel(f"* fewer than {config.MIN_N['pitches']} pitches (faded)", fontsize=SMALL_SIZE, color="#555555")
    fig.subplots_adjust(left=0.2, right=0.97, top=0.82, bottom=0.2)
    return fig


def movement_chart(points: pd.DataFrame, color_by: str = "pitch_type", chart_title: str = "Pitch Movement",
                   width_in: float = 3.2, height_in: float = 3.3) -> Figure:
    """IVB vs HB, one dot per pitch colored by type, with a large ringed dot at each type's average.
    HB is plotted as TrackMan reports it (+ = third-base side), which is the pitcher's view."""
    fig, ax = new_figure(width_in, height_in)
    lim = config.MOVEMENT_PLOT_IN
    ax.axhline(0, color="#9AA5B1", lw=0.6)
    ax.axvline(0, color="#9AA5B1", lw=0.6)
    handles = []
    for code in [c for c in config.PITCH_TYPES if c in set(points[color_by])]:
        sub = points[points[color_by] == code]
        col = pitch_color(code)
        ax.scatter(sub["HorzBreak"].clip(-lim, lim), sub["InducedVertBreak"].clip(-lim, lim), s=9,
                   color=col, alpha=0.65, lw=0)
        ax.scatter(sub["HorzBreak"].mean(), sub["InducedVertBreak"].mean(), s=55, color=col,
                   edgecolor="black", lw=0.8, zorder=4)
        handles.append(Line2D([], [], marker="o", ls="", color=col, markersize=5, label=f"{code} ({len(sub)})"))
    if points.empty:
        empty_message(ax, "No pitches with movement data")
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.grid(color="#E6E8EB", lw=0.5)
    ax.set_xlabel("Horizontal break (in)  ·  + = 3B side", fontsize=SMALL_SIZE)
    ax.set_ylabel("Induced vertical break (in)", fontsize=SMALL_SIZE)
    ax.tick_params(labelsize=SMALL_SIZE)
    title(ax, chart_title, "Pitcher's view · ringed dot = average · (n pitches)")
    if handles:
        ax.legend(handles=handles, fontsize=SMALL_SIZE, loc="upper left", bbox_to_anchor=(1.01, 1),
                  frameon=False, handletextpad=0.2)
    fig.subplots_adjust(left=0.15, right=0.78, top=0.88, bottom=0.13)
    return fig


def rate_bars(table: pd.DataFrame, column: str, chart_title: str, min_note: str,
              width_in: float = 3.4, height_in: float = 2.2) -> Figure:
    """One bar per pitch type for a rate column of the pitch-type table, value and n on each bar. Bars
    below their minimum n are grey. The "All" row is the dashed reference line, labelled in the subtitle."""
    fig, ax = new_figure(width_in, height_in)
    rows = table.drop(index="All", errors="ignore")
    codes = list(rows.index)
    label_size = SMALL_SIZE * max(0.65, min(1.0, 6 / max(len(codes), 1), fit_scale(width_in, height_in, 3.4, 2.2)))
    for i, code in enumerate(codes):
        s = rows.loc[code, column]
        v = s.value
        color = config.LOW_SAMPLE_GREY if (s.low or v is None) else pitch_color(code)
        ax.bar(i, v or 0, color=color, width=0.65, edgecolor="white", zorder=2)
        label = f"{s.text()}\nn={s.n}"
        ax.text(i, (v or 0) + 2, label, ha="center", va="bottom", fontsize=label_size, zorder=4,
                color=config.LOW_SAMPLE_TEXT if s.low else config.NAVY,
                bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none"))
    sub = None
    if "All" in table.index:
        a = table.loc["All", column]
        if a.value is not None:
            ax.axhline(a.value, color=config.NAVY, lw=0.8, ls="--", zorder=3)
        sub = f"Dashed line = all pitches: {a.text()} (n={a.n})"
    if not codes:
        empty_message(ax, "No pitches")
    ax.set_xticks(range(len(codes)), codes, fontsize=LABEL_SIZE if len(codes) <= 6 else SMALL_SIZE)
    top = max([rows.loc[c, column].value or 0 for c in codes] + [10])
    ax.set_ylim(0, top + 28)
    ax.set_yticks([t for t in (0, 25, 50, 75, 100) if t <= top + 5])
    ax.tick_params(axis="y", labelsize=SMALL_SIZE)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    title(ax, chart_title, sub)
    ax.set_xlabel(f"Grey = {min_note}", fontsize=SMALL_SIZE, color="#555555")
    fig.subplots_adjust(left=0.1, right=0.97, top=0.85, bottom=0.2)
    return fig


def whiff_locations_chart(whiffs: pd.DataFrame, width_in: float = 3.0, height_in: float = 3.3) -> Figure:
    """Every whiff with a tracked location, catcher's view, colored by pitch type."""
    fig, ax = new_figure(width_in, height_in)
    draw_zone(ax)
    inside, off = clip_to_window(whiffs["plot_x"], whiffs["plot_y"])
    pts = whiffs[inside]
    handles = []
    for code in [c for c in config.PITCH_TYPES if c in set(whiffs["pitch_type"])]:
        sub = pts[pts["pitch_type"] == code]
        ax.scatter(sub["plot_x"], sub["plot_y"], s=26, color=pitch_color(code), edgecolor="white", lw=0.5, zorder=5)
        handles.append(Line2D([], [], marker="o", ls="", color=pitch_color(code), markersize=4,
                              label=f"{code} ({int((whiffs['pitch_type'] == code).sum())})"))
    if whiffs.empty:
        empty_message(ax, "No whiffs")
    location_axes(ax)
    off_note = f" · {off} off chart" if off else ""
    title(ax, "Whiff Locations", f"Catcher's view · whiffs: {len(whiffs)}{off_note}")
    if handles:
        ax.legend(handles=handles, fontsize=SMALL_SIZE, loc="upper center", bbox_to_anchor=(0.5, 0.0),
                  ncol=min(4, len(handles)), frameon=False, handletextpad=0.1, columnspacing=0.6)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.9, bottom=0.12)
    return fig
