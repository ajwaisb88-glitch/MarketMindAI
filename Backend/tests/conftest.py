"""Shared test setup.

Force offline/deterministic pricing during tests: the live-price seam
(manipulation.live_mid) would otherwise hit Binance/MT5 for every asset, making
the suite slow and non-deterministic. With this flag the feed uses each asset's
static profile mid, exactly as the tests expect.
"""
import os

os.environ.setdefault("MARKETMIND_LIVE_PRICES", "0")
