"""The order-book diff calibration must reject MM churn but keep real pulls."""
from app.connectors.binance_feed import BinanceOrderBookFeed


def _book(bid_px, bid_sz, ask_px, ask_sz):
    return {"bid_prices": bid_px, "bid_sizes": bid_sz,
            "ask_prices": ask_px, "ask_sizes": ask_sz}


def test_benign_reprice_is_not_a_cancel():
    """A resting order that moves one tick (cancel + re-add nearby) is a reprice,
    not a spoof pull — it must net to (near) zero cancel size."""
    feed = BinanceOrderBookFeed()
    d0 = _book([100.0, 99.0, 98.0], [5.0, 5.0, 5.0], [101.0, 102.0, 103.0], [5.0, 5.0, 5.0])
    # the 99.0 order (5.0) is repriced to 98.5-ish → drop at 99, add at 99.0 shifted.
    d1 = _book([100.0, 98.0, 97.0], [5.0, 10.0, 5.0], [101.0, 102.0, 103.0], [5.0, 5.0, 5.0])
    tick = 1.0
    mid = 100.5
    events = feed._diff_events(d0, d1, mid, tick)
    cancel_size = sum(e.size for e in events if e.action == "cancel")
    assert cancel_size == 0.0  # the pulled 5 @99 is absorbed by the +5 @98 reprice


def test_real_wall_pull_is_flagged_as_cancel():
    """A large wall a few ticks back that vanishes with no matching add is a
    genuine cancellation and MUST be flagged."""
    feed = BinanceOrderBookFeed()
    d0 = _book([100.0, 99.0, 95.0], [5.0, 5.0, 80.0], [101.0, 102.0, 103.0], [5.0, 5.0, 5.0])
    d1 = _book([100.0, 99.0, 95.0], [5.0, 5.0, 0.0], [101.0, 102.0, 103.0], [5.0, 5.0, 5.0])
    events = feed._diff_events(d0, d1, mid=100.5, tick=1.0)
    cancels = [e for e in events if e.action == "cancel"]
    assert len(cancels) == 1
    assert cancels[0].size == 80.0
    assert cancels[0].distance_ticks > 3  # the wall sat back from the touch


def test_tiny_churn_below_threshold_ignored():
    feed = BinanceOrderBookFeed()
    d0 = _book([100.0, 99.0], [5.0, 5.0], [101.0, 102.0], [5.0, 5.0])
    d1 = _book([100.0, 99.0], [4.9, 5.0], [101.0, 102.0], [5.0, 5.0])  # trivial 0.1 change
    events = feed._diff_events(d0, d1, mid=100.5, tick=1.0)
    assert all(e.action != "cancel" for e in events)
