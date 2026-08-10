"""Backtest the ITBV (Institutional Time × BetterVolume) gold strategy.

Walks historical 15m bars, and on every bar classifies the institutional window
(from that bar's timestamp) and the BetterVolume state, runs the same decision
matrix the live signal uses, and — when it says BUY/SELL — simulates the trade
forward against an ATR stop/target (stop wins ties). One position at a time.

Reports the metrics the roadmap asked for: win rate, profit factor, average R,
net R, max drawdown, and the breakdown BY institutional session and BY
BetterVolume colour — so we can see which windows and which colours actually pay.
Honest and reproducible; no look-ahead (the entry bar's own future is scanned
only after the decision is made on its close).
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from . import itbv
from .better_volume import classify
from .connectors.binance import BinanceConnector

_RR = 2.0          # target = 2R (matches _atr_plan default)
_K_STOP = 1.5      # stop = 1.5 * ATR
_MAX_HOLD = 32     # bars (8h on 15m) before a trade is abandoned
_WARMUP = 40


def _atr(h, l, c, i, period=14):
    a, b = max(1, i - period), i + 1
    tr = np.maximum(h[a:b] - l[a:b], np.maximum(abs(h[a:b] - c[a - 1:b - 1]), abs(l[a:b] - c[a - 1:b - 1])))
    return float(tr.mean()) if len(tr) else 0.0


def _fetch_bars(bc: BinanceConnector, asset: str, interval: str, total: int) -> list[dict]:
    """Binance klines with endTime paging so we can backtest on more than the
    1000-bar single-call cap (older batches prepended)."""
    sym = bc.resolve(asset)
    out: list[dict] = []
    end = None
    while len(out) < total:
        params = {"symbol": sym, "interval": interval, "limit": 1000}
        if end is not None:
            params["endTime"] = end
        data = bc._get("/api/v3/klines", params)
        if not isinstance(data, list) or not data:
            break
        batch = [{"t": int(x[0]), "open": float(x[1]), "high": float(x[2]),
                  "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])} for x in data]
        out = batch + out
        end = batch[0]["t"] - 1
        if len(batch) < 1000:
            break
    return out[-total:]


def run(asset: str = "gold", limit: int = 4000, balance: float = 10000.0, risk_pct: float = 1.0) -> dict:
    bc = BinanceConnector()
    k = _fetch_bars(bc, asset, "15m", min(limit, 6000))
    if not k or len(k) < _WARMUP + 20:
        return {"status": "error", "message": "not enough history", "asset": asset}
    t = [int(b["t"]) for b in k]
    o = np.array([b["open"] for b in k], float); h = np.array([b["high"] for b in k], float)
    l = np.array([b["low"] for b in k], float); c = np.array([b["close"] for b in k], float)
    v = np.array([b["volume"] for b in k], float)

    trades: list[dict] = []
    i = _WARMUP
    while i < len(k) - 1:
        now = datetime.fromtimestamp(t[i] / 1000, tz=timezone.utc)
        win = itbv.current_window(now) if hasattr(itbv, "current_window") else itbv.sessions.current_window(now)
        bv = classify(h[:i + 1], l[:i + 1], c[:i + 1], v[:i + 1], o[:i + 1])
        d = itbv.decide(win, bv)
        if d["direction"] not in ("BUY", "SELL"):
            i += 1
            continue
        atr = _atr(h, l, c, i)
        if atr <= 0:
            i += 1
            continue
        entry = c[i]; risk = _K_STOP * atr
        buy = d["direction"] == "BUY"
        sl = entry - risk if buy else entry + risk
        tp = entry + _RR * risk if buy else entry - _RR * risk
        outcome, rmult, exit_j = "OPEN", 0.0, min(i + _MAX_HOLD, len(k) - 1)
        for j in range(i + 1, min(i + _MAX_HOLD + 1, len(k))):
            hit_sl = l[j] <= sl if buy else h[j] >= sl
            hit_tp = h[j] >= tp if buy else l[j] <= tp
            if hit_sl:                       # stop wins ties (conservative)
                outcome, rmult, exit_j = "SL", -1.0, j; break
            if hit_tp:
                outcome, rmult, exit_j = "TP", _RR, j; break
        else:
            outcome = "EXPIRED"; rmult = (c[exit_j] - entry) / risk * (1 if buy else -1)
        trades.append({"i": i, "dir": d["direction"], "window": d["window"],
                       "window_label": d["window_label"], "color": d["bv_color"],
                       "outcome": outcome, "r": round(rmult, 2)})
        i = exit_j + 1                        # one position at a time

    return _aggregate(asset, len(k), trades, balance, risk_pct)


def _bucket():
    return {"trades": 0, "wins": 0, "losses": 0, "gross_win": 0.0, "gross_loss": 0.0, "net_r": 0.0}


def _finalize(b):
    closed = b["wins"] + b["losses"]
    b["win_rate"] = round(100 * b["wins"] / closed, 1) if closed else None
    b["profit_factor"] = (round(b["gross_win"] / b["gross_loss"], 2) if b["gross_loss"] > 0
                          else (None if b["gross_win"] == 0 else 99.9))
    b["net_r"] = round(b["net_r"], 2)
    b["gross_win"] = round(b["gross_win"], 2); b["gross_loss"] = round(b["gross_loss"], 2)
    return b


def _aggregate(asset, n_bars, trades, balance=10000.0, risk_pct=1.0):
    overall, by_session, by_color = _bucket(), {}, {}
    r_equity, r_peak, max_dd_r = 0.0, 0.0, 0.0
    # money curve: risk a fixed % of CURRENT equity per trade (compounding).
    money, m_peak, max_dd_money = float(balance), float(balance), 0.0
    for tr in trades:
        r = tr["r"]
        for b in (overall, by_session.setdefault(tr["window_label"], _bucket()),
                  by_color.setdefault(tr["color"], _bucket())):
            b["trades"] += 1
            b["net_r"] += r
            if r > 0:
                b["wins"] += 1; b["gross_win"] += r
            elif r < 0:
                b["losses"] += 1; b["gross_loss"] += abs(r)
        r_equity += r; r_peak = max(r_peak, r_equity); max_dd_r = max(max_dd_r, r_peak - r_equity)
        money += r * (money * risk_pct / 100.0)             # profit/loss in dollars
        m_peak = max(m_peak, money); max_dd_money = max(max_dd_money, (m_peak - money) / m_peak * 100)

    net_profit = money - balance
    return_pct = (money / balance - 1.0) * 100.0 if balance else 0.0
    return {
        "status": "ok", "asset": asset, "bars": n_bars, "days": round(n_bars * 15 / 60 / 24, 1),
        "overall": _finalize(overall), "max_drawdown_r": round(max_dd_r, 2),
        # return vs profit — the money view (start balance, % risk per trade, compounding)
        "money": {"start_balance": round(balance, 2), "risk_pct": risk_pct,
                  "end_balance": round(money, 2), "net_profit": round(net_profit, 2),
                  "return_pct": round(return_pct, 1), "max_drawdown_pct": round(max_dd_money, 1)},
        "by_session": {k: _finalize(v) for k, v in sorted(by_session.items(), key=lambda x: -x[1]["net_r"])},
        "by_color": {k: _finalize(v) for k, v in sorted(by_color.items(), key=lambda x: -x[1]["net_r"])},
        "params": {"rr": _RR, "k_stop": _K_STOP, "max_hold_bars": _MAX_HOLD, "timeframe": "15m"},
        "note": "Walk-forward on 15m bars; ATR stop/target, one position at a time, stop wins ties. "
                "PAXG is the gold proxy; weekends are non-institutional (no trades).",
    }
