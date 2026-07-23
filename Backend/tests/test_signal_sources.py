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
    monkeypatch.setattr(ss, "_SEL_FILE", str(tmp_path / "sel.json"))
    # a fake source that always returns a BUY so we can assert routing
    class _Fake(ss.SignalSource):
        key = "monster"
        def get(self, asset):
            return {"source": "monster", "asset": asset, "direction": "BUY",
                    "entry": 100.0, "stop_loss": 98.0, "take_profit": 104.0}
    monkeypatch.setitem(ss.REGISTRY, "monster", _Fake())
    sel = ss.SignalSelector()
    sel.set_modes({"monster": "auto", "whale": "off", "marketmind": "off"})
    feed = sel.feed("gold")
    sig = feed["signals"]["monster"]
    assert sig["mode"] == "auto"
    assert sig["execution"]["order"]["side"] == "BUY"          # routed to the terminal
    assert "queued" in sig["execution"]["status"]              # MT not connected yet


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
