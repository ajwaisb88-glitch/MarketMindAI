"""Tests for the 3-way signal-source selector (Better Volume offline)."""
import numpy as np

import app.signal_sources as ss
from app.better_volume import classify


def test_three_sources_registered():
    assert set(ss.REGISTRY) == {"marketmind", "whale", "monster"}


def test_selector_defaults_to_all_and_can_narrow(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "_SEL_FILE", str(tmp_path / "sel.json"))
    sel = ss.SignalSelector()
    assert set(sel.selected) == {"marketmind", "whale", "monster"}
    sel.select(["monster", "whale"])
    assert set(sel.selected) == {"monster", "whale"}
    # persists + reloads
    assert set(ss.SignalSelector().selected) == {"monster", "whale"}


def test_selector_rejects_empty():
    sel = ss.SignalSelector()
    try:
        sel.select(["nonsense"])
        assert False, "should reject unknown-only selection"
    except ValueError:
        pass


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
