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
# GCSU_CATALYTICS_DATA_DIR moves the database folder (the server's persistent volume, DEPLOY.md).
DATA_DIR = Path(os.environ.get("GCSU_CATALYTICS_DATA_DIR", ROOT / "data"))
# GCSU_CATALYTICS_DB points the app at another database file (used for testing).
DB_PATH = Path(os.environ.get("GCSU_CATALYTICS_DB", DATA_DIR / "catalytics.db"))
EXPORT_DIR = ROOT / "exports"
# Browser test version (GitHub Pages, built by tools/build_pages.py): runs in the visitor's browser, keeps
# nothing after the tab closes, offers PDFs as downloads instead of saving to exports/, and has no
# weather lookup. On when a DEMO_MODE file sits next to this one or GCSU_CATALYTICS_DEMO=1.
DEMO_MODE = os.environ.get("GCSU_CATALYTICS_DEMO") == "1" or (ROOT / "DEMO_MODE").exists()
LOGO_PATH = ROOT / "assets" / "logo.png"

# --- Server mode (GCSU's AWS; DEPLOY.md) ----------------------------------------------------------
# On with GCSU_CATALYTICS_SERVER=1. PDFs come as downloads (nothing is written to the server's disk but
# the database), and every page needs a signed-in user, passed in by the single-sign-on proxy in front of
# the app (the AWS load balancer's OIDC sign-in). The app has no passwords of its own.
SERVER_MODE = os.environ.get("GCSU_CATALYTICS_SERVER") == "1"
# Request header that carries the signed-in user. The AWS load balancer sends the user's claims as a JWT
# in x-amzn-oidc-data (the email is read from it); another proxy can name a plain header instead.
USER_HEADER = os.environ.get("GCSU_CATALYTICS_USER_HEADER", "x-amzn-oidc-data").lower()
# Refuse every page when no user header arrives. On by default in server mode; set to 0 only to test the
# container without the sign-in proxy.
REQUIRE_USER = SERVER_MODE and os.environ.get("GCSU_CATALYTICS_REQUIRE_USER", "1") != "0"
# Optional: only these signed-in users may use the app (comma-separated emails). Empty = anyone the
# sign-in proxy lets through (restrict it with an identity-provider group instead, DEPLOY.md).
ALLOWED_USERS = {u.strip().lower() for u in os.environ.get("GCSU_CATALYTICS_ALLOWED_USERS", "").split(",")
                 if u.strip()}

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
HARD_HIT_MPH = 92.5  # coaches' definition (ASSUMPTIONS.md A8, answered Oct 2026; MLB uses 95)
# HitLaunchConfidence values excluded from exit velo, launch angle and Hard Hit %. The coaches chose to
# keep every reading, Low included (A6, answered Oct 2026). Add "Low" or "Estimated" here to drop them.
EXCLUDED_LAUNCH_CONFIDENCE: list[str] = []
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
# One of the app's two network calls (the other: fetching a box-score link), made only when this is True.
# No API key is needed.
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
SCHEDULED_INNINGS = 9        # default for a game; a 7-inning game is set on the Game Context page

# --- Official play-by-play (METRICS.md section 4) -----------------------------------------------
# Fetched only when the operator pastes a box-score link and presses Fetch. Only that public page is
# requested; nothing is sent. A saved copy of the page can be uploaded instead (the only way in the
# browser test version).
PBP_USER_AGENT = "gcsu-catalytics (GCSU Baseball report app)"
PBP_TIMEOUT_S = 20

# --- Situations (Clutch Score, RISP) ------------------------------------------------------------
LATE_INNING = 7              # "7th inning or later"
LATE_MARGIN = 2              # "game is within 2 runs"

# --- Pitcher velo tiers (hitter report) ---------------------------------------------------------
# A pitcher's tier comes from his average fastball velo over the games in the report.
FASTBALL_TYPES = ["FF", "SI"]
VELO_TIERS = [  # (tier, lowest average fastball velo in the tier, label); checked top to bottom
    (1, 94.0, "94+ mph"),
    (2, 90.0, "90–93.9"),
    (3, 85.0, "85–89.9"),
    (4, 80.0, "80–84.9"),
    (5, 0.0, "79.9 or below"),
]

# --- Pitcher, Hitter and Clutch Scores (METRICS.md section 5) -----------------------------------
# From the coaches' scoring sheet (Oct 2026). Each game is scored separately; a report shows the
# average over its games. Each part earns its points in a straight line from `floor` (0 points) to
# `goal` (all its points); past the goal it stays at full points. For a "lower is better" stat the
# floor is above the goal. Floors were proposed by us and approved by the coaches (Oct 2026). A part
# with no data in a game (no balls in play, say) is left out and the others are scaled up to 100.
# Bonuses and penalties are then added, and the total is held between 1 and 100.
SCORE_RANGE = (1, 100)

PITCHER_SCORE_PARTS = [  # (key, label, points, floor, goal)
    ("strike_pct", "Strike %", 20, 45.0, 65.0),
    ("one_one_win_pct", "1-1 Count Win %", 15, 35.0, 65.0),
    ("first_pitch_strike_pct", "1st-Pitch Strike %", 15, 40.0, 65.0),
    ("whiff_pct", "Whiff %", 10, 5.0, 25.0),
    ("chase_pct", "Chase %", 10, 10.0, 25.0),
    ("k_minus_bb_pct", "K% − BB%", 15, -10.0, 20.0),
    ("runs_allowed", "Runs Allowed", 15, 5.0, 0.0),
]
PITCHER_SCORE_ADJUSTMENTS = {  # key: (label, points each)
    "bb_4_pitch": ("4-pitch walk", -5),
    "bb_5_pitch": ("5-pitch walk", -3),
    "hit_0_2": ("Hit on 0-2", -4),
    "bb_after_0_2": ("Walk after 0-2", -8),
    "hbp_0_2": ("HBP on 0-2", -6),
    "out_3_pitches": ("Out in 3 pitches or fewer", 1),  # coaches lowered from 2 (Oct 2026)
    "out_4_pitches": ("Out in 4 pitches", 1),
    "inning_12": ("Inning of 12 pitches or fewer", 4),
    "inning_15": ("Inning of 13–15 pitches", 2),
    "one_two_three": ("1-2-3 inning", 4),
}

PITCHER_BONUS_CAP = 15   # most the bonuses can add in one game (coaches, Oct 2026); penalties uncapped

HITTER_SCORE_PARTS = [
    ("hard_hit_pct", "Hard Hit %", 35, 10.0, 40.0),
    ("qab_pct", "QAB %", 30, 20.0, 60.0),
    ("chase_pct", "Chase %", 25, 40.0, 10.0),
    ("rbi", "RBIs", 10, 0.0, 4.0),
]
HITTER_SCORE_ADJUSTMENTS = {
    "k_looking": ("K looking", -4),
    "k_swinging": ("K swinging", -2),
    "k_looking_risp": ("K looking, RISP", -8),
    "k_swinging_risp": ("K swinging, RISP", -6),
    "hbp": ("HBP", 5),
    "hard_hit_0_2": ("Hard hit on 0-2", 3),
    "hard_hit_1_2": ("Hard hit on 1-2", 1),
    "bb_after_0_2": ("Walk after 0-2", 3),
}

CLUTCH_SCORE_PARTS = [
    ("hl_hard_hit_pct", "HL Hard Hit %", 25, 10.0, 40.0),
    ("hl_qab_pct", "HL QAB %", 25, 20.0, 60.0),
    ("hl_obp", "HL OBP", 20, 0.200, 0.500),
    ("hl_slg", "HL SLG", 15, 0.150, 0.600),
    ("risp_rbi", "RISP Production (RBI)", 15, 0.0, 2.0),
]
CLUTCH_SCORE_ADJUSTMENTS = {
    "hl_k": ("HL strikeout", -4),
    "hl_k_looking": ("HL strikeout looking", -8),
    "hl_dp": ("HL double play", -6),
    "walk_off_hit": ("Walk-off hit", 10),
    "go_ahead_rbi": ("Go-ahead RBI", 8),
    "tying_rbi": ("Game-tying RBI", 6),
    "two_out_rbi": ("Two-out RBI", 5),
}
