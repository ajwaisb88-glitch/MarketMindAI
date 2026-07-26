from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from app import backtest as backtest_mod
from app import quant
from app import scalping as scalping_mod
from app.manipulation import (
    MARKET_PROFILES,
    OrderBookFeed,
    build_trade_plan,
    estimate_signals_per_day,
    grade_rank,
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

# Assets that route to Binance first (live, key-free) before yfinance/simulated.
# Gold uses PAX Gold (PAXGUSDT) — a live gold order book without needing MT5.
CRYPTO_ASSETS = {"btc", "eth", "doge", "shib", "pepe", "gold", "xauusd", "xauusdt", "paxg"}

app = FastAPI(title="MarketMind AI Backend", version="0.2.0")

origins = [
    "http://localhost:4000",
    "http://127.0.0.1:4000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",   # Vite dev server
    "http://127.0.0.1:5173",
    "http://localhost:4173",   # Vite preview
    "http://127.0.0.1:4173",
]

@app.on_event("startup")
async def _warm():
    """Pre-compute the slow money-flow tree in the background so the first view
    is instant instead of waiting ~13s on live data."""
    try:
        from app.money_flow import warm_flow
        warm_flow()
    except Exception as exc:  # noqa: BLE001
        logger.warning("startup warm failed: %s", exc)


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


def _fetch_ohlc(asset: str, intraday: bool) -> tuple:
    """Return (highs, lows, closes, source) for an asset.

    Priority: real bars from FMP (if FMP_API_KEY is set) → yfinance → a
    deterministic synthetic series so the endpoint always works. The ``source``
    field tells the caller which was used.
    """
    from app import fmp_client, strategies as strat

    # 1) Financial Modeling Prep — real data when the user's key is configured
    if fmp_client.is_configured():
        try:
            fmp_bars = fmp_client.get_ohlc(asset, intraday=intraday)
            if fmp_bars is not None:
                h, l, c = fmp_bars
                return h, l, c, "fmp"
        except Exception as exc:  # noqa: BLE001
            logger.warning("FMP OHLC failed for %s: %s", asset, exc)

    # 2) Binance — live crypto data, key-free (crypto assets only)
    if asset.lower() in CRYPTO_ASSETS:
        try:
            from app.connectors.binance import BinanceConnector
            k = BinanceConnector().klines(asset, "15m" if intraday else "1d", 500)
            if k and len(k) > 60:
                highs = np.array([b["high"] for b in k], dtype=float)
                lows = np.array([b["low"] for b in k], dtype=float)
                closes = np.array([b["close"] for b in k], dtype=float)
                return highs, lows, closes, "binance"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Binance OHLC failed for %s: %s", asset, exc)

    # 3) yfinance
    ticker = ASSET_TICKERS.get(asset.lower())
    if ticker is not None:
        try:
            import yfinance as yf
            kwargs = (dict(period="5d", interval="15m") if intraday
                      else dict(period="2y", interval="1d"))
            data = yf.download(ticker, progress=False, auto_adjust=True, **kwargs)
            if not data.empty and len(data) > 60:
                def col(name):
                    c = data[name]
                    return (c.iloc[:, 0] if hasattr(c, "columns") else c).dropna().to_numpy(dtype=float).ravel()
                return col("High"), col("Low"), col("Close"), "yfinance"
        except Exception as exc:  # noqa: BLE001
            logger.warning("OHLC fetch failed for %s: %s", asset, exc)

    # deterministic synthetic fallback
    seed = abs(hash(asset.lower())) % 10_000
    h, l, c = strat.synthetic_ohlc(n=(500 if intraday else 800), seed=seed,
                                   vol=(0.006 if intraday else 0.014))
    return h, l, c, "simulated"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    from app import fmp_client
    return {
        "status": "ok",
        "version": app.version,
        "fmp_configured": fmp_client.is_configured(),
        "live_data": "fmp" if fmp_client.is_configured() else "yfinance/simulated",
    }


@app.get("/quote")
async def quote(asset: str = "xauusd"):
    """Live quote for an asset via FMP (requires FMP_API_KEY). 404 if unavailable."""
    from app import fmp_client
    if not fmp_client.is_configured():
        raise HTTPException(status_code=503, detail="FMP_API_KEY not set — live quotes unavailable")
    q = fmp_client.get_quote(asset)
    if q is None:
        raise HTTPException(status_code=404, detail=f"No FMP quote for '{asset}'")
    return q


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

def _single_scan(asset: str, spoof: bool | None, seed: int) -> dict:
    """Run one order-book window and build the full radar response dict."""
    feed = OrderBookFeed.for_asset(asset, seed=seed)
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


@app.get("/manipulation")
async def manipulation(
    asset: str = "btc",
    spoof: bool | None = Query(default=None, description="Force a spoof/clean scenario; omit for random."),
    seed: int | None = None,
    min_grade: str | None = Query(default=None, description="Only surface setups at this grade or better (e.g. A1)."),
    max_scans: int = Query(default=100, ge=1, le=1000, description="How many windows to scan when filtering by grade."),
):
    """Spoofing radar for one order-book window.

    Uses the deterministic simulated order-book feed (the seam where a live
    exchange depth/trade stream would be plugged in). With ``min_grade`` it keeps
    scanning fresh windows (up to ``max_scans``) and returns the first setup at
    that grade or better — the "only show me A+/A1" filter — falling back to the
    best it found with ``filtered.found = false``.
    """
    import random

    base_seed = seed if seed is not None else random.randint(0, 1_000_000)
    if min_grade is None:
        return _single_scan(asset, spoof, base_seed)

    want = grade_rank(min_grade)
    best, best_rank = None, -99
    for k in range(max_scans):
        result = _single_scan(asset, spoof, base_seed + k)
        rank = grade_rank(result["grade"])
        if rank >= want:
            result["filtered"] = {"min_grade": min_grade, "scans": k + 1, "found": True}
            return result
        if rank > best_rank:
            best, best_rank = result, rank
    best["filtered"] = {"min_grade": min_grade, "scans": max_scans, "found": False}
    return best


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


# ---------------------------------------------------------------------------
# Long-term + intraday strategy routes (price/OHLC based)
# ---------------------------------------------------------------------------

@app.get("/strategy/signal")
async def strategy_signal(
    asset: str = "btc",
    horizon: str = Query("intraday", pattern="^(intraday|long-term|longterm)$"),
):
    """Current graded signal (entry/SL/TP) for an asset at the chosen horizon."""
    from app import strategies as strat

    long_term = horizon != "intraday"
    highs, lows, closes, source = _fetch_ohlc(asset, intraday=not long_term)
    sig = (strat.longterm_signal(closes, highs, lows) if long_term
           else strat.intraday_signal(highs, lows, closes))
    out = sig.as_dict()
    out["asset"] = asset.lower()
    out["data_source"] = source
    return out


@app.get("/strategy/backtest")
async def strategy_backtest(
    asset: str = "btc",
    horizon: str = Query("intraday", pattern="^(intraday|long-term|longterm)$"),
):
    """Walk-forward backtest of the strategy on the asset's bars."""
    from app import strategies as strat

    long_term = horizon != "intraday"
    highs, lows, closes, source = _fetch_ohlc(asset, intraday=not long_term)
    fn = strat.longterm_signal if long_term else strat.intraday_signal
    result = strat.backtest(highs, lows, closes, fn,
                            max_hold=(30 if long_term else 12))
    result["asset"] = asset.lower()
    result["horizon"] = "long-term" if long_term else "intraday"
    result["data_source"] = source
    result["bars"] = len(closes)
    return result


@app.post("/strategy/backtest_csv")
async def strategy_backtest_csv(
    request: Request,
    horizon: str = Query("long-term", pattern="^(intraday|long-term|longterm)$"),
    max_bars: int = Query(8000, ge=250, le=50000,
                          description="Cap on bars used (the most recent N) to bound backtest time."),
):
    """Backtest a strategy on user-uploaded OHLC bars.

    POST the CSV file contents as the raw request body (e.g.
    `curl --data-binary @data.csv '.../strategy/backtest_csv?horizon=long-term'`).
    Understands Investing.com, Dukascopy, generic Date/OHLC and headerless
    MetaTrader exports (Date,Time,O,H,L,C,V). The current signal always uses the
    full series; only the walk-forward backtest is capped to the most recent
    ``max_bars`` bars so a huge 1-minute file can't hang the request.
    """
    from app import csv_loader, strategies as strat

    raw = (await request.body()).decode("utf-8", errors="replace")
    if not raw.strip():
        raise HTTPException(status_code=400, detail="empty request body — POST the CSV contents")
    try:
        highs, lows, closes = csv_loader.load_ohlc_csv(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"could not parse CSV: {exc}")

    total_bars = len(closes)
    long_term = horizon != "intraday"
    fn = strat.longterm_signal if long_term else strat.intraday_signal
    signal = (strat.longterm_signal(closes, highs, lows) if long_term
              else strat.intraday_signal(highs, lows, closes)).as_dict()

    # cap the backtest window (most recent bars) to keep the walk-forward bounded
    if total_bars > max_bars:
        highs, lows, closes = highs[-max_bars:], lows[-max_bars:], closes[-max_bars:]
    result = strat.backtest(highs, lows, closes, fn, max_hold=(30 if long_term else 12))
    return {
        "horizon": "long-term" if long_term else "intraday",
        "bars_total": total_bars,
        "bars_backtested": len(closes),
        "data_source": "user_csv",
        "current_signal": signal,
        "backtest": result,
    }


@app.get("/license")
async def license_status():
    """Current license state + this machine's id (for machine-locked keys)."""
    from app.licensing import current_status, machine_id
    s = current_status().as_dict()
    s["machine_id"] = machine_id()
    return s


@app.get("/moneyflow")
async def moneyflow(refresh: bool = False):
    """Global money flow tree: liquidity → currencies → asset classes → instruments,
    with regime, rotation and the proven risk_off_vix signal. Separate engine —
    it never feeds the confluence/trade score. Cached (~3 min); pass refresh=1 to force."""
    from app.money_flow import get_flow
    return get_flow(force=refresh)


@app.get("/signals/sources")
async def signal_sources_list():
    """The 3 signal systems and each one's mode (off / manual / auto)."""
    from app.signal_sources import get_selector
    return {"sources": get_selector().sources_info()}


@app.post("/signals/sources/mode")
async def signal_sources_mode(
    source: str = Query(..., description="monster | whale | marketmind"),
    mode: str = Query(..., pattern="^(off|manual|auto)$",
                      description="off = ignore · manual = show only · auto = send to MT4/MT5"),
):
    """Set a source's mode. Auto routes its signals to MT4/MT5; manual just shows them."""
    from app.signal_sources import get_selector
    try:
        modes = get_selector().set_mode(source, mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"modes": modes}


@app.get("/signals/feed")
async def signals_feed(asset: str = "gold", lots: float = 0.01):
    """Live signals for an asset from every active source. Auto-mode signals are
    routed to MT4/MT5 (queued until the terminal is connected); manual are shown."""
    from app.signal_sources import get_selector
    return get_selector().feed(asset, lots=lots)


@app.get("/crypto/signals")
async def crypto_signals(asset: str = "btc", scalp: bool = True):
    """Live crypto signals from Binance (key-free): the three SEPARATE types —
    scalp (spoofing radar on the live order book), intraday (EMA/RSI) and
    longterm (SMA/momentum). Crypto only; gold uses a different engine + MT5.
    Signals are kept independent, never blended into one score.
    """
    from app.crypto_signals import CryptoSignalService

    svc = CryptoSignalService()
    out: dict = {
        "asset": asset.lower(),
        "data_source": "binance",
        "intraday": svc.intraday(asset),
        "longterm": svc.longterm(asset),
    }
    if scalp:
        out["scalp"] = svc.scalp(asset)
    return out
