"""Hitter-report charts (P2): spray chart, contact point, chase map, swing decisions."""
from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

import config
from charts.base import (
    LABEL_SIZE, SMALL_SIZE, clip_to_window, draw_zone, empty_message, footnote, heat, location_axes,
    new_figure, pitch_color, title,
)
from metrics.common import Stat
from metrics.hitting import SWING_DECISIONS, ChaseMap, ContactData, SprayData

RESULT_ORDER = ["1B", "2B", "3B", "HR", "ROE", "FC", "SF", "SH", "Out", "Other"]


# --- Spray chart --------------------------------------------------------------------------------

def _fence_radius(theta_rad: np.ndarray) -> np.ndarray:
    """Smooth fence for drawing only: SPRAY_FIELD_FT lf/rf at the foul poles, cf at 0°."""
    f = config.SPRAY_FIELD_FT
    side = np.where(theta_rad < 0, f["lf"], f["rf"])
    return side + (f["cf"] - side) * np.cos(2 * theta_rad)


def _draw_field(ax) -> None:
    th = np.radians(np.linspace(-45, 45, 91))
    r = _fence_radius(th)
    ax.fill(np.concatenate([[0], r * np.sin(th)]), np.concatenate([[0], r * np.cos(th)]),
            color="#EEF5EE", zorder=0)
    ax.plot(r * np.sin(th), r * np.cos(th), color=config.GREEN, lw=1.2)
    for sign in (-1, 1):
        end = _fence_radius(np.radians(45 * sign))
        ax.plot([0, sign * end * np.sin(np.radians(45))], [0, end * np.cos(np.radians(45))], color="#9AA5B1", lw=0.8)
    arc = config.SPRAY_GROUND_BALL_ARC_FT
    ax.plot(arc * np.sin(th), arc * np.cos(th), color="#9AA5B1", lw=0.6, ls=":")
    b = 90 / np.sqrt(2)
    ax.add_patch(Polygon([(0, 0), (b, b), (0, 2 * b), (-b, b)], closed=True, fill=False, edgecolor="#9AA5B1", lw=0.6))
    f = config.SPRAY_FIELD_FT
    for x, y, t in [(-f["lf"] * 0.707, f["lf"] * 0.707, str(f["lf"])), (0, f["cf"], str(f["cf"])),
                    (f["rf"] * 0.707, f["rf"] * 0.707, str(f["rf"]))]:
        ax.text(x * 0.86, y * 0.86, t, ha="center", va="center", fontsize=SMALL_SIZE, color="#555555")


def spray_chart(spray: SprayData, width_in: float = 3.0, height_in: float = 3.3) -> Figure:
    """Balls in play by Bearing and Distance, colored by result; ground balls (triangles) sit on the
    dotted infield arc at their real bearing. Left field is on the left."""
    fig, ax = new_figure(width_in, height_in)
    _draw_field(ax)
    pts = spray.points
    handles = []
    for res in [r for r in RESULT_ORDER if r in set(pts["result"])]:
        sub = pts[pts["result"] == res]
        color = config.RESULT_COLORS.get(res, config.RESULT_COLORS["Other"])
        for on_arc, marker in [(False, "o"), (True, "^")]:
            s = sub[sub["on_arc"] == on_arc]
            ax.scatter(s["x"], s["y"], s=24, marker=marker, color=color, edgecolor="white", lw=0.5, zorder=5)
        handles.append(Line2D([], [], marker="o", ls="", color=color, markersize=4, label=f"{res} ({len(sub)})"))
    if pts.empty:
        empty_message(ax, "No tracked balls in play")
    f = config.SPRAY_FIELD_FT
    reach = max([f["cf"], *(np.hypot(pts["x"], pts["y"]).tolist())]) + 30
    ax.set_xlim(-reach * 0.78, reach * 0.78)
    ax.set_ylim(-25, reach)
    ax.set_aspect("equal")
    ax.axis("off")
    title(ax, "Spray Chart", f"Balls in play: {spray.n_bip} · ▲ = ground ball, drawn on the infield arc")
    if handles:
        ax.legend(handles=handles, fontsize=SMALL_SIZE, loc="upper center", bbox_to_anchor=(0.5, 0.02),
                  ncol=min(5, len(handles)), frameon=False, handletextpad=0.1, columnspacing=0.6)
    if spray.n_missing:
        footnote(fig, f"{spray.n_missing} ball(s) in play not plotted: no Bearing or Distance")
    fig.subplots_adjust(left=0.02, right=0.98, top=0.88, bottom=0.12)
    return fig


# --- Contact point ------------------------------------------------------------------------------

def contact_chart(contact: ContactData, width_in: float = 3.0, height_in: float = 3.3) -> Figure:
    """Top-down view over home plate, pitcher at the top, lefties mirrored so inside / pull is on the
    left. Dots are colored by exit velo (grey = no trusted exit velo)."""
    fig, ax = new_figure(width_in, height_in)
    hw = 17 / 24
    ax.add_patch(Polygon([(0, 0), (hw, hw), (hw, 2 * hw), (-hw, 2 * hw), (-hw, hw)], closed=True,
                         facecolor="white", edgecolor=config.NAVY, lw=1))
    front = config.CONTACT_OUT_FRONT_FT
    ax.axhline(front, color=config.GREEN, lw=0.8, ls="--")
    ax.text(1.95, front + 0.04, "front of plate", ha="right", va="bottom", fontsize=SMALL_SIZE, color=config.GREEN)
    pts = contact.points
    for _, p in pts.iterrows():
        face = heat(p["ev"], config.ZONE_EV_SCALE) if pd.notna(p["ev"]) else config.LOW_SAMPLE_GREY
        ax.scatter(p["x"], p["y"], s=26, color=face, edgecolor=config.NAVY, lw=0.4, zorder=5)
    if pts.empty:
        empty_message(ax, "No contact data")
    ax.text(-1.95, 3.85, "Inside / pull", ha="left", va="top", fontsize=SMALL_SIZE, color="#555555")
    ax.text(1.95, 3.85, "Away / oppo", ha="right", va="top", fontsize=SMALL_SIZE, color="#555555")
    ax.text(0, 3.85, "▲ pitcher", ha="center", va="top", fontsize=SMALL_SIZE, color="#555555")
    for y, s, label in [(-0.3, contact.out_front_ev, "Out front"), (-0.62, contact.deep_ev, "Deep")]:
        ax.text(0, y, f"{label}: {_ev_text(s)}", ha="center", va="center", fontsize=LABEL_SIZE,
                color=config.LOW_SAMPLE_TEXT if s.low else config.NAVY,
                fontweight="normal" if s.low else "bold")
    ax.set_xlim(-2, 2)
    ax.set_ylim(-0.85, 3.9)
    ax.set_aspect("equal")
    ax.axis("off")
    title(ax, "Contact Point", f"Balls in play with contact data: {contact.n} · lefties mirrored")
    footnote(fig, "Avg exit velo of tracked balls; grey text = fewer than "
                  f"{config.MIN_N['contact_group']}. Dot color = exit velo.")
    fig.subplots_adjust(left=0.02, right=0.98, top=0.88, bottom=0.08)
    return fig


def _ev_text(s: Stat) -> str:
    return f"{s.text()} mph (n={s.n})" if s.value is not None else f"— (n={s.n})"


# --- Chase map ----------------------------------------------------------------------------------

REGION_LABELS = {"up": "Up", "down": "Down", "inside": "Inside", "away": "Away"}


def chase_map_chart(chase: ChaseMap, sides: list[str], width_in: float = 3.0, height_in: float = 3.3) -> Figure:
    """Every chase, catcher's view, colored by pitch type, with chase % for each region outside the
    zone. Inside / away labels sit on the hitter's side; for a switch hitter they go in the footnote."""
    fig, ax = new_figure(width_in, height_in)
    draw_zone(ax, grid_lines=False)
    inside, off = clip_to_window(chase.points["plot_x"], chase.points["plot_y"])
    pts = chase.points[inside]
    handles = []
    for code in [c for c in config.PITCH_TYPES if c in set(chase.points["pitch_type"])]:
        sub = pts[pts["pitch_type"] == code]
        ax.scatter(sub["plot_x"], sub["plot_y"], s=26, color=pitch_color(code), edgecolor="white", lw=0.5, zorder=5)
        handles.append(Line2D([], [], marker="o", ls="", color=pitch_color(code), markersize=4,
                              label=f"{code} ({int((chase.points['pitch_type'] == code).sum())})"))
    if chase.points.empty:
        empty_message(ax, "No chases")

    hw, lo, hi = config.ZONE_HALF_WIDTH_FT, config.ZONE_BOTTOM_FT, config.ZONE_TOP_FT
    pos = {"up": (0, hi + 0.55), "down": (0, lo - 0.55)}
    one_side = len(sides) == 1
    if one_side:
        # Catcher's view: a RHH stands on the left, so inside is the left side for him.
        inside_x = -(hw + 0.6) if sides[0] == "Right" else hw + 0.6
        pos["inside"] = (inside_x, (lo + hi) / 2)
        pos["away"] = (-inside_x, (lo + hi) / 2)
    for region, (x, y) in pos.items():
        s = chase.regions[region]
        ax.text(x, y, f"{REGION_LABELS[region]}\n{s.text()}\nn={s.n}", ha="center", va="center",
                fontsize=SMALL_SIZE, color=config.LOW_SAMPLE_TEXT if s.low else config.NAVY,
                fontweight="normal" if s.low else "bold",
                bbox=dict(boxstyle="round,pad=0.2", fc=config.LIGHT_GREY if s.low else "white", ec="none", alpha=0.85),
                zorder=6)
    location_axes(ax)
    total = len(chase.points)
    title(ax, "Chase Map", f"Catcher's view · chases: {total}")
    if handles:
        ax.legend(handles=handles, fontsize=SMALL_SIZE, loc="upper center", bbox_to_anchor=(0.5, 0.0),
                  ncol=min(4, len(handles)), frameon=False, handletextpad=0.1, columnspacing=0.6)
    notes = []
    if not one_side:
        notes.append(" · ".join(f"{REGION_LABELS[r]} {chase.regions[r].text()} (n={chase.regions[r].n})"
                                for r in ("inside", "away")))
    if off:
        notes.append(f"{off} off the chart")
    notes.append(f"Chase % = chases ÷ pitches in the region; grey = fewer than {config.MIN_N['chase_region']}")
    footnote(fig, " · ".join(notes))
    fig.subplots_adjust(left=0.02, right=0.98, top=0.88, bottom=0.12)
    return fig


# --- Swing decisions ----------------------------------------------------------------------------

DECISION_MARKERS = {"Swing, in zone": "o", "Take, in zone": "o", "Chase": "X", "Take, out of zone": "o"}


def swing_decisions_chart(points: pd.DataFrame, counts: dict[str, int], width_in: float = 3.0,
                          height_in: float = 3.3) -> Figure:
    """Every pitch with a location, catcher's view: swing or take, in or out of the zone."""
    fig, ax = new_figure(width_in, height_in)
    draw_zone(ax, grid_lines=False)
    inside, off = clip_to_window(points["plot_x"], points["plot_y"])
    pts = points[inside]
    handles = []
    for d in SWING_DECISIONS:
        sub = pts[pts["decision"] == d]
        color = config.DECISION_COLORS[d]
        filled = d.startswith("Swing") or d == "Chase"
        ax.scatter(sub["plot_x"], sub["plot_y"], s=20, marker=DECISION_MARKERS[d],
                   facecolors=color if filled else "none", edgecolors=color, lw=0.9, zorder=5)
        handles.append(Line2D([], [], marker=DECISION_MARKERS[d], ls="", markersize=4,
                              markerfacecolor=color if filled else "none", markeredgecolor=color,
                              label=f"{d} ({counts.get(d, 0)})"))
    if points.empty:
        empty_message(ax, "No tracked pitches")
    location_axes(ax)
    off_note = f" · {off} off chart" if off else ""
    title(ax, "Swing Decisions", f"Catcher's view · pitches: {len(points)}{off_note} · filled = swing")
    ax.legend(handles=handles, fontsize=SMALL_SIZE, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=2,
              frameon=False, handletextpad=0.1, columnspacing=0.6)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.88, bottom=0.16)
    return fig
