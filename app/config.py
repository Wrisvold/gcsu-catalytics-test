"""Every threshold, cutoff, color and constant the app uses (rule 4).

Metric functions read from here; nothing below is hard-coded anywhere else.
Definitions for each metric live in METRICS.md. Open questions for the coaches live in ASSUMPTIONS.md.
"""
import os
from pathlib import Path

# --- App identity -------------------------------------------------------------------------------
APP_TITLE = "GCSU Catalytics"
APP_TITLE_CAPS = "GCSU CATALYTICS"
TEAM_CODE = "GEO_COL1"  # TrackMan team code for GCSU Baseball
FOOTER_VALUES = "SPORTSMANSHIP | SERVANT LEADERSHIP | PROFESSIONALISM | CHARACTER | LEGACY"
DATA_SOURCE_NOTE = "Data: TrackMan."

# --- Paths --------------------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
# GCSU_CATALYTICS_DB points the app at another database file (used for testing).
DB_PATH = Path(os.environ.get("GCSU_CATALYTICS_DB", DATA_DIR / "catalytics.db"))
EXPORT_DIR = ROOT / "exports"
# Browser test version (GitHub Pages, built by tools/build_pages.py): runs in the visitor's browser, keeps
# nothing after the tab closes, offers PDFs as downloads instead of saving to exports/, and has no
# weather lookup. On when a DEMO_MODE file sits next to this one or GCSU_CATALYTICS_DEMO=1.
DEMO_MODE = os.environ.get("GCSU_CATALYTICS_DEMO") == "1" or (ROOT / "DEMO_MODE").exists()
LOGO_PATH = ROOT / "assets" / "logo.png"

# --- Branding -----------------------------------------------------------------------------------
NAVY = "#0B2545"  # TODO: confirm official values with GCSU Athletics
GREEN = "#1B7A3E"  # TODO: confirm official values with GCSU Athletics
LIGHT_GREY = "#E6E8EB"
LOW_SAMPLE_GREY = "#BDBDBD"  # fill for cells below their minimum n (Section 4b)

# --- Strike zone (rule 10) ----------------------------------------------------------------------
# Plate half-width (8.5 in) plus one ball radius (~1.45 in) = 0.83 ft. Fixed height: the data has no
# batter-specific zone heights.
ZONE_HALF_WIDTH_FT = 0.83
ZONE_BOTTOM_FT = 1.5
ZONE_TOP_FT = 3.5
ZONE_GRID = 3  # 3x3 grid for zone charts

# Sign convention inferred in AUDIT.md section 3: positive PlateLocSide = third-base side (catcher's
# left). Catcher's-view charts therefore plot x = PLATE_SIDE_TO_CATCHER_X * PlateLocSide, which puts
# the first-base side on the right.
PLATE_SIDE_TO_CATCHER_X = -1.0
# ContactPositionZ uses the opposite sign (positive = first-base side).
CONTACT_Z_TO_CATCHER_X = 1.0

# --- Batted balls (rules 17, 18) ----------------------------------------------------------------
HARD_HIT_MPH = 95.0  # coaches' definition
# HitLaunchConfidence values excluded from exit velo, launch angle and Hard Hit %. Add "Estimated"
# here to drop those too (ASSUMPTIONS.md, A6).
EXCLUDED_LAUNCH_CONFIDENCE = ["Low"]
# Contact point: ContactPositionX is measured toward the pitcher. Assumed origin = back tip of the
# plate, so the front edge is at 17 in. "Out front" = X greater than this (ASSUMPTIONS.md, A7).
CONTACT_OUT_FRONT_FT = 17 / 12
# Spray chart: TrackMan's Distance on a ground ball is the first bounce, so ground balls are drawn on
# this fixed arc at their real bearing (ASSUMPTIONS.md, A4).
SPRAY_GROUND_BALL_ARC_FT = 120.0
SPRAY_FIELD_FT = {"lf": 330, "cf": 400, "rf": 330}  # drawing only; not used in any metric

# --- Minimum n to display a value normally (Section 4b) -----------------------------------------
# Below these, the value is shown greyed with its n. The key names are referenced in METRICS.md.
MIN_N = {
    "pitches": 10,          # Strike %, usage, Seen %, Swing %; also the pitch-type row asterisk
    "first_pitches": 10,    # First-Pitch Strike %
    "swings": 5,            # Whiff %
    "out_of_zone": 5,       # Chase %
    "pa": 10,               # K %, BB %, OBP, wOBA
    "ab": 10,               # AVG, BAA, SLG
    "babip": 5,             # BABIP denominator (AB - K - HR + SF)
    "pa_ended": 5,          # Out %
    "bip": 5,               # Avg/Max EV, Avg LA, Hard Hit %, GB %, FB %
    "zone_cell_ab": 3,      # zone-chart BAA / AVG cell
    "zone_cell_bip": 3,     # zone-chart average exit velo cell
    "chase_region": 5,      # chase % per region on the chase map
    "contact_group": 3,     # avg EV for out-front vs deep contact
}

# --- Pitch types (rules 7, 9) -------------------------------------------------------------------
# Display order, label and one fixed color per type. FF/SL/CH/CU/SI follow the GCSU mockup.
PITCH_TYPES = {
    "FF": {"label": "Four-Seam", "color": "#D62828"},
    "SI": {"label": "Sinker", "color": "#2A9D3F"},
    "FC": {"label": "Cutter", "color": "#E07B00"},
    "SL": {"label": "Slider", "color": "#F2C230"},
    "ST": {"label": "Sweeper", "color": "#E05D9C"},
    "CU": {"label": "Curveball", "color": "#6A2C91"},
    "CH": {"label": "Changeup", "color": "#2F6FD6"},
    "FS": {"label": "Splitter", "color": "#17A2B8"},
    "KN": {"label": "Knuckleball", "color": "#7A7A7A"},
    "OT": {"label": "Other", "color": "#5D4037"},
}
# AutoPitchType text -> code. Lookups are case- and space-insensitive; anything unknown maps to OT.
AUTO_PITCH_TYPE_MAP = {
    "four-seam": "FF", "fourseam": "FF", "fastball": "FF",
    "sinker": "SI", "two-seam": "SI", "twoseam": "SI",
    "cutter": "FC",
    "slider": "SL",
    "sweeper": "ST",
    "curveball": "CU", "knucklecurve": "CU",
    "changeup": "CH",
    "splitter": "FS",
    "knuckleball": "KN",
    "other": "OT",
}

# --- Batted-ball result colors (spray chart) ----------------------------------------------------
RESULT_COLORS = {
    "1B": "#2A9D3F", "2B": "#2F6FD6", "3B": "#6A2C91", "HR": "#D62828",
    "Out": "#8C8C8C", "ROE": "#E07B00", "FC": "#B08900", "SF": "#17A2B8", "SH": "#17A2B8",
    "Other": "#5D4037",
}

# --- Charts -------------------------------------------------------------------------------------
# Heat-scale bounds for the 3x3 zone charts. Values outside the bounds get the end color.
ZONE_AVG_SCALE = (0.100, 0.400)   # AVG / BAA cells
ZONE_EV_SCALE = (70.0, 100.0)     # average exit velo cells (mph)
ZONE_CMAP = "coolwarm"            # matplotlib colormap: cold = low, hot = high
# Plot window for location charts (catcher's view, ft). Pitches beyond it are counted in the footnote.
LOC_PLOT_X = (-2.0, 2.0)
LOC_PLOT_Y = (0.0, 5.0)
MOVEMENT_PLOT_IN = 25             # pitch-break chart spans +/- this many inches on both axes
# Swing-decision chart: one color per category.
DECISION_COLORS = {
    "Swing, in zone": "#1B7A3E",
    "Take, in zone": "#E07B00",
    "Chase": "#D62828",
    "Take, out of zone": "#9AA5B1",
}
LOW_SAMPLE_TEXT = "#7A7A7A"       # text color for values below their minimum n

# --- wOBA (P2) ----------------------------------------------------------------------------------
# MLB 2025 linear weights. Source: FanGraphs Guts!, wOBA & FIP constants,
# https://www.fangraphs.com/guts.aspx?type=cn (retrieved 2026-10-07). Labelled "wOBA (MLB weights)".
WOBA_SEASON = 2025
WOBA_WEIGHTS = {"BB": 0.691, "HBP": 0.722, "1B": 0.882, "2B": 1.252, "3B": 1.584, "HR": 2.037}

# --- Weather lookup (P5) ------------------------------------------------------------------------
# The only network call the app makes, and only when this is True. No API key is needed.
WEATHER_LOOKUP_ENABLED = False
# NWS requires a User-Agent naming the app and a contact it can reach if the app misbehaves.
NWS_USER_AGENT = "(gcsu-catalytics test version)"
NWS_BASE_URL = "https://api.weather.gov"
NWS_TIMEOUT_S = 10           # per request
NWS_WINDOW_MINUTES = 90      # accept observations within this many minutes of first pitch
NWS_MAX_STATIONS = 3         # nearest stations to try: KMLJ (5.6 mi), KMCN (36 mi), ... (ASSUMPTIONS.md A22)
FIELD_LAT = 33.0732  # TODO: confirm John Kurtz Field coordinates
FIELD_LON = -83.2363  # TODO: confirm John Kurtz Field coordinates
FIELD_TZ = "America/New_York"  # used only when a first-pitch time has no UTC offset

# --- Game context (P3) --------------------------------------------------------------------------
GAME_TYPES = ["Game", "Scrimmage", "Intrasquad", "Bullpen"]
HOME_AWAY = ["Home", "Away", "Neutral"]
