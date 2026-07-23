"""Offline tests for the Binance connector + order-book feed (no network).

The HTTP layer (`BinanceConnector._get`) is monkeypatched with canned Binance
responses, so these run deterministically in CI. Live behaviour is exercised
separately/manually — here we lock the parsing and the derived microstructure
math (order-flow delta, book imbalance, snapshot-diff cancels).
"""
import numpy as np
import pytest

from app.connectors.binance import BinanceConnector, BookImbalance, OrderFlow
from app.connectors.binance_feed import BinanceOrderBookFeed


# ── canned Binance payloads ──
_KLINES = [
    [1, "100.0", "110.0", "90.0", "105.0", "12.5", 2, "0", 3, "0", "0", "0"],
    [2, "105.0", "120.0", "104.0", "118.0", "20.0", 3, "0", 4, "0", "0", "0"],
]
_DEPTH = {
    "bids": [["100.0", "5.0"], ["99.0", "3.0"], ["98.0", "2.0"]],
    "asks": [["101.0", "1.0"], ["102.0", "1.0"], ["103.0", "1.0"]],
}
_AGG = [
    {"T": 1000, "p": "100.5", "q": "2.0", "m": False},  # aggressor BUY
    {"T": 1001, "p": "100.4", "q": "1.0", "m": True},   # aggressor SELL
    {"T": 1002, "p": "100.6", "q": "0.5", "m": False},  # aggressor BUY
]


@pytest.fixture
def bc(monkeypatch):
    c = BinanceConnector()
    def fake_get(path, params):
        if "klines" in path:
            return _KLINES
        if "depth" in path:
            return _DEPTH
        if "aggTrades" in path:
            return _AGG
        return None
    monkeypatch.setattr(c, "_get", fake_get)
    return c


def test_klines_parse(bc):
    k = bc.klines("btc", "1h", 2)
    assert len(k) == 2
    assert k[-1]["close"] == 118.0 and k[-1]["high"] == 120.0


def test_order_book_imbalance_sign(bc):
    ob = bc.order_book("btc")
    assert isinstance(ob, BookImbalance)
    assert ob.bid_volume == 10.0 and ob.ask_volume == 3.0
    assert ob.imbalance > 0            # bids stacked → positive
    assert ob.spread == pytest.approx(1.0)


def test_order_flow_delta_sign(bc):
    of = bc.agg_trades("btc")
    assert isinstance(of, OrderFlow)
    assert of.buy_volume == pytest.approx(2.5)   # 2.0 + 0.5
    assert of.sell_volume == pytest.approx(1.0)
    assert of.delta == pytest.approx(1.5)
    assert of.pressure > 0                        # net buyers


def test_symbol_resolution(bc):
    assert bc.resolve("btc") == "BTCUSDT"
    assert bc.resolve("ETH-USD") == "ETHUSDT"
    assert bc.resolve("XRPUSDT") == "XRPUSDT"     # passthrough
    # gold routes to PAX Gold (Binance has no XAUUSDT)
    assert bc.resolve("gold") == "PAXGUSDT"
    assert bc.resolve("xauusd") == "PAXGUSDT"
    assert bc.resolve("xauusdt") == "PAXGUSDT"


def test_feed_tick_and_snapshot():
    feed = BinanceOrderBookFeed()
    tick = feed._tick([100.0, 99.0, 98.0, 101.0, 102.0])
    assert tick == pytest.approx(1.0)
    snap = feed._snapshot({
        "bid_prices": [100.0, 99.0], "bid_sizes": [5.0, 3.0],
        "ask_prices": [101.0, 102.0], "ask_sizes": [1.0, 1.0],
    })
    assert snap.mid == pytest.approx(100.5)
    assert snap.spread == pytest.approx(1.0)
    assert isinstance(snap.bid_sizes, np.ndarray)
