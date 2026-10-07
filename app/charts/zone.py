"""3x3 strike-zone charts (catcher's view) with the Section 4b small-sample rule: a cell below its
minimum n is grey, its value small, and "n=2" printed beneath it, with no heat color."""
from __future__ import annotations

import matplotlib
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

import config
from charts.base import (
    LABEL_SIZE, SMALL_SIZE, draw_plate_catcher_view, fit_scale, footnote, heat, new_figure, text_color_on,
    title,
)
from metrics.common import ZoneGrid


def zone_heatmap(grid: ZoneGrid, chart_title: str, scale: tuple[float, float], what: str,
                 width_in: float = 3.0, height_in: float = 3.3) -> Figure:
    """`what` names the events in the footnote, e.g. "at-bats" or "balls in play"."""
    fig, ax = new_figure(width_in, height_in)
    hw, lo, hi, g = config.ZONE_HALF_WIDTH_FT, config.ZONE_BOTTOM_FT, config.ZONE_TOP_FT, config.ZONE_GRID
    cw, ch = 2 * hw / g, (hi - lo) / g
    k = fit_scale(width_in, height_in)
    small, big = SMALL_SIZE * max(k, 0.8), (LABEL_SIZE + 2) * k
    for r in range(g):
        for c in range(g):
            s = grid.cells[r][c]
            x0, y0 = -hw + c * cw, hi - (r + 1) * ch
            if s.n == 0 or s.value is None:
                face = "white"
            elif s.low:
                face = config.LOW_SAMPLE_GREY
            else:
                face = heat(s.value, scale)
            ax.add_patch(Rectangle((x0, y0), cw, ch, facecolor=face, edgecolor=config.NAVY, lw=0.8))
            cx, cy = x0 + cw / 2, y0 + ch / 2
            if s.n == 0:
                ax.text(cx, cy, "n=0", ha="center", va="center", fontsize=small, color=config.LOW_SAMPLE_TEXT)
                continue
            ink = text_color_on(face)
            if s.low:
                ax.text(cx, cy + ch * 0.12, s.text(), ha="center", va="center", fontsize=small, color="#333333")
            else:
                ax.text(cx, cy + ch * 0.12, s.text(), ha="center", va="center", fontsize=big,
                        fontweight="bold", color=ink)
            ax.text(cx, cy - ch * 0.28, f"n={s.n}", ha="center", va="center", fontsize=small,
                    color="#333333" if s.low else ink)
    ax.add_patch(Rectangle((-hw, lo), 2 * hw, hi - lo, fill=False, edgecolor=config.NAVY, lw=1.6))
    draw_plate_catcher_view(ax, y_top=lo - 0.25)
    ax.set_xlim(-hw - 0.15, hw + 0.15)
    ax.set_ylim(lo - 0.65, hi + 0.1)
    ax.set_aspect("equal")
    ax.axis("off")
    title(ax, chart_title, "Catcher's view")

    sm = ScalarMappable(Normalize(*scale), matplotlib.colormaps[config.ZONE_CMAP])
    cb = fig.colorbar(sm, ax=ax, fraction=0.06, pad=0.03)
    cb.ax.tick_params(labelsize=SMALL_SIZE)
    if scale[1] < 1:
        cb.ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.3f}".lstrip("0")))
    footnote(fig, f"Grey = fewer than {_min_for(grid)} {what}.\n"
                  f"Not shown: {grid.n_outside} outside zone, {grid.n_untracked} no location.", ax=ax, y=-0.035)
    fig.subplots_adjust(left=0.02, right=0.9, top=0.88, bottom=0.12)
    return fig


def _min_for(grid: ZoneGrid) -> int:
    return grid.cells[0][0].min_n
