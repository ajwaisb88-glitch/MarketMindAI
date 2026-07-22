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


def load_ohlc_csv(text: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse CSV text → (highs, lows, closes) as float arrays, oldest first.

    Column detection is case-insensitive. ``Price`` or ``Close`` is the close.
    Raises ValueError if the required columns can't be found or no rows parse.
    """
    text = text.lstrip("﻿")  # strip a UTF-8 BOM if present
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError("CSV has no data rows")
    header, body = rows[0], rows[1:]

    i_close = _pick(header, "close", "price")
    i_high = _pick(header, "high")
    i_low = _pick(header, "low")
    i_date = _pick(header, "date", "timestamp", "time", "datetime")  # dukascopy uses 'timestamp'
    if i_close is None:
        raise ValueError("CSV needs a 'Close' or 'Price' column")

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
