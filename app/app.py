"""GCSU Catalytics Streamlit app. Run with `streamlit run app.py`."""
import logging

import streamlit as st

import config
from ui import corrections_page, games_page, hitter_page, pitcher_page, team_page
from ui.common import inject_css, require_user

if config.SERVER_MODE:  # audit lines (ui.common.audit) go to stdout, which the container platform collects
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)
st.set_page_config(page_title=config.APP_TITLE, layout="wide",
                   page_icon=str(config.LOGO_PATH) if config.LOGO_PATH.exists() else "⚾")
if config.LOGO_WIDE_PATH.exists():
    st.logo(str(config.LOGO_WIDE_PATH), size="large",
            icon_image=str(config.LOGO_PATH) if config.LOGO_PATH.exists() else None)
inject_css()
require_user()
st.sidebar.markdown(f"## {config.APP_TITLE}")
if config.DEMO_MODE:
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
