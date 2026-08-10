"""The vendored Monster confluence engine must run offline via the bars seam."""
import math

from app.monster.confluence import ConfluenceEngine, MODE_PRESETS, set_bars_provider
from app.signal_sources import _grade_from_score


def _synth_bars(n=400, start=4000.0, step=1.5, vol=1000.0):
    """Deterministic rising series — enough bars for every timeframe."""
    out = []
    t = 1_700_000_000_000
    p = start
    for i in range(n):
        o = p
        c = p + step * math.sin(i / 9.0) + step * 0.35
        h = max(o, c) + step * 0.5
        l = min(o, c) - step * 0.5
        out.append({"t": t + i * 3_600_000, "o": o, "h": h, "l": l, "c": c,
                    "v": vol * (1 + 0.4 * math.sin(i / 5.0))})
        p = c
    return out


def _provider(tf, symbol):
    return _synth_bars()


def test_confluence_runs_and_scores_offline():
    set_bars_provider(_provider)
    r = ConfluenceEngine().analyze(mode="SWING", symbol="XAUUSD")
    assert r["status"] == "ok"
    sc = r["score"]
    # both sides scored on the 100-point scale, with a margin
    assert 0 <= sc["buy"] <= 100 and 0 <= sc["sell"] <= 100
    assert sc["margin"] >= 0
    # five factors are reported per side
    assert len(r["factors"]["buy"]) == 5
    assert r["tier"] and r["reason"]


def test_confluence_reports_no_data_without_provider():
    set_bars_provider(lambda tf, symbol: [])
    r = ConfluenceEngine().analyze(mode="SWING", symbol="XAUUSD")
    assert r["status"] == "error"
    assert "candles" in r["message"].lower()


def test_elliott_wave_excluded_by_design():
    set_bars_provider(_provider)
    r = ConfluenceEngine().analyze(mode="SWING", symbol="XAUUSD")
    names = " ".join(f["name"].lower() for f in r["factors"]["buy"])
    assert "elliott" not in names and "wave" not in names


def test_mode_presets_actionable_thresholds():
    # every mode is actionable at >=66 with 3 of 5 factors
    for m, cfg in MODE_PRESETS.items():
        assert cfg["hits"] == 3
        assert 66 <= cfg["score"] <= 72


def test_grade_ladder_from_confluence_score():
    assert _grade_from_score(90) == "A+"
    assert _grade_from_score(80) == "A1"
    assert _grade_from_score(70) == "A"
    assert _grade_from_score(60) == "B"
    assert _grade_from_score(20) == "C"
