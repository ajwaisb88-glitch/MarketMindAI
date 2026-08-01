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

# Colours that actually pay in the walk-forward backtest (v1.1 pruning):
#   * White  — climax-down / stopping volume → the strongest reversal (BUY). Best PF.
#   * Green  — churn / absorption → go with the close (either side).
# Red (climax-up) and Magenta (climax-churn) LOST money across both the 10-day and
# 42-day samples, so they are demoted to context only — never an entry. Per the
# project rule: if the backtest doesn't support a rule, it doesn't trade.
_TRIGGER_COLORS = ("White", "Green")


def decide(window: dict, bv: BVResult) -> dict:
    """Fuse the institutional window and the BetterVolume state into one action.

    Only White (stopping volume → bounce) and Green (absorption → with the close)
    fire, and only inside a tradeable institutional window. Everything else waits.
    """
    behavior = window.get("behavior")
    base = {"window": window.get("window"), "window_label": window.get("label"),
            "liquidity": window.get("liquidity"), "behavior": behavior,
            "bv_color": bv.color, "bv_story": bv.story, "volume_ratio": bv.volume_ratio}

    if not window.get("tradeable"):
        reason = ("Data-shock window — stand aside; trade the second move once it settles."
                  if behavior == "SHOCK" else
                  f"{window.get('label')} — low-liquidity / non-institutional. No trade.")
        return {**base, **_WAIT, "reason": reason}

    if bv.color not in _TRIGGER_COLORS:
        why = ("low-volume — no institutional footprint" if bv.color in ("Yellow", "Neutral")
               else f"{bv.color} climax — backtest shows no edge here; context only")
        return {**base, **_WAIT, "reason": f"{window.get('label')} is live, but {why}. Waiting."}

    if bv.color == "White":            # stopping volume → high-conviction bounce (top PF)
        d = {"action": "BUY READY", "direction": "BUY", "grade": "A1"}
        verb = "stopping-volume bounce"
    else:                              # Green absorption → go with the close
        if bv.direction not in ("BUY", "SELL"):
            return {**base, **_WAIT, "reason": f"{window.get('label')}: Green gives no clean side yet."}
        d = {"action": bv.direction, "direction": bv.direction, "grade": "A"}
        verb = "absorption, go with the close"

    reason = f"{window.get('label')} × {bv.color}: {verb} → {d['direction']}. {bv.story}"
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
