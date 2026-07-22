"""Financial Modeling Prep (FMP) data adapter.

Fetches real quotes and OHLC bars for the strategy engines. The API key is read
from the ``FMP_API_KEY`` environment variable — never hard-coded, never
committed. Every function fails soft (returns ``None``) when the key is missing
or the request fails, so the backend can fall back to yfinance / synthetic data
without crashing.

Set your key before launching the backend::

    export FMP_API_KEY=your_key_here      # macOS/Linux
    setx  FMP_API_KEY your_key_here       # Windows (new shell)

FMP symbols come from ``MARKET_PROFILES[asset]["fmp"]`` (e.g. xauusd -> XAUUSD).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

import numpy as np

from .manipulation import market_profile

logger = logging.getLogger("marketmind.fmp")

_BASE = "https://financialmodelingprep.com"
_INTRADAY_INTERVAL = "15min"     # bar size used for intraday strategies
_TIMEOUT = 15


def api_key() -> str | None:
    key = os.environ.get("FMP_API_KEY", "").strip()
    return key or None


def is_configured() -> bool:
    return api_key() is not None


def _get(path: str, params: dict) -> list | dict | None:
    key = api_key()
    if key is None:
        return None
    params = {**params, "apikey": key}
    url = f"{_BASE}{path}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MarketMindAI/1.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("FMP request failed (%s): %s", path, exc)
        return None


def fmp_symbol(asset: str) -> str | None:
    return market_profile(asset).get("fmp")


def get_quote(asset: str) -> dict | None:
    """Latest quote for an asset, or None. Keys mirror FMP's /quote payload."""
    symbol = fmp_symbol(asset)
    if symbol is None:
        return None
    data = _get(f"/api/v3/quote/{urllib.parse.quote(symbol)}", {})
    if isinstance(data, list) and data:
        q = data[0]
        return {"asset": asset.lower(), "symbol": symbol, "price": q.get("price"),
                "change_pct": q.get("changesPercentage"), "day_high": q.get("dayHigh"),
                "day_low": q.get("dayLow"), "volume": q.get("volume")}
    return None


def get_ohlc(asset: str, intraday: bool, limit: int = 800) -> tuple | None:
    """Return (highs, lows, closes) oldest→newest, or None if unavailable.

    Intraday uses the 15-minute chart; long-term uses daily EOD bars.
    """
    symbol = fmp_symbol(asset)
    if symbol is None:
        return None
    enc = urllib.parse.quote(symbol)

    if intraday:
        data = _get(f"/api/v3/historical-chart/{_INTRADAY_INTERVAL}/{enc}", {})
        rows = data if isinstance(data, list) else None
    else:
        data = _get(f"/api/v3/historical-price-full/{enc}", {"timeseries": limit})
        rows = data.get("historical") if isinstance(data, dict) else None

    if not rows:
        return None
    # FMP returns newest-first; reverse to oldest-first and cap length
    rows = list(reversed(rows))[-limit:]
    try:
        highs = np.array([float(r["high"]) for r in rows])
        lows = np.array([float(r["low"]) for r in rows])
        closes = np.array([float(r["close"]) for r in rows])
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("FMP OHLC parse failed for %s: %s", symbol, exc)
        return None
    if len(closes) < 60:
        return None
    return highs, lows, closes
