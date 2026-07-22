from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app import backtest as backtest_mod
from app import quant
from app import scalping as scalping_mod
from app.manipulation import (
    MARKET_PROFILES,
    OrderBookFeed,
    build_trade_plan,
    estimate_signals_per_day,
    grade_signal,
    scan_assets,
    spoofing_probability,
)

logger = logging.getLogger("marketmind")

# ---------------------------------------------------------------------------
# Asset ticker map
# ---------------------------------------------------------------------------
ASSET_TICKERS: dict[str, str] = {
    "gold": "GC=F",
    "silver": "SI=F",
    "oil": "CL=F",
    "btc": "BTC-USD",
    "eth": "ETH-USD",
    "eurusd": "EURUSD=X",
    "gbpusd": "GBPUSD=X",
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
}

app = FastAPI(title="MarketMind AI Backend", version="0.2.0")

origins = [
    "http://localhost:4000",
    "http://127.0.0.1:4000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# ML helpers
# ---------------------------------------------------------------------------

def _compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    """Relative Strength Index for the last bar."""
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[-period:].mean() if len(gains) >= period else gains.mean()
    avg_loss = losses[-period:].mean() if len(losses) >= period else losses.mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _predict_from_prices(closes: np.ndarray) -> dict:
    """Simple rule-based signal derived from SMA crossover and RSI."""
    if len(closes) < 26:
        return {"prediction": "neutral", "confidence": 0.5, "note": "insufficient data"}

    sma_fast = float(closes[-10:].mean())
    sma_slow = float(closes[-26:].mean())
    rsi = _compute_rsi(closes)
    last = float(closes[-1])
    pct_change_5d = float((closes[-1] - closes[-6]) / closes[-6] * 100) if len(closes) >= 6 else 0.0

    score = 0.0
    if sma_fast > sma_slow:
        score += 1.0
    else:
        score -= 1.0
    if rsi < 30:
        score += 1.5   # oversold → bullish
    elif rsi > 70:
        score -= 1.5   # overbought → bearish
    if pct_change_5d > 1:
        score += 0.5
    elif pct_change_5d < -1:
        score -= 0.5

    if score >= 1.5:
        prediction, confidence = "bullish", min(0.5 + score * 0.1, 0.95)
    elif score <= -1.5:
        prediction, confidence = "bearish", min(0.5 + abs(score) * 0.1, 0.95)
    else:
        prediction, confidence = "neutral", 0.5

    return {
        "prediction": prediction,
        "confidence": round(confidence, 3),
        "sma_fast": round(sma_fast, 4),
        "sma_slow": round(sma_slow, 4),
        "rsi": round(rsi, 2),
        "last_price": round(last, 4),
        "pct_change_5d": round(pct_change_5d, 3),
    }


def _fetch_closes(ticker: str, period: str = "3mo") -> Optional[np.ndarray]:
    try:
        import yfinance as yf  # lazy import so CI can still run without it
        data = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        if data.empty:
            return None
        close = data["Close"]
        # yfinance >= 0.2.31 returns multi-level columns; flatten to 1-D
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        arr = close.dropna().to_numpy(dtype=float).ravel()
        return arr if arr.ndim == 1 and len(arr) > 0 else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance fetch failed for %s: %s", ticker, exc)
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "version": app.version}


@app.get("/assets")
async def list_assets():
    """Return the supported asset names."""
    return {"assets": sorted(ASSET_TICKERS.keys())}


@app.get("/predict")
async def predict(asset: str = "gold"):
    """Return a directional signal for the given asset."""
    key = asset.lower()
    ticker = ASSET_TICKERS.get(key)
    if ticker is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown asset '{asset}'. Available: {sorted(ASSET_TICKERS)}",
        )

    closes = _fetch_closes(ticker)
    if closes is None or len(closes) == 0:
        # Graceful fallback so smoke tests still pass when network is unavailable
        return {"asset": key, "prediction": "neutral", "confidence": 0.5, "note": "live data unavailable"}

    result = _predict_from_prices(closes)
    result["asset"] = key
    result["ticker"] = ticker
    return result


# ---------------------------------------------------------------------------
# Manipulation radar + quant toolkit routes
# ---------------------------------------------------------------------------

@app.get("/manipulation")
async def manipulation(
    asset: str = "btc",
    spoof: bool | None = Query(default=None, description="Force a spoof/clean scenario; omit for random."),
    seed: int | None = None,
):
    """Spoofing radar for one order-book window.

    Uses the deterministic simulated order-book feed (the seam where a live
    exchange depth/trade stream would be plugged in) and returns the spoofing
    probability, order-book features and SPOOF/SHEEP/WHALE sentiment triangle.
    """
    import random

    feed = OrderBookFeed.for_asset(asset, seed=seed if seed is not None else random.randint(0, 10_000))
    is_spoof = feed.rng.random() < 0.4 if spoof is None else spoof
    side = "bid" if feed.rng.random() < 0.5 else "ask"
    snap, events = feed.sample(spoof=is_spoof, side=side)
    report = spoofing_probability(snap, events, funding_rate=feed.funding_rate())
    grade = grade_signal(report.probability, asset, report.predicted_move, report.funding_rate)
    direction = "long" if report.predicted_move > 0 else "short" if report.predicted_move < 0 else "flat"
    trade_plan = (
        build_trade_plan(asset, snap.mid, direction)
        if grade["grade"] != "NO-TRADE" and direction != "flat" else None
    )
    return {
        "asset": asset.lower(),
        "scenario": "spoof" if is_spoof else "clean",
        "mid": snap.mid,
        "spread": snap.spread,
        "grade": grade["grade"],
        "score": grade["score"],
        "conviction": grade["conviction"],
        "tradability": grade["tradability"],
        "trade_plan": trade_plan,
        "probability": report.probability,
        "label": report.label,
        "posterior": round(report.posterior, 4),
        "pressure_side": report.pressure_side,
        "predicted_move": report.predicted_move,
        "direction": direction,
        "funding_rate": report.funding_rate,
        "features": report.features,
        "sentiment": report.sentiment,
        "order_book": {
            "bid_prices": snap.bid_prices.round(6).tolist(),
            "bid_sizes": snap.bid_sizes.round(3).tolist(),
            "ask_prices": snap.ask_prices.round(6).tolist(),
            "ask_sizes": snap.ask_sizes.round(3).tolist(),
        },
    }


@app.get("/manipulation/scan")
async def manipulation_scan(seed: int = 0):
    """Spoofing radar across every supported asset, ranked highest-risk first.

    A single watchlist call that scans crypto, metals, FX and indices uniformly —
    the "use all coins" view. Each row carries the probability, the fade
    direction and the sentiment triangle for that instrument.
    """
    return {"assets": sorted(MARKET_PROFILES.keys()), "scan": scan_assets(seed=seed)}


@app.get("/signals/frequency")
async def signals_frequency(
    asset: str = "btc",
    scan_interval_sec: float = Query(30.0, gt=0, description="How often the radar re-evaluates the book"),
    spoof_base_rate: float = Query(0.05, ge=0.0, le=1.0, description="Fraction of windows that contain real manipulation"),
    min_grade: str = Query("A", description="Minimum grade to count as a signal"),
):
    """Estimate how many gradeable signals a day the radar fires for an asset.

    Reports the raw fire count and — honestly — splits it into real signals vs
    false alarms with a precision figure, because at a realistic low base rate
    the raw count is dominated by benign look-alikes (the base-rate effect).
    """
    return estimate_signals_per_day(
        asset=asset, scan_interval_sec=scan_interval_sec,
        spoof_base_rate=spoof_base_rate, min_grade=min_grade,
    )


@app.get("/quant/kelly")
async def quant_kelly(
    p: float = Query(..., ge=0.0, le=1.0, description="Win probability"),
    b: float = Query(1.0, gt=0.0, description="Net odds (payout per unit staked)"),
    c: float = Query(0.5, ge=0.0, le=1.0, description="Kelly fraction"),
):
    """Fractional Kelly stake and its expected log-growth rate."""
    f = quant.fractional_kelly(p, b, c=c)
    full = quant.fractional_kelly(p, b, c=1.0)
    return {
        "p": p, "b": b, "c": c,
        "fraction": round(f, 4),
        "full_kelly_fraction": round(full, 4),
        "expected_log_growth": round(quant.kelly_growth_rate(f, p, b), 6),
    }


@app.get("/backtest")
async def run_backtest():
    """Run the full quant + manipulation backtest suite and return the metrics."""
    return backtest_mod.run_all()


@app.get("/scalping")
async def scalping(
    edge: float = Query(0.56, ge=0.5, le=0.7, description="Signal win probability p"),
    scalp_move_pct: float = Query(0.5, gt=0.0, description="Stop distance as % of price"),
    trades: int = Query(600, ge=1, le=5000),
    kelly_fraction: float = Query(0.5, ge=0.0, le=1.0),
    paths: int = Query(3000, ge=100, le=20000),
):
    """Monte-Carlo the scalping strategy from $100 and report the outcome distribution.

    Answers the "$100 -> $1000" question with probabilities, not one lucky path:
    P(reach $1000), P(ruin), median equity, drawdown — plus edge and scalp-size
    sweeps showing how sensitive the result is to a *real* edge and to fee drag.
    """
    cfg = scalping_mod.ScalpConfig(
        edge=edge, scalp_move_pct=scalp_move_pct, trades=trades, kelly_fraction=kelly_fraction,
    )
    result = scalping_mod.simulate_paths(cfg, paths=paths)
    result["edge_sweep"] = scalping_mod.edge_sweep(cfg, paths=min(paths, 4000))
    result["scalp_size_sweep"] = scalping_mod.scalp_size_sweep(cfg, paths=min(paths, 4000))
    return result


@app.get("/scalping/signal")
async def scalping_signal(
    p_impact: float = Query(0.7, ge=0.0, le=1.0,
                            description="Assumed P(a detected spoof pushes price the predicted way)"),
    paths: int = Query(4000, ge=100, le=20000),
):
    """Signal-driven scalping backtest: the edge is *measured* from the detector.

    Instead of assuming a win rate, this runs the real spoofing detector over
    simulated windows, trades the direction it infers, and measures the realised
    hit-rate under the given price-impact assumption — then Monte-Carlos the
    strategy from $100 with that measured edge. Includes an impact sweep showing
    how completely the outcome hinges on that one assumption.
    """
    result = scalping_mod.backtest_from_signal(p_impact=p_impact, paths=paths)
    result["impact_sweep"] = scalping_mod.impact_sweep(paths=min(paths, 4000))
    return result


@app.get("/scalping/scan")
async def scalping_scan(
    p_impact: float = Query(0.7, ge=0.0, le=1.0),
    paths: int = Query(3000, ge=100, le=20000),
):
    """Signal-driven scalp backtest for every asset, ranked by P(reach $1,000).

    Each instrument uses its own scalp width, so the "all coins" view exposes how
    tight-scalp majors (FX, indices) bleed to leverage/fees while wider markets
    keep more of the edge.
    """
    return {"p_impact": p_impact, "scan": scalping_mod.scan_assets_scalping(p_impact=p_impact, paths=paths)}
