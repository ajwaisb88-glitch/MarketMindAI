"""Market Read — the full mathematical picture for gold, then a pinpoint entry.

Fuses everything the app measures into ONE bias number, showing the math at every
layer (nothing hidden):

    bias = w_htf·HTF-trend + w_bv·BetterVolume + w_ob·book-imbalance
         + w_of·order-flow-CVD + w_pr·taker-pressure          (each in [-1, 1])

then gated by the institutional TIME window and discounted by spoof probability.

Direction comes from the sign of the bias; confidence from its size × time-quality
× (1 − spoof). Only a genuine multi-factor agreement inside a prime window trades.

PINPOINT ENTRY across timeframes (top-down): the higher timeframes (D1/H4/H1) set
the bias and permission; the entry timeframe (M15) is the setup; the low timeframes
(M5/M1) pinpoint the exact entry price and put the stop just beyond the M5 swing —
a tighter, better-R entry than a blunt M15 ATR stop. Targets are 1R/2R/3R (trailing).
"""
from __future__ import annotations

import numpy as np

from . import sessions
from .better_volume import classify
from .connectors.binance import BinanceConnector

# component weights (sum = 1.0)
_W = {"htf": 0.30, "bv": 0.25, "ob": 0.20, "of": 0.15, "pr": 0.10}
_TFS = {"D1": "1d", "H4": "4h", "H1": "1h", "M15": "15m", "M5": "5m", "M1": "1m"}


def _ema(x, n):
    k = 2.0 / (n + 1)
    e = x[0]
    for val in x[1:]:
        e = val * k + e * (1 - k)
    return e


def _trend(closes):
    """+1 bull / -1 bear / 0 flat from EMA9 vs EMA21 and recent slope."""
    if len(closes) < 22:
        return 0, "flat"
    e9, e21 = _ema(closes[-30:], 9), _ema(closes[-40:], 21)
    slope = closes[-1] - closes[-6]
    if e9 > e21 and slope > 0:
        return 1, "bull"
    if e9 < e21 and slope < 0:
        return -1, "bear"
    return 0, "flat"


def _bars(bc, asset, tf, limit=200):
    k = bc.klines(asset, tf, limit)
    if not k:
        return None
    return {"h": np.array([b["high"] for b in k], float), "l": np.array([b["low"] for b in k], float),
            "c": np.array([b["close"] for b in k], float), "v": np.array([b["volume"] for b in k], float),
            "o": np.array([b["open"] for b in k], float)}


def read(asset: str = "gold") -> dict:
    bc = BinanceConnector()
    tfb = {name: _bars(bc, asset, tf) for name, tf in _TFS.items()}
    if not tfb.get("M15") or not tfb.get("M1"):
        return {"status": "error", "asset": asset, "message": "no data"}

    price = float(tfb["M1"]["c"][-1])
    tf_dir = {}
    for name in _TFS:
        b = tfb.get(name)
        tf_dir[name] = (_trend(b["c"])[1] if b is not None else "n/a")

    # ── 1. HTF trend (H4 + H1 agreement) ──
    h4 = _trend(tfb["H4"]["c"])[0] if tfb.get("H4") is not None else 0
    h1 = _trend(tfb["H1"]["c"])[0] if tfb.get("H1") is not None else 0
    d1 = _trend(tfb["D1"]["c"])[0] if tfb.get("D1") is not None else 0
    htf = (0.5 * d1 + 1.0 * h4 + 1.0 * h1) / 2.5            # [-1,1], H4/H1 weighted, D1 context

    # ── 2. BetterVolume (M15) ──
    m = tfb["M15"]
    bv = classify(m["h"], m["l"], m["c"], m["v"], m["o"])
    bv_score = 0.0
    if bv.color == "White":
        bv_score = 0.8                                     # stopping volume → bounce (BUY bias)
    elif bv.color == "Green":
        bv_score = 0.8 if bv.direction == "BUY" else -0.8 if bv.direction == "SELL" else 0.0

    # ── 3. Order-book imbalance (DOM heat-map) ──
    ob = bc.order_book(asset, limit=100)
    ob_imb = float(ob.imbalance) if ob else 0.0            # already [-1,1]

    # ── 4. Order flow (taker CVD) ──
    of = bc.agg_trades(asset, limit=500)
    of_cvd = 0.0
    of_detail = {}
    if of:
        buy, sell = float(of.buy_volume), float(of.sell_volume)
        tot = buy + sell
        of_cvd = (buy - sell) / tot if tot else 0.0        # [-1,1]
        of_detail = {"buy": round(buy, 2), "sell": round(sell, 2), "cvd": round(buy - sell, 2),
                     "cvd_norm": round(of_cvd, 3)}

    # ── 5. Taker pressure / spoof (real order-book feed) ──
    spoof_prob, pr_side, pr_score = 0.0, "flat", 0.0
    try:
        from .crypto_signals import CryptoSignalService
        sc = CryptoSignalService().scalp(asset, blocking=False)
        spoof_prob = float(sc.get("spoof_probability") or 0.0) / 100.0
        pr_side = sc.get("pressure_side") or "flat"
        pr_score = 1.0 if sc.get("direction") == "BUY" else -1.0 if sc.get("direction") == "SELL" else 0.0
    except Exception:  # noqa: BLE001
        pass

    # ── fuse ──
    bias = (_W["htf"] * htf + _W["bv"] * bv_score + _W["ob"] * ob_imb
            + _W["of"] * of_cvd + _W["pr"] * pr_score)      # [-1,1]
    win = sessions.current_window()
    time_q = {"HIGH": 1.0, "MED": 0.7, "LOW": 0.3}.get(win["liquidity"], 0.3)
    confidence = round(abs(bias) * time_q * (1 - 0.5 * spoof_prob) * 100, 1)

    direction = "BUY" if bias > 0.12 else "SELL" if bias < -0.12 else "NONE"
    grade = "A+" if confidence >= 55 else "A1" if confidence >= 40 else "A" if confidence >= 28 else "-"
    tradeable = win["tradeable"] and direction != "NONE" and grade != "-"

    entry_plan = _pinpoint_entry(tfb, direction) if tradeable else None

    layers = {
        "htf": {"D1": tf_dir["D1"], "H4": tf_dir["H4"], "H1": tf_dir["H1"], "score": round(htf, 3)},
        "bettervolume": {"tf": "M15", "color": bv.color, "direction": bv.direction,
                         "vol_ratio": bv.volume_ratio, "score": round(bv_score, 3)},
        "order_book": {"bid_vol": round(ob.bid_volume, 1) if ob else None,
                       "ask_vol": round(ob.ask_volume, 1) if ob else None,
                       "imbalance": round(ob_imb, 3), "score": round(ob_imb, 3),
                       "read": "buy-stacked" if ob_imb > 0.05 else "sell-stacked" if ob_imb < -0.05 else "balanced"},
        "order_flow": {**of_detail, "score": round(of_cvd, 3),
                       "read": "buyers aggressive" if of_cvd > 0.05 else "sellers aggressive" if of_cvd < -0.05 else "balanced"},
        "pressure": {"spoof_prob_pct": round(spoof_prob * 100, 1), "side": pr_side, "score": round(pr_score, 3)},
    }
    return {
        "status": "ok", "asset": asset, "price": round(price, 2),
        "bias": round(bias, 3), "confidence": confidence, "direction": direction, "grade": grade,
        "tradeable": tradeable, "window": win, "weights": _W,
        "layers": layers, "timeframes": tf_dir, "entry": entry_plan,
        "reason": _reason(direction, grade, win, layers, bias, tradeable),
    }


def _pinpoint_entry(tfb, direction: str) -> dict:
    """Top-down pinpoint entry: enter at the M1 price, stop just beyond the recent
    M5 swing (tighter than an M15 ATR stop), targets 1R/2R/3R with trailing TP3."""
    m1, m5 = tfb["M1"], tfb["M5"]
    entry = float(m1["c"][-1])
    swing_lo = float(m5["l"][-10:].min()); swing_hi = float(m5["h"][-10:].max())
    buf = (swing_hi - swing_lo) * 0.08 or entry * 0.0005
    if direction == "BUY":
        stop = swing_lo - buf
        risk = max(entry - stop, entry * 0.0004)
        tps = [round(entry + i * risk, 2) for i in (1, 2, 3)]
    else:
        stop = swing_hi + buf
        risk = max(stop - entry, entry * 0.0004)
        tps = [round(entry - i * risk, 2) for i in (1, 2, 3)]
    return {
        "entry": round(entry, 2), "stop_loss": round(stop, 2),
        "tp1": tps[0], "tp2": tps[1], "tp3": tps[2], "trailing_tp": "TP3",
        "risk": round(risk, 2), "risk_reward": 3.0,
        "entry_tf": "M1", "stop_basis": "M5 10-bar swing",
        "note": "HTF/M15 set the bias; M5/M1 pinpoint the entry and the tight stop.",
    }


def _reason(direction, grade, win, layers, bias, tradeable):
    if not win["tradeable"]:
        return f"{win['label']} — not a prime institutional window. Stand aside regardless of the tape."
    if direction == "NONE":
        return f"Factors disagree (net bias {bias:+.2f}) — no clean side. Wait for alignment."
    if not tradeable:
        return f"Leaning {direction} (bias {bias:+.2f}) but confidence too low for a grade. Watching."
    ob, of = layers["order_book"], layers["order_flow"]
    return (f"{win['label']} × {layers['bettervolume']['color']} → {direction} (grade {grade}). "
            f"HTF {layers['htf']['H1']}/{layers['htf']['H4']}, book {ob['read']} ({ob['imbalance']:+}), "
            f"flow {of['read']}. Pinpoint entry on M1, stop beyond the M5 swing.")
