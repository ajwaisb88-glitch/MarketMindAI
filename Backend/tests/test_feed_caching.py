"""Caching must speed up polling without ever serving stale data as fresh."""
import time

import app.signal_sources as ss
from app.connectors import binance_feed as bf


def test_bar_cache_collapses_duplicate_fetches(monkeypatch):
    calls = {"n": 0}

    class _FakeBC:
        def klines(self, sym, interval, limit):
            calls["n"] += 1
            return [{"t": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 9.0}]

    monkeypatch.setattr(ss, "_bc", _FakeBC())
    monkeypatch.setattr(ss, "_MT5_ASSETS", set())      # force the Binance path
    ss.clear_bar_cache()
    for _ in range(5):
        ss._monster_bars("H1", "btc")
    assert calls["n"] == 1                              # 5 requests, 1 fetch


def test_bar_cache_expires(monkeypatch):
    calls = {"n": 0}

    class _FakeBC:
        def klines(self, sym, interval, limit):
            calls["n"] += 1
            return [{"t": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 9.0}]

    monkeypatch.setattr(ss, "_bc", _FakeBC())
    monkeypatch.setattr(ss, "_MT5_ASSETS", set())
    monkeypatch.setattr(ss, "_BAR_TTL", 0.05)
    ss.clear_bar_cache()
    ss._monster_bars("H1", "btc")
    time.sleep(0.08)
    ss._monster_bars("H1", "btc")
    assert calls["n"] == 2                              # refetched after expiry


def test_spoof_report_cached_then_refreshed(monkeypatch):
    observed = {"n": 0}

    class _Rep:
        probability = 42

    def _fake_observe(self, symbol, window_sec=1.0):
        observed["n"] += 1
        return ("snap", [])

    monkeypatch.setattr(bf.BinanceOrderBookFeed, "observe", _fake_observe)
    monkeypatch.setattr(bf, "spoofing_probability", lambda s, e: _Rep())
    bf._REPORT_CACHE.clear()

    f = bf.BinanceOrderBookFeed()
    f.report("btc", 0.1, max_age=60)
    f.report("btc", 0.1, max_age=60)
    assert observed["n"] == 1                           # second served from cache

    f.report("btc", 0.1, max_age=0)                     # explicit fresh read
    assert observed["n"] == 2


def test_scalp_window_is_short_for_the_feed():
    # the feed's observe window is wall-clock sleep — keep it small
    assert ss.MarketMindSource.scalp_window_sec <= 0.5
