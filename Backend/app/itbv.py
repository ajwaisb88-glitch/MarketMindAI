"""ITBV — Institutional Time + BetterVolume decision engine (gold).

The MarketMind brain, rebuilt on one testable hypothesis:

    Institutional TIME decides WHEN to trade.
    BetterVolume decides WHAT institutions are doing.

Every signal is traceable to (a) an institutional window from the Dubai session
map and (b) a BetterVolume state — nothing else. Outside a tradeable window the
answer is always WAIT/IGNORE, which is the whole point: it stops MarketMind
trading the thin, random hours where it was bleeding.

Decision matrix (window behaviour × BV colour):
  * REVERSAL windows (London open, fixes): fade climaxes, take churn on the turn.
  * CONTINUATION windows (NY overlap, London): go with churn / with the close.
  * SHOCK (US data): stand aside — no entry on the spike.
  * AVOID (Asia, dead, weekend): IGNORE regardless of BetterVolume.
Yellow (low volume) is always WAIT — no institutional participation.
"""
from __future__ import annotations

from . import sessions
from .better_volume import BVResult

_WAIT = {"action": "WAIT", "direction": "NONE", "grade": "-"}


def _reversal(bv: BVResult) -> dict:
    """Sweep-and-reclaim windows: fade exhaustion, trade absorption on the turn."""
    c = bv.color
    if c == "Red":        # climax up → fade the sweep high
        return {"action": "SELL READY", "direction": "SELL", "grade": "A1"}
    if c == "White":      # climax down → fade the sweep low
        return {"action": "BUY READY", "direction": "BUY", "grade": "A1"}
    if c == "Magenta":    # major fight at the extreme → reversal side
        return {"action": ("BUY READY" if bv.direction == "BUY" else "SELL READY"),
                "direction": bv.direction, "grade": "A+"}
    if c == "Green":      # absorption → go with the reclaim
        return {"action": ("BUY" if bv.direction == "BUY" else "SELL"),
                "direction": bv.direction, "grade": "A1"}
    return _WAIT           # Yellow / Neutral


def _continuation(bv: BVResult) -> dict:
    """Overlap / trend windows: ride the move with volume behind it."""
    c = bv.color
    if c == "Green":      # churn/absorption with the close → strongest continuation
        return {"action": ("BUY" if bv.direction == "BUY" else "SELL"),
                "direction": bv.direction, "grade": "A+"}
    if c == "Magenta":
        return {"action": ("BUY" if bv.direction == "BUY" else "SELL"),
                "direction": bv.direction, "grade": "A+"}
    if c in ("Red", "White"):   # climax in a trend window = continuation unless rejected
        return {"action": ("BUY" if bv.direction == "BUY" else "SELL" if bv.direction == "SELL" else "WAIT"),
                "direction": bv.direction, "grade": "A"}
    return _WAIT


def decide(window: dict, bv: BVResult) -> dict:
    """Fuse the institutional window and the BetterVolume state into one action."""
    behavior = window.get("behavior")
    base = {"window": window.get("window"), "window_label": window.get("label"),
            "liquidity": window.get("liquidity"), "behavior": behavior,
            "bv_color": bv.color, "bv_story": bv.story, "volume_ratio": bv.volume_ratio}

    if not window.get("tradeable"):
        # AVOID (Asia/dead/weekend) or SHOCK (data spike) → never enter.
        reason = ("Data-shock window — stand aside; trade the second move once it settles."
                  if behavior == "SHOCK" else
                  f"{window.get('label')} — low-liquidity / non-institutional. No trade.")
        return {**base, **_WAIT, "reason": reason}

    if bv.color in ("Yellow", "Neutral"):
        return {**base, **_WAIT,
                "reason": f"{window.get('label')} is live, but volume is {bv.color.lower()} — "
                          "no institutional footprint yet. Wait for a BetterVolume signal."}

    d = _reversal(bv) if behavior in ("REVERSAL", "FADE") else _continuation(bv)
    if d["direction"] == "NONE":
        return {**base, **_WAIT, "reason": f"{window.get('label')}: {bv.color} gives no clean side yet."}

    verb = "fade the sweep" if behavior in ("REVERSAL", "FADE") else "ride the move"
    reason = (f"{window.get('label')} × {bv.color}: {verb} → {d['direction']}. {bv.story}")
    return {**base, **d, "reason": reason}


def signal_for(asset: str, bars: list[dict], now=None) -> dict:
    """Full ITBV read for an asset from OHLCV bars: classify the window, read
    BetterVolume on the bars, run the matrix. `bars` = [{o,h,l,c,v}] (>= 30)."""
    import numpy as np

    from .better_volume import classify
    win = sessions.current_window(now)
    if not bars or len(bars) < 30:
        return {**win, "action": "WAIT", "direction": "NONE", "grade": "-",
                "bv_color": None, "reason": "Not enough bars to read BetterVolume."}
    h = np.array([b["h"] for b in bars], float); l = np.array([b["l"] for b in bars], float)
    c = np.array([b["c"] for b in bars], float); v = np.array([b["v"] for b in bars], float)
    o = np.array([b["o"] for b in bars], float)
    bv = classify(h, l, c, v, o)
    return decide(win, bv)
