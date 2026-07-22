from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app import backtest as backtest_mod
from app import quant
from app.manipulation import OrderBookFeed, spoofing_probability

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

    feed = OrderBookFeed(seed=seed if seed is not None else random.randint(0, 10_000))
    is_spoof = feed.rng.random() < 0.4 if spoof is None else spoof
    side = "bid" if feed.rng.random() < 0.5 else "ask"
    snap, events = feed.sample(spoof=is_spoof, side=side)
    report = spoofing_probability(snap, events, funding_rate=feed.funding_rate())
    return {
        "asset": asset.lower(),
        "scenario": "spoof" if is_spoof else "clean",
        "mid": snap.mid,
        "spread": snap.spread,
        "probability": report.probability,
        "label": report.label,
        "posterior": round(report.posterior, 4),
        "funding_rate": report.funding_rate,
        "features": report.features,
        "sentiment": report.sentiment,
        "order_book": {
            "bid_prices": snap.bid_prices.round(2).tolist(),
            "bid_sizes": snap.bid_sizes.round(3).tolist(),
            "ask_prices": snap.ask_prices.round(2).tolist(),
            "ask_sizes": snap.ask_sizes.round(3).tolist(),
        },
    }


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
