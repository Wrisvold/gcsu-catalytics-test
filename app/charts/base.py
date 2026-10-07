"""Shared drawing helpers for every chart. Charts are plain matplotlib Figures (no pyplot state), so
the same figure renders in the app (`st.pyplot`) and in the PDF."""
from __future__ import annotations

import matplotlib
from matplotlib.colors import Normalize, to_rgb
from matplotlib.figure import Figure
from matplotlib.patches import Polygon, Rectangle

import config

DPI = 200
TITLE_SIZE = 9
LABEL_SIZE = 7
SMALL_SIZE = 6

matplotlib.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": LABEL_SIZE,
    "axes.edgecolor": "#9AA5B1",
    "axes.labelcolor": config.NAVY,
    "xtick.color": "#555555",
    "ytick.color": "#555555",
})


def new_figure(width_in: float, height_in: float) -> tuple[Figure, "matplotlib.axes.Axes"]:
    fig = Figure(figsize=(width_in, height_in), dpi=DPI)
    ax = fig.add_subplot()
    return fig, ax


def title(ax, text: str, sub: str | None = None) -> None:
    ax.set_title(text.upper(), fontsize=TITLE_SIZE, fontweight="bold", color=config.NAVY, loc="left", pad=10)
    if sub:
        ax.text(0, 1.005, sub, transform=ax.transAxes, fontsize=SMALL_SIZE, color="#555555", va="bottom")


def footnote(fig: Figure, text: str, ax=None, y: float = -0.02) -> None:
    """Note under the chart. Anchored to `ax` when given, so it can never sit on a colorbar or ticks."""
    if not text:
        return
    if ax is None:
        fig.text(0.5, 0.01, text, ha="center", va="bottom", fontsize=SMALL_SIZE, color="#555555", wrap=True)
    else:
        ax.text(0.5, y, text, transform=ax.transAxes, ha="center", va="top", fontsize=SMALL_SIZE,
                color="#555555", wrap=True)


def fit_scale(width_in: float, height_in: float, base_w: float = 3.0, base_h: float = 3.3) -> float:
    """How much smaller than its design size a chart is drawn (1.0 = design size, floor 0.6)."""
    return max(0.6, min(1.0, width_in / base_w, height_in / base_h))


def pitch_color(code: str) -> str:
    return config.PITCH_TYPES.get(code, config.PITCH_TYPES["OT"])["color"]


def pitch_label(code: str) -> str:
    return config.PITCH_TYPES.get(code, config.PITCH_TYPES["OT"])["label"]


def text_color_on(face) -> str:
    """Black or white text, whichever reads better on `face`."""
    r, g, b = to_rgb(face)
    return "black" if 0.299 * r + 0.587 * g + 0.114 * b > 0.55 else "white"


def heat(value: float, scale: tuple[float, float]):
    return matplotlib.colormaps[config.ZONE_CMAP](Normalize(*scale, clip=True)(value))


# --- Strike zone (catcher's view) ---------------------------------------------------------------

def draw_plate_catcher_view(ax, y_top: float = 0.45) -> None:
    """Home plate seen from behind the catcher: flat edge up, point toward the catcher (down)."""
    hw = 17 / 24
    ax.add_patch(Polygon([(-hw, y_top), (hw, y_top), (hw, y_top - 0.12), (0, y_top - 0.3), (-hw, y_top - 0.12)],
                         closed=True, facecolor="white", edgecolor=config.NAVY, lw=1))


def draw_zone(ax, grid_lines: bool = True) -> None:
    hw, lo, hi, g = config.ZONE_HALF_WIDTH_FT, config.ZONE_BOTTOM_FT, config.ZONE_TOP_FT, config.ZONE_GRID
    ax.add_patch(Rectangle((-hw, lo), 2 * hw, hi - lo, fill=False, edgecolor=config.NAVY, lw=1.4, zorder=3))
    if grid_lines:
        for i in range(1, g):
            x = -hw + i * 2 * hw / g
            y = lo + i * (hi - lo) / g
            ax.plot([x, x], [lo, hi], color=config.NAVY, lw=0.5, ls=":", zorder=3)
            ax.plot([-hw, hw], [y, y], color=config.NAVY, lw=0.5, ls=":", zorder=3)
    draw_plate_catcher_view(ax)


def location_axes(ax) -> None:
    """Fixed window, equal aspect, no ticks: every location chart lines up."""
    ax.set_xlim(*config.LOC_PLOT_X)
    ax.set_ylim(*config.LOC_PLOT_Y)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def clip_to_window(x, y):
    """Points outside the location window, and how many there are."""
    (x0, x1), (y0, y1) = config.LOC_PLOT_X, config.LOC_PLOT_Y
    inside = (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
    return inside, int((~inside).sum())


def empty_message(ax, text: str) -> None:
    ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center", fontsize=LABEL_SIZE,
            color="#555555", style="italic", zorder=10)
