"""Backtest harness for the MarketMind quant + manipulation stack.

Each ``backtest_*`` function builds a *labelled* synthetic scenario, runs the
corresponding model from :mod:`app.quant` / :mod:`app.manipulation`, and returns
the metrics that show whether the model actually works. :func:`run_all` bundles
them and :func:`format_report` renders a readable summary. Everything is
deterministic (fixed seeds) so results reproduce exactly, offline and in CI.

Run directly to print the report::

    python -m app.backtest
"""

from __future__ import annotations

import numpy as np

from . import quant
from .manipulation import OrderBookFeed, spoofing_probability


# ---------------------------------------------------------------------------
# 1. Spoofing detector — precision / recall on labelled scenarios
# ---------------------------------------------------------------------------

def backtest_spoofing(n: int = 400, spoof_rate: float = 0.35, threshold: int = 70, seed: int = 7) -> dict:
    """Classify n order-book windows (labelled spoof/clean) and score detection."""
    rng = np.random.default_rng(seed)
    feed = OrderBookFeed(seed=seed)
    y_true, scores = [], []
    for i in range(n):
        is_spoof = rng.random() < spoof_rate
        side = "bid" if rng.random() < 0.5 else "ask"
        strength = float(rng.uniform(0.2, 1.0)) if is_spoof else None
        snap, events = feed.sample(spoof=is_spoof, side=side, strength=strength)
        report = spoofing_probability(snap, events, funding_rate=feed.funding_rate())
        y_true.append(int(is_spoof))
        scores.append(report.probability)

    y = np.array(y_true)
    s = np.array(scores)
    pred = (s >= threshold).astype(int)

    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / n

    return {
        "n": n,
        "threshold": threshold,
        "spoof_events": int(y.sum()),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "auc": round(_auc(y, s), 4),
        "mean_score_spoof": round(float(s[y == 1].mean()), 2),
        "mean_score_clean": round(float(s[y == 0].mean()), 2),
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }


def _auc(y: np.ndarray, score: np.ndarray) -> float:
    """ROC AUC via the rank (Mann-Whitney U) identity."""
    pos = score[y == 1]
    neg = score[y == 0]
    if pos.size == 0 or neg.size == 0:
        return 0.5
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(score) + 1)
    # average ranks for ties
    _, inv, counts = np.unique(score, return_inverse=True, return_counts=True)
    cum = np.cumsum(counts)
    avg_rank_by_val = (cum - (counts - 1) / 2.0)
    ranks = avg_rank_by_val[inv]
    r_pos = ranks[y == 1].sum()
    auc = (r_pos - pos.size * (pos.size + 1) / 2.0) / (pos.size * neg.size)
    return float(auc)


# ---------------------------------------------------------------------------
# 2. Fractional Kelly — bankroll growth vs alternatives
# ---------------------------------------------------------------------------

def backtest_kelly(p: float = 0.55, b: float = 1.0, rounds: int = 500, paths: int = 400, seed: int = 3) -> dict:
    """Simulate repeated favourable bets under several staking rules.

    Compares full Kelly, half Kelly (the fractional default) and a flat 20%
    stake by median terminal bankroll and worst-path drawdown.
    """
    rng = np.random.default_rng(seed)
    full = quant.fractional_kelly(p, b, c=1.0)
    half = quant.fractional_kelly(p, b, c=0.5)
    flat = 0.20

    def simulate(f: float) -> tuple[np.ndarray, float]:
        wins = rng.random((paths, rounds)) < p
        terminal = np.ones(paths)
        max_dd = 0.0
        bankroll = np.ones(paths)
        peak = np.ones(paths)
        for t in range(rounds):
            step = np.where(wins[:, t], 1 + f * b, 1 - f)
            bankroll = bankroll * step
            peak = np.maximum(peak, bankroll)
            max_dd = max(max_dd, float(((peak - bankroll) / peak).max()))
        terminal = bankroll
        return terminal, max_dd

    results = {}
    for name, f in [("full_kelly", full), ("half_kelly", half), ("flat_20pct", flat)]:
        terminal, dd = simulate(f)
        results[name] = {
            "fraction": round(f, 4),
            "median_bankroll": round(float(np.median(terminal)), 4),
            "mean_log_growth_per_round": round(float(np.log(np.median(terminal)) / rounds), 6),
            "theoretical_growth": round(quant.kelly_growth_rate(f, p, b), 6),
            "max_drawdown": round(dd, 4),
            "prob_below_start": round(float((terminal < 1.0).mean()), 4),
        }
    return {"p": p, "b": b, "rounds": rounds, "paths": paths, "strategies": results}


# ---------------------------------------------------------------------------
# 3. Conformal filter — empirical coverage vs nominal
# ---------------------------------------------------------------------------

def backtest_conformal(n: int = 2000, alpha: float = 0.1, seed: int = 11) -> dict:
    """Point model + split conformal; check realised coverage ~ 1 - alpha.

    Data: y = 0.5 x + heteroskedastic noise. A deliberately imperfect linear
    model produces residuals; conformal should still hit ~90% coverage.
    """
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1, n)
    noise = (0.5 + 0.5 * np.abs(x)) * rng.normal(0, 1, n)
    y = 0.5 * x + noise

    n_train = n // 2
    n_cal = n // 4
    xt, yt = x[:n_train], y[:n_train]
    xc, yc = x[n_train:n_train + n_cal], y[n_train:n_train + n_cal]
    xe, ye = x[n_train + n_cal:], y[n_train + n_cal:]

    # simple OLS slope/intercept
    A = np.vstack([xt, np.ones_like(xt)]).T
    coef, *_ = np.linalg.lstsq(A, yt, rcond=None)
    predict = lambda xx: coef[0] * xx + coef[1]

    cal_res = yc - predict(xc)
    lowers, uppers = [], []
    for xi in xe:
        lo, hi = quant.conformal_interval(predict(xi), cal_res, alpha=alpha)
        lowers.append(lo)
        uppers.append(hi)
    coverage = quant.conformal_coverage(ye, lowers, uppers)
    avg_width = float(np.mean(np.array(uppers) - np.array(lowers)))

    return {
        "n_eval": len(ye),
        "nominal_coverage": round(1 - alpha, 3),
        "empirical_coverage": round(coverage, 4),
        "avg_interval_width": round(avg_width, 4),
        "coverage_ok": bool(coverage >= (1 - alpha) - 0.03),
    }


# ---------------------------------------------------------------------------
# 4. Quantile volatility — pinball loss vs a Gaussian benchmark
# ---------------------------------------------------------------------------

def backtest_quantile_vol(n: int = 3000, seed: int = 5) -> dict:
    """Forecast the 5%/95% next-return quantiles; check coverage + pinball loss.

    Returns are fat-tailed (Student-t), so a Gaussian VaR is miscalibrated — it
    inflates sigma to fit the tails and ends up over-wide — while the empirical
    quantile stays close to the 90% target.
    """
    rng = np.random.default_rng(seed)
    ret = rng.standard_t(df=4, size=n) * 0.01

    train, test = ret[: n // 2], ret[n // 2:]
    q = quant.quantile_volatility(train, tau=(0.05, 0.95))
    q05, q95 = q[0.05], q[0.95]

    inside = np.mean((test >= q05) & (test <= q95))
    breach_low = float(np.mean(test < q05))
    breach_high = float(np.mean(test > q95))

    # Gaussian benchmark (mean/std VaR) for comparison
    mu, sd = train.mean(), train.std()
    g05, g95 = mu - 1.645 * sd, mu + 1.645 * sd
    inside_gauss = np.mean((test >= g05) & (test <= g95))

    pinball_05 = quant.pinball_loss(test, np.full_like(test, q05), 0.05)
    pinball_95 = quant.pinball_loss(test, np.full_like(test, q95), 0.95)

    return {
        "n_test": len(test),
        "target_interval": 0.90,
        "empirical_quantile_coverage": round(float(inside), 4),
        "gaussian_var_coverage": round(float(inside_gauss), 4),
        "breach_below_5pct": round(breach_low, 4),
        "breach_above_5pct": round(breach_high, 4),
        "pinball_loss_q05": round(pinball_05, 6),
        "pinball_loss_q95": round(pinball_95, 6),
        "q05": round(q05, 5),
        "q95": round(q95, 5),
    }


# ---------------------------------------------------------------------------
# 5. Hawkes process — parameter recovery from simulated events
# ---------------------------------------------------------------------------

def _simulate_hawkes(mu: float, alpha: float, beta: float, t_max: float, seed: int) -> np.ndarray:
    """Ogata thinning simulation of a univariate Hawkes process."""
    rng = np.random.default_rng(seed)
    events: list[float] = []
    t = 0.0
    while t < t_max:
        lam_bar = quant.hawkes_intensity(t + 1e-9, events, mu, alpha, beta)
        lam_bar = max(lam_bar, mu)
        t += rng.exponential(1.0 / lam_bar)
        if t >= t_max:
            break
        if rng.random() <= quant.hawkes_intensity(t, events, mu, alpha, beta) / lam_bar:
            events.append(t)
    return np.array(events)

def backtest_hawkes(mu: float = 0.5, alpha: float = 0.8, beta: float = 2.0, t_max: float = 4000.0, seed: int = 9) -> dict:
    """Simulate a Hawkes process, refit by grid-search MLE, report recovery."""
    events = _simulate_hawkes(mu, alpha, beta, t_max, seed)

    mu_grid = np.linspace(0.2, 0.9, 15)
    alpha_grid = np.linspace(0.3, 1.2, 19)
    beta_grid = np.linspace(1.0, 3.5, 26)
    best = (-np.inf, mu, alpha, beta)
    for m in mu_grid:
        for a in alpha_grid:
            for be in beta_grid:
                if a >= be:  # stationarity: branching ratio alpha/beta < 1
                    continue
                ll = quant.hawkes_log_likelihood(events, m, a, be, t_end=t_max)
                if ll > best[0]:
                    best = (ll, m, a, be)
    _, mu_hat, alpha_hat, beta_hat = best

    return {
        "n_events": int(events.size),
        "true": {"mu": mu, "alpha": alpha, "beta": beta,
                 "branching_ratio": round(alpha / beta, 3)},
        "fitted": {"mu": round(float(mu_hat), 3), "alpha": round(float(alpha_hat), 3),
                   "beta": round(float(beta_hat), 3),
                   "branching_ratio": round(float(alpha_hat / beta_hat), 3)},
        "log_likelihood": round(best[0], 2),
    }


# ---------------------------------------------------------------------------
# 6. Bayesian classifier — regime classification accuracy
# ---------------------------------------------------------------------------

def backtest_bayes(n: int = 2000, seed: int = 13) -> dict:
    """Gaussian NB on 2-feature bull/bear regimes; report accuracy."""
    rng = np.random.default_rng(seed)
    n_half = n // 2
    # bull: higher momentum, lower vol ; bear: negative momentum, higher vol
    bull = np.column_stack([rng.normal(1.0, 1.0, n_half), rng.normal(-0.5, 1.0, n_half)])
    bear = np.column_stack([rng.normal(-1.0, 1.2, n_half), rng.normal(0.8, 1.2, n_half)])
    X = np.vstack([bull, bear])
    y = np.array(["bull"] * n_half + ["bear"] * n_half)

    idx = rng.permutation(n)
    X, y = X[idx], y[idx]
    split = n // 2
    Xtr, ytr, Xte, yte = X[:split], y[:split], X[split:], y[split:]

    stats = {}
    for label in ("bull", "bear"):
        cls = Xtr[ytr == label]
        stats[label] = {"prior": len(cls) / len(Xtr), "mean": cls.mean(axis=0), "var": cls.var(axis=0)}

    correct = 0
    for xi, yi in zip(Xte, yte):
        post = quant.gaussian_nb_predict(xi, stats)
        pred = max(post, key=post.get)
        correct += int(pred == yi)

    return {"n_test": len(yte), "accuracy": round(correct / len(yte), 4)}


# ---------------------------------------------------------------------------
# 7. Random matrix theory — signal recovery from a factor model
# ---------------------------------------------------------------------------

def backtest_rmt(n_assets: int = 60, n_samples: int = 300, n_factors: int = 3, seed: int = 17) -> dict:
    """Build returns with a few real factors + noise; check RMT recovers them."""
    rng = np.random.default_rng(seed)
    factors = rng.normal(0, 1, (n_samples, n_factors))
    loadings = rng.normal(0, 1, (n_factors, n_assets))
    signal = factors @ loadings
    noise = rng.normal(0, 1, (n_samples, n_assets)) * 3.0  # noise dominates per-asset
    returns = signal + noise

    res = quant.rmt_denoise(returns)
    return {
        "n_assets": n_assets,
        "n_samples": n_samples,
        "true_factors": n_factors,
        "detected_signal_eigenvalues": res.n_signal_eigenvalues,
        "lambda_1": round(res.lambda_1, 3),
        "mp_upper_edge": round(res.lambda_max_theory, 3),
        "signal_variance_fraction": round(res.signal_variance_fraction, 4),
        "recovered": bool(res.n_signal_eigenvalues == n_factors),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all() -> dict:
    return {
        "spoofing_radar": backtest_spoofing(),
        "fractional_kelly": backtest_kelly(),
        "conformal_filter": backtest_conformal(),
        "quantile_volatility": backtest_quantile_vol(),
        "hawkes_process": backtest_hawkes(),
        "bayesian_classifier": backtest_bayes(),
        "random_matrix_theory": backtest_rmt(),
    }


def format_report(results: dict | None = None) -> str:
    r = results or run_all()
    L: list[str] = []
    L.append("=" * 64)
    L.append("  MarketMind AI — quant & manipulation backtest report")
    L.append("=" * 64)

    s = r["spoofing_radar"]
    L.append("\n[1] SPOOFING RADAR  (Bayesian fusion + Hawkes cancel bursts)")
    L.append(f"    windows={s['n']}  spoof events={s['spoof_events']}  threshold={s['threshold']}/100")
    L.append(f"    precision={s['precision']}  recall={s['recall']}  F1={s['f1']}  AUC={s['auc']}")
    L.append(f"    mean score  spoof={s['mean_score_spoof']}  clean={s['mean_score_clean']}")
    L.append(f"    confusion   {s['confusion']}")

    k = r["fractional_kelly"]
    L.append(f"\n[2] FRACTIONAL KELLY  (p={k['p']}, odds b={k['b']}, {k['rounds']} rounds x {k['paths']} paths)")
    for name, v in k["strategies"].items():
        L.append(f"    {name:<11} f={v['fraction']:<6} median_bankroll={v['median_bankroll']:<12} "
                 f"maxDD={v['max_drawdown']:<7} P(loss)={v['prob_below_start']}")

    c = r["conformal_filter"]
    L.append("\n[3] CONFORMAL FILTER  (split conformal prediction interval)")
    L.append(f"    nominal={c['nominal_coverage']}  empirical={c['empirical_coverage']}  "
             f"avg_width={c['avg_interval_width']}  ok={c['coverage_ok']}")

    q = r["quantile_volatility"]
    L.append("\n[4] QUANTILE VOLATILITY  (5%/95% next-return quantiles, fat tails)")
    L.append(f"    target=0.90  quantile_coverage={q['empirical_quantile_coverage']}  "
             f"gaussian_VaR_coverage={q['gaussian_var_coverage']}")
    L.append(f"    tail breaches  below={q['breach_below_5pct']}  above={q['breach_above_5pct']}")

    h = r["hawkes_process"]
    L.append("\n[5] HAWKES PROCESS  (parameter recovery via MLE)")
    L.append(f"    events={h['n_events']}")
    L.append(f"    true   {h['true']}")
    L.append(f"    fitted {h['fitted']}")

    b = r["bayesian_classifier"]
    L.append("\n[6] BAYESIAN CLASSIFIER  (Gaussian NB regime detection)")
    L.append(f"    test={b['n_test']}  accuracy={b['accuracy']}")

    m = r["random_matrix_theory"]
    L.append("\n[7] RANDOM MATRIX THEORY  (Marchenko-Pastur signal separation)")
    L.append(f"    true_factors={m['true_factors']}  detected={m['detected_signal_eigenvalues']}  "
             f"lambda_1={m['lambda_1']}  MP_edge={m['mp_upper_edge']}  recovered={m['recovered']}")

    L.append("\n" + "=" * 64)
    return "\n".join(L)


if __name__ == "__main__":
    print(format_report())
