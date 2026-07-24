"""
Signal-source selector — pick which system's signals you want and run the
service for those. Three independent sources (never blended):

  - marketmind : crypto (Binance) — spoof scalp + intraday + longterm
  - whale      : Better Volume 7-buffer engine
  - monster    : confluence swing (structure/momentum) with trailing

Each source produces a normalized signal {direction, grade, entry, stop_loss,
take_profit, risk_reward, source, engine, story}. The user selects any subset;
the feed runs continuously for the selected sources only.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

import numpy as np

from . import better_volume as bv
from . import strategies as strat
from .connectors.binance import BinanceConnector

_SEL_FILE = os.getenv("MARKETMIND_SOURCES_FILE", "selected_sources.json")
_bc = BinanceConnector()


# ── shared bar cache ───────────────────────────────
# Every source pulls bars, and the confluence engine pulls 5-6 timeframes. Without
# this, one feed call refetches the same series many times over. Short TTL keeps
# signals live while collapsing the duplicate network/terminal round-trips.
_BAR_TTL = float(os.getenv("MARKETMIND_BAR_TTL_SEC", "10"))
_bar_cache: dict[tuple, tuple[float, object]] = {}


def _cached(key: tuple, fetch):
    now = time.time()
    hit = _bar_cache.get(key)
    if hit and (now - hit[0]) < _BAR_TTL:
        return hit[1]
    val = fetch()
    _bar_cache[key] = (now, val)
    return val


def clear_bar_cache() -> None:
    _bar_cache.clear()


def _bars(asset: str, interval: str, limit: int = 300):
    """OHLCV arrays for an asset via Binance (crypto + PAXG gold). Cached."""
    def _fetch():
        k = _bc.klines(asset, interval, limit)
        if not k or len(k) < 60:
            return None
        return (np.array([b["high"] for b in k], float), np.array([b["low"] for b in k], float),
                np.array([b["close"] for b in k], float), np.array([b["volume"] for b in k], float),
                np.array([b["open"] for b in k], float))
    return _cached(("arr", asset.lower(), interval, limit), _fetch)


def _atr_plan(direction: str, close: float, atr: float, rr: float = 2.0, k_stop: float = 1.5) -> dict:
    risk = k_stop * atr
    if direction == "BUY":
        sl, tp = close - risk, close + rr * risk
    else:
        sl, tp = close + risk, close - rr * risk
    d = 6 if close < 10 else 4 if close < 100 else 2
    return {"entry": round(close, d), "stop_loss": round(sl, d), "take_profit": round(tp, d),
            "risk_reward": rr, "trailing_tp": f"arm +1R, trail {k_stop}xATR (no cap)"}


class SignalSource:
    key = name = description = engine = ""

    def get(self, asset: str) -> Optional[dict]:
        raise NotImplementedError


class MarketMindSource(SignalSource):
    key, name = "marketmind", "MarketMind"
    description = "Crypto — spoof scalp + intraday + longterm (Binance order flow)"
    engine = "spoof-radar / EMA-RSI / momentum"

    # order-book observation window; the feed uses a short one so the endpoint
    # stays responsive (it is pure wall-clock sleep between depth snapshots).
    scalp_window_sec = float(os.getenv("MARKETMIND_SCALP_WINDOW_SEC", "0.35"))

    def get(self, asset: str) -> Optional[dict]:
        from .crypto_signals import CryptoSignalService
        svc = CryptoSignalService()
        intr = svc.intraday(asset) or {}
        return {"source": self.key, "engine": self.engine, "asset": asset,
                "direction": ("SELL" if intr.get("direction") == "short" else "BUY" if intr.get("direction") == "long" else "NONE"),
                "grade": intr.get("grade", "-"), "entry": intr.get("entry"),
                "stop_loss": intr.get("stop_loss"), "take_profit": intr.get("take_profit"),
                "risk_reward": intr.get("risk_reward"),
                "scalp": svc.scalp(asset, window_sec=self.scalp_window_sec),
                "story": "MarketMind intraday + live scalp from the order book."}


class WhaleSource(SignalSource):
    key, name = "whale", "Whale"
    description = "Better Volume 7-buffer engine (climax / churn / absorption)"
    engine = "BetterVolume 1.4"

    def get(self, asset: str) -> Optional[dict]:
        b = _bars(asset, "1h", 200)
        if b is None:
            return None
        highs, lows, closes, vols, opens = b
        r = bv.classify(highs, lows, closes, vols, opens)
        out = {"source": self.key, "engine": self.engine, "asset": asset,
               "direction": r.direction, "grade": r.grade, "story": r.story,
               "bv_color": r.color, "volume_ratio": r.volume_ratio,
               "entry": None, "stop_loss": None, "take_profit": None, "risk_reward": None}
        if r.direction != "NONE":
            atr = strat.atr(highs, lows, closes)
            out.update(_atr_plan(r.direction, float(closes[-1]), atr))
        return out


# Monster's timeframes -> Binance intervals (Binance serves all of them natively)
_TF_TO_BINANCE = {"M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h",
                  "H4": "4h", "D1": "1d", "W1": "1w"}


# assets that should come from the broker terminal rather than Binance
_MT5_ASSETS = {"gold", "xauusd", "silver", "eurusd", "gbpusd", "usdjpy"}


def _monster_bars(tf: str, symbol: str) -> list[dict]:
    """Bar provider for the vendored confluence engine.

    Broker (MT5) for gold/FX/metals — real bars and tick volume, which is what
    Better Volume expects. Binance for crypto. Falls back to Binance if the
    terminal isn't running, so the engine never goes dark.
    """
    tf_u = str(tf).upper()

    def _fetch():
        if symbol.lower() in _MT5_ASSETS:
            try:
                from .connectors import mt5 as mt5c
                if mt5c.is_available():
                    b = mt5c.bars(symbol, tf_u, 500)
                    if b:
                        return b
            except Exception:
                pass
        interval = _TF_TO_BINANCE.get(tf_u)
        if not interval:
            return []
        k = _bc.klines(symbol, interval, 500)
        return [{"t": b["t"], "o": b["open"], "h": b["high"],
                 "l": b["low"], "c": b["close"], "v": b["volume"]} for b in k]

    return _cached(("mon", symbol.lower(), tf_u), _fetch)


def _grade_from_score(score: float) -> str:
    """Confluence score -> A-tier ladder. Actionable starts at 68."""
    if score >= 85:
        return "A+"
    if score >= 76:
        return "A1"
    if score >= 68:
        return "A"
    if score >= 55:
        return "B"
    return "C"


class MonsterSource(SignalSource):
    key, name = "monster", "Monster"
    description = "Full confluence score — HTF · Better Volume retest · Session · 60-Agents · Quick"
    engine = "confluence-100pt"

    def get(self, asset: str, mode: str = "SWING") -> Optional[dict]:
        from .monster.confluence import ConfluenceEngine, set_bars_provider

        set_bars_provider(_monster_bars)
        r = ConfluenceEngine().analyze(mode=mode, symbol=asset)
        if r.get("status") != "ok":
            return {"source": self.key, "engine": self.engine, "asset": asset,
                    "direction": "NONE", "grade": "-", "story": r.get("message", "no data")}

        side = r.get("side", "WAIT")
        sc = r.get("score", {})
        best = max(sc.get("buy", 0), sc.get("sell", 0))
        direction = "BUY" if "CONFLUENCE BUY" in side else "SELL" if "CONFLUENCE SELL" in side else "NONE"
        grade = _grade_from_score(best)

        out = {
            "source": self.key, "engine": self.engine, "asset": asset,
            "direction": direction, "grade": grade,
            "confluence_score": best, "margin": sc.get("margin"),
            "tier": r.get("tier"), "story": r.get("reason"),
            "factors": r.get("factors", {}).get(sc.get("winner", "BUY").lower() if False else "buy"),
            "htf": r.get("htf"), "session": (r.get("session") or {}).get("state"),
            "bv_trigger": (r.get("bv_trigger") or {}).get("text"),
            "agent_pressure": (r.get("agent_pressure") or {}).get("pressure"),
            "mode": mode,
            "entry": None, "stop_loss": None, "take_profit": None, "risk_reward": None,
        }
        # levels from ATR on the entry timeframe
        if direction != "NONE":
            b = _bars(asset, "1h", 200)
            if b is not None:
                highs, lows, closes, _v, _o = b
                out.update(_atr_plan(direction, float(closes[-1]), strat.atr(highs, lows, closes)))
        return out


REGISTRY: dict[str, SignalSource] = {s.key: s for s in (MarketMindSource(), WhaleSource(), MonsterSource())}
ALL_KEYS = list(REGISTRY.keys())


MODES = ("off", "manual", "auto")   # off = ignore · manual = show only · auto = send to MT4/MT5


class SignalSelector:
    """Per-source mode (off / manual / auto), persisted. Simple: pick a source,
    set it Manual (just show the signal) or Auto (route it to MT4/MT5)."""

    def __init__(self):
        self.modes = self._load()

    def _load(self) -> dict[str, str]:
        modes = {k: "manual" for k in ALL_KEYS}   # safe default: show, don't auto-trade
        try:
            if os.path.exists(_SEL_FILE):
                saved = json.load(open(_SEL_FILE))
                for k, m in saved.items():
                    if k in REGISTRY and m in MODES:
                        modes[k] = m
        except Exception:
            pass
        return modes

    def _save(self):
        try:
            json.dump(self.modes, open(_SEL_FILE, "w"))
        except Exception:
            pass

    def set_mode(self, source: str, mode: str) -> dict[str, str]:
        source, mode = source.lower(), mode.lower()
        if source not in REGISTRY:
            raise ValueError(f"unknown source '{source}' — pick from {ALL_KEYS}")
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.modes[source] = mode
        self._save()
        return self.modes

    def set_modes(self, mapping: dict[str, str]) -> dict[str, str]:
        for k, m in mapping.items():
            self.set_mode(k, m)
        return self.modes

    def active(self) -> list[str]:
        return [k for k, m in self.modes.items() if m != "off"]

    def sources_info(self) -> list[dict]:
        return [{"key": s.key, "name": s.name, "description": s.description,
                 "engine": s.engine, "mode": self.modes.get(s.key, "off")} for s in REGISTRY.values()]

    def feed(self, asset: str, lots: float = 0.01) -> dict:
        """Signals for one asset from every active source. Auto-mode directional
        signals are routed to MT4/MT5 (executor); manual-mode are shown only."""
        from . import executor
        out = {}
        for key in self.active():
            mode = self.modes[key]
            try:
                sig = REGISTRY[key].get(asset)
            except Exception as exc:  # noqa: BLE001
                out[key] = {"source": key, "mode": mode, "error": str(exc)}
                continue
            if sig:
                sig["mode"] = mode
                if mode == "auto":
                    sig["execution"] = executor.route(sig, lots=lots)
            out[key] = sig
        return {"asset": asset, "modes": self.modes, "signals": out}


_selector: Optional[SignalSelector] = None


def get_selector() -> SignalSelector:
    global _selector
    if _selector is None:
        _selector = SignalSelector()
    return _selector
