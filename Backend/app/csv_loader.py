"""Load OHLC bars from user-supplied CSV files.

Handles the common Investing.com export format

    "Date","Price","Open","High","Low","Vol.","Change %"

as well as a generic ``Date,Open,High,Low,Close`` layout. Numbers may carry
thousands separators and quotes (e.g. ``"4,146.65"``). Rows are returned
oldest→newest so they feed straight into the strategy engines.
"""

from __future__ import annotations

import csv
import io

import numpy as np


def _num(x: str) -> float:
    return float(str(x).replace(",", "").replace('"', "").replace("﻿", "").strip())


def _clean(cell: str) -> str:
    return cell.replace("﻿", "").strip().strip('"').lower()


def _pick(header: list[str], *names: str) -> int | None:
    lower = [_clean(h) for h in header]
    for n in names:
        if n in lower:
            return lower.index(n)
    return None


_HEADER_TOKENS = {"date", "time", "datetime", "timestamp", "open", "high", "low",
                  "close", "price", "volume", "vol", "vol."}


def _is_header(row: list[str]) -> bool:
    return any(_clean(c) in _HEADER_TOKENS for c in row)


def _mt_layout(first_row: list[str]) -> dict:
    """Column indices for a headerless MetaTrader-style row.

    MT4/MT5 export as ``Date,Time,O,H,L,C,V`` (7 cols) or ``Date,O,H,L,C,V``.
    Detected by whether the second field looks like a HH:MM time.
    """
    n = len(first_row)
    has_time = len(first_row) > 1 and ":" in first_row[1]
    if has_time:
        return {"date": 0, "open": 2, "high": 3, "low": 4, "close": 5,
                "vol": 6 if n > 6 else None}
    return {"date": 0, "open": 1, "high": 2, "low": 3, "close": 4,
            "vol": 5 if n > 5 else None}


def load_ohlc_csv(text: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse CSV text → (highs, lows, closes) as float arrays, oldest first.

    Understands three layouts: a named header (Investing.com / Dukascopy /
    generic), and headerless MetaTrader exports (``Date,Time,O,H,L,C,V`` or
    ``Date,O,H,L,C,V``). Dates may use ``.``, ``/`` or ``-`` and row order is
    auto-detected. Raises ValueError if OHLC columns can't be found.
    """
    text = text.lstrip("﻿")  # strip a UTF-8 BOM if present
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError("CSV has no data rows")

    if _is_header(rows[0]):
        header, body = rows[0], rows[1:]
        i_close = _pick(header, "close", "price")
        i_high = _pick(header, "high")
        i_low = _pick(header, "low")
        i_date = _pick(header, "date", "timestamp", "time", "datetime")
        if i_close is None:
            raise ValueError("CSV needs a 'Close' or 'Price' column")
    else:
        body = rows
        layout = _mt_layout(rows[0])
        i_close, i_high, i_low, i_date = (
            layout["close"], layout["high"], layout["low"], layout["date"])

    highs, lows, closes, dates = [], [], [], []
    for r in body:
        try:
            close = _num(r[i_close])
            high = _num(r[i_high]) if i_high is not None else close
            low = _num(r[i_low]) if i_low is not None else close
        except (ValueError, IndexError):
            continue  # skip malformed rows
        closes.append(close)
        highs.append(high)
        lows.append(low)
        dates.append(r[i_date].strip().strip('"') if i_date is not None else "")

    if len(closes) < 2:
        raise ValueError("no numeric rows parsed from CSV")

    # Detect order: if the first date is newer than the last, reverse to oldest-first.
    if _looks_newest_first(dates):
        highs, lows, closes = highs[::-1], lows[::-1], closes[::-1]

    return np.array(highs), np.array(lows), np.array(closes)


def _parse_date_key(d: str):
    """Turn a date/timestamp string into a comparable integer, or None.

    Handles MM/DD/YYYY, YYYY-MM-DD, ISO datetimes (``2025-01-01T00:00:00``),
    and millisecond/second epoch timestamps (dukascopy-node output).
    """
    d = d.strip().strip('"')
    if not d:
        return None
    if d.isdigit():                       # epoch ms or s
        return int(d)
    day = d.split("T")[0].split(" ")[0]   # drop any time portion
    for sep in ("/", "-", "."):
        if sep in day:
            parts = day.split(sep)
            if len(parts) == 3:
                try:
                    if len(parts[0]) == 4:                 # YYYY-MM-DD
                        return int(parts[0]) * 10000 + int(parts[1]) * 100 + int(parts[2])
                    return int(parts[2]) * 10000 + int(parts[0]) * 100 + int(parts[1])  # MM/DD/YYYY
                except ValueError:
                    return None
    return None


def _looks_newest_first(dates: list[str]) -> bool:
    """Heuristic: many exports (Investing.com) list newest row first."""
    first, last = _parse_date_key(dates[0]), _parse_date_key(dates[-1])
    if first is None or last is None:
        return False
    return first > last
