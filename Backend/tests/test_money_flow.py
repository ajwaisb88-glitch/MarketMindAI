"""Offline tests for the money-flow engine (no network)."""
import app.money_flow as mf


def test_signed_dollar_flow_direction_and_scale():
    # up day then down day; flow is signed by price direction, returned in $B
    closes = [100.0, 110.0, 100.0]
    volumes = [0.0, 1e9, 2e9]
    # last bar only: price fell -> negative, 100 * 2e9 / 1e9 = -200
    assert mf.signed_dollar_flow(closes, volumes, 1) == -200.0
    # both bars: +110*1e9 then -100*2e9 -> (110 - 200) = -90
    assert mf.signed_dollar_flow(closes, volumes, 2) == -90.0


def test_signed_dollar_flow_needs_two_points():
    assert mf.signed_dollar_flow([100.0], [1e9], 1) == 0.0
    assert mf.signed_dollar_flow([], [], 1) == 0.0


def test_fred_returns_empty_without_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert mf.fetch_fred_liquidity() == {}


def test_fred_ignores_placeholder_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "your_fred_key_here")
    assert mf.fetch_fred_liquidity() == {}


def test_fmt_signs_dollars():
    assert mf._fmt(1.5).startswith("+$")
    assert mf._fmt(-1.5).startswith("-$")
