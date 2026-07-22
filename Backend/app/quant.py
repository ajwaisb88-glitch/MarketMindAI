"""Quantitative toolkit for MarketMind AI.

Real, self-contained implementations of the six quant models shown in the
project brief. Each function is deterministic given its inputs, depends only on
numpy, and carries the formula it implements in its docstring so the maths can
be checked against the code.

    1. Hawkes process ...... lambda(t) = mu + sum a * exp(-beta * (t - t_i))
    2. Bayesian classifier .. P(H|E) = P(E|H) P(H) / P(E)
    3. Quantile volatility .. Q_tau(r_{t+h} | X_t)
    4. Conformal filter ..... C_t = [y_hat_t - q_hat, y_hat_t + q_hat]
    5. Fractional Kelly ..... f* = c (b p - q) / b
    6. Random matrix theory . C = (1/T) X X^T -> lambda_1 (Marchenko-Pastur)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

ArrayLike = Sequence[float] | np.ndarray


# ---------------------------------------------------------------------------
# 1. Hawkes process — self-exciting point process intensity
# ---------------------------------------------------------------------------

def hawkes_intensity(
    t: float,
    event_times: ArrayLike,
    mu: float,
    alpha: float,
    beta: float,
) -> float:
    """Conditional intensity of a univariate Hawkes process at time ``t``.

        lambda(t) = mu + sum_{t_i < t} alpha * exp(-beta * (t - t_i))

    ``mu`` is the baseline rate, ``alpha`` the jump in intensity caused by each
    past event and ``beta`` the exponential decay speed. Only events strictly
    before ``t`` contribute.
    """
    if beta <= 0:
        raise ValueError("beta must be positive")
    times = np.asarray(event_times, dtype=float)
    past = times[times < t]
    if past.size == 0:
        return float(mu)
    excitation = alpha * np.exp(-beta * (t - past)).sum()
    return float(mu + excitation)


def hawkes_intensity_path(
    grid: ArrayLike,
    event_times: ArrayLike,
    mu: float,
    alpha: float,
    beta: float,
) -> np.ndarray:
    """Vectorised :func:`hawkes_intensity` evaluated on a whole time ``grid``."""
    grid = np.asarray(grid, dtype=float)
    return np.array([hawkes_intensity(t, event_times, mu, alpha, beta) for t in grid])


def hawkes_log_likelihood(
    event_times: ArrayLike,
    mu: float,
    alpha: float,
    beta: float,
    t_end: float | None = None,
) -> float:
    """Exact log-likelihood of a Hawkes process using the recursive kernel.

    Uses Ogata's recursion so the sum over history is O(n) rather than O(n^2)::

        log L = -mu * T - (alpha/beta) * sum(1 - exp(-beta (T - t_i)))
                + sum_i log(mu + alpha * R_i)

    where ``R_i = exp(-beta (t_i - t_{i-1})) (1 + R_{i-1})``.
    """
    times = np.sort(np.asarray(event_times, dtype=float))
    n = times.size
    if n == 0:
        return 0.0
    T = float(times[-1] if t_end is None else t_end)

    compensator = mu * T + (alpha / beta) * np.sum(1.0 - np.exp(-beta * (T - times)))

    log_sum = np.log(mu)  # first event has empty history
    r = 0.0
    for i in range(1, n):
        r = np.exp(-beta * (times[i] - times[i - 1])) * (1.0 + r)
        log_sum += np.log(mu + alpha * r)
    return float(log_sum - compensator)


# ---------------------------------------------------------------------------
# 2. Bayesian classifier — posterior via Bayes' theorem
# ---------------------------------------------------------------------------

def bayes_posterior(
    likelihood: float,
    prior: float,
    evidence: float | None = None,
    likelihood_not: float | None = None,
) -> float:
    """Posterior probability P(H|E) from Bayes' theorem.

        P(H|E) = P(E|H) P(H) / P(E)

    ``evidence`` = P(E) may be supplied directly. If it is omitted it is
    computed from the law of total probability using ``likelihood_not`` = P(E|~H)::

        P(E) = P(E|H) P(H) + P(E|~H) (1 - P(H))
    """
    if evidence is None:
        if likelihood_not is None:
            raise ValueError("provide either evidence P(E) or likelihood_not P(E|~H)")
        evidence = likelihood * prior + likelihood_not * (1.0 - prior)
    if evidence <= 0:
        return 0.0
    return float(likelihood * prior / evidence)


def gaussian_nb_predict(
    x: ArrayLike,
    class_stats: dict[str, dict[str, np.ndarray | float]],
) -> dict[str, float]:
    """Gaussian Naive Bayes posterior over classes for one feature vector.

    ``class_stats`` maps a class label to ``{"prior", "mean", "var"}``. Returns
    normalised posteriors P(class | x) computed in log-space for stability.
    """
    x = np.asarray(x, dtype=float)
    log_post: dict[str, float] = {}
    for label, s in class_stats.items():
        mean = np.asarray(s["mean"], dtype=float)
        var = np.asarray(s["var"], dtype=float) + 1e-12
        log_lik = -0.5 * np.sum(np.log(2 * np.pi * var) + (x - mean) ** 2 / var)
        log_post[label] = float(np.log(s["prior"]) + log_lik)
    m = max(log_post.values())
    exp = {k: np.exp(v - m) for k, v in log_post.items()}
    total = sum(exp.values())
    return {k: float(v / total) for k, v in exp.items()}


# ---------------------------------------------------------------------------
# 3. Quantile volatility — conditional return quantiles
# ---------------------------------------------------------------------------

def quantile_volatility(
    returns: ArrayLike,
    tau: float | Sequence[float] = (0.05, 0.5, 0.95),
    horizon: int = 1,
) -> dict[float, float]:
    """Empirical conditional quantiles Q_tau(r_{t+h} | X_t) of forward returns.

    A distribution-free estimate of the ``tau``-quantile of the ``horizon``-step
    ahead return, which is the volatility object in the brief. Returning the
    0.05 / 0.95 pair gives a symmetric interval whose half-width is a robust
    volatility proxy (VaR-style).
    """
    r = np.asarray(returns, dtype=float)
    if horizon > 1:
        # overlapping h-step cumulative returns
        r = np.array([r[i:i + horizon].sum() for i in range(len(r) - horizon + 1)])
    taus = [tau] if np.isscalar(tau) else list(tau)
    return {float(q): float(np.quantile(r, q)) for q in taus}


def pinball_loss(y_true: ArrayLike, y_pred: ArrayLike, tau: float) -> float:
    """Quantile (pinball) loss — the proper scoring rule for quantile forecasts.

        L_tau(y, y_hat) = mean( max(tau (y - y_hat), (tau - 1) (y - y_hat)) )
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    diff = y_true - y_pred
    return float(np.mean(np.maximum(tau * diff, (tau - 1.0) * diff)))


# ---------------------------------------------------------------------------
# 4. Conformal filter — distribution-free prediction interval
# ---------------------------------------------------------------------------

def conformal_interval(
    point_forecast: float,
    calibration_residuals: ArrayLike,
    alpha: float = 0.1,
) -> tuple[float, float]:
    """Split-conformal prediction interval around a point forecast.

        C_t = [ y_hat_t - q_hat , y_hat_t + q_hat ]

    ``q_hat`` is the (1-alpha) empirical quantile of absolute calibration
    residuals, with the finite-sample correction ceil((n+1)(1-alpha))/n that
    guarantees marginal coverage >= 1-alpha.
    """
    res = np.abs(np.asarray(calibration_residuals, dtype=float))
    n = res.size
    if n == 0:
        raise ValueError("need at least one calibration residual")
    level = np.ceil((n + 1) * (1.0 - alpha)) / n
    level = min(level, 1.0)
    q_hat = float(np.quantile(res, level, method="higher"))
    return point_forecast - q_hat, point_forecast + q_hat


def conformal_coverage(
    y_true: ArrayLike,
    lowers: ArrayLike,
    uppers: ArrayLike,
) -> float:
    """Fraction of realised values that fall inside their conformal intervals."""
    y = np.asarray(y_true, dtype=float)
    lo = np.asarray(lowers, dtype=float)
    hi = np.asarray(uppers, dtype=float)
    return float(np.mean((y >= lo) & (y <= hi)))


# ---------------------------------------------------------------------------
# 5. Fractional Kelly — risk-scaled optimal bet size
# ---------------------------------------------------------------------------

def fractional_kelly(
    p: float,
    b: float,
    c: float = 0.5,
    q: float | None = None,
) -> float:
    """Fractional Kelly stake as a fraction of bankroll.

        f* = c * (b p - q) / b

    ``p`` win probability, ``q = 1 - p`` loss probability, ``b`` net odds
    (payout per unit staked) and ``c`` the Kelly fraction (0.5 = "half Kelly").
    The result is clipped to [0, 1]; a non-positive edge yields 0 (no bet).
    """
    if b <= 0:
        raise ValueError("odds b must be positive")
    if q is None:
        q = 1.0 - p
    full_kelly = (b * p - q) / b
    f = c * full_kelly
    return float(min(max(f, 0.0), 1.0))


def kelly_growth_rate(f: float, p: float, b: float) -> float:
    """Expected log-growth rate of bankroll for a binary bet at fraction ``f``.

        g(f) = p log(1 + f b) + (1 - p) log(1 - f)
    """
    if f <= 0:
        return 0.0
    if f >= 1:
        return float("-inf")
    return float(p * np.log(1 + f * b) + (1 - p) * np.log(1 - f))


# ---------------------------------------------------------------------------
# 6. Random matrix theory — Marchenko-Pastur signal/noise separation
# ---------------------------------------------------------------------------

def marchenko_pastur_bounds(n_samples: int, n_assets: int, sigma: float = 1.0) -> tuple[float, float]:
    """Support [lambda_-, lambda_+] of the Marchenko-Pastur law.

        lambda_+/- = sigma^2 (1 +/- sqrt(q))^2,  q = n_assets / n_samples

    Eigenvalues of the empirical correlation matrix above lambda_+ are signal;
    those inside the band are indistinguishable from noise.
    """
    q = n_assets / n_samples
    lam_min = sigma ** 2 * (1.0 - np.sqrt(q)) ** 2
    lam_max = sigma ** 2 * (1.0 + np.sqrt(q)) ** 2
    return float(lam_min), float(lam_max)


@dataclass
class RMTResult:
    eigenvalues: np.ndarray
    lambda_max_theory: float
    lambda_min_theory: float
    lambda_1: float                     # largest empirical eigenvalue
    n_signal_eigenvalues: int           # eigenvalues above the MP edge
    signal_variance_fraction: float     # share of variance in signal modes
    denoised_correlation: np.ndarray = field(repr=False)


def rmt_denoise(returns_matrix: np.ndarray) -> RMTResult:
    """Random-matrix-theory analysis of a T x N returns matrix.

        C = (1/T) X X^T   (correlation of standardised returns)  ->  lambda_1

    Standardises each column, forms the correlation matrix, compares its
    eigenvalues to the Marchenko-Pastur noise band, and rebuilds a denoised
    correlation matrix keeping only the eigenmodes above the upper edge (plus a
    rescaled noise floor so the diagonal stays 1). ``lambda_1`` — the top
    eigenvalue, i.e. the market mode — is reported explicitly.
    """
    X = np.asarray(returns_matrix, dtype=float)
    T, N = X.shape
    mean = X.mean(axis=0)
    std = X.std(axis=0) + 1e-12
    Z = (X - mean) / std
    corr = (Z.T @ Z) / T

    eigvals, eigvecs = np.linalg.eigh(corr)
    order = np.argsort(eigvals)[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]

    lam_min, lam_max = marchenko_pastur_bounds(T, N, sigma=1.0)
    signal_mask = eigvals > lam_max
    n_signal = int(signal_mask.sum())
    signal_frac = float(eigvals[signal_mask].sum() / eigvals.sum()) if eigvals.sum() > 0 else 0.0

    # Denoise: keep signal eigenvalues, replace the bulk with their average,
    # then rescale the diagonal back to 1 (Bouchaud/Potters clipping).
    cleaned = eigvals.copy()
    if (~signal_mask).any():
        cleaned[~signal_mask] = eigvals[~signal_mask].mean()
    denoised = eigvecs @ np.diag(cleaned) @ eigvecs.T
    d = np.sqrt(np.diag(denoised))
    denoised = denoised / np.outer(d, d)

    return RMTResult(
        eigenvalues=eigvals,
        lambda_max_theory=lam_max,
        lambda_min_theory=lam_min,
        lambda_1=float(eigvals[0]),
        n_signal_eigenvalues=n_signal,
        signal_variance_fraction=signal_frac,
        denoised_correlation=denoised,
    )
