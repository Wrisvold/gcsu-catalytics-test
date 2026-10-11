"""Read a Sidearm Sports box-score page (the format of gcsubobcats.com and most Peach Belt schools).

Only the official text is kept: every play-by-play row with the running score printed beside it, each
half-inning's left-on-base count, the pitching lines and the line score. Nothing is interpreted here;
`pbp.plays` does that at read time, so the stored rows are always the official record (rule 1).
"""
from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import asdict, dataclass, field


class BoxScoreError(ValueError):
    pass


@dataclass
class HalfInning:
    inning: int
    half: str                                   # "Top" or "Bottom"
    team: str                                   # batting team, as the page names it
    rows: list[list] = field(default_factory=list)   # [text, away_score, home_score] after each row
    lob: int | None = None                      # left on base, from the page


@dataclass
class PitcherLine:
    team: str
    name: str
    ip: str
    h: int
    r: int
    er: int
    bb: int
    so: int
    bf: int | None = None
    np: int | None = None


@dataclass
class BoxScore:
    away: str
    home: str
    away_runs: int | None
    home_runs: int | None
    halves: list[HalfInning]
    pitching: list[PitcherLine]
    source: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(text: str) -> "BoxScore":
        d = json.loads(text)
        return BoxScore(d["away"], d["home"], d["away_runs"], d["home_runs"],
                        [HalfInning(**h) for h in d["halves"]], [PitcherLine(**p) for p in d["pitching"]],
                        d.get("source", ""))


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _text(fragment: str) -> str:
    return _WS.sub(" ", html_lib.unescape(_TAG.sub(" ", fragment))).strip()


def _int(text: str) -> int | None:
    text = text.strip()
    return int(text) if re.fullmatch(r"-?\d+", text) else None


_HALF_CAPTION = re.compile(r"<caption>\s*([^<]*?)\s+-\s+(Top|Bottom)\s+of\s+(\d+)(?:st|nd|rd|th)\s*</caption>(.*?)</table>"
                           r"(.*?)(?=<caption>|$)", re.S | re.I)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_LOB = re.compile(r"Left On Base\s*</dt>\s*<dd>\s*(\d+)", re.I)
_PITCHING = re.compile(r"<caption>\s*([^<]*?)\s*<span[^>]*>\s*-\s*Pitching Stats\s*</span>\s*</caption>(.*?)</table>",
                       re.S | re.I)
_LINE_SCORE = re.compile(r"<caption>\s*Team Score By Innings\s*</caption>(.*?)</table>", re.S | re.I)
_DECISION = re.compile(r"\((?:W|L|S|H|BS)[^)]*\)")


def parse_html(page: str, source: str = "") -> BoxScore:
    """Box-score page HTML -> BoxScore. Raises BoxScoreError if the page has no play-by-play."""
    halves: dict[tuple[int, str], HalfInning] = {}
    for team, half, inning, body, after in _HALF_CAPTION.findall(page):
        key = (int(inning), half.title())
        if key in halves:            # the page prints the play-by-play twice (all innings, then by inning)
            continue
        h = HalfInning(int(inning), half.title(), _text(team))
        for row in _ROW.findall(body):
            cells = [_text(c) for c in _CELL.findall(row)]
            if len(cells) >= 3 and cells[0]:
                h.rows.append([cells[0], _int(cells[-2]), _int(cells[-1])])
        if m := _LOB.search(after[:2000]):
            h.lob = int(m.group(1))
        halves[key] = h
    if not halves:
        raise BoxScoreError("No play-by-play found on this page. Use the game's box score page "
                            "(…/sports/baseball/stats/<season>/<opponent>/boxscore/<number>).")
    ordered = [halves[k] for k in sorted(halves, key=lambda k: (k[0], k[1] != "Top"))]
    away = next((h.team for h in ordered if h.half == "Top"), "")
    home = next((h.team for h in ordered if h.half == "Bottom"), "")

    pitching = []
    for team, body in _PITCHING.findall(page):
        heads = [_text(t) for t in re.findall(r"<th[^>]*>(.*?)</th>", body, re.S)]
        for row in _ROW.findall(body):
            cells = _CELL.findall(row)
            if not cells:
                continue
            name = _text(_DECISION.sub("", _text(cells[0])))
            if not name or name.lower().startswith("total"):
                continue
            vals = dict(zip(heads[1:], (_text(c) for c in cells[1:])))
            pitching.append(PitcherLine(_text(team), name, vals.get("IP", ""), _int(vals.get("H", "")) or 0,
                                        _int(vals.get("R", "")) or 0, _int(vals.get("ER", "")) or 0,
                                        _int(vals.get("BB", "")) or 0, _int(vals.get("SO", "")) or 0,
                                        _int(vals.get("BF", "")), _int(vals.get("NP", ""))))

    away_runs = home_runs = None
    if m := _LINE_SCORE.search(page):
        heads = [_text(t) for t in re.findall(r"<th[^>]*>(.*?)</th>", m.group(1), re.S)]
        rows = [[_text(c) for c in _CELL.findall(r)] for r in _ROW.findall(m.group(1))]
        rows = [r for r in rows if len(r) == len(heads)]
        if "R" in heads and len(rows) >= 2:
            i = heads.index("R")
            away_runs, home_runs = _int(rows[0][i]), _int(rows[1][i])
    return BoxScore(away, home, away_runs, home_runs, ordered, pitching, source)
