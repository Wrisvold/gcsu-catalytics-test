"""Pitch Type Corrections page (rule 8). Corrections are stored in SQLite and applied at query time to
every report; the raw pitch rows are never changed."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import db
from charts.pitching import movement_chart
from metrics import pitching
from reports.context import ReportFilters, display_name, fmt_date
from ui.common import frame, get_conn, header

CODES = list(config.PITCH_TYPES)


def code_label(code: str) -> str:
    return f"{config.PITCH_TYPES.get(code, config.PITCH_TYPES['OT'])['label']} ({code})"


def _summary(p: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for code in [c for c in CODES if c in set(p["auto_type"])]:
        sub = p[p["auto_type"] == code]
        now = sub["pitch_type"].value_counts()
        rows.append({
            "TrackMan type": code_label(code), "Pitches": len(sub),
            "Velo (avg)": round(sub["RelSpeed"].mean(), 1), "Velo (range)":
                f"{sub['RelSpeed'].min():.1f}–{sub['RelSpeed'].max():.1f}" if sub["RelSpeed"].notna().any() else "—",
            "Spin": round(sub["SpinRate"].mean()) if sub["SpinRate"].notna().any() else None,
            "IVB": round(sub["InducedVertBreak"].mean(), 1), "HB": round(sub["HorzBreak"].mean(), 1),
            "Now reported as": ", ".join(f"{c} {n}" for c, n in now.items()),
        })
    return pd.DataFrame(rows)


def _rule_text(r: dict) -> str:
    rng = ""
    if r["min_velo"] is not None and r["max_velo"] is not None:
        rng = f" at {r['min_velo']:g}–{r['max_velo']:g} mph"
    elif r["min_velo"] is not None:
        rng = f" at {r['min_velo']:g} mph or faster"
    elif r["max_velo"] is not None:
        rng = f" at {r['max_velo']:g} mph or slower"
    note = f" — {r['note']}" if r["note"] else ""
    return f"{display_name(r['pitcher_name'] or r['pitcher_id'])}: {code_label(r['auto_type'])}{rng} → " \
           f"{code_label(r['corrected_type'])}{note}"


def render() -> None:
    conn = get_conn()
    header("Pitch Type Corrections")
    df = frame(ReportFilters())
    if df.empty:
        st.info("No data yet. Load a TrackMan CSV on the **Load Data** page.")
        return
    st.markdown("Reports use TrackMan's automatic pitch type (`AutoPitchType`). When it's wrong for a pitcher, "
                "map it to the right type here. A correction applies to **every report, every date** that "
                "pitcher appears in. The raw TrackMan data is never changed, and deleting a correction "
                "undoes it.")
    roster = pitching.list_pitchers(df)
    labels = {r.PitcherId: f"{r.Pitcher} ({r.PitcherThrows[:1]}HP) · {r.pitches} pitches" for r in roster.itertuples()}
    pid = st.selectbox("Pitcher", list(labels), format_func=labels.get, key="corr_pitcher")
    p = pitching.for_pitcher(df, pid)
    name = p["Pitcher"].iloc[-1]

    pts = pitching.movement_points(p)
    c1, c2 = st.columns(2)
    c1.pyplot(movement_chart(pts, color_by="auto_type", chart_title="TrackMan auto type"))
    c2.pyplot(movement_chart(pts, color_by="pitch_type", chart_title="After corrections"))
    st.dataframe(_summary(p), hide_index=True)

    st.markdown("#### Add a correction")
    present = [c for c in CODES if c in set(p["auto_type"])]
    with st.form("add_rule", clear_on_submit=True):
        c1, c2 = st.columns(2)
        auto = c1.selectbox("TrackMan calls it", present, format_func=code_label)
        corrected = c2.selectbox("It should be", CODES, format_func=code_label)
        c1, c2, c3 = st.columns(3)
        min_v = c1.number_input("Only at this speed or faster (mph)", value=None, min_value=40.0,
                                max_value=105.0, step=0.5, placeholder="any speed")
        max_v = c2.number_input("Only at this speed or slower (mph)", value=None, min_value=40.0,
                                max_value=105.0, step=0.5, placeholder="any speed")
        note = c3.text_input("Note (optional)", placeholder="e.g. confirmed with pitching coach")
        if st.form_submit_button("Save correction", type="primary"):
            if auto == corrected:
                st.error("The corrected type is the same as TrackMan's type.")
            elif min_v is not None and max_v is not None and min_v > max_v:
                st.error("The minimum speed is above the maximum speed.")
            else:
                db.add_rule(conn, pid, name, auto, corrected, min_v, max_v, note.strip() or None)
                st.rerun()

    rules = db.get_rules(conn)
    mine = [r for r in rules if r["pitcher_id"] == str(pid)]
    st.markdown("#### This pitcher's corrections")
    if not mine:
        st.caption("None yet.")
    for r in mine:
        c1, c2 = st.columns([6, 1])
        c1.markdown(_rule_text(r))
        if c2.button("Delete", key=f"del-rule-{r['id']}"):
            db.delete_rule(conn, r["id"])
            st.rerun()

    with st.expander("Correct individual pitches"):
        st.caption("For a one-off mislabel. A single-pitch correction overrides any rule above.")
        overrides = db.get_overrides(conn)
        table = pd.DataFrame({
            "PitchUID": p["PitchUID"], "Date": p["game_date"].map(fmt_date), "Inning": p["Inning"],
            "Pitch #": p["PitchNo"], "Velo": p["RelSpeed"].round(1), "Spin": p["SpinRate"].round(0),
            "IVB": p["InducedVertBreak"].round(1), "HB": p["HorzBreak"].round(1), "TrackMan": p["auto_type"],
            "Now": p["pitch_type"], "Single-pitch override": p["PitchUID"].map(overrides).fillna(""),
        })
        if config.DEMO_MODE:  # stlite's Streamlit can't run st.data_editor; pick one pitch at a time
            _single_pitch_picker(conn, table, overrides, pid)
            _all_rules(rules)
            return
        edited = st.data_editor(
            table, hide_index=True, key=f"ov-{pid}", disabled=[c for c in table.columns if c != "Single-pitch override"],
            column_config={"PitchUID": None, "Single-pitch override": st.column_config.SelectboxColumn(
                options=["", *CODES], help="Blank = no override")})
        if st.button("Save single-pitch changes"):
            for uid, new in zip(edited["PitchUID"], edited["Single-pitch override"]):
                old = overrides.get(uid, "")
                new = new or ""
                if new != old:
                    if new:
                        db.set_override(conn, uid, new)
                    else:
                        db.delete_override(conn, uid)
            st.rerun()

    _all_rules(rules)


def _all_rules(rules: list[dict]) -> None:
    if rules:
        with st.expander(f"All corrections ({len(rules)})"):
            for r in rules:
                st.markdown(f"- {_rule_text(r)}")


def _single_pitch_picker(conn, table: pd.DataFrame, overrides: dict[str, str], pid: str) -> None:
    """One pitch at a time: pick it from a list, pick the type, save or remove."""
    st.dataframe(table.drop(columns=["PitchUID"]), hide_index=True)
    labels = {r["PitchUID"]: f"{r['Date']} · inning {r['Inning']} · pitch #{r['Pitch #']} · {r['Velo']} mph · "
                             f"TrackMan {r['TrackMan']} · now {r['Now']}" for r in table.to_dict("records")}
    c1, c2 = st.columns([3, 2])
    uid = c1.selectbox("Pitch", list(labels), format_func=labels.get, key=f"ov-pick-{pid}")
    current = overrides.get(uid, "")
    new = c2.selectbox("Should be", ["", *CODES], index=(["", *CODES].index(current) if current in CODES else 0),
                       format_func=lambda c: code_label(c) if c else "(no override)", key=f"ov-type-{pid}-{uid}")
    if st.button("Save single-pitch change", key=f"ov-save-{pid}"):
        if new:
            db.set_override(conn, uid, new)
        elif current:
            db.delete_override(conn, uid)
        st.rerun()
