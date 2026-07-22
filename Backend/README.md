# MarketMind AI — Backend (FastAPI)

Quick start (recommended inside a Python virtual environment):

```powershell
cd Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Endpoints:
- `GET /health` — health check
- `GET /predict?asset=gold` — SMA/RSI directional signal
- `GET /manipulation?asset=btc` — spoofing radar for one order-book window
- `GET /quant/kelly?p=0.55&b=1&c=0.5` — fractional Kelly stake + log-growth
- `GET /backtest` — run the full quant + manipulation backtest suite

## Quant + manipulation stack

Two self-contained, numpy-only modules implement the models from the project brief:

- `app/quant.py` — Hawkes process, Bayesian classifier, quantile volatility,
  conformal prediction interval, fractional Kelly, and random-matrix-theory
  (Marchenko–Pastur) denoising. Each function documents the exact formula.
- `app/manipulation.py` — a spoofing/layering detector. From an L2 order-book
  snapshot + a window of order-flow events it derives book imbalance,
  cancel/trade ratio, phantom liquidity and a Hawkes cancel-burst intensity,
  then fuses them via Bayes into a 0–100 spoofing probability and a
  SPOOF/SHEEP/WHALE sentiment triangle. `OrderBookFeed` is the deterministic
  simulated data source and the single seam where a live exchange depth/trade
  stream would plug in.

### Backtests

`app/backtest.py` builds labelled synthetic scenarios and scores every model.
Run it with:

```bash
cd Backend
python -m app.backtest
```

Representative results (deterministic, fixed seeds):

| Model | Metric | Result |
|-------|--------|--------|
| Spoofing radar | recall / precision / AUC | 1.00 / 0.85 / 0.99 |
| Fractional Kelly (p=0.55) | median bankroll, 500 rounds | full 12.2× vs flat-20% 0.93× |
| Conformal filter | coverage (target 0.90) | 0.886 |
| Quantile volatility | 90% interval coverage (fat tails) | 0.897 vs Gaussian 0.921 |
| Hawkes process | branching-ratio recovery | 0.40 true → 0.41 fitted |
| Bayesian classifier | regime accuracy | 0.865 |
| Random matrix theory | factor count recovered | 3 / 3 |

The spoofing benchmark includes legitimate market-maker *repricing* as a
confounder in the clean class, which is why precision is 0.85 (false positives)
rather than a trivial 1.0.

### Scalping strategy backtest

`app/scalping.py` wires the signal → sizing → exit loop into a trading strategy
and Monte-Carlos it across thousands of $100 accounts to test the "$100 → $1,000"
claim as a *distribution* rather than one lucky path. Run it with:

```bash
cd Backend
python -m app.scalping
```

Key finding (600 scalps, half-Kelly, 0.5% stops = 10× leverage, 6bps fee):

| Signal win rate | Expectancy/trade | Median end | P(reach $1,000) | P(ruin) |
|-----------------|------------------|-----------|-----------------|---------|
| 50% (coin flip) | 0.00% | $100 | 0.0% | 0.0% |
| 56% | 0.00% | $69 | 0.2% | 2.1% |
| 58% | +0.20% | $128 | 1.2% | 0.3% |
| 60% | +0.40% | $234 | 5.9% | 0.0% |

The 10× is real but rare: even at a generous 58% win rate only ~1 in 80 accounts
reaches $1,000 and ~2 in 5 end below the starting $100. Leverage/fee drag is the
hidden killer — chasing 0.2% scalps forces 25× leverage and ruins ~86% of
accounts on the same edge. `DesktopApp/scalp_reality.html` renders this as a
standalone visual report. Endpoint: `GET /scalping?edge=0.58&scalp_move_pct=0.5`.

#### Signal-driven edge (measured, not assumed)

`measure_signal_edge()` closes the loop: it runs the real spoofing detector over
simulated windows, trades the direction the detector infers from the phantom-wall
side, and measures the realised win rate under a price-impact assumption
`p_impact` = P(a detected spoof actually pushes price the predicted way). The
measured edge tracks that assumption almost linearly:

| p_impact | measured edge | median end | P(reach $1,000) |
|----------|---------------|-----------|-----------------|
| 0.50 (coin flip) | 0.51 | $77 | 0.0% |
| 0.60 | 0.59 | $191 | 3.7% |
| 0.70 | 0.69 | $3,401 | 94.7% |
| 0.80 | 0.78 | $4,860 | 97.9% |

The detector *detects* spoofs reliably (recall ~1.0); whether that converts into
a tradable edge depends entirely on `p_impact` — the one assumption no backtest
can settle, only live forward-testing on real order-book data can.
Endpoint: `GET /scalping/signal?p_impact=0.7`.

### All assets

Every instrument in the app (btc, eth, gold, silver, oil, eurusd, gbpusd, sp500,
nasdaq) has a market profile in `manipulation.MARKET_PROFILES` — realistic price,
tick size, a `crypto` flag (only perps carry a funding rate) and a default scalp
width. The radar and the scalp backtest run uniformly across all of them:

- `GET /manipulation/scan` — spoofing radar over every asset, ranked highest-risk
  first (the watchlist view).
- `GET /scalping/scan?p_impact=0.7` — signal-driven scalp backtest per asset. The
  same edge produces very different outcomes because each asset's scalp width sets
  its leverage: wide markets (oil, 0.4% ≈ 12×) keep the edge, while tight majors
  (eurusd, 0.1% ≈ 50×) bleed to fees. Unknown symbols fall back to a safe default
  so the engine never errors.

> Live exchange feed: the seam is `OrderBookFeed` — swap it for a real depth/trade
> adapter and everything downstream is unchanged. Note that a live feed needs an
> environment whose network policy allows the exchange host; the default policy in
> Claude Code web sessions blocks exchange APIs (only package registries are
> reachable), so the bundled feed is simulated.

Next steps:
- Plug a live exchange feed into `OrderBookFeed`
- Add authentication and API token handling
