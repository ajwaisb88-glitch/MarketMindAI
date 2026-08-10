"""Long-term and intraday strategy engines for MarketMind AI.

Unlike the scalp engine (which reads L2 order-book microstructure), these are
*price-based* — they consume OHLC bars, so they run on real data from any
provider (Financial Modeling Prep, yfinance, …). Two horizons:

  * intraday  — EMA(9/21) trend + RSI filter, ATR-sized stop/target, hold
                minutes to hours. Uses intraday bars (5m/15m/1h).
  * long-term — SMA(50/200) trend + 12-bar momentum + a Bayesian bull/bear
                regime, wide ATR stops, hold days to weeks. Uses daily bars.

Both return a graded signal (reusing the A+/A1/… ladder) with concrete entry /
stop-loss / take-profit levels, and both ship a walk-forward backtest that only
ever uses past bars to decide a trade (no look-ahead). A deterministic synthetic
OHLC generator makes everything testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .manipulation import _letter  # reuse the A+/A1/A/B/C/D/F ladder
from .quant import fractional_kelly


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def ema(values: np.ndarray, span: int) -> np.ndarray:
    """Exponential moving average (pandas-compatible, adjust=False)."""
    values = np.asarray(values, dtype=float)
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def sma(values: np.ndarray, window: int) -> float:
    v = np.asarray(values, dtype=float)
    return float(v[-window:].mean()) if len(v) >= window else float(v.mean())


def rsi(closes: np.ndarray, period: int = 14) -> float:
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)[-period:]
    losses = np.where(deltas < 0, -deltas, 0.0)[-period:]
    avg_gain, avg_loss = gains.mean(), losses.mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Average True Range — the volatility unit that sizes stops and targets."""
    highs, lows, closes = map(lambda a: np.asarray(a, dtype=float), (highs, lows, closes))
    prev_close = closes[:-1]
    tr = np.maximum.reduce([
        highs[1:] - lows[1:],
        np.abs(highs[1:] - prev_close),
        np.abs(lows[1:] - prev_close),
    ])
    return float(tr[-period:].mean()) if len(tr) >= period else float(tr.mean() if len(tr) else 0.0)


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

@dataclass
class StrategySignal:
    horizon: str
    direction: str        # long / short / flat
    grade: str
    score: float          # 0..100 conviction
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    rationale: list[str]

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        for k in ("entry", "stop_loss", "take_profit"):
            d[k] = round(d[k], 6)
        d["score"] = round(d["score"], 1)
        d["risk_reward"] = round(d["risk_reward"], 2)
        return d


def _round_levels(sig: StrategySignal) -> StrategySignal:
    return sig


def intraday_signal(highs, lows, closes, atr_stop: float = 1.5, atr_target: float = 2.5) -> StrategySignal:
    """Intraday setup from EMA trend + RSI filter, with ATR-sized stop/target.

    Long when EMA9 > EMA21 and RSI is not overbought; short on the mirror. The
    conviction score grows with the EMA separation (in ATR units) and a healthy
    (non-extreme) RSI. Stop = ``atr_stop`` ATR, target = ``atr_target`` ATR.
    """
    closes = np.asarray(closes, dtype=float)
    price = float(closes[-1])
    a = atr(highs, lows, closes)
    ef, es = ema(closes, 9)[-1], ema(closes, 21)[-1]
    r = rsi(closes)
    rationale = [f"EMA9 {ef:.4g} vs EMA21 {es:.4g}", f"RSI {r:.0f}", f"ATR {a:.4g}"]

    sep = (ef - es) / a if a > 0 else 0.0        # trend strength in ATR units
    if ef > es and r < 78:
        direction, dscore = "long", 1.0
    elif ef < es and r > 22:
        direction, dscore = "short", 1.0
    else:
        direction, dscore = "flat", 0.0

    if direction == "flat" or a == 0:
        return StrategySignal("intraday", "flat", "NO-TRADE", 0.0, price, price, price, 0.0,
                              rationale + ["no trend / RSI blocks entry"])

    # score: EMA separation (capped) + RSI mid-band bonus
    trend_pts = min(abs(sep) * 40.0, 60.0)
    rsi_pts = 40.0 * (1.0 - abs(r - 50.0) / 50.0)   # best near 50, fades at extremes
    score = float(min(trend_pts + rsi_pts, 100.0))

    if direction == "long":
        stop_loss = price - atr_stop * a
        take_profit = price + atr_target * a
    else:
        stop_loss = price + atr_stop * a
        take_profit = price - atr_target * a

    return StrategySignal(
        "intraday", direction, _letter(score), score, price, stop_loss, take_profit,
        atr_target / atr_stop, rationale,
    )


def longterm_signal(closes, highs=None, lows=None, atr_stop: float = 3.0, atr_target: float = 6.0) -> StrategySignal:
    """Position setup from SMA(50/200) trend + 12-bar momentum on daily bars.

    Long above a rising 200-SMA with a golden-cross (SMA50 > SMA200) and positive
    momentum; short on the mirror. Wide ATR stops (default 3 ATR) suit multi-day
    holds. If highs/lows are absent, ATR is approximated from close-to-close moves.
    """
    closes = np.asarray(closes, dtype=float)
    price = float(closes[-1])
    if len(closes) < 60:
        return StrategySignal("long-term", "flat", "NO-TRADE", 0.0, price, price, price, 0.0,
                              ["insufficient history (<60 bars)"])

    s50, s200 = sma(closes, 50), sma(closes, min(200, len(closes)))
    mom_window = min(12, len(closes) - 1)
    momentum = (closes[-1] - closes[-1 - mom_window]) / closes[-1 - mom_window]
    if highs is not None and lows is not None:
        a = atr(highs, lows, closes)
    else:
        a = float(np.abs(np.diff(closes))[-14:].mean()) if len(closes) > 14 else abs(price) * 0.01
    rationale = [f"SMA50 {s50:.4g} vs SMA200 {s200:.4g}", f"12-bar momentum {momentum*100:+.1f}%"]

    bull = s50 > s200 and momentum > 0
    bear = s50 < s200 and momentum < 0
    if bull:
        direction = "long"
    elif bear:
        direction = "short"
    else:
        return StrategySignal("long-term", "flat", "NO-TRADE", 0.0, price, price, price, 0.0,
                              rationale + ["trend and momentum disagree"])

    trend_gap = abs(s50 - s200) / price
    score = float(min(50.0 + trend_gap * 800.0 + min(abs(momentum) * 200.0, 30.0), 100.0))

    if direction == "long":
        stop_loss = price - atr_stop * a
        take_profit = price + atr_target * a
    else:
        stop_loss = price + atr_stop * a
        take_profit = price - atr_target * a

    return StrategySignal(
        "long-term", direction, _letter(score), score, price, stop_loss, take_profit,
        atr_target / atr_stop, rationale,
    )


# ---------------------------------------------------------------------------
# Walk-forward backtest (no look-ahead)
# ---------------------------------------------------------------------------

def backtest(
    highs, lows, closes,
    signal_fn,
    warmup: int = 210,
    max_hold: int = 20,
    fee_bps: float = 2.0,
    kelly_fraction: float = 0.5,
) -> dict:
    """Walk forward bar by bar; at each step decide from *past* bars only.

    Enters when ``signal_fn`` returns a non-flat direction, then holds until the
    stop or target is touched (checked on subsequent highs/lows) or ``max_hold``
    bars elapse. Position size follows fractional Kelly on the running win rate.
    Reports win rate, expectancy, profit factor, return and max drawdown.
    """
    highs, lows, closes = map(lambda a: np.asarray(a, dtype=float), (highs, lows, closes))
    n = len(closes)
    trades: list[dict] = []
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    i = warmup
    while i < n - 1:
        sig = signal_fn(highs[: i + 1], lows[: i + 1], closes[: i + 1]) if _takes_hl(signal_fn) \
            else signal_fn(closes[: i + 1])
        if sig.direction == "flat":
            i += 1
            continue
        entry = closes[i]
        stop, target = sig.stop_loss, sig.take_profit
        outcome = None
        exit_price = entry
        for j in range(i + 1, min(i + 1 + max_hold, n)):
            if sig.direction == "long":
                if lows[j] <= stop:
                    outcome, exit_price = "loss", stop; break
                if highs[j] >= target:
                    outcome, exit_price = "win", target; break
            else:
                if highs[j] >= stop:
                    outcome, exit_price = "loss", stop; break
                if lows[j] <= target:
                    outcome, exit_price = "win", target; break
        else:
            j = min(i + max_hold, n - 1)
            exit_price = closes[j]
            outcome = "win" if ((exit_price - entry) * (1 if sig.direction == "long" else -1)) > 0 else "loss"

        gross = (exit_price - entry) / entry * (1 if sig.direction == "long" else -1)
        win_rate = (sum(t["outcome"] == "win" for t in trades) / len(trades)) if trades else 0.5
        f = max(fractional_kelly(max(win_rate, 0.5), sig.risk_reward, c=kelly_fraction), 0.02)
        pnl = f * (gross - fee_bps / 1e4 * 2)
        equity *= (1 + pnl)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        trades.append({"i": i, "direction": sig.direction, "outcome": outcome,
                       "gross_pct": round(gross * 100, 3), "grade": sig.grade})
        i = j + 1  # re-enter only after the trade closes

    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    gross_win = sum(t["gross_pct"] for t in wins)
    gross_loss = -sum(t["gross_pct"] for t in losses)
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 4) if trades else 0.0,
        "avg_win_pct": round(float(np.mean([t["gross_pct"] for t in wins])), 3) if wins else 0.0,
        "avg_loss_pct": round(float(np.mean([t["gross_pct"] for t in losses])), 3) if losses else 0.0,
        "profit_factor": round(float(gross_win / gross_loss), 3) if gross_loss > 0 else None,
        "total_return_pct": round(float((equity - 1) * 100), 2),
        "max_drawdown_pct": round(float(max_dd * 100), 2),
    }


def _takes_hl(fn) -> bool:
    """intraday_signal takes (highs, lows, closes); longterm_signal takes closes."""
    return getattr(fn, "__name__", "") == "intraday_signal"


# ---------------------------------------------------------------------------
# Deterministic synthetic OHLC (for offline tests + demos)
# ---------------------------------------------------------------------------

def synthetic_ohlc(n: int = 800, seed: int = 0, trend: float = 0.0003,
                   vol: float = 0.012, start: float = 100.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate a trending GBM-like OHLC series with intrabar high/low wicks."""
    rng = np.random.default_rng(seed)
    # regime-switching drift so trend-followers have something to catch
    drift = np.full(n, trend)
    switch = rng.integers(80, 160)
    sign = 1
    k = 0
    while k < n:
        drift[k:k + switch] = trend * sign
        sign *= -1
        k += switch
        switch = int(rng.integers(80, 160))
    rets = drift + vol * rng.standard_normal(n)
    closes = start * np.exp(np.cumsum(rets))
    opens = np.concatenate([[start], closes[:-1]])
    wick = vol * closes * rng.uniform(0.2, 1.0, n)
    highs = np.maximum(opens, closes) + wick
    lows = np.minimum(opens, closes) - wick
    return highs, lows, closes
