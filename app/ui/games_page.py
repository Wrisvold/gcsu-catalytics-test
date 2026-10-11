"""Load Data and Game Context pages (P3). Loading a CSV shows a context form for each GameID in it."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import db
import ingest
from metrics.common import prepare
from pbp.boxscore import BoxScore, BoxScoreError, parse_html
from pbp.match import GameMatch, match_game
from reports.context import fmt_date
from ui.common import game_label, get_conn, header

NOT_SET = "(not set)"


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


WEATHER_KEYS = ["temp", "humidity", "wind", "wind_dir"]


def _from_nws(g: pd.Series) -> bool:
    return str(g.get("weather_source") or "").startswith("NWS")


def _lookup_weather(conn, g: pd.Series, key: str) -> None:
    """Fetch NWS conditions into the game row, then reset the form's weather widgets to show them."""
    from weather import nws  # imported only when the lookup is on (rule 20)

    with st.spinner("Asking the National Weather Service…"):
        res = nws.prefill_game(conn, g["game_id"], overwrite=True)
    if res is None:
        st.session_state[f"{key}-nws-miss"] = True
        return
    for k in WEATHER_KEYS:
        st.session_state.pop(f"{key}-{k}", None)
    st.rerun()


def game_form(conn, g: pd.Series, key: str) -> None:
    """Edit one game's context. Date and stadium come from the CSV; everything else is the coach's.
    With the weather lookup on, weather fields can be pre-filled from NWS and are marked with the station."""
    st.markdown(f"**{fmt_date(g['game_date'])}** · {g['stadium'] or 'stadium not in file'} · "
                f"`{g['game_id']}`")
    nws_help = f"from {g['weather_source']}" if _from_nws(g) else None
    if nws_help:
        st.caption(f"Weather fields are from {g['weather_source']}. Edit them if they look wrong.")
    if config.WEATHER_LOOKUP_ENABLED:
        if st.button("Look up weather (National Weather Service)", key=f"{key}-nws",
                     help="Fills temperature, humidity and wind from the nearest NWS station at first pitch. "
                          "NWS keeps only about the last 7 days."):
            _lookup_weather(conn, g, key)
        if st.session_state.pop(f"{key}-nws-miss", False):
            st.warning("NWS has no observation near first pitch for this game (it keeps about 7 days). "
                       "Enter the weather by hand.")
    with st.form(f"game-{key}"):
        c1, c2, c3 = st.columns(3)
        types = [NOT_SET, *config.GAME_TYPES]
        game_type = c1.selectbox("Game type", types, key=f"{key}-type",
                                 index=types.index(g["game_type"]) if g["game_type"] in types else 0)
        opponent = c2.text_input("Opponent", key=f"{key}-opponent", value=g["opponent"] or "")
        ha_opts = [NOT_SET, *config.HOME_AWAY]
        home_away = c3.selectbox("Home / away", ha_opts, key=f"{key}-ha",
                                 index=ha_opts.index(g["home_away"]) if g["home_away"] in ha_opts else 0)
        weather = {
            "temp_f": c1.number_input("Temperature (°F)", key=f"{key}-temp", value=_num(g["temp_f"]),
                                      min_value=-20.0, max_value=130.0, step=1.0, placeholder="blank",
                                      help=nws_help),
            "humidity_pct": c2.number_input("Humidity (%)", key=f"{key}-humidity", value=_num(g["humidity_pct"]),
                                            min_value=0.0, max_value=100.0, step=1.0, placeholder="blank",
                                            help=nws_help),
            "wind_mph": c3.number_input("Wind speed (mph)", key=f"{key}-wind", value=_num(g["wind_mph"]),
                                        min_value=0.0, max_value=100.0, step=1.0, placeholder="blank",
                                        help=nws_help),
        }
        wind_dir = c1.text_input("Wind direction", key=f"{key}-wind_dir", value=g["wind_dir"] or "",
                                 placeholder="e.g. out to LF, or from 225°", help=nws_help)
        weather["wind_dir"] = wind_dir.strip() or None
        innings_opts = [9, 7]
        current = int(_num(g.get("innings")) or config.SCHEDULED_INNINGS)
        innings = c2.selectbox("Scheduled innings", innings_opts, key=f"{key}-innings",
                               index=innings_opts.index(current) if current in innings_opts else 0,
                               help="7 for a 7-inning game. Sets when a walk-off chance can start (Clutch Score).")
        notes = st.text_area("Notes", key=f"{key}-notes", value=g["notes"] or "", height=68)
        if st.form_submit_button("Save game details", type="primary"):
            fields = {
                "game_type": None if game_type == NOT_SET else game_type,
                "opponent": opponent.strip() or None,
                "home_away": None if home_away == NOT_SET else home_away,
                "notes": notes.strip() or None, "innings": innings, **weather,
            }
            source = g.get("weather_source")
            if source and not source.endswith(", edited") and any(
                    weather[k] != (_num(g[k]) if k != "wind_dir" else g[k]) for k in weather):
                fields["weather_source"] = f"{source}, edited"
            db.update_game(conn, g["game_id"], fields)
            st.toast("Game details saved.", icon=":material/check:")  # a toast survives the rerun
            st.rerun()


def _pbp_summary(conn, gid: str) -> tuple[GameMatch, BoxScore] | None:
    stored = db.get_play_by_play(conn, [gid]).get(gid)
    if not stored:
        return None
    box = BoxScore.from_json(stored["box_json"])
    df = prepare(db.query_pitches(conn, game_ids=[gid]), db.get_rules(conn), db.get_overrides(conn))
    return match_game(df, box), box


def _save_pbp(conn, gid: str, page: str, source: str) -> None:
    """Parse a box-score page, check it is this game, and store it. Errors go to the page as messages."""
    try:
        box = parse_html(page, source)
    except BoxScoreError as e:
        st.session_state[f"pbp-msg-{gid}"] = ("error", str(e))
        return
    df = prepare(db.query_pitches(conn, game_ids=[gid]), db.get_rules(conn), db.get_overrides(conn))
    m = match_game(df, box)
    if m.tm_pas and m.matched < 0.5 * m.tm_pas:
        st.session_state[f"pbp-msg-{gid}"] = (
            "error", f"This box score ({box.away} at {box.home}) matched only {m.matched} of TrackMan's {m.tm_pas} "
                     "plate appearances, so it looks like a different game. Not saved.")
        return
    db.set_play_by_play(conn, gid, box.to_json(), source)
    st.session_state[f"pbp-msg-{gid}"] = ("success", f"Play-by-play saved: {box.away} {box.away_runs} at "
                                                     f"{box.home} {box.home_runs}.")


def pbp_panel(conn, g: pd.Series, key: str) -> None:
    """Load, check and remove the game's official play-by-play."""
    gid = g["game_id"]
    st.markdown("**Official play-by-play** — runners on base, score, RBI and earned runs, which TrackMan "
                "doesn't record. Needed for the Clutch Score, RBIs and RISP in the Hitter Score, and official "
                "R / ER.")
    if msg := st.session_state.pop(f"pbp-msg-{gid}", None):
        getattr(st, msg[0])(msg[1])
    found = _pbp_summary(conn, gid)
    if found:
        m, box = found
        stored = db.get_play_by_play(conn, [gid])[gid]
        icon = ":material/check_circle:" if m.ok else ":material/warning:"
        st.markdown(f"{icon} {box.away} {box.away_runs} at {box.home} {box.home_runs} · matched **{m.matched} of "
                    f"{m.tm_pas}** TrackMan plate appearances ({m.official_pas} official) · from "
                    f"{stored['source']}")
        problems = [("Play-by-play checks", m.replay_warnings),
                    ("TrackMan and the official scoring disagree", m.disagreements),
                    ("TrackMan plate appearances with no official match", m.unmatched_tm),
                    ("Official plate appearances not in TrackMan", m.unmatched_official),
                    ("Official pitchers not found in TrackMan (their R / ER isn't used)", m.unmatched_pitchers)]
        for title, items in problems:
            if items:
                with st.expander(f"{title} ({len(items)})"):
                    st.markdown("\n".join(f"- {i}" for i in items))
        if st.button("Remove play-by-play", key=f"{key}-pbp-del"):
            db.delete_play_by_play(conn, gid)
            st.rerun()
    c1, c2 = st.columns(2)
    if not config.DEMO_MODE:
        url = c1.text_input("Box-score link", key=f"{key}-pbp-url",
                            placeholder="https://gcsubobcats.com/sports/baseball/stats/2026/…/boxscore/…",
                            help="The game's box score page on the home team's athletics site.")
        if c1.button("Fetch play-by-play", key=f"{key}-pbp-fetch", disabled=not url):
            from pbp.fetch import FetchError, fetch_page  # network only on this click

            try:
                with st.spinner("Downloading the box score…"):
                    page = fetch_page(url)
            except FetchError as e:
                st.session_state[f"pbp-msg-{gid}"] = ("error", str(e))
            else:
                _save_pbp(conn, gid, page, url.strip())
            st.rerun()
    up = c2.file_uploader("…or upload the saved box-score page", type=["html", "htm"], key=f"{key}-pbp-file",
                          help="In your browser, open the box score and save it (Ctrl+S, \"Webpage, HTML only\").")
    if up is not None and c2.button("Load uploaded page", key=f"{key}-pbp-load"):
        _save_pbp(conn, gid, up.getvalue().decode("utf-8", errors="replace"), up.name)
        st.rerun()


def _games_table(conn) -> pd.DataFrame:
    games = db.get_games(conn)
    counts = db.game_pitch_counts(conn)
    pbp = db.get_play_by_play(conn)
    return pd.DataFrame({
        "Date": games["game_date"].map(fmt_date), "Type": games["game_type"], "Opponent": games["opponent"],
        "H/A": games["home_away"], "Temp °F": games["temp_f"], "Humidity %": games["humidity_pct"],
        "Wind mph": games["wind_mph"], "Wind dir": games["wind_dir"], "Stadium": games["stadium"],
        "Weather from": games["weather_source"], "Pitches": games["game_id"].map(counts),
        "Play-by-play": games["game_id"].map(lambda gid: "yes" if gid in pbp else ""),
        "GameID": games["game_id"],
    })


def load_page() -> None:
    conn = get_conn()
    header("Load TrackMan Data")
    n = db.count_pitches(conn)
    games = db.get_games(conn)
    st.markdown(f"The database holds **{n} pitches** from **{len(games)} game(s)**. "
                "Everything stays on this computer.")

    files = st.file_uploader("TrackMan CSV export(s)", type=["csv"], accept_multiple_files=True,
                             help="Load the file straight from TrackMan. Loading a file twice adds nothing: "
                                  "pitches already stored (same PitchUID) are skipped.")
    if files and st.button("Load files", type="primary"):
        loaded, errors = [], []
        for up in files:
            try:
                res = ingest.load_csv(conn, up, up.name)
            except ingest.IngestError as e:
                errors.append(str(e))
                continue
            except Exception as e:  # unreadable file: say so, keep going with the others
                errors.append(f"{up.name}: could not read this file as a CSV ({e}).")
                continue
            loaded.append(res)
            if config.WEATHER_LOOKUP_ENABLED and res.new_game_ids:
                from weather import nws

                with st.spinner("Looking up game-time weather from the National Weather Service…"):
                    for gid in res.new_game_ids:
                        nws.prefill_game(conn, gid)
        st.session_state["last_load"] = [(r.summary(), r.game_ids, r.new_game_ids) for r in loaded]
        st.session_state["last_load_errors"] = errors
        st.rerun()  # redraw so the pitch and game counts above include this load

    for message in st.session_state.get("last_load_errors", []):
        st.error(message)
    for summary, game_ids, new_ids in st.session_state.get("last_load", []):
        st.success(summary)
        if game_ids:
            st.markdown(f"**Game details for this file** ({len(new_ids)} new game(s)). Fill in what the CSV "
                        "doesn't have; you can come back to this on the Game Context page.")
            all_games = db.get_games(conn).set_index("game_id", drop=False)
            for gid in game_ids:
                with st.expander(game_label(all_games.loc[gid]), expanded=gid in new_ids):
                    game_form(conn, all_games.loc[gid], f"load-{gid}")
                    pbp_panel(conn, all_games.loc[gid], f"load-{gid}")

    with st.expander("Load history"):
        st.dataframe(db.get_loads(conn).rename(columns={
            "source_file": "File", "loaded_at": "Loaded", "rows_in_file": "Rows", "added": "Added",
            "skipped_duplicate": "Skipped (duplicate)", "skipped_no_uid": "Skipped (no PitchUID)"}),
            hide_index=True)


def context_page() -> None:
    conn = get_conn()
    header("Game Context")
    games = db.get_games(conn)
    if games.empty:
        st.info("No games yet. Load a TrackMan CSV on the **Load Data** page.")
        return
    st.markdown("TrackMan files don't include game type, opponent, home/away, weather or the game situation "
                "(runners, score, RBI). Enter the details here and load the official play-by-play below; reports "
                "can then be filtered by game type, home/away and temperature.")
    st.dataframe(_games_table(conn), hide_index=True)
    g = games.sort_values(["game_date", "game_id"], ascending=False).set_index("game_id", drop=False)
    gid = st.selectbox("Edit game", g.index.tolist(), format_func=lambda x: game_label(g.loc[x]))
    game_form(conn, g.loc[gid], f"ctx-{gid}")
    st.divider()
    pbp_panel(conn, g.loc[gid], f"ctx-{gid}")
