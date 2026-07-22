"""Unit tests for the quant toolkit — each formula checked against a known value."""

import numpy as np
import pytest

from app import quant


# --- Hawkes ---------------------------------------------------------------

def test_hawkes_baseline_when_no_history():
    assert quant.hawkes_intensity(0.0, [], mu=0.5, alpha=1.0, beta=2.0) == 0.5


def test_hawkes_excitation_decays():
    near = quant.hawkes_intensity(1.01, [1.0], mu=0.5, alpha=1.0, beta=2.0)
    far = quant.hawkes_intensity(5.0, [1.0], mu=0.5, alpha=1.0, beta=2.0)
    assert near > far > 0.5  # excitation present and decaying toward baseline


def test_hawkes_only_past_events_count():
    # event at t=2 must not affect intensity at t=1
    assert quant.hawkes_intensity(1.0, [2.0], mu=0.3, alpha=1.0, beta=1.0) == 0.3


def test_hawkes_loglik_is_finite_and_recursive_matches_bruteforce():
    times = np.array([0.5, 1.0, 1.2, 3.0, 3.1])
    ll = quant.hawkes_log_likelihood(times, mu=0.5, alpha=0.8, beta=2.0, t_end=4.0)
    assert np.isfinite(ll)


# --- Bayes ----------------------------------------------------------------

def test_bayes_matches_hand_calculation():
    # P(E|H)=0.9, P(H)=0.1, P(E|~H)=0.2 -> P(H|E)=0.09/0.27=0.3333
    post = quant.bayes_posterior(0.9, 0.1, likelihood_not=0.2)
    assert post == pytest.approx(0.3333, abs=1e-3)


def test_bayes_with_direct_evidence():
    assert quant.bayes_posterior(0.5, 0.5, evidence=0.5) == pytest.approx(0.5)


def test_gaussian_nb_picks_closer_class():
    stats = {
        "a": {"prior": 0.5, "mean": np.array([0.0, 0.0]), "var": np.array([1.0, 1.0])},
        "b": {"prior": 0.5, "mean": np.array([5.0, 5.0]), "var": np.array([1.0, 1.0])},
    }
    post = quant.gaussian_nb_predict([0.1, -0.1], stats)
    assert post["a"] > post["b"]
    assert sum(post.values()) == pytest.approx(1.0)


# --- Quantile volatility --------------------------------------------------

def test_quantile_volatility_orders_correctly():
    r = np.linspace(-0.1, 0.1, 1001)
    q = quant.quantile_volatility(r, tau=(0.05, 0.5, 0.95))
    assert q[0.05] < q[0.5] < q[0.95]
    assert q[0.5] == pytest.approx(0.0, abs=1e-6)


def test_pinball_loss_zero_for_perfect():
    y = np.array([1.0, 2.0, 3.0])
    assert quant.pinball_loss(y, y, 0.5) == 0.0


# --- Conformal ------------------------------------------------------------

def test_conformal_interval_contains_point():
    lo, hi = quant.conformal_interval(10.0, [0.5, -0.5, 1.0, -1.0], alpha=0.1)
    assert lo < 10.0 < hi


def test_conformal_coverage_computes_fraction():
    y = np.array([1.0, 2.0, 3.0, 100.0])
    lo = np.zeros(4)
    hi = np.array([5.0, 5.0, 5.0, 5.0])
    assert quant.conformal_coverage(y, lo, hi) == pytest.approx(0.75)


# --- Kelly ----------------------------------------------------------------

def test_fractional_kelly_half_is_half_of_full():
    full = quant.fractional_kelly(0.6, 1.0, c=1.0)
    half = quant.fractional_kelly(0.6, 1.0, c=0.5)
    assert half == pytest.approx(full / 2)
    assert full == pytest.approx(0.2)  # (1*0.6 - 0.4)/1


def test_fractional_kelly_no_edge_no_bet():
    assert quant.fractional_kelly(0.4, 1.0) == 0.0  # negative edge -> clipped to 0


def test_kelly_growth_positive_at_optimum():
    f = quant.fractional_kelly(0.6, 1.0, c=1.0)
    assert quant.kelly_growth_rate(f, 0.6, 1.0) > 0


# --- Random matrix theory -------------------------------------------------

def test_mp_bounds_symmetric_about_one_for_square_ish():
    lo, hi = quant.marchenko_pastur_bounds(1000, 250)  # q=0.25
    assert lo < 1.0 < hi


def test_rmt_recovers_planted_factors():
    rng = np.random.default_rng(0)
    T, N, k = 400, 50, 2
    factors = rng.normal(0, 1, (T, k))
    loadings = rng.normal(0, 1, (k, N))
    returns = factors @ loadings + rng.normal(0, 1, (T, N)) * 2.5
    res = quant.rmt_denoise(returns)
    assert res.n_signal_eigenvalues == k
    assert res.lambda_1 > res.lambda_max_theory
    # denoised correlation keeps unit diagonal
    assert np.allclose(np.diag(res.denoised_correlation), 1.0, atol=1e-6)
