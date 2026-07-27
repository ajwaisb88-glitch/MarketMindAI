"""Live-forward signal performance tracker.

Every actionable signal the app shows (entry + stop + target) is logged once,
then graded against what the market actually did afterwards — did price reach the
target (TP), the stop (SL), or is it still open? This is the honest scoreboard:
real signals, real prices from Binance, no simulated wins.

Outcomes are evaluated on the price *path* since the signal fired (bar highs/lows
from Binance), not just the latest tick, so an intrabar touch of TP or SL is
caught. If both were touched in the same window the stop wins (conservative).

State is a small JSON file, same pattern as the source-mode file.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

from .connectors.binance import SYMBOL_MAP, BinanceConnector

logger = logging.getLogger("marketmind.tracker")

_PERF_FILE = os.getenv("MARKETMIND_PERF_FILE", "signal_performance.json")
_MAX_ROWS = 400
_OPEN_TTL_SEC = 7 * 24 * 3600      # a signal still open after 7d is marked stale
_lock = threading.Lock()
_bc = BinanceConnector()

_BUY, _SELL = "BUY", "SELL"


def _load() -> list[dict]:
    try:
        if os.path.exists(_PERF_FILE):
            with open(_PERF_FILE) as f:
                return json.load(f)
    except Exception as exc:  # noqa: BLE001
        logger.warning("perf load failed: %s", exc)
    return []


def _save(rows: list[dict]) -> None:
    try:
        with open(_PERF_FILE, "w") as f:
            json.dump(rows[-_MAX_ROWS:], f)
    except Exception as exc:  # noqa: BLE001
        logger.warning("perf save failed: %s", exc)


def _sig_id(source: str, asset: str, direction: str) -> str:
    # One open position per system+asset+direction — re-polls of the same live
    # setup (entry drifting a few cents) collapse into it instead of spamming rows.
    return f"{source}:{asset}:{direction}"


def _binance_symbol(asset: str) -> str:
    return SYMBOL_MAP.get(asset.lower(), f"{asset.upper()}USDT")


def _price_path(asset: str, since_ts: float) -> tuple[float | None, float | None, float | None]:
    """(max_high, min_low, last_close) since since_ts via Binance; Nones if no data."""
    try:
        bars = _bc.klines(_binance_symbol(asset), "5m", 500)
        rel = [b for b in bars if (b["t"] / 1000.0) >= since_ts - 300]
        rel = rel or bars[-1:]
        if not rel:
            return None, None, None
        return (max(b["high"] for b in rel), min(b["low"] for b in rel), rel[-1]["close"])
    except Exception:  # noqa: BLE001
        return None, None, None


def _r_multiple(direction: str, entry: float, sl: float, exit_px: float) -> float:
    risk = abs(entry - sl) or 1e-9
    move = (exit_px - entry) if direction == _BUY else (entry - exit_px)
    return round(move / risk, 2)


def record(signals: dict, asset: str) -> None:
    """Log any actionable signals (with entry/stop/target) not already open."""
    asset = asset.lower()
    with _lock:
        rows = _load()
        open_ids = {r["id"] for r in rows if r["status"] == "OPEN"}
        added = False
        for source, sig in (signals or {}).items():
            if not isinstance(sig, dict):
                continue
            direction = sig.get("direction")
            entry, sl, tp = sig.get("entry"), sig.get("stop_loss"), sig.get("take_profit")
            if direction not in (_BUY, _SELL) or None in (entry, sl, tp):
                continue
            sid = _sig_id(source, asset, direction)
            if sid in open_ids:
                continue
            rows.append({
                "id": sid, "source": source, "asset": asset, "direction": direction,
                "grade": sig.get("grade", "-"), "entry": round(float(entry), 6),
                "stop_loss": round(float(sl), 6), "take_profit": round(float(tp), 6),
                "tier": sig.get("tier"), "ts": time.time(), "status": "OPEN",
                "exit_price": None, "closed_ts": None, "r_multiple": None,
            })
            open_ids.add(sid)
            added = True
        if added:
            _save(rows)


def update_outcomes() -> None:
    """Grade every OPEN signal against the price path since it fired."""
    with _lock:
        rows = _load()
        changed = False
        for r in rows:
            if r["status"] != "OPEN":
                continue
            hi, lo, last = _price_path(r["asset"], r["ts"])
            if hi is None:
                if time.time() - r["ts"] > _OPEN_TTL_SEC:
                    r["status"] = "STALE"; changed = True
                continue
            buy = r["direction"] == _BUY
            tp, sl = r["take_profit"], r["stop_loss"]
            tp_hit = hi >= tp if buy else lo <= tp
            sl_hit = lo <= sl if buy else hi >= sl
            if sl_hit:  # conservative: stop wins ties
                r.update(status="SL", exit_price=sl, closed_ts=time.time(),
                         r_multiple=_r_multiple(r["direction"], r["entry"], sl, sl))
                changed = True
            elif tp_hit:
                r.update(status="TP", exit_price=tp, closed_ts=time.time(),
                         r_multiple=_r_multiple(r["direction"], r["entry"], sl, tp))
                changed = True
            elif time.time() - r["ts"] > _OPEN_TTL_SEC:
                r.update(status="STALE", exit_price=last, closed_ts=time.time(),
                         r_multiple=_r_multiple(r["direction"], r["entry"], sl, last))
                changed = True
        if changed:
            _save(rows)


def stats() -> dict:
    """Per-system scoreboard + recent rows. Updates outcomes first."""
    update_outcomes()
    with _lock:
        rows = _load()
    by: dict[str, dict] = {}
    for r in rows:
        s = by.setdefault(r["source"], {"source": r["source"], "total": 0, "open": 0,
                                        "wins": 0, "losses": 0, "stale": 0, "sum_r": 0.0})
        s["total"] += 1
        st = r["status"]
        if st == "OPEN":
            s["open"] += 1
        elif st == "TP":
            s["wins"] += 1; s["sum_r"] += r.get("r_multiple") or 0.0
        elif st == "SL":
            s["losses"] += 1; s["sum_r"] += r.get("r_multiple") or 0.0
        elif st == "STALE":
            s["stale"] += 1; s["sum_r"] += r.get("r_multiple") or 0.0
    for s in by.values():
        closed = s["wins"] + s["losses"]
        s["win_rate"] = round(100 * s["wins"] / closed, 1) if closed else None
        graded = s["wins"] + s["losses"] + s["stale"]
        s["avg_r"] = round(s["sum_r"] / graded, 2) if graded else None
        s["sum_r"] = round(s["sum_r"], 2)
    recent = sorted(rows, key=lambda r: r["ts"], reverse=True)[:40]
    total_closed = sum(s["wins"] + s["losses"] for s in by.values())
    return {"systems": list(by.values()), "recent": recent,
            "tracked": len(rows), "closed": total_closed}
