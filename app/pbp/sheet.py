"""The coach play-by-play sheet: a CSV the coaches fill in or fix in Excel when there is no official box
score (scrimmages) or the official one is wrong.

One row per plate appearance, plus a row for each runner move between plate appearances (steal, wild
pitch, pickoff, ...). Each row says where the batter and every runner ended up, by base. Reading the
sheet writes those rows out in StatCrew's wording and replays them with `pbp.plays`, so a coach sheet
becomes the same `BoxScore` an official page does: matching, game situations and scores all work
unchanged. Runs, outs and the running score are counted from the moves, never typed. Definitions are
in METRICS.md section 4.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pandas as pd

from pbp.boxscore import BoxScore, HalfInning, PitcherLine
from pbp.plays import HOME, OUT, PlayRow, replay

COACH_SOURCE = "coach sheet"

COLUMNS = ["inning", "half", "batter", "pitcher", "tm_result", "tm_outs", "tm_runs",
           "result", "batter_to", "r1_to", "r2_to", "r3_to", "rbi", "notes"]
REQUIRED = ["inning", "half", "batter", "result", "batter_to", "r1_to", "r2_to", "r3_to", "rbi"]

# Plate-appearance results, the base the batter usually ends on, and how the row is written.
PA_RESULTS = {
    "1B": (1, "singled"), "2B": (2, "doubled"), "3B": (3, "tripled"), "HR": (HOME, "homered"),
    "BB": (1, "walked"), "IBB": (1, "intentionally walked"), "HBP": (1, "hit by pitch"),
    "K": (OUT, "struck out"), "ROE": (1, "reached on an error"), "FC": (1, "reached on a fielder's choice"),
    "CI": (1, "reached on catcher's interference"), "SF": (OUT, "flied out, sacrifice fly"),
    "SH": (OUT, "sacrifice bunt"), "Out": (OUT, "hit into an out"),
}
# Runner-only rows: how a runner's move is written, and the words after it.
RUNNER_EVENTS = {
    "SB": ("stole", ""), "CS": ("caught stealing", ""), "PO": ("picked off", ""),
    "WP": ("", " on a wild pitch"), "PB": ("", " on a passed ball"), "BK": ("", " on a balk"),
    "DI": ("", " on defensive indifference"), "E": ("", " on an error"), "OA": ("", ""),
}
_ALIASES = {"OUT": "Out", "E": "E", "KL": "K", "KS": "K", "SAC": "SH", "ERROR": "ROE"}
_BASE_WORD = {1: "first", 2: "second", 3: "third", HOME: "home"}
_BASE_CELL = {1: "1", 2: "2", 3: "3", HOME: "H", OUT: "X"}
_CELL_BASE = {"1": 1, "2": 2, "3": 3, "H": HOME, "HOME": HOME, "4": HOME, "S": HOME, "SCORED": HOME,
              "X": OUT, "OUT": OUT}

HELP = ("result: 1B 2B 3B HR BB IBB HBP K ROE FC CI SF SH Out on a plate appearance; on a row with no "
        "batter, SB CS PO WP PB BK DI E (error) or OA (other). batter_to, r1_to, r2_to, r3_to: where the "
        "batter / the runner who started on first, second, third ended up: 1, 2, 3, H (scored) or X (out). "
        "Leave batter_to blank for the usual base (1B = first, K = out, ...) and a runner blank if he "
        "stayed.")


class SheetError(ValueError):
    """The sheet can't be read. `problems` lists every row that needs fixing."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass
class SheetResult:
    box: BoxScore
    warnings: list[str] = field(default_factory=list)   # sheet problems; replay checks run later (match_game)


def is_coach(source: str | None) -> bool:
    return str(source or "").startswith(COACH_SOURCE)


# --- Writing the sheet ---------------------------------------------------------------------------

def _runner_event(text: str) -> str:
    t = text.lower()
    for words, code in [("stole", "SB"), ("caught stealing", "CS"), ("picked off", "PO"), ("wild pitch", "WP"),
                        ("passed ball", "PB"), ("balk", "BK"), ("indifference", "DI"), ("error", "E")]:
        if words in t:
            return code
    return "OA"


def _tm_columns(tm: pd.DataFrame | None) -> dict[int, dict]:
    """TrackMan pa_id -> the sheet's reference columns, from a TrackMan-only analysis frame."""
    if tm is None or tm.empty:
        return {}
    ends = tm[tm["pa_end"]]
    return {int(r["pa_id"]): {"pitcher": _display(r["Pitcher"]), "tm_result": r["outcome"],
                              "tm_outs": int(r["outs_on_pitch"]),
                              "tm_runs": int(r["RunsScored"]) if pd.notna(r["RunsScored"]) else 0}
            for _, r in ends.iterrows()}


def _display(name: str) -> str:
    if "," in str(name):
        last, first = (p.strip() for p in str(name).split(",", 1))
        return f"{first} {last}".strip()
    return str(name).strip()


def _cell(to: int | None) -> str:
    return "" if to is None else _BASE_CELL[to]


def sheet_from_box(box: BoxScore, tm: pd.DataFrame | None = None) -> pd.DataFrame:
    """The sheet pre-filled from a stored play-by-play (official or coach). With the game's TrackMan-only
    analysis frame, each plate appearance also gets TrackMan's pitcher, result, outs and runs. From an
    official box score, `notes` holds the official wording of each play (reading the sheet ignores it)."""
    from pbp.match import match_game  # match imports pandas-heavy code; only needed here

    rep = replay(box)
    pairs = match_game(tm, box).pairs if tm is not None and not tm.empty else {}
    tm_cols = _tm_columns(tm)
    out, n_pa = [], 0
    for r in rep.rows:
        row = dict.fromkeys(COLUMNS, "")
        row.update(inning=r.inning, half=r.half, notes="" if is_coach(box.source) else r.text)
        if r.code is not None:
            row.update(tm_cols.get(pairs.get(n_pa), {}))
            n_pa += 1
            row.update(batter=r.batter, result=r.code, rbi=r.rbi,
                       batter_to="" if r.batter_to == PA_RESULTS[r.code][0] else _cell(r.batter_to))
        else:
            row.update(result=_runner_event(r.text), rbi=0)
        for k, to in r.moves.items():
            row[f"r{k}_to"] = _cell(to)
        out.append(row)
    return pd.DataFrame(out, columns=COLUMNS, dtype=object)


def sheet_from_trackman(tm: pd.DataFrame) -> pd.DataFrame:
    """The sheet pre-filled from TrackMan alone: one row per plate appearance with TrackMan's result.
    Runner moves and RBIs are left for the coach (TrackMan doesn't know who was on base)."""
    if tm.empty:
        return pd.DataFrame(columns=COLUMNS, dtype=object)
    tm_cols = _tm_columns(tm)
    out = []
    for _, r in tm[tm["pa_end"]].iterrows():
        row = dict.fromkeys(COLUMNS, "")
        row.update(inning=int(r["Inning"]), half=r["Top/Bottom"], batter=_display(r["hitter"]),
                   **tm_cols[int(r["pa_id"])])
        row["result"] = row["tm_result"] if row["tm_result"] in PA_RESULTS else ""
        out.append(row)
    return pd.DataFrame(out, columns=COLUMNS, dtype=object)


def trackman_teams(tm: pd.DataFrame) -> tuple[str, str]:
    """(away, home) TrackMan team codes: the batting team in the top and in the bottom of innings."""
    def batting(half: str, fallback: str) -> str:
        if not {"Top/Bottom", "BatterTeam"} <= set(tm.columns):
            return fallback
        teams = tm.loc[tm["Top/Bottom"] == half, "BatterTeam"]
        teams = teams[teams.astype(str).str.strip() != ""]
        return str(teams.mode().iloc[0]) if len(teams) else fallback
    return batting("Top", "Away"), batting("Bottom", "Home")


def to_csv_bytes(sheet: pd.DataFrame) -> bytes:
    """UTF-8 with a byte-order mark, so Excel shows accented names correctly."""
    return sheet.to_csv(index=False).encode("utf-8-sig")


# --- Reading the sheet ---------------------------------------------------------------------------

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):   # Excel's "CSV" on Windows saves in cp1252
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _result(cell: str) -> str:
    c = cell.strip()
    if c in PA_RESULTS or c in RUNNER_EVENTS:
        return c
    up = c.upper()
    for code in [*PA_RESULTS, *RUNNER_EVENTS]:
        if code.upper() == up:
            return code
    return _ALIASES.get(up, c)


def _base(cell: str) -> int | None | str:
    """1-3, HOME, OUT, None (blank), or the cell text if it isn't a base."""
    c = cell.strip().upper()
    if c.endswith(".0"):            # a number Excel saved as 2.0
        c = c[:-2]
    if not c:
        return None
    return _CELL_BASE.get(c, cell)


@dataclass
class _Row:
    line: int                       # spreadsheet row number (header = 1)
    inning: int
    half: str
    batter: str
    code: str
    batter_to: int | None
    moves: dict[int, int]
    rbi: int


def _parse_rows(df: pd.DataFrame) -> tuple[list[_Row], list[str]]:
    rows, problems = [], []
    for i, r in df.iterrows():
        line = int(i) + 2
        if not any(str(v).strip() for v in r[REQUIRED]):
            continue
        bad = []
        inning = str(r["inning"]).strip().removesuffix(".0")
        if not inning.isdigit() or int(inning) < 1:
            bad.append(f"inning \"{r['inning']}\" isn't a number")
        half = {"T": "Top", "TOP": "Top", "B": "Bottom", "BOT": "Bottom", "BOTTOM": "Bottom"}.get(
            str(r["half"]).strip().upper())
        if half is None:
            bad.append(f"half \"{r['half']}\" should be Top or Bottom")
        batter = re.sub(r"\s+", " ", str(r["batter"]).replace(";", ",")).strip()
        code = _result(str(r["result"]))
        if batter and code == "E":
            code = "ROE"
        if not code:
            bad.append("result is blank")
        elif batter and code not in PA_RESULTS:
            bad.append(f"result \"{code}\" isn't a plate-appearance result ({' '.join(PA_RESULTS)})")
        elif not batter and code not in RUNNER_EVENTS:
            bad.append(f"result \"{code}\" needs a batter, or use a runner result "
                       f"({' '.join(RUNNER_EVENTS)}) on a row with no batter")
        moves = {}
        for k in (1, 2, 3):
            to = _base(str(r[f"r{k}_to"]))
            if isinstance(to, str):
                bad.append(f"r{k}_to \"{to}\" should be 1, 2, 3, H or X")
            elif to is not None and to != k:
                if to != OUT and to < k:
                    bad.append(f"r{k}_to is {to}: a runner can't go back a base")
                else:
                    moves[k] = to
        batter_to = _base(str(r["batter_to"]))
        if isinstance(batter_to, str):
            bad.append(f"batter_to \"{batter_to}\" should be 1, 2, 3, H or X")
        elif batter_to is not None and not batter:
            bad.append("batter_to is filled in on a row with no batter")
        rbi = str(r["rbi"]).strip().removesuffix(".0") or "0"
        if not rbi.isdigit() or int(rbi) > 4:
            bad.append(f"rbi \"{r['rbi']}\" should be a number from 0 to 4")
        if bad:
            problems.append(f"Row {line}: " + "; ".join(bad))
            continue
        if batter and batter_to is None:
            batter_to = PA_RESULTS[code][0]
        rows.append(_Row(line, int(inning), half, batter, code, batter_to, moves, int(rbi)))
    return rows, problems


def _write_text(r: _Row, on: dict[int, str | None]) -> str:
    """The row in StatCrew's wording, which `pbp.plays` reads back."""
    clauses = []
    if r.batter:
        default, verb = PA_RESULTS[r.code]
        text = f"{r.batter} {verb}"
        to = r.batter_to
        if to != default:
            if to == HOME:
                text += ", scored"
            elif to == OUT:
                text += ", out on the play"
            elif default in (1, 2, 3) and to > default:
                text += f", advanced to {_BASE_WORD[to]}"
            else:
                text += f", reached {_BASE_WORD[to]}"
        if r.rbi:
            text += ", RBI" if r.rbi == 1 else f", {r.rbi} RBI"
        clauses.append(text)
    verb, tail = RUNNER_EVENTS.get(r.code, ("", "")) if not r.batter else ("", "")
    for k in sorted(r.moves, reverse=True):   # lead runner first, as StatCrew writes it
        to, name = r.moves[k], on[k]
        if to == OUT:
            how = f"{verb}, out on the play" if verb in ("picked off", "caught stealing") else "out on the play"
            clauses.append(f"{name} {how}{tail}")
        elif to == HOME:
            clauses.append(f"{name} {'stole home' if verb == 'stole' else 'scored'}{tail}")
        else:
            clauses.append(f"{name} {'stole' if verb == 'stole' else 'advanced to'} {_BASE_WORD[to]}{tail}")
    return "; ".join(clauses) + "."


def read_sheet(data: bytes, away: str, home: str, pitching: list[PitcherLine] | None = None,
               name: str = "") -> SheetResult:
    """A filled-in sheet (CSV bytes) -> BoxScore. `away` / `home` name the teams; `pitching` keeps the
    official pitching lines when the sheet corrects an official box score (the sheet can't charge runs
    or decide earned runs). Raises SheetError listing every row that can't be read."""
    try:
        df = pd.read_csv(io.StringIO(_decode(data)), dtype=str, keep_default_na=False, skip_blank_lines=True)
    except Exception as e:  # not a CSV at all
        raise SheetError([f"Couldn't read the file as a CSV ({e})."]) from e
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise SheetError([f"The sheet is missing the column(s) {', '.join(missing)}. Start from the downloaded "
                          "sheet and keep its first row."])
    rows, problems = _parse_rows(df)
    if problems:
        raise SheetError(problems)
    if not rows:
        raise SheetError(["The sheet has no plays."])

    order = sorted({(r.inning, r.half) for r in rows}, key=lambda k: (k[0], k[1] != "Top"))
    by_half = {k: [r for r in rows if (r.inning, r.half) == k] for k in order}
    halves, warnings = [], []
    for (inning, half), plays in by_half.items():
        where = f"{half} {inning}"
        h = HalfInning(inning, half, away if half == "Top" else home)
        on: dict[int, str | None] = {1: None, 2: None, 3: None}
        for r in plays:
            for k in [k for k in r.moves if on[k] is None]:
                warnings.append(f"Row {r.line} ({where}): r{k}_to is filled in but nobody is on "
                                f"{_BASE_WORD[k]}; ignored")
                del r.moves[k]
            if not r.batter and not r.moves:
                warnings.append(f"Row {r.line} ({where}): {r.code} row moves no runner")
            scored = sum(to == HOME for to in r.moves.values()) + (r.batter_to == HOME)
            if r.rbi > scored:
                warnings.append(f"Row {r.line} ({where}): {r.rbi} RBI but {scored} run(s) scored on the play")
            h.rows.append([_write_text(r, on), None, None])
            new = {k: (None if k in r.moves else v) for k, v in on.items()}
            for k, to in r.moves.items():
                if to in (1, 2, 3):
                    new[to] = on[k]
            if r.batter and r.batter_to in (1, 2, 3):
                new[r.batter_to] = r.batter
            on = new
        halves.append(h)

    box = BoxScore(away, home, None, None, halves, list(pitching or []), f"{COACH_SOURCE}: {name}".rstrip(": "))
    # The printed running score is the replay's own count, so the score always adds up; the replay's
    # other checks (three outs, runners on base) are shown wherever the play-by-play is.
    rep = replay(box)
    played = iter(rep.rows)
    for h in halves:
        for row in h.rows:
            r: PlayRow = next(played)
            row[1], row[2] = r.away, r.home
    final = (rep.rows[-1].away, rep.rows[-1].home) if rep.rows else (0, 0)
    box.away_runs, box.home_runs = final
    return SheetResult(box, warnings)
