"""The warning engine must fire on real divergences and stay quiet otherwise."""
from app.money_flow import build_warnings

_QUIET_PROVEN = {"active": False}


def _cls(cid, label, f1, f5, children=None):
    return {"id": cid, "label": label, "flow_1d_b": f1, "flow_5d_b": f5, "children": children or []}


def _titles(ws):
    return " | ".join(w["title"] for w in ws)


def test_risk_on_into_draining_liquidity_is_high():
    liq = {"dir": "down", "flow_b": -69.6}
    ws = build_warnings(liq, [_cls("stocks", "STOCKS", 10.0, 12.0)], "RISK-ON", 17.0,
                        _QUIET_PROVEN, {"rrp_b": 500})
    hit = [w for w in ws if "fighting the liquidity" in w["title"]]
    assert hit and hit[0]["level"] == "high"


def test_empty_rrp_buffer_is_high():
    ws = build_warnings({"dir": "up", "flow_b": 10}, [_cls("stocks", "STOCKS", 1.0, 1.0)],
                        "RISK-ON", 17.0, _QUIET_PROVEN, {"rrp_b": 1.0})
    hit = [w for w in ws if "Reverse-repo" in w["title"]]
    assert hit and hit[0]["level"] == "high"


def test_today_against_the_week_flags_bounce():
    ws = build_warnings({"dir": "up"}, [_cls("stocks", "STOCKS", 13.0, -31.0)],
                        "RISK-ON", 17.0, _QUIET_PROVEN, {"rrp_b": 500})
    assert "against the week" in _titles(ws)


def test_rotation_inside_class_detected():
    kids = [{"label": "SPY", "flow_1d_b": 41.0}, {"label": "QQQ", "flow_1d_b": -30.0}]
    ws = build_warnings({"dir": "up"}, [_cls("stocks", "STOCKS", 11.0, 11.0, kids)],
                        "RISK-ON", 17.0, _QUIET_PROVEN, {"rrp_b": 500})
    assert "rotation inside the class" in _titles(ws)


def test_active_proven_signal_is_high():
    ws = build_warnings({"dir": "up"}, [_cls("stocks", "STOCKS", 1.0, 1.0)], "RISK-OFF",
                        25.0, {"active": True}, {"rrp_b": 500})
    hit = [w for w in ws if "PROVEN SIGNAL ACTIVE" in w["title"]]
    assert hit and hit[0]["level"] == "high"


def test_quiet_market_says_nothing_unusual():
    ws = build_warnings({"dir": "up", "flow_b": 5}, [_cls("stocks", "STOCKS", 2.0, 3.0)],
                        "RISK-ON", 18.0, _QUIET_PROVEN, {"rrp_b": 500})
    assert len(ws) == 1 and ws[0]["level"] == "info"
    assert "Nothing unusual" in ws[0]["title"]
