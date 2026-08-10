"""Tests for the long-term + intraday strategy engines."""

import numpy as np
import pytest

from app import strategies as s


# --- indicators -----------------------------------------------------------

def test_sma_and_ema_track_level():
    x = np.full(50, 10.0)
    assert s.sma(x, 20) == pytest.approx(10.0)
    assert s.ema(x, 10)[-1] == pytest.approx(10.0)


def test_rsi_bounds():
    up = np.arange(1, 60, dtype=float)          # monotonic up -> RSI 100
    down = np.arange(60, 1, -1, dtype=float)     # monotonic down -> RSI 0
    assert s.rsi(up) == 100.0
    assert s.rsi(down) == 0.0
    assert 0.0 <= s.rsi(np.random.default_rng(0).normal(50, 5, 100)) <= 100.0


def test_atr_positive():
    h, l, c = s.synthetic_ohlc(n=100, seed=1)
    assert s.atr(h, l, c) > 0


# --- synthetic data -------------------------------------------------------

def test_synthetic_ohlc_is_valid_and_deterministic():
    h1, l1, c1 = s.synthetic_ohlc(n=300, seed=5)
    h2, l2, c2 = s.synthetic_ohlc(n=300, seed=5)
    assert np.allclose(c1, c2)                    # deterministic
    assert np.all(h1 >= c1) and np.all(c1 >= l1)  # high >= close >= low
    assert np.all(h1 >= l1)


# --- signals --------------------------------------------------------------

def test_intraday_signal_levels_bracket_entry():
    h, l, c = s.synthetic_ohlc(n=600, seed=3)
    sig = s.intraday_signal(h, l, c)
    assert sig.horizon == "intraday"
    if sig.direction == "long":
        assert sig.stop_loss < sig.entry < sig.take_profit
    elif sig.direction == "short":
        assert sig.take_profit < sig.entry < sig.stop_loss
    assert sig.grade in {"A+", "A1", "A", "B", "C", "D", "F", "NO-TRADE"}


def test_longterm_signal_needs_history():
    _, _, c = s.synthetic_ohlc(n=40, seed=1)
    assert s.longterm_signal(c).grade == "NO-TRADE"      # <60 bars
    h, l, c = s.synthetic_ohlc(n=600, seed=2)
    sig = s.longterm_signal(c, h, l)
    assert sig.horizon == "long-term"
    if sig.direction != "flat":
        assert sig.risk_reward == pytest.approx(2.0)


def test_uptrend_gives_long_bias():
    # strong steady uptrend -> long-term should read long
    n = 400
    c = 100 * np.exp(np.cumsum(np.full(n, 0.004)))
    h, l = c * 1.005, c * 0.995
    sig = s.longterm_signal(c, h, l)
    assert sig.direction == "long"


# --- backtest -------------------------------------------------------------

def test_backtest_returns_valid_metrics():
    h, l, c = s.synthetic_ohlc(n=900, seed=7)
    r = s.backtest(h, l, c, s.intraday_signal, warmup=210, max_hold=12)
    assert r["trades"] >= 0
    assert 0.0 <= r["win_rate"] <= 1.0
    assert "total_return_pct" in r and "max_drawdown_pct" in r


def test_backtest_no_lookahead_dispatch():
    # longterm_signal takes closes only; intraday takes highs/lows/closes.
    h, l, c = s.synthetic_ohlc(n=900, seed=8)
    assert s.backtest(h, l, c, s.longterm_signal, max_hold=30)["trades"] >= 0
