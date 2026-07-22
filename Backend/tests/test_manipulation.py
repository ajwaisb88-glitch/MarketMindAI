"""Unit tests for the spoofing detection engine."""

import numpy as np

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


def test_feed_is_deterministic():
    a = m.OrderBookFeed(seed=42).sample(spoof=True, strength=0.7)
    b = m.OrderBookFeed(seed=42).sample(spoof=True, strength=0.7)
    assert np.allclose(a[0].bid_sizes, b[0].bid_sizes)
    assert len(a[1]) == len(b[1])
