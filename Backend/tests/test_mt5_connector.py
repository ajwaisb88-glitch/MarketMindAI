"""MT5 connector must degrade gracefully when no terminal/package is present.

These run in CI (no MetaTrader5, no terminal), so every call must return a safe
empty value rather than raising, and the bars provider must fall back to Binance.
"""
import app.connectors.mt5 as m
import app.signal_sources as ss


def _no_mt5(monkeypatch):
    monkeypatch.setattr(m, "_mt5", lambda: None)
    monkeypatch.setattr(m, "_started", False, raising=False)


def test_connect_false_without_package(monkeypatch):
    _no_mt5(monkeypatch)
    assert m.connect() is False
    assert m.is_available() is False


def test_reads_return_safe_empties_without_terminal(monkeypatch):
    _no_mt5(monkeypatch)
    assert m.bars("gold", "H1") == []
    assert m.quote("gold") is None
    assert m.account() is None
    assert m.symbol_limits("gold") is None
    assert m.depth("gold") is None
    assert m.resolve_symbol("gold") is None


def test_symbol_candidates_cover_common_broker_suffixes():
    for cand in ("XAUUSD", "GOLD", "XAUUSD.m"):
        assert cand in m.SYMBOL_CANDIDATES["gold"]
    assert "EURUSD" in m.SYMBOL_CANDIDATES["eurusd"]


def test_monster_bars_falls_back_to_binance_when_mt5_absent(monkeypatch):
    _no_mt5(monkeypatch)
    called = {}

    class _FakeBC:
        def klines(self, sym, interval, limit):
            called["interval"] = interval
            return [{"t": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}]

    monkeypatch.setattr(ss, "_bc", _FakeBC())
    out = ss._monster_bars("H1", "gold")          # gold is an MT5 asset...
    assert called["interval"] == "1h"              # ...but fell back to Binance
    assert out and out[0]["c"] == 1.5 and out[0]["v"] == 10.0


def test_monster_bars_rejects_unknown_timeframe(monkeypatch):
    _no_mt5(monkeypatch)
    assert ss._monster_bars("M3", "btc") == []
