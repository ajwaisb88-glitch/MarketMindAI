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


def test_measured_edge_tracks_price_impact():
    # A coin-flip impact must yield ~coin-flip edge; strong impact a real edge.
    flip = scalping.measure_signal_edge(p_impact=0.5, n=4000, seed=0)
    strong = scalping.measure_signal_edge(p_impact=0.85, n=4000, seed=0)
    assert abs(flip["measured_edge"] - 0.5) < 0.05
    assert strong["measured_edge"] > flip["measured_edge"] + 0.15
    assert 0.0 < flip["trade_rate"] <= 1.0


def test_backtest_from_signal_shape():
    r = scalping.backtest_from_signal(p_impact=0.7, paths=800, seed=1)
    assert "signal" in r and "strategy" in r
    assert 0.5 <= r["strategy"]["config"]["edge"] <= 0.7


def test_impact_sweep_is_monotonic_in_edge():
    rows = scalping.impact_sweep(paths=800, seed=0)
    edges = [r["measured_edge"] for r in rows]
    assert edges == sorted(edges)


def test_config_for_asset_uses_profile_width():
    from app.manipulation import market_profile
    cfg = scalping.config_for_asset("gold")
    assert cfg.scalp_move_pct == market_profile("gold")["scalp_move_pct"]


def test_scalping_scan_covers_all_assets():
    from app.manipulation import MARKET_PROFILES
    rows = scalping.scan_assets_scalping(paths=600, seed=0)
    assert {r["asset"] for r in rows} == set(MARKET_PROFILES.keys())
    # ranked by upside, all probabilities valid
    reach = [r["prob_reach_1000"] for r in rows]
    assert reach == sorted(reach, reverse=True)
    for r in rows:
        assert 0.0 <= r["prob_reach_1000"] <= 1.0
        assert 0.0 <= r["prob_ruin"] <= 1.0
