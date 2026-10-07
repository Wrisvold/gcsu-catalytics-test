"""GCSU Catalytics Streamlit app. Run with `streamlit run app.py`."""
import streamlit as st

import config
from ui import corrections_page, games_page, hitter_page, pitcher_page
from ui.common import inject_css

st.set_page_config(page_title=config.APP_TITLE, page_icon="⚾", layout="wide")
inject_css()
st.sidebar.markdown(f"## {config.APP_TITLE}")
if config.DEMO_MODE:
    st.info("**Test version.** This runs entirely in your browser: your TrackMan file is never uploaded, "
            "and everything you load is cleared when you close this tab.", icon=":material/science:")

page = st.navigation([
    st.Page(games_page.load_page, title="Load Data", url_path="load", default=True),
    st.Page(games_page.context_page, title="Game Context", url_path="games"),
    st.Page(pitcher_page.render, title="Pitcher Report", url_path="pitcher"),
    st.Page(hitter_page.render, title="Hitter Report", url_path="hitter"),
    st.Page(corrections_page.render, title="Pitch Type Corrections", url_path="corrections"),
])
page.run()
