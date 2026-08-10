"""Offline test for the live-crypto endpoint (Binance mocked)."""
import asyncio

import app.crypto_signals as cs
from app.main import crypto_signals


class _FakeSvc:
    def intraday(self, asset):
        return {"horizon": "intraday", "direction": "long", "grade": "A",
                "entry": 100.0, "stop_loss": 98.0, "take_profit": 104.0}

    def longterm(self, asset):
        return {"horizon": "longterm", "direction": "flat", "grade": "NO-TRADE",
                "entry": 100.0, "stop_loss": 100.0, "take_profit": 100.0}

    def scalp(self, asset, window_sec=1.0):
        return {"type": "scalp", "symbol": asset, "spoof_probability": 72,
                "pressure_side": "ask", "direction": "BUY", "label": "spoof"}


def test_crypto_endpoint_returns_three_separate_signals(monkeypatch):
    monkeypatch.setattr(cs, "CryptoSignalService", _FakeSvc)
    r = asyncio.run(crypto_signals(asset="BTC", scalp=True))
    assert r["asset"] == "btc"
    assert r["data_source"] == "binance"
    # three separate signal blocks, never blended
    assert r["intraday"]["direction"] == "long"
    assert r["longterm"]["grade"] == "NO-TRADE"
    assert r["scalp"]["direction"] == "BUY"


def test_crypto_endpoint_scalp_can_be_disabled(monkeypatch):
    monkeypatch.setattr(cs, "CryptoSignalService", _FakeSvc)
    r = asyncio.run(crypto_signals(asset="eth", scalp=False))
    assert "scalp" not in r
    assert "intraday" in r and "longterm" in r
