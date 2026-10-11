"""Replay official play-by-play rows to get the game state before every plate appearance.

StatCrew (the scoring program behind Sidearm box scores) writes one row per play in a fixed
vocabulary: "Pat Smith singled through the right side, RBI (1-2 SBS); Sam Jones scored." The first
clause is the batter (or, on a row with no count, a runner); each clause after a ";" moves one runner.
Every runner movement is written out, so replaying the rows in order gives the runners and outs
before each plate appearance. The score comes from the running score the page prints on every row.

Each half-inning is checked as it is replayed: three outs (except a game-ending half), the runs on
each row against the printed score, and runners left on base against the page's count. Anything
that doesn't add up is reported as a warning; nothing is silently guessed.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from pbp.boxscore import BoxScore, HalfInning

HOME, OUT = 4, -1
_BASE = {"first": 1, "second": 2, "third": 3, "home": HOME}

COUNT = re.compile(r"\((\d)-(\d)(?:\s+([A-Za-z]*))?\)")
_SUB = re.compile(r"^(?P<new>.+?)\s+(?:to\s+(?:p|c|1b|2b|3b|ss|lf|cf|rf|dh)|pinch\s+(?P<pinch>hit|ran))\s+for\s+"
                  r"(?P<old>.+?)\.?$", re.I)
_BATTER_VERBS = ("singled", "doubled", "tripled", "homered", "walked", "intentionally walked", "struck out",
                 "grounded", "flied", "lined", "popped", "fouled", "infield fly", "hit by pitch", "reached",
                 "sacrifice", "hit into", "bunted", "out on batter")
_RUNNER_VERBS = ("stole", "advanced", "scored", "out at", "out on the play", "picked off", "caught stealing")
_ACTOR = re.compile(r"\s(?:" + "|".join(re.escape(v) for v in _BATTER_VERBS + _RUNNER_VERBS + ("failed", "was"))
                    + r")\b", re.I)
_FATE = re.compile(r"reached (first|second|third)|advanced to (second|third|home)|stole (second|third|home)|"
                   r"(\bscored\b)|out at (first|second|third|home)|(out on the play)|(caught stealing)", re.I)
_RBI = re.compile(r"(\d+)\s+RBI|\bRBI\b")


@dataclass
class PlateAppearance:
    inning: int
    half: str                 # "Top" (away team batting) or "Bottom"
    seq: int                  # 0-based order among the half-inning's plate appearances
    batter: str
    code: str                 # K BB IBB HBP CI 1B 2B 3B HR ROE FC SF SH Out
    rbi: int
    outs_before: int
    on1: str | None           # runner names on each base before the play
    on2: str | None
    on3: str | None
    bat_before: int           # batting team's score before the play
    fld_before: int
    bat_after: int
    fld_after: int
    outs_on_play: int         # outs made on the play (batter and runners)
    dp: bool                  # the play produced two or more outs
    advanced: bool            # a runner already on base moved up (scored or took a base) on the play
    balls: int | None         # final count as scored, when given
    strikes: int | None
    text: str

    @property
    def runners_on(self) -> int:
        return sum(r is not None for r in (self.on1, self.on2, self.on3))

    @property
    def risp(self) -> bool:
        return self.on2 is not None or self.on3 is not None


@dataclass
class Replay:
    pas: list[PlateAppearance] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z ]", "", name.lower().replace(",", " ")).strip()


def split_name(name: str) -> tuple[str, str]:
    """(last, first) from "Last, First" or "First Last" (suffixes like Jr. dropped)."""
    if "," in name:
        last, first = name.split(",", 1)
    else:
        parts = [p for p in name.split() if p.lower().strip(".") not in {"jr", "sr", "ii", "iii", "iv"}]
        if not parts:
            return "", ""
        last, first = parts[-1], " ".join(parts[:-1])
    return _norm(last).replace(" ", ""), _norm(first)


def name_similarity(a: str, b: str) -> float:
    """0-1. Mostly the last name (spelled slightly differently in TrackMan and the box score, e.g.
    "Jonson" / "Jonsen"), plus a little for a matching first initial."""
    la, fa = split_name(a)
    lb, fb = split_name(b)
    if not la or not lb:
        return 0.0
    last = difflib.SequenceMatcher(None, la, lb).ratio()
    first = 1.0 if fa[:1] and fa[:1] == fb[:1] else 0.0
    return 0.85 * last + 0.15 * first


def _actor(clause: str) -> tuple[str, str]:
    """Split "Sam Jones advanced to second" into ("Sam Jones", "advanced to second")."""
    m = _ACTOR.search(" " + clause)
    if not m or m.start() == 0:
        return "", clause
    i = m.start() - 1
    return clause[:i].strip(), clause[i:].strip()


def _fate(text: str) -> int | None:
    """Where the clause leaves its subject: 1-3, HOME, OUT, or None if it doesn't move."""
    last = None
    for m in _FATE.finditer(text):
        reached, advanced, stole, scored, out_at, out_play, cs = m.groups()
        if scored:
            last = HOME
        elif out_at or out_play or cs:
            last = OUT
        else:
            last = _BASE[(reached or advanced or stole).lower()]
    return last


def _batter_result(clause: str) -> tuple[str, int]:
    """(outcome code, default destination) from the batter clause."""
    c = clause.lower()
    if "intentionally walked" in c:
        return "IBB", 1
    if "walked" in c:
        return "BB", 1
    if "hit by pitch" in c:
        return "HBP", 1
    if "struck out" in c:
        return "K", OUT
    for word, code, base in [("homered", "HR", HOME), ("tripled", "3B", 3), ("doubled", "2B", 2),
                             ("singled", "1B", 1)]:
        if word in c:
            return code, base
    if "interference" in c and "catcher" in c:
        return "CI", 1
    if "fielder's choice" in c or "fielders choice" in c:
        return "FC", 1
    if "reached" in c and "error" in c:
        return "ROE", 1
    if "sacrifice fly" in c or re.search(r"\bSF\b", clause):
        return "SF", OUT
    if "sacrifice" in c or re.search(r"\bSAC\b", clause):
        return "SH", OUT
    return "Out", OUT


def _is_pa(first: str) -> bool:
    if COUNT.search(first):
        return True
    _, rest = _actor(first)
    return rest.lower().startswith(_BATTER_VERBS)


class _Bases:
    def __init__(self):
        self.b: dict[int, str | None] = {1: None, 2: None, 3: None}

    def find(self, name: str) -> int | None:
        on = [(k, v) for k, v in self.b.items() if v]
        for k, v in on:
            if _norm(v) == _norm(name):
                return k
        scored = sorted(((name_similarity(v, name), k) for k, v in on), reverse=True)
        if scored and scored[0][0] >= 0.75 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
            return scored[0][1]
        return None


def replay_half(h: HalfInning, start: tuple[int, int], final_half: bool) -> tuple[list[PlateAppearance], list[str],
                                                                                    tuple[int, int]]:
    """Replay one half-inning from the score `start` = (away, home). Returns its plate appearances,
    warnings, and the score after it."""
    where = f"{h.half} {h.inning}"
    bat = 0 if h.half == "Top" else 1
    bases, outs, score = _Bases(), 0, list(start)
    pas, warnings = [], []
    ended_on_runner = False
    for text, away, home in h.rows:
        clauses = [c.strip().rstrip(".") for c in text.split(";") if c.strip()]
        first = clauses[0]
        if sub := _SUB.match(first):
            if (sub["pinch"] or "").lower() == "ran" and (k := bases.find(sub["old"])):
                bases.b[k] = sub["new"].strip()
            continue
        pa = _is_pa(first)
        before = dict(bases.b)
        outs_before = outs
        runner_clauses = clauses[1:] if pa else clauses
        moves, runs, advanced = [], 0, False
        for c in runner_clauses:
            name, rest = _actor(c)
            to = _fate(rest)
            if to is None:
                continue
            k = bases.find(name) if name else None
            if k is None:
                warnings.append(f"{where}: runner \"{name or c}\" isn't on base (\"{text}\")")
                if to == HOME:
                    runs += 1
                elif to == OUT:
                    outs += 1
                continue
            moves.append((k, to))
        new = dict(bases.b)
        for k, _ in moves:
            new[k] = None
        for k, to in moves:
            if to == HOME:
                runs += 1
            elif to == OUT:
                outs += 1
            else:
                if new[to] is not None:
                    warnings.append(f"{where}: two runners on base {to} after \"{text}\"")
                new[to] = bases.b[k]
            advanced |= to == HOME or (to != OUT and to > k)
        code = rbi = None
        batter = ""
        if pa:
            batter, rest = _actor(first)
            code, dest = _batter_result(rest)
            fate = _fate(COUNT.sub("", rest))
            if fate is not None and not (code == "K" and fate == OUT):
                dest = fate
            if code == "K" and re.search(r"reached (first|on)", rest, re.I):
                dest = fate if fate not in (None, OUT) else 1
            if dest == HOME:
                runs += 1
            elif dest == OUT:
                outs += 1
            else:
                if new[dest] is not None:        # a runner the text didn't move: push him (and those ahead) up
                    warnings.append(f"{where}: base {dest} was occupied for the batter (\"{text}\")")
                    top = dest
                    while top < 3 and new[top + 1] is not None:
                        top += 1
                    for b in range(top, dest - 1, -1):
                        if b == 3:
                            runs += 1
                        else:
                            new[b + 1] = new[b]
                        new[b] = None
                new[dest] = batter
            m = _RBI.search(first)
            rbi = int(m.group(1)) if m and m.group(1) else (1 if m else 0)
        if away is not None and home is not None:
            printed = (away, home)[bat] - score[bat]
            if printed != runs:
                warnings.append(f"{where}: {runs} run(s) by the play-by-play but the score moved {printed} "
                                f"(\"{text}\")")
            after = [away, home]
        else:
            after = list(score)
            after[bat] += runs
        if pa:
            count = COUNT.search(first)
            pas.append(PlateAppearance(
                h.inning, h.half, len(pas), batter, code, rbi, outs_before,
                before[1], before[2], before[3], score[bat], score[1 - bat], after[bat], after[1 - bat],
                outs - outs_before, outs - outs_before >= 2, advanced,
                int(count.group(1)) if count else None, int(count.group(2)) if count else None, text))
        bases.b, score = new, after
        ended_on_runner = not pa
    left = sum(v is not None for v in bases.b.values())
    if outs != 3 and not final_half:
        warnings.append(f"{where}: {outs} outs counted, expected 3")
    # StatCrew's left-on-base count disagrees with the bases when a half ends on a caught stealing or
    # pickoff, so it is only checked when the half ended on a plate appearance.
    if h.lob is not None and outs == 3 and left != h.lob and not ended_on_runner:
        warnings.append(f"{where}: {left} runner(s) left on base by the replay, the box score says {h.lob}")
    return pas, warnings, (score[0], score[1])


def replay(box: BoxScore) -> Replay:
    """Every plate appearance in the game, in order, with the state before it."""
    out = Replay()
    score = (0, 0)
    played = [h for h in box.halves if h.rows]
    for i, h in enumerate(played):
        pas, warnings, score = replay_half(h, score, final_half=i == len(played) - 1)
        out.pas += pas
        out.warnings += warnings
    if box.away_runs is not None and score != (box.away_runs, box.home_runs):
        out.warnings.append(f"Replayed final score {score[0]}-{score[1]} doesn't match the box score "
                            f"{box.away_runs}-{box.home_runs}")
    return out
