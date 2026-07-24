"""
Binance connector — live crypto data with NO API key (public market data).

Gives the three things Yahoo never could:
  - klines()      : OHLCV history / real volume (signals)
  - order_book()  : live bids/asks = pending orders / DOM (spoofing radar)
  - agg_trades()  : trades tagged buyer/seller = real order flow (delta / CVD)

Public endpoints need no key and are near real-time. A key is only ever needed
for placing orders (not done here — this is data only).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import requests

# klines are shared by several engines in one pass — cache briefly
_KLINE_TTL = float(os.getenv("MARKETMIND_KLINE_TTL_SEC", "10"))
_KLINE_CACHE: dict[tuple, tuple[float, list]] = {}

# Primary host; binance.us is the fallback for US-restricted regions.
_HOSTS = ("https://api.binance.com", "https://api.binance.us")
_TIMEOUT = 15

# app symbol -> Binance symbol
# Gold: Binance has no XAUUSDT, but PAXGUSDT (PAX Gold, a gold-backed token)
# tracks spot gold with a real live order book — the tradeable gold proxy here.
SYMBOL_MAP = {
    "BTC-USD": "BTCUSDT", "ETH-USD": "ETHUSDT",
    "DOGE-USD": "DOGEUSDT", "SHIB-USD": "SHIBUSDT", "PEPE-USD": "PEPEUSDT",
    "USDT-USD": "USDCUSDT", "USDC-USD": "USDCUSDT",
    "btc": "BTCUSDT", "eth": "ETHUSDT", "doge": "DOGEUSDT",
    # gold via PAX Gold token
    "gold": "PAXGUSDT", "xauusd": "PAXGUSDT", "xauusdt": "PAXGUSDT", "paxg": "PAXGUSDT",
}


@dataclass
class OrderFlow:
    """Order-flow summary from recent aggregate trades."""
    buy_volume: float
    sell_volume: float
    delta: float          # buy - sell (net aggressive flow)
    cvd: float            # same as delta over the window (cumulative if chained)
    trades: int

    @property
    def pressure(self) -> float:
        tot = self.buy_volume + self.sell_volume
        return round((self.delta / tot), 4) if tot else 0.0


@dataclass
class BookImbalance:
    """Order-book snapshot → pending-order pressure (feeds spoofing radar)."""
    bid_volume: float
    ask_volume: float
    best_bid: float
    best_ask: float
    imbalance: float      # (bid-ask)/(bid+ask), + = buy-side stacked

    @property
    def spread(self) -> float:
        return round(self.best_ask - self.best_bid, 8)


class BinanceConnector:
    def __init__(self):
        self._host = None

    def _get(self, path: str, params: dict) -> Optional[list | dict]:
        hosts = (self._host,) + _HOSTS if self._host else _HOSTS
        for host in hosts:
            if host is None:
                continue
            try:
                r = requests.get(f"{host}{path}", params=params, timeout=_TIMEOUT)
                if r.status_code == 200:
                    self._host = host
                    return r.json()
            except Exception:
                continue
        return None

    def resolve(self, symbol: str) -> str:
        return SYMBOL_MAP.get(symbol, symbol.replace("-", "").upper())

    def klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> list[dict]:
        """OHLCV bars. interval: 1m,5m,15m,30m,1h,4h,1d,1w …

        Cached for _KLINE_TTL seconds — several engines request the same series
        in one pass, and a bar hasn't changed within that window anyway.
        """
        key = (self.resolve(symbol), interval, limit)
        now = time.time()
        hit = _KLINE_CACHE.get(key)
        if hit and (now - hit[0]) < _KLINE_TTL:
            return hit[1]
        data = self._get("/api/v3/klines", {"symbol": key[0], "interval": interval, "limit": limit})
        if not isinstance(data, list):
            return []
        out = [{
            "t": int(k[0]), "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
        } for k in data]
        _KLINE_CACHE[key] = (now, out)
        return out

    def order_book(self, symbol: str, limit: int = 100) -> Optional[BookImbalance]:
        """Live DOM. Aggregated bid/ask volume = pending-order pressure."""
        data = self._get("/api/v3/depth", {"symbol": self.resolve(symbol), "limit": limit})
        if not isinstance(data, dict) or not data.get("bids"):
            return None
        bids = [(float(p), float(q)) for p, q in data["bids"]]
        asks = [(float(p), float(q)) for p, q in data["asks"]]
        bidv = sum(q for _, q in bids)
        askv = sum(q for _, q in asks)
        tot = bidv + askv
        return BookImbalance(
            bid_volume=bidv, ask_volume=askv,
            best_bid=bids[0][0], best_ask=asks[0][0],
            imbalance=round((bidv - askv) / tot, 4) if tot else 0.0,
        )

    def raw_depth(self, symbol: str, limit: int = 100) -> Optional[dict]:
        """Raw L2 levels as numpy-ready lists — for building an OrderBookSnapshot."""
        data = self._get("/api/v3/depth", {"symbol": self.resolve(symbol), "limit": limit})
        if not isinstance(data, dict) or not data.get("bids"):
            return None
        bids = [(float(p), float(q)) for p, q in data["bids"]]
        asks = [(float(p), float(q)) for p, q in data["asks"]]
        return {
            "bid_prices": [p for p, _ in bids], "bid_sizes": [q for _, q in bids],
            "ask_prices": [p for p, _ in asks], "ask_sizes": [q for _, q in asks],
        }

    def raw_agg_trades(self, symbol: str, limit: int = 500) -> list[dict]:
        """Raw recent trades: [{t, price, qty, buyer_is_maker}] for flow events."""
        data = self._get("/api/v3/aggTrades", {"symbol": self.resolve(symbol), "limit": limit})
        if not isinstance(data, list):
            return []
        return [{"t": int(x["T"]), "price": float(x["p"]), "qty": float(x["q"]), "m": bool(x["m"])} for x in data]

    def agg_trades(self, symbol: str, limit: int = 500) -> Optional[OrderFlow]:
        """Recent trades → order flow. `m`=True means the buyer was the maker,
        i.e. the aggressor SOLD; `m`=False means the aggressor BOUGHT."""
        data = self._get("/api/v3/aggTrades", {"symbol": self.resolve(symbol), "limit": limit})
        if not isinstance(data, list) or not data:
            return None
        buy = sell = 0.0
        for t in data:
            q = float(t["q"])
            if t.get("m"):
                sell += q
            else:
                buy += q
        return OrderFlow(buy_volume=buy, sell_volume=sell, delta=buy - sell, cvd=buy - sell, trades=len(data))
