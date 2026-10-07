"""Report tables as plain data: which text goes in each cell, where its n is printed, and whether it is
greyed. The app renders these as HTML and the PDF as ReportLab tables, so both show n the same way
(METRICS.md section 6)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from metrics.common import Stat


@dataclass(frozen=True)
class Col:
    key: str
    header: str
    mode: str = "rate"  # rate: value + n | measure: n only when it differs from the row count | count | plain


@dataclass(frozen=True)
class Cell:
    text: str
    n: int | None = None   # printed beneath the value when not None
    low: bool = False      # below its minimum n: greyed


@dataclass
class TableSpec:
    headers: list[tuple[str, int | None]]   # (label, n printed once in the header or None)
    rows: list[tuple[str, list[Cell]]]       # (row key, cells); row key "All" is the totals row
    has_asterisk: bool


PITCH_TYPE_COLS = [
    Col("Count", "Count", "count"), Col("Usage %", "Usage %"),
    Col("Avg Velo", "Avg Velo", "measure"), Col("Max Velo", "Max Velo", "measure"),
    Col("Avg Spin", "Avg Spin", "measure"), Col("Max Spin", "Max Spin", "measure"),
    Col("IVB", "IVB (in)", "measure"), Col("HB", "HB (in)", "measure"),
    Col("Extension", "Ext (ft)", "measure"), Col("Rel Height", "Rel Ht (ft)", "measure"),
    Col("Strike %", "Strike %"), Col("Whiff %", "Whiff %"), Col("Chase %", "Chase %"), Col("Out %", "Out %"),
]
PITCHER_SPLIT_COLS = [Col("PA", "PA", "plain"), Col("BAA", "BAA"), Col("K %", "K %"), Col("BB %", "BB %"),
                      Col("GB %", "GB %"), Col("FB %", "FB %"), Col("HH %", "HH %"), Col("BABIP", "BABIP")]
BREAKDOWN_COLS = [Col("Pitches", "Pitches", "count"), Col("Seen %", "Seen %"), Col("Swing %", "Swing %"),
                  Col("Whiff %", "Whiff %"), Col("Chase %", "Chase %"),
                  Col("Avg Exit Velo", "Avg EV (mph)"), Col("Avg Launch Angle", "Avg LA")]
HITTER_SPLIT_COLS = [Col("PA", "PA", "plain"), Col("AVG", "AVG"), Col("Max EV", "Max EV"),
                     Col("Avg EV", "Avg EV"), Col("HH %", "HH %"), Col("Whiff %", "Whiff %"),
                     Col("Chase %", "Chase %"), Col("BABIP", "BABIP")]


def build_table(df: pd.DataFrame, cols: list[Col], count_key: str | None = None) -> TableSpec:
    """A column whose cells all share one n (none greyed) prints n once in the header; otherwise each
    cell carries its own n. Count cells below their minimum get an asterisk. Low-n cells are greyed,
    never hidden (Section 4b)."""
    headers, shared_n = [], {}
    for c in cols:
        stats = [v for v in df[c.key] if isinstance(v, Stat)]
        shared = (c.mode == "rate" and len(stats) > 1 and len({s.n for s in stats}) == 1
                  and not any(s.low for s in stats))
        shared_n[c.key] = stats[0].n if shared else None
        headers.append((c.header, shared_n[c.key]))
    rows, asterisk = [], False
    for idx, row in df.iterrows():
        row_count = row[count_key].n if count_key and isinstance(row.get(count_key), Stat) else None
        cells = []
        for c in cols:
            v = row[c.key]
            if not isinstance(v, Stat):
                cells.append(Cell(str(v)))
            elif c.mode == "count":
                asterisk |= v.low
                cells.append(Cell(v.text() + ("*" if v.low else "")))
            else:
                show_n = (c.mode == "rate" and shared_n[c.key] is None) or (
                    c.mode == "measure" and row_count is not None and v.n != row_count and v.value is not None)
                cells.append(Cell(v.text(), v.n if show_n else None, v.low))
        rows.append((str(idx), cells))
    return TableSpec(headers, rows, asterisk)
