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


def test_marketmind_uses_15m_and_higher_only():
    # minimum-timeframe policy: no sub-15m scalp (that's what made the signal
    # flip every tick). MarketMind confirms across 15m and higher only.
    allowed = {"15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w"}
    assert set(ss.MarketMindSource._TFS) <= allowed
    assert "15m" in ss.MarketMindSource._TFS
    assert not hasattr(ss.MarketMindSource, "scalp_window_sec")


def test_report_cached_never_blocks_the_caller(monkeypatch):
    """The polling path must not run the slow order-book observation inline."""
    observed = {"n": 0}

    def _slow_observe(self, symbol, window_sec=1.0):
        observed["n"] += 1
        time.sleep(0.5)                 # would stall the request if called inline
        return ("snap", [])

    class _Rep:
        probability = 10
        predicted_move = 0
    monkeypatch.setattr(bf.BinanceOrderBookFeed, "observe", _slow_observe)
    monkeypatch.setattr(bf, "spoofing_probability", lambda s, e: _Rep())
    bf._REPORT_CACHE.clear(); bf._REFRESH_INFLIGHT.clear()

    f = bf.BinanceOrderBookFeed()
    t0 = time.time()
    first = f.report_cached("btc", 0.1, stale_after=0)   # empty cache
    assert (time.time() - t0) < 0.2                        # returned immediately
    assert first is None                                   # nothing cached yet
    # the background thread eventually fills the cache
    for _ in range(30):
        if bf._REPORT_CACHE.get("btc"):
            break
        time.sleep(0.05)
    assert bf._REPORT_CACHE.get("btc") is not None
    assert observed["n"] == 1                              # observed once, off-thread
