"""Tests for the 3-way signal-source selector (Better Volume offline)."""
import numpy as np

import app.signal_sources as ss
from app.better_volume import classify


def test_three_sources_registered():
    assert set(ss.REGISTRY) == {"marketmind", "whale", "monster"}


def test_modes_default_manual_and_persist(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "_SEL_FILE", str(tmp_path / "sel.json"))
    sel = ss.SignalSelector()
    assert sel.modes == {"marketmind": "manual", "whale": "manual", "monster": "manual"}
    # choose just monster on auto, the rest off
    sel.set_modes({"monster": "auto", "whale": "off", "marketmind": "off"})
    assert sel.active() == ["monster"]
    # persists + reloads
    assert ss.SignalSelector().modes["monster"] == "auto"


def test_mode_validation():
    sel = ss.SignalSelector()
    for bad in [("monster", "sideways"), ("nope", "auto")]:
        try:
            sel.set_mode(*bad)
            assert False, "should reject invalid mode/source"
        except ValueError:
            pass


def test_auto_signal_is_routed_to_terminal(tmp_path, monkeypatch):
    """AUTO signals must reach the router — with the router itself stubbed.

    SAFETY: never let a test call the real executor. A live MT5 terminal with
    AutoTrading enabled would place an actual order from the test suite.
    """
    monkeypatch.setattr(ss, "_SEL_FILE", str(tmp_path / "sel.json"))

    sent = {}

    def _fake_route(signal, lots=0.01, terminal="MT5"):
        sent["signal"] = signal
        return {"routed": False, "status": "stubbed in tests",
                "order": {"side": signal["direction"], "lots": lots}}

    import app.executor as ex
    monkeypatch.setattr(ex, "route", _fake_route)

    class _Fake(ss.SignalSource):
        key = "monster"
        def get(self, asset):
            # Only A+ setups are actionable/routed under the elite-only policy.
            return {"source": "monster", "asset": asset, "direction": "BUY", "grade": "A+",
                    "entry": 100.0, "stop_loss": 98.0, "take_profit": 104.0}
    monkeypatch.setitem(ss.REGISTRY, "monster", _Fake())

    sel = ss.SignalSelector()
    sel.set_modes({"monster": "auto", "whale": "off", "marketmind": "off"})
    sig = sel.feed("gold")["signals"]["monster"]

    assert sig["mode"] == "auto"
    assert sent["signal"]["direction"] == "BUY"                # reached the router
    assert sig["execution"]["order"]["side"] == "BUY"
    assert sig["execution"]["status"] == "stubbed in tests"    # never hit MT5


def test_manual_signals_never_reach_the_router(tmp_path, monkeypatch):
    """The other half of the safety contract: manual mode must not route."""
    monkeypatch.setattr(ss, "_SEL_FILE", str(tmp_path / "sel.json"))
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        return {"routed": False, "status": "should not be called", "order": None}

    import app.executor as ex
    monkeypatch.setattr(ex, "route", _boom)

    class _Fake(ss.SignalSource):
        key = "monster"
        def get(self, asset):
            # Only A+ setups are actionable/routed under the elite-only policy.
            return {"source": "monster", "asset": asset, "direction": "BUY", "grade": "A+",
                    "entry": 100.0, "stop_loss": 98.0, "take_profit": 104.0}
    monkeypatch.setitem(ss.REGISTRY, "monster", _Fake())

    sel = ss.SignalSelector()
    sel.set_modes({"monster": "manual", "whale": "off", "marketmind": "off"})
    sig = sel.feed("gold")["signals"]["monster"]

    assert sig["mode"] == "manual"
    assert "execution" not in sig
    assert called["n"] == 0                                    # router never touched


def test_better_volume_flags_green_churn_buy():
    # 40 calm bars then a high-volume, narrow-range UP bar → Green churn absorption.
    n = 40
    highs = np.full(n, 101.0); lows = np.full(n, 99.0)
    closes = np.full(n, 100.0); opens = np.full(n, 100.0)
    vols = np.full(n, 100.0)
    # last bar: big volume, small range, up close
    highs[-1], lows[-1], opens[-1], closes[-1], vols[-1] = 100.4, 99.9, 100.0, 100.35, 400.0
    r = classify(highs, lows, closes, vols, opens)
    assert r.color in ("Green", "Magenta")
    assert r.direction == "BUY"
    assert r.grade in ("A", "A1", "A+")
