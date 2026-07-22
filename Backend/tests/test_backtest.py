"""Smoke + threshold tests for the backtest harness.

These assert the models clear sane performance bars on the synthetic
benchmarks, so a regression that breaks a detector is caught in CI.
"""

from app import backtest


def test_spoofing_detects_well():
    r = backtest.backtest_spoofing(n=200)
    assert r["recall"] >= 0.9
    assert r["auc"] >= 0.9


def test_kelly_full_beats_flat_overbet():
    r = backtest.backtest_kelly(rounds=200, paths=100)
    full = r["strategies"]["full_kelly"]["median_bankroll"]
    flat = r["strategies"]["flat_20pct"]["median_bankroll"]
    assert full > flat


def test_conformal_hits_nominal_coverage():
    r = backtest.backtest_conformal(n=1500)
    assert r["empirical_coverage"] >= r["nominal_coverage"] - 0.04


def test_quantile_vol_near_target():
    r = backtest.backtest_quantile_vol(n=2000)
    assert abs(r["empirical_quantile_coverage"] - 0.90) <= 0.04


def test_hawkes_recovers_branching_ratio():
    r = backtest.backtest_hawkes(t_max=2000.0)
    true_br = r["true"]["branching_ratio"]
    fit_br = r["fitted"]["branching_ratio"]
    assert abs(true_br - fit_br) <= 0.1


def test_bayes_accuracy_reasonable():
    r = backtest.backtest_bayes(n=1000)
    assert r["accuracy"] >= 0.75


def test_rmt_recovers_factor_count():
    r = backtest.backtest_rmt()
    assert r["recovered"] is True


def test_run_all_returns_all_sections():
    r = backtest.run_all()
    assert set(r) == {
        "spoofing_radar", "fractional_kelly", "conformal_filter",
        "quantile_volatility", "hawkes_process", "bayesian_classifier",
        "random_matrix_theory",
    }
