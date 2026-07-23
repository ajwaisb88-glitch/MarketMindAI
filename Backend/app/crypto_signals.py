"""
Crypto signal service — the MarketMind (crypto) side, on live Binance data.

Produces the three SEPARATE crypto signal types (kept independent, never
blended — per project rule):
  - scalp    : spoofing radar reads the live order book (binance_feed)
  - intraday : EMA 9/21 + RSI + ATR on 15m klines (strategies.intraday_signal)
  - longterm : SMA 50/200 + momentum on 1d klines (strategies.longterm_signal)

All fed by Binance (key-free). Gold uses a different engine + MT5 entirely.
"""
from __future__ import annotations

import numpy as np

from .connectors.binance import BinanceConnector
from .connectors.binance_feed import BinanceOrderBookFeed
from .strategies import intraday_signal, longterm_signal


class CryptoSignalService:
    def __init__(self):
        self.bc = BinanceConnector()
        self.feed = BinanceOrderBookFeed(self.bc)

    def _ohlc(self, symbol: str, interval: str, limit: int = 300):
        k = self.bc.klines(symbol, interval, limit)
        if not k:
            return None
        highs = np.array([b["high"] for b in k], dtype=float)
        lows = np.array([b["low"] for b in k], dtype=float)
        closes = np.array([b["close"] for b in k], dtype=float)
        return highs, lows, closes

    def intraday(self, symbol: str) -> dict | None:
        o = self._ohlc(symbol, "15m", 300)
        if o is None:
            return None
        return intraday_signal(*o).as_dict()

    def longterm(self, symbol: str) -> dict | None:
        o = self._ohlc(symbol, "1d", 300)
        if o is None:
            return None
        h, l, c = o
        return longterm_signal(c, h, l).as_dict()

    def scalp(self, symbol: str, window_sec: float = 1.0) -> dict:
        r = self.feed.report(symbol, window_sec)
        return {
            "type": "scalp", "symbol": symbol,
            "spoof_probability": r.probability, "pressure_side": r.pressure_side,
            "direction": ("BUY" if r.predicted_move > 0 else "SELL" if r.predicted_move < 0 else "NONE"),
            "label": r.label,
        }

    def all_signals(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "scalp": self.scalp(symbol),
            "intraday": self.intraday(symbol),
            "longterm": self.longterm(symbol),
        }
