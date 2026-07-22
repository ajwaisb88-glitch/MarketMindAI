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

### Signal grading (A+ / A1 / A / B / C / D / F)

`grade_signal()` turns a raw detection into a tradeable grade by fusing two
independent things:

- **conviction** — the 0–100 spoof probability (how sure the radar is), and
- **tradability** — `tradability_score(asset)`: how much of an edge survives the
  asset's leverage/fee drag. Tight-scalp instruments need huge leverage, so their
  fee bleed caps the grade no matter how strong the signal.

Tradability *gates* conviction (`score = conviction × (0.45 + 0.55·tradability)`
minus a funding penalty), so a blatant spoof on an un-tradable book is capped:

| Asset | Scalp | Tradability | Grade @100 conviction |
|-------|-------|-------------|-----------------------|
| oil | 0.45% | 75 | **A+** |
| gold / silver | 0.40% | 72 | **A1** |
| btc / nasdaq | 0.30% | 62 | **A1** |
| sp500 | 0.25% | 54 | **A1** |
| eurusd / gbpusd | 0.10–0.12% | 0–5 | **C** |

Ladder (best→worst): `A+` elite · `A1` excellent · `A` strong · `B` good · `C`
fair · `D` weak · `F` avoid · `NO-TRADE` when the book is clean. Every scan row
and the single `/manipulation` response carry `grade`, `score`, `conviction`,
`tradability` and a `direction` (long/short). The desktop Manipulation Radar shows
the grade as a coloured badge.

### Trade plan (SL / TP / trailing TP)

`build_trade_plan()` turns a graded signal into concrete levels. The stop sits one
scalp-move from entry; the take-profit is `payoff` (default 1.5) times that
distance; a trailing take-profit arms at +1R and then trails 0.5R behind the peak,
so a runner keeps giving while a reversal still banks profit. Example (BTC short at
$60,000, 0.30% scalp): `entry 60000 · SL 60180 (−0.30%) · TP 59730 (+0.45%) · RR
1.5 · trailing arms at 59820`. Every actionable scan row and `/manipulation`
response carry a `trade_plan`; the desktop radar renders entry/SL/TP boxes.

### How many signals per day

`estimate_signals_per_day()` projects daily signal counts, and is deliberately
honest about the **base-rate effect**: at a realistic low spoof rate the raw fire
count is dominated by benign look-alikes (legitimate repricing). It reports real
signals vs false alarms with a precision figure. Example (BTC, scan every 30s, 5%
of windows truly manipulated, grade ≥ A):

| Metric | Value |
|--------|-------|
| windows scanned / day | 2,880 |
| raw signals / day | ~316 |
| **real** signals / day | ~144 |
| false alarms / day | ~171 |
| precision | ~0.46 |

So the radar fires often, but under half are real at a 5% base rate — raise the
grade bar or the base rate and precision climbs. Un-tradable assets (eurusd) fire
zero graded-A signals. Endpoint:
`GET /signals/frequency?asset=btc&scan_interval_sec=30&spoof_base_rate=0.05&min_grade=A`.

### Grade filter & watchlist

- `GET /manipulation?asset=btc&min_grade=A1` — the "only show me A+/A1" filter. It
  keeps scanning fresh windows (up to `max_scans`) and returns the first setup at
  that grade or better, with `filtered.found` telling you whether it succeeded.
- The desktop app has an **all-coins watchlist** (`/manipulation/scan`) with grade
  filter chips (All / ≥B / ≥A / A+·A1) and entry/SL/TP per asset, plus a grade
  filter on the single-asset radar.

### Asset universe

`MARKET_PROFILES` now spans crypto (btc, eth), **meme coins** (doge, shib, pepe),
**stablecoins** (usdt, usdc — pegged, so they grade NO-TRADE, which is honest),
**metals** (gold, **xauusd**, silver, xagusd), energy (oil), **forex** (eurusd,
gbpusd, usdjpy, audusd) and indices (sp500, nasdaq). Each profile carries a
`class` tag and an `fmp` symbol for pulling real prices.

## Long-term & intraday strategies

`app/strategies.py` adds two **price/OHLC-based** engines (distinct from the
order-book scalp engine), so they run on real bars from any provider:

- **intraday** — EMA(9/21) trend + RSI filter, stop/target sized in ATR units,
  hold minutes–hours. `intraday_signal(highs, lows, closes)`.
- **long-term** — SMA(50/200) trend + 12-bar momentum, wide ATR stops, hold
  days–weeks. `longterm_signal(closes, highs, lows)`.

Both return a graded signal (same A+/A1/… ladder) with entry/SL/TP, and both ship
a **walk-forward backtest** that only ever uses past bars (no look-ahead), reporting
win rate, profit factor, return and max drawdown. Endpoints:

- `GET /strategy/signal?asset=xauusd&horizon=long-term`
- `GET /strategy/backtest?asset=btc&horizon=intraday`

### Live data with your FMP key

The backend can pull **real** quotes and bars from Financial Modeling Prep. Set
your API key as an environment variable before launching — it is read from the
env only, never hard-coded or committed:

```bash
export FMP_API_KEY=your_key_here     # macOS/Linux
setx  FMP_API_KEY your_key_here      # Windows (open a new terminal after)
cd Backend && uvicorn app.main:app --port 8000
```

Then the data priority becomes **FMP → yfinance → synthetic**, per request. Check
it's picked up:

- `GET /health` → `"fmp_configured": true`, `"live_data": "fmp"`
- `GET /quote?asset=xauusd` → live price
- `GET /strategy/signal?asset=xauusd&horizon=long-term` → the `data_source` field
  reads `"fmp"` when real bars were used.

Symbols map via `MARKET_PROFILES[asset]["fmp"]` (e.g. `xauusd → XAUUSD`,
`btc → BTCUSD`, `doge → DOGEUSD`). Without a key the backend falls back to
yfinance and then a deterministic synthetic series, so it always runs.

> Note: FMP's servers are not reachable from Claude Code web sessions (the network
> policy blocks them), so live FMP data works when you run the backend on your own
> machine, not inside a web session.

### Backtest your own CSV

Upload OHLC bars directly — no API needed. The loader (`app/csv_loader.py`)
handles the **Investing.com export** (`Date,Price,Open,High,Low,…`, comma
thousands, quotes, UTF-8 BOM, newest-first) and a generic
`Date,Open,High,Low,Close` layout, auto-detecting row order.

```bash
curl --data-binary @XAU_USD_Historical_Data.csv \
  'http://127.0.0.1:8000/strategy/backtest_csv?horizon=long-term'
```

Returns the current signal plus the walk-forward backtest. A real sample lives at
`Backend/data/sample_xauusd_daily.csv` (≈390 daily XAUUSD bars). On that data the
long-term trend strategy scores a **profit factor ≈ 1.6** (win rate 46%, avg win
+7.0% vs avg loss −3.7%, max drawdown ≈ 3%) — a modest 13-trade sample, but real.

Next steps:
- Plug a live exchange feed into `OrderBookFeed`
- Add authentication and API token handling
