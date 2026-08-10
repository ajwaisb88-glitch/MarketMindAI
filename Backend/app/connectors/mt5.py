"""
MetaTrader 5 connector — real broker bars, tick volume and quotes.

Talks to the MT5 terminal running on the same machine (no API key, no server).
Data is read-only here; order placement lives in executor.py and is gated
separately so nothing can fire from a data call.

Volume note: for FX/CFDs MT5 reports **tick volume** (number of price updates),
not contracts. That is exactly the input the Better Volume indicator was
designed around, so the engines behave the same as they do on an MT4/MT5 chart.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger("marketmind.mt5")
_lock = threading.Lock()
_started = False

# Monster/app timeframe names -> MT5 constants (resolved lazily)
_TF_NAMES = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1",
}

# app asset -> common broker symbol candidates (first that exists wins)
SYMBOL_CANDIDATES = {
    "gold": ["XAUUSD", "GOLD", "XAUUSD.m", "XAUUSDm", "XAUUSD_i"],
    "xauusd": ["XAUUSD", "GOLD", "XAUUSD.m", "XAUUSDm"],
    "silver": ["XAGUSD", "SILVER", "XAGUSD.m"],
    "eurusd": ["EURUSD", "EURUSD.m"],
    "gbpusd": ["GBPUSD", "GBPUSD.m"],
    "usdjpy": ["USDJPY", "USDJPY.m"],
}

_resolved: dict[str, str] = {}


def _mt5():
    try:
        import MetaTrader5 as mt5  # noqa: N813
        return mt5
    except Exception as exc:  # noqa: BLE001
        logger.warning("MetaTrader5 package unavailable: %s", exc)
        return None


def connect() -> bool:
    """Initialise the terminal link once. Safe to call repeatedly."""
    global _started
    mt5 = _mt5()
    if mt5 is None:
        return False
    with _lock:
        if _started:
            return True
        if not mt5.initialize():
            logger.warning("MT5 initialize failed: %s", mt5.last_error())
            return False
        _started = True
    return True


def is_available() -> bool:
    return connect()


def account() -> Optional[dict]:
    """Account summary, including whether this is a DEMO or REAL account."""
    if not connect():
        return None
    mt5 = _mt5()
    a = mt5.account_info()
    t = mt5.terminal_info()
    if a is None:
        return None
    kind = {0: "DEMO", 1: "CONTEST"}.get(a.trade_mode, "REAL")
    return {"kind": kind, "server": a.server, "currency": a.currency,
            "leverage": a.leverage, "balance": a.balance, "equity": a.equity,
            "trade_allowed": bool(t.trade_allowed) if t else False,
            "is_real": kind == "REAL"}


def resolve_symbol(asset: str) -> Optional[str]:
    """Map an app asset to this broker's symbol name (brokers differ)."""
    key = asset.lower()
    if key in _resolved:
        return _resolved[key]
    if not connect():
        return None
    mt5 = _mt5()
    for cand in SYMBOL_CANDIDATES.get(key, [asset.upper()]):
        if mt5.symbol_info(cand) is not None:
            mt5.symbol_select(cand, True)
            _resolved[key] = cand
            return cand
    # last resort: first symbol containing the asset name
    for s in (mt5.symbols_get() or []):
        if key.upper().replace("USD", "") in s.name.upper():
            mt5.symbol_select(s.name, True)
            _resolved[key] = s.name
            return s.name
    return None


def bars(asset: str, timeframe: str = "H1", count: int = 500) -> list[dict]:
    """OHLCV bars as {t,o,h,l,c,v} — v is tick volume. Matches the bars-provider seam."""
    if not connect():
        return []
    mt5 = _mt5()
    sym = resolve_symbol(asset)
    tf_attr = _TF_NAMES.get(str(timeframe).upper())
    if not sym or not tf_attr:
        return []
    rates = mt5.copy_rates_from_pos(sym, getattr(mt5, tf_attr), 0, count)
    if rates is None or len(rates) == 0:
        return []
    return [{"t": int(r[0]) * 1000, "o": float(r[1]), "h": float(r[2]),
             "l": float(r[3]), "c": float(r[4]), "v": float(r[5])} for r in rates]


def quote(asset: str) -> Optional[dict]:
    """Live bid/ask/spread."""
    if not connect():
        return None
    mt5 = _mt5()
    sym = resolve_symbol(asset)
    if not sym:
        return None
    t = mt5.symbol_info_tick(sym)
    info = mt5.symbol_info(sym)
    if t is None or info is None:
        return None
    return {"symbol": sym, "bid": t.bid, "ask": t.ask,
            "spread": round(t.ask - t.bid, info.digits), "digits": info.digits}


def symbol_limits(asset: str) -> Optional[dict]:
    """Lot constraints — needed so position sizing can't submit an invalid volume."""
    if not connect():
        return None
    sym = resolve_symbol(asset)
    if not sym:
        return None
    i = _mt5().symbol_info(sym)
    return {"symbol": sym, "min_lot": i.volume_min, "max_lot": i.volume_max,
            "lot_step": i.volume_step, "digits": i.digits, "point": i.point}


def depth(asset: str) -> Optional[list[dict]]:
    """Depth of market (pending orders). Many brokers don't offer it for CFDs."""
    if not connect():
        return None
    mt5 = _mt5()
    sym = resolve_symbol(asset)
    if not sym or not mt5.market_book_add(sym):
        return None
    try:
        book = mt5.market_book_get(sym)
        if not book:
            return None
        return [{"type": b.type, "price": b.price, "volume": b.volume} for b in book]
    finally:
        mt5.market_book_release(sym)


def shutdown() -> None:
    global _started
    mt5 = _mt5()
    if mt5 and _started:
        mt5.shutdown()
        _started = False
