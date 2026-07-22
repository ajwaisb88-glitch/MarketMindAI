"""Tests for the scalping strategy backtest."""

from app import scalping
from app.scalping import ScalpConfig


def test_no_edge_means_no_bet():
    # Kelly says stake nothing at a coin-flip, so equity is unchanged.
    cfg = ScalpConfig(edge=0.50)
    r = scalping.simulate_paths(cfg, paths=500, seed=0)
    assert r["risk_per_trade"] == 0.0
    assert r["median_final_equity"] == cfg.start_equity


def test_leverage_is_derived_from_scalp_geometry():
    # risk 5% of equity on a 0.5% move => 10x leverage.
    cfg = ScalpConfig(edge=0.56, scalp_move_pct=0.5, max_risk=0.05)
    r = scalping.simulate_paths(cfg, paths=200, seed=0)
    assert abs(r["implied_leverage"] - 10.0) < 1e-6


def test_leverage_clamped_to_exchange_cap():
    cfg = ScalpConfig(edge=0.60, scalp_move_pct=0.1, max_risk=0.5, max_leverage=50.0)
    r = scalping.simulate_paths(cfg, paths=200, seed=0)
    assert r["implied_leverage"] <= 50.0 + 1e-9


def test_probabilities_are_valid():
    r = scalping.simulate_paths(ScalpConfig(), paths=1000, seed=1)
    for key in ("prob_reach_1000", "prob_ruin", "prob_below_start", "median_max_drawdown"):
        assert 0.0 <= r[key] <= 1.0


def test_bigger_edge_reaches_target_more_often():
    low = scalping.simulate_paths(ScalpConfig(edge=0.54), paths=3000, seed=2)
    high = scalping.simulate_paths(ScalpConfig(edge=0.60), paths=3000, seed=2)
    assert high["prob_reach_1000"] >= low["prob_reach_1000"]


def test_tighter_scalp_costs_more():
    wide = scalping.simulate_paths(ScalpConfig(scalp_move_pct=1.2), paths=200, seed=0)
    tight = scalping.simulate_paths(ScalpConfig(scalp_move_pct=0.2), paths=200, seed=0)
    assert tight["cost_per_trade_pct"] > wide["cost_per_trade_pct"]


def test_one_path_stops_at_target_or_ruin():
    r = scalping.one_path(ScalpConfig(edge=0.6), seed=5)
    assert "equity_curve" in r
    assert r["final_equity"] >= 0.0
    if r["reached_1000"]:
        assert r["equity_curve"][-1] >= 1000.0


def test_sweeps_return_rows():
    assert len(scalping.edge_sweep(paths=300)) == 6
    assert len(scalping.scalp_size_sweep(paths=300)) == 5
