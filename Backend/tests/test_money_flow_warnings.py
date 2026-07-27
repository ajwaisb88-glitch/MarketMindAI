"""The warning engine must fire on real divergences and stay quiet otherwise.

Signature: build_warnings(liquidity, classes, regime, proven, fred).
The universe is crypto (majors / alts / meme / gold / stable) — Binance-only.
"""
from app.money_flow import build_warnings

_QUIET_PROVEN = {"active": False}


def _cls(cid, label, f1, f5, children=None):
    return {"id": cid, "label": label, "flow_1d_b": f1, "flow_5d_b": f5, "children": children or []}


def _titles(ws):
    return " | ".join(w["title"] for w in ws)


def _has_explain(ws):
    return all("explain" in w and w["explain"] for w in ws)


def test_risk_on_into_draining_liquidity_is_high():
    liq = {"dir": "down", "flow_b": -69.6}
    ws = build_warnings(liq, [_cls("majors", "MAJORS", 10.0, 12.0)], "RISK-ON",
                        _QUIET_PROVEN, {"rrp_b": 500})
    hit = [w for w in ws if "fighting the Fed" in w["title"]]
    assert hit and hit[0]["level"] == "high"
    assert _has_explain(ws)


def test_empty_rrp_buffer_is_high():
    ws = build_warnings({"dir": "up", "flow_b": 10}, [_cls("majors", "MAJORS", 1.0, 1.0)],
                        "RISK-ON", _QUIET_PROVEN, {"rrp_b": 1.0})
    hit = [w for w in ws if "safety cushion" in w["title"]]
    assert hit and hit[0]["level"] == "high"


def test_burning_stablecoins_flags_shrinking_dry_powder():
    ws = build_warnings({"dir": "up"}, [_cls("stable", "STABLECOIN", -1.2, -0.4)],
                        "RISK-ON", _QUIET_PROVEN, {"rrp_b": 500})
    assert "Dry powder is shrinking" in _titles(ws)


def test_meme_leading_the_majors_is_flagged():
    classes = [_cls("majors", "MAJORS", 2.0, 3.0), _cls("meme", "MEME", 5.0, 4.0)]
    ws = build_warnings({"dir": "up"}, classes, "RISK-ON", _QUIET_PROVEN, {"rrp_b": 500})
    assert "Gamble money is leading" in _titles(ws)


def test_today_against_the_week_flags_bounce():
    ws = build_warnings({"dir": "up"}, [_cls("majors", "MAJORS", 13.0, -31.0)],
                        "RISK-ON", _QUIET_PROVEN, {"rrp_b": 500})
    assert "today fights the week" in _titles(ws)


def test_active_proven_signal_is_high():
    ws = build_warnings({"dir": "up"}, [_cls("majors", "MAJORS", 1.0, 1.0)], "RISK-OFF",
                        {"active": True}, {"rrp_b": 500})
    hit = [w for w in ws if "Fear pattern is ON" in w["title"]]
    assert hit and hit[0]["level"] == "high"


def test_quiet_market_says_nothing_unusual():
    ws = build_warnings({"dir": "up", "flow_b": 5}, [_cls("majors", "MAJORS", 2.0, 3.0)],
                        "RISK-ON", _QUIET_PROVEN, {"rrp_b": 500})
    assert len(ws) == 1 and ws[0]["level"] == "info"
    assert "Nothing unusual" in ws[0]["title"]
    assert _has_explain(ws)
