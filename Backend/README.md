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

Run the test suite with `python -m pytest -q`.

Next steps:
- Plug a live exchange feed into `OrderBookFeed`
- Add authentication and API token handling
