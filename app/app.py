"""GCSU Catalytics Streamlit app. Run with `streamlit run app.py`."""
import logging

import streamlit as st

import config
from ui import corrections_page, games_page, hitter_page, pitcher_page, team_page
from ui.common import inject_css, require_user

if config.SERVER_MODE:  # audit lines (ui.common.audit) go to stdout, which the container platform collects
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)
logo, logo_wide = config.mark(config.LOGO_PATH), config.mark(config.LOGO_WIDE_PATH)
st.set_page_config(page_title=config.APP_TITLE, layout="wide", page_icon=str(logo) if logo else "⚾")
if logo_wide:
    st.logo(str(logo_wide), size="large", icon_image=str(logo) if logo else None)
inject_css()
require_user()
st.sidebar.markdown(f"## {config.APP_TITLE}")
if config.SAVES_IN_BROWSER:
    st.info("**Test version.** This runs entirely in your browser: your TrackMan files are never uploaded. "
            "What you load is kept in this browser on this computer, so it's here next time. It isn't shared "
            "with anyone else, and clearing the browser's site data deletes it: use **Back up or restore** on "
            "Load Data to keep a copy or move it to another computer.", icon=":material/science:")
elif config.DEMO_MODE:
    st.info("**Test version.** This runs entirely in your browser: your TrackMan file is never uploaded, "
            "and everything you load is cleared when you close this tab.", icon=":material/science:")

page = st.navigation([
    st.Page(games_page.load_page, title="Load Data", url_path="load", default=True),
    st.Page(games_page.context_page, title="Game Context", url_path="games"),
    st.Page(pitcher_page.render, title="Pitcher Report", url_path="pitcher"),
    st.Page(hitter_page.render, title="Hitter Report", url_path="hitter"),
    st.Page(team_page.render_pitchers, title="Team Pitchers", url_path="team-pitchers"),
    st.Page(team_page.render_hitters, title="Team Hitters", url_path="team-hitters"),
    st.Page(corrections_page.render, title="Pitch Type Corrections", url_path="corrections"),
])
page.run()
