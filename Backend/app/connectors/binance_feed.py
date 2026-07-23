"""
Live Binance order-book feed for the spoofing radar.

This is the real-exchange adapter the manipulation engine was designed for:
it yields the same ``OrderBookSnapshot`` + ``FlowEvent`` objects the synthetic
``OrderBookFeed`` produces, so ``spoofing_probability`` and everything
downstream run unchanged — only now on live data.

Method: take two depth snapshots a short window apart plus the trades in
between. Trades come from aggTrades; adds/cancels are inferred by diffing the
two snapshots per price level (a resting size that shrinks with no matching
trade is a cancellation — the spoofing tell). This is REST-poll based; the
WebSocket depth-diff stream is the precise upgrade, same objects out.
"""
from __future__ import annotations

import time

import numpy as np

from ..manipulation import FlowEvent, OrderBookSnapshot, spoofing_probability
from .binance import BinanceConnector


class BinanceOrderBookFeed:
    def __init__(self, connector: BinanceConnector | None = None):
        self.bc = connector or BinanceConnector()

    @staticmethod
    def _tick(prices: list[float]) -> float:
        """Estimate tick size from the median gap between adjacent levels."""
        if len(prices) < 2:
            return 0.01
        gaps = np.abs(np.diff(sorted(prices)))
        gaps = gaps[gaps > 0]
        return float(np.median(gaps)) if len(gaps) else 0.01

    def _snapshot(self, depth: dict) -> OrderBookSnapshot:
        return OrderBookSnapshot(
            bid_prices=np.array(depth["bid_prices"], dtype=float),
            bid_sizes=np.array(depth["bid_sizes"], dtype=float),
            ask_prices=np.array(depth["ask_prices"], dtype=float),
            ask_sizes=np.array(depth["ask_sizes"], dtype=float),
            ts=time.time(),
        )

    def observe(self, symbol: str, window_sec: float = 1.0) -> tuple[OrderBookSnapshot, list[FlowEvent]]:
        """One (snapshot, flow-window) pair from live Binance data."""
        d0 = self.bc.raw_depth(symbol, 100)
        t0 = self.bc.raw_agg_trades(symbol, 500)
        time.sleep(window_sec)
        d1 = self.bc.raw_depth(symbol, 100)
        snap = self._snapshot(d1)
        mid = snap.mid
        tick = self._tick(d1["bid_prices"] + d1["ask_prices"])
        events: list[FlowEvent] = []

        # Trades in the window (aggressor side + distance from mid)
        cutoff = (t0[0]["t"] if t0 else 0)
        for tr in self.bc.raw_agg_trades(symbol, 500):
            side = "ask" if not tr["m"] else "bid"   # m=False → aggressor bought (hit ask)
            dist = abs(tr["price"] - mid) / tick if tick else 0.0
            events.append(FlowEvent(ts=tr["t"] / 1000.0, side=side, action="trade",
                                    size=tr["qty"], distance_ticks=dist))

        events += self._diff_events(d0, d1, mid, tick)
        return snap, events

    def _diff_events(self, d0: dict, d1: dict, mid: float, tick: float) -> list[FlowEvent]:
        """Calibrated add/cancel events from a depth diff (pure — unit-tested).

        Cuts false positives from normal market-maker churn:
          - only levels within BAND_TICKS of the mid (ignore book-edge shifts
            caused purely by price drifting — not order pulls);
          - only size changes above the churn threshold (`_min_size`);
          - net a cancel against a near-simultaneous add on the same side within
            `replace_ticks` (a reprice/replace, not a spoof pull).
        """
        events: list[FlowEvent] = []
        band = self.BAND_TICKS
        min_size = self._min_size(d1)
        for side, pk, sk in (("bid", "bid_prices", "bid_sizes"), ("ask", "ask_prices", "ask_sizes")):
            a = dict(zip(d0[pk], d0[sk]))
            b = dict(zip(d1[pk], d1[sk]))
            adds: list[list] = []       # [price, size]
            cancels: list[tuple[float, float]] = []
            for price, size_b in b.items():
                if (abs(price - mid) / tick if tick else 0.0) > band:
                    continue
                grew = size_b - a.get(price, 0.0)
                if grew > min_size:
                    adds.append([price, grew])
            for price, size_a in a.items():
                if (abs(price - mid) / tick if tick else 0.0) > band:
                    continue
                pulled = size_a - b.get(price, 0.0)
                if pulled > min_size:
                    cancels.append((price, pulled))
            for price, pulled in cancels:
                net = pulled
                for pair in adds:                      # net off a nearby reprice
                    if pair[1] > 0 and abs(pair[0] - price) / tick <= self.replace_ticks:
                        used = min(net, pair[1])
                        net -= used
                        pair[1] -= used
                        if net <= 0:
                            break
                if net > min_size:
                    events.append(FlowEvent(time.time(), side, "cancel", net,
                                            abs(price - mid) / tick if tick else 0.0))
            for price, grew in adds:
                if grew > min_size:
                    events.append(FlowEvent(time.time(), side, "add", grew,
                                            abs(price - mid) / tick if tick else 0.0))
        return events

    BAND_TICKS: float = 25.0        # only diff levels within this many ticks of mid
    replace_ticks: float = 2.0      # a cancel matched by an add within this many ticks = reprice

    @staticmethod
    def _min_size(depth: dict) -> float:
        """Ignore size changes below the 40th percentile of resting sizes (churn)."""
        sizes = np.array(depth["bid_sizes"] + depth["ask_sizes"], dtype=float)
        sizes = sizes[sizes > 0]
        return float(np.percentile(sizes, 40)) if len(sizes) else 0.0

    def report(self, symbol: str, window_sec: float = 1.0):
        """Live spoofing report for a symbol."""
        snap, events = self.observe(symbol, window_sec)
        return spoofing_probability(snap, events)
