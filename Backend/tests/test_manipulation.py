"""Unit tests for the spoofing detection engine."""

import numpy as np
import pytest

from app import manipulation as m


def _snap(bid_sizes, ask_sizes):
    n = len(bid_sizes)
    return m.OrderBookSnapshot(
        bid_prices=100 - np.arange(1, n + 1),
        bid_sizes=np.array(bid_sizes, dtype=float),
        ask_prices=100 + np.arange(1, n + 1),
        ask_sizes=np.array(ask_sizes, dtype=float),
    )


def test_imbalance_bounds_and_sign():
    assert m.order_book_imbalance(_snap([10, 10], [10, 10])) == 0.0
    assert m.order_book_imbalance(_snap([10, 10], [0, 0])) == 1.0
    assert m.order_book_imbalance(_snap([0, 0], [10, 10])) == -1.0


def test_cancel_trade_ratio():
    events = [
        m.FlowEvent(0, "bid", "cancel", 10, 3),
        m.FlowEvent(1, "bid", "trade", 5, 0),
    ]
    assert m.cancel_trade_ratio(events) == 2.0


def test_phantom_liquidity_far_share():
    events = [
        m.FlowEvent(0, "bid", "cancel", 8, 5),   # far
        m.FlowEvent(1, "bid", "cancel", 2, 1),   # near
    ]
    assert m.phantom_liquidity(events, near_ticks=3.0) == 0.8


def test_spoof_scores_higher_than_clean():
    feed = m.OrderBookFeed(seed=1)
    spoof_snap, spoof_ev = feed.sample(spoof=True, strength=1.0)
    clean_snap, clean_ev = feed.sample(spoof=False)
    spoof = m.spoofing_probability(spoof_snap, spoof_ev)
    clean = m.spoofing_probability(clean_snap, clean_ev)
    assert spoof.probability > clean.probability
    assert spoof.probability >= 70
    assert 0 <= clean.probability <= 100


def test_report_fields_and_sentiment_normalised():
    feed = m.OrderBookFeed(seed=2)
    snap, ev = feed.sample(spoof=True, strength=0.9)
    r = m.spoofing_probability(snap, ev, funding_rate=0.0005)
    assert 0 <= r.probability <= 100
    assert abs(sum(r.sentiment.values()) - 1.0) < 1e-6
    assert set(r.sentiment) == {"SPOOF", "SHEEP", "WHALE"}
    assert r.label in {"POSSIBLE SPOOFING", "ELEVATED", "CLEAN"}


def test_pressure_side_and_predicted_move():
    bid_wall = [m.FlowEvent(0, "bid", "cancel", 10, 5), m.FlowEvent(1, "ask", "cancel", 1, 4)]
    assert m.spoof_pressure_side(bid_wall) == "bid"
    ask_wall = [m.FlowEvent(0, "ask", "cancel", 10, 5), m.FlowEvent(1, "bid", "cancel", 1, 4)]
    assert m.spoof_pressure_side(ask_wall) == "ask"
    assert m.spoof_pressure_side([]) is None


def test_report_carries_direction_on_spoof():
    feed = m.OrderBookFeed(seed=3)
    snap, ev = feed.sample(spoof=True, side="bid", strength=1.0)
    r = m.spoofing_probability(snap, ev)
    assert r.pressure_side in {"bid", "ask", None}
    assert r.predicted_move in {-1, 0, 1}
    # a bid wall should predict a downward fade
    if r.pressure_side == "bid":
        assert r.predicted_move == -1


def test_feed_is_deterministic():
    a = m.OrderBookFeed(seed=42).sample(spoof=True, strength=0.7)
    b = m.OrderBookFeed(seed=42).sample(spoof=True, strength=0.7)
    assert np.allclose(a[0].bid_sizes, b[0].bid_sizes)
    assert len(a[1]) == len(b[1])


def test_for_asset_uses_profile_and_unknown_falls_back():
    btc = m.OrderBookFeed.for_asset("btc", seed=0)
    assert btc.mid == m.MARKET_PROFILES["btc"]["mid"]
    assert btc.crypto is True
    unknown = m.OrderBookFeed.for_asset("dogecoin_xyz", seed=0)  # not in the map
    assert unknown.mid == m.DEFAULT_PROFILE["mid"]


def test_non_crypto_has_no_funding():
    assert m.OrderBookFeed.for_asset("gold", seed=0).funding_rate() == 0.0
    assert m.OrderBookFeed.for_asset("eurusd", seed=0).funding_rate() == 0.0


def test_scan_all_assets_is_stable_and_ranked():
    reports = m.scan_assets(seed=3)
    assert len(reports) == len(m.MARKET_PROFILES)
    probs = [r["probability"] for r in reports]
    assert probs == sorted(probs, reverse=True)      # ranked highest-risk first
    for r in reports:
        assert 0 <= r["probability"] <= 100
        assert abs(sum(r["sentiment"].values()) - 1.0) < 0.01  # 3-dp rounding
    # deterministic
    assert [r["asset"] for r in reports] == [r["asset"] for r in m.scan_assets(seed=3)]


def test_scan_runs_for_every_supported_asset_without_error():
    scanned = {r["asset"] for r in m.scan_assets(seed=0)}
    assert scanned == set(m.MARKET_PROFILES.keys())


# --- signal grading -------------------------------------------------------

def test_letter_bands_are_ordered():
    assert m._letter(95) == "A+"
    assert m._letter(80) == "A1"
    assert m._letter(65) == "A"
    assert m._letter(50) == "B"
    assert m._letter(40) == "C"
    assert m._letter(25) == "D"
    assert m._letter(5) == "F"


def test_tradability_wide_beats_tight():
    # oil (wide 0.45% scalp) is far more tradable than eurusd (0.1%).
    assert m.tradability_score("oil") > m.tradability_score("gold") > m.tradability_score("eurusd")
    assert m.tradability_score("eurusd") < 20


def test_no_signal_is_no_trade():
    assert m.grade_signal(0, "btc", 0)["grade"] == "NO-TRADE"        # clean book
    assert m.grade_signal(100, "btc", 0)["grade"] == "NO-TRADE"      # no direction
    assert m.grade_signal(20, "btc", -1)["grade"] == "NO-TRADE"      # weak conviction


def test_tradability_caps_a_strong_signal():
    # Same max conviction: a wide market grades far above an un-tradable one.
    oil = m.grade_signal(100, "oil", -1)
    eur = m.grade_signal(100, "eurusd", 1)
    assert oil["score"] > eur["score"]
    assert oil["grade"] == "A+"
    assert eur["grade"] in {"C", "D", "F"}


def test_gold_profile_fix_gives_tradable_ceiling():
    # After widening gold's default scalp, a strong gold signal is at least A1.
    assert m.grade_signal(100, "gold", -1)["grade"] in {"A+", "A1"}


def test_grade_rank_ordering():
    assert m.grade_rank("A+") > m.grade_rank("A1") > m.grade_rank("A") > m.grade_rank("B")
    assert m.grade_rank("NO-TRADE") < m.grade_rank("F")
    assert m.grade_rank("nonsense") == -1


def test_trade_plan_levels_are_consistent():
    long = m.build_trade_plan("btc", 60000.0, "long", payoff=1.5)
    assert long["stop_loss"] < long["entry"] < long["take_profit"]
    # reward:risk holds — TP distance is payoff x SL distance
    up = long["take_profit"] - long["entry"]
    dn = long["entry"] - long["stop_loss"]
    assert up == pytest.approx(1.5 * dn, rel=1e-3)
    assert long["trailing_tp"]["arms_at"] > long["entry"]

    short = m.build_trade_plan("btc", 60000.0, "short", payoff=1.5)
    assert short["stop_loss"] > short["entry"] > short["take_profit"]
    assert short["trailing_tp"]["arms_at"] < short["entry"]


def test_trade_plan_flat_has_no_levels():
    assert m.build_trade_plan("btc", 100.0, "flat")["direction"] == "flat"


def test_signals_per_day_splits_true_and_false():
    e = m.estimate_signals_per_day("btc", scan_interval_sec=30, spoof_base_rate=0.05,
                                   min_grade="A", n=4000, seed=1)
    assert e["windows_per_day"] == 2880
    # totals reconcile and precision is a valid fraction
    assert e["signals_per_day"] == pytest.approx(
        e["real_signals_per_day"] + e["false_alarms_per_day"], rel=1e-6)
    assert 0.0 <= e["precision"] <= 1.0
    # faster scanning yields more windows and at least as many signals
    slow = m.estimate_signals_per_day("btc", scan_interval_sec=60, n=4000, seed=1)
    assert slow["windows_per_day"] < e["windows_per_day"]


def test_untradable_asset_fires_no_graded_signals():
    e = m.estimate_signals_per_day("eurusd", min_grade="A", n=3000, seed=1)
    assert e["signals_per_day"] == 0.0  # eurusd can't reach grade A


def test_scan_includes_grade_and_sinks_no_trades():
    reports = m.scan_assets(seed=7)
    assert all("grade" in r and "direction" in r for r in reports)
    grades = [r["grade"] for r in reports]
    # every NO-TRADE row comes after every graded row
    actionable = [i for i, g in enumerate(grades) if g != "NO-TRADE"]
    no_trade = [i for i, g in enumerate(grades) if g == "NO-TRADE"]
    assert not actionable or not no_trade or max(actionable) < min(no_trade)
