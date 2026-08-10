"""Confluence scoring engine — Phase 1.2.

Ported from whale-framework/Confluence.html.js (scoreSide + supporting engines).
Elliott Wave is intentionally excluded: it stays a separate engine and must
never feed this score (see CLAUDE.md sections 0, 3 and 5).

Weights (100 total): HTF Trend 25 - BV Retest Trigger 25 - Session Engine 19
- Agent Pressure 19 - Quick Trigger 12.
Actionable tier: score >= mode.score, hits >= mode.hits (of 5 factors),
margin (winning side - losing side) >= mode.margin.

The BV Retest Trigger factor already implements the YELLOW/GREEN close-break
+ retest rule that Phase 1.3 (Y/G Ladder TP/SL) will reuse for entry/SL/TP
levels — it is not a placeholder.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import polars as pl

from .agents_60 import SixtyAgentsEngine

# ─── Mode presets (ported from whale MODE_PRESETS) ───
# M1 is not available in stored parquet data (only 5min/15min/1h/1d exist),
# so SCALP/INTRADAY quick-triggers substitute M5 where whale used M1.
MODE_PRESETS: dict[str, dict[str, Any]] = {
    "SCALP": {
        "entry": "M5", "htf_a": "H1", "htf_b": "M15", "quick": ["M15", "M5", "M5"],
        "session_tf": "M5", "score": 72, "hits": 3, "margin": 14,
        "label": "SCALP / snapshot", "session_filter": "KILLZONE",
    },
    "INTRADAY": {
        "entry": "M5", "htf_a": "D1", "htf_b": "H4", "quick": ["M15", "M5", "M5"],
        "session_tf": "M5", "score": 70, "hits": 3, "margin": 15,
        "label": "INTRADAY / short-term", "session_filter": "NO_OFFHOURS",
    },
    "SWING": {
        "entry": "H1", "htf_a": "W1", "htf_b": "D1", "quick": ["H4", "H1", "M15"],
        "session_tf": "H1", "score": 68, "hits": 3, "margin": 12,
        "label": "SWING", "session_filter": "NONE",
    },
    "LONGTERM": {
        "entry": "H4", "htf_a": "W1", "htf_b": "D1", "quick": ["D1", "H4", "H1"],
        "session_tf": "H4", "score": 66, "hits": 3, "margin": 10,
        "label": "LONGTERM / position", "session_filter": "NONE",
    },
}

_NATIVE_TF_FILE = {"M5": "5min", "M15": "15min", "H1": "1h", "D1": "1d"}
_DT_FORMAT = "%Y-%m-%d %H:%M:%S%.f%:z"


# ─── Small numeric helpers ───

def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _rng(bar: dict) -> float:
    return max(1e-7, bar["h"] - bar["l"])


def _body_pct(bar: dict) -> float:
    return abs(bar["c"] - bar["o"]) / _rng(bar)


# ── Change 1: timeframe-scaled SIGNAL SCAN distance ──
# H1/H4/D1/W1 scan LONG history so old YELLOW/GREEN (and new RED) zones stay live
# for retest; M1/M5/M15 stay SHORT (~20) — reaching far back on low timeframes
# produces too many false signals. NOTE: this scales only how far the SIGNAL SCAN
# looks back — the bar-COLOR classification stays 20-bar on every timeframe.
_SIGNAL_SCAN_LONG = 150
_SIGNAL_SCAN_SHORT = 20
_HIGH_TFS = ("H1", "H4", "D1", "W1")


def signal_scan_distance(tf: str) -> int:
    return _SIGNAL_SCAN_LONG if str(tf).upper() in _HIGH_TFS else _SIGNAL_SCAN_SHORT


# ─── Timeframe loading / resampling ───

def _to_datetime(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.with_columns(pl.col("datetime").str.to_datetime(format=_DT_FORMAT, strict=False).alias("dt"))
        .drop_nulls("dt")
        .sort("dt")
    )


def _resample(df: pl.DataFrame, every: str) -> pl.DataFrame:
    df = _to_datetime(df)
    return (
        df.group_by_dynamic("dt", every=every, closed="left", label="left")
        .agg([
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
        ])
        .drop_nulls(["open", "high", "low", "close"])
    )


def _bars_from_df(df: pl.DataFrame) -> list[dict]:
    if "dt" not in df.columns:
        df = _to_datetime(df)
    out: list[dict] = []
    for row in df.iter_rows(named=True):
        ts = row["dt"]
        out.append({
            "t": int(ts.timestamp() * 1000) if ts is not None else 0,
            "o": float(row["open"]), "h": float(row["high"]),
            "l": float(row["low"]), "c": float(row["close"]),
            "v": float(row.get("volume") or 0.0),
        })
    return out


# ── data seam ────────────────────────────────────────
# The app injects a provider so this engine is data-source agnostic
# (Binance today, MT5 broker feed next). Provider signature:
#     provider(tf: str, symbol: str) -> list[{t,o,h,l,c,v}]
_bars_provider = None


def set_bars_provider(fn) -> None:
    """Install the bar provider used for every timeframe."""
    global _bars_provider
    _bars_provider = fn


def _load_timeframe_bars(tf: str, symbol: str = "XAUUSD") -> list[dict]:
    if _bars_provider is None:
        return []
    try:
        return _bars_provider(tf, symbol) or []
    except Exception:
        return []


def _bars_to_df(bars: list[dict]) -> pl.DataFrame:
    return pl.DataFrame({
        "open": [b["o"] for b in bars],
        "high": [b["h"] for b in bars],
        "low": [b["l"] for b in bars],
        "close": [b["c"] for b in bars],
        "volume": [b["v"] for b in bars],
    })


# ─── Trend / HTF permission ───

def _trend(bars: list[dict]) -> str:
    if len(bars) < 20:
        return "FLAT"
    closes = [b["c"] for b in bars]
    fast = _avg(closes[-5:])
    slow = _avg(closes[-20:])
    last = bars[-1]
    if fast > slow and last["c"] > fast:
        return "BULL"
    if fast < slow and last["c"] < fast:
        return "BEAR"
    return "FLAT"


def _big_permission(o: str, t: str) -> dict:
    if o == "BULL" and t == "BULL":
        return {"allow": "BUY", "name": "Ocean/Tide BUY"}
    if o == "BEAR" and t == "BEAR":
        return {"allow": "SELL", "name": "Ocean/Tide SELL"}
    if o == "BULL" and t == "BEAR":
        return {"allow": "WAIT", "name": "Rip Tide"}
    if o == "BEAR" and t == "BULL":
        return {"allow": "WAIT", "name": "Dead Cat Bounce"}
    return {"allow": "SMALL", "name": "No Current"}


# ─── Better Volume buffer classification (ported, identical spec to better_volume.py's buffers) ───

def _better_volume_series(bars: list[dict], lookback: int = 20, use_2bars: bool = True) -> list[dict]:
    n = len(bars)
    if n == 0:
        return []
    v = {k: [0.0] * n for k in range(1, 23)}
    for i, c in enumerate(bars):
        rng = _rng(c)
        vol = c["v"] or 0.0
        if c["c"] > c["o"] and rng > 0:
            v[1][i] = vol * (rng / (2 * rng + c["o"] - c["c"]))
        elif c["c"] < c["o"] and rng > 0:
            v[1][i] = vol * ((rng + c["c"] - c["o"]) / (2 * rng + c["c"] - c["o"]))
        else:
            v[1][i] = 0.5 * vol
        v[2][i] = vol - v[1][i]
        v[3][i] = abs(v[1][i] + v[2][i])
        v[4][i] = v[1][i] * rng
        v[5][i] = (v[1][i] - v[2][i]) * rng
        v[6][i] = v[2][i] * rng
        v[7][i] = (v[2][i] - v[1][i]) * rng
        if rng > 0:
            v[8][i] = v[1][i] / rng
            v[9][i] = (v[1][i] - v[2][i]) / rng
            v[10][i] = v[2][i] / rng
            v[11][i] = (v[2][i] - v[1][i]) / rng
            v[12][i] = v[3][i] / rng
        if i > 0:
            tr = max(bars[i]["h"], bars[i - 1]["h"]) - min(bars[i]["l"], bars[i - 1]["l"])
            v[13][i] = v[3][i] + v[3][i - 1]
            v[14][i] = (v[1][i] + v[1][i - 1]) * tr
            v[15][i] = (v[1][i] + v[1][i - 1] - v[2][i] - v[2][i - 1]) * tr
            v[16][i] = (v[2][i] + v[2][i - 1]) * tr
            v[17][i] = (v[2][i] + v[2][i - 1] - v[1][i] - v[1][i - 1]) * tr
            if tr > 0:
                v[18][i] = (v[1][i] + v[1][i - 1]) / tr
                v[19][i] = (v[1][i] + v[1][i - 1] - v[2][i] - v[2][i - 1]) / tr
                v[20][i] = (v[2][i] + v[2][i - 1]) / tr
                v[21][i] = (v[2][i] + v[2][i - 1] - v[1][i] - v[1][i - 1]) / tr
                v[22][i] = v[13][i] / tr

    def highest(arr: list[float], s: int, e: int) -> float:
        window = [x for x in arr[s:e + 1] if math.isfinite(x)]
        return max(window) if window else float("-inf")

    def lowest(arr: list[float], s: int, e: int) -> float:
        window = [x for x in arr[s:e + 1] if math.isfinite(x)]
        return min(window) if window else float("inf")

    def near_high(val: float, hi: float) -> bool:
        return math.isfinite(val) and math.isfinite(hi) and val >= hi - 1e-9

    def near_low(val: float, lo: float) -> bool:
        return math.isfinite(val) and math.isfinite(lo) and val <= lo + 1e-9

    # ── Classification matches MT4 "BetterVolume 1.4" (raw-volume spec). ──
    # v[1]/v[2]/v[3] (buy/sell split) above are kept ONLY for the buy/sell ratio
    # display; the color is decided by 1.4's Volume*Range / Volume/Range rules.
    out: list[dict] = []
    for i in range(n):
        c = bars[i]
        rng_i = c["h"] - c["l"]
        vol = c["v"] or 0.0
        val2 = vol * rng_i
        val3 = (vol / rng_i) if rng_i != 0 else 0.0
        window = bars[max(0, i - lookback + 1):i + 1]
        hi2 = max((b["v"] or 0.0) * (b["h"] - b["l"]) for b in window)
        hi3_vals = [(b["v"] or 0.0) / (b["h"] - b["l"]) for b in window if (b["h"] - b["l"]) != 0]
        hi3 = max(hi3_vals) if hi3_vals else 0.0
        vol_lowest = min((b["v"] or 0.0) for b in window)
        mid = (c["h"] + c["l"]) / 2.0
        is_max2 = val2 >= hi2 - 1e-9
        is_max3 = rng_i != 0 and val3 >= hi3 - 1e-9
        # 1.4 precedence (last block wins in the .mq4): white > magenta > green > red > yellow.
        if is_max2 and c["c"] <= mid:
            color = "WHITE"
        elif is_max2 and is_max3:
            color = "MAGENTA"
        elif is_max3:
            color = "GREEN"
        elif is_max2 and c["c"] > mid:
            color = "RED"
        elif vol <= vol_lowest + 1e-9:
            color = "YELLOW"
        else:
            color = "NORMAL"
        out.append({"color": color, "buy_vol": v[1][i], "sell_vol": v[2][i], "total": v[3][i]})
    return out


# ─── BV Retest Trigger (YELLOW/GREEN close-break + retest; shared with Phase 1.3 Y/G Ladder) ───

def _bv_trigger(bars: list[dict], bv: list[dict], n: int = 18) -> dict:
    best: dict[str, Any] = {
        "side": "WAIT", "strength": 0,
        "text": "No yellow/green close-break + retest in window",
        "break_idx": None, "retest_idx": None,
    }
    armed = None
    watch = None
    from_i = max(1, len(bv) - n)
    for i in range(from_i, len(bv)):
        col = bv[i]["color"]
        if col not in ("YELLOW", "GREEN"):
            continue
        tb = bars[i]
        broken = False
        for j in range(i + 1, len(bars)):
            c = bars[j]

            def mk(direction: str, level: float) -> dict | None:
                nonlocal watch
                retest_idx = -1
                for k in range(j + 1, len(bars)):
                    r = bars[k]
                    if direction == "BUY" and r["l"] <= level and r["c"] > level:
                        retest_idx = k
                        break
                    if direction == "SELL" and r["h"] >= level and r["c"] < level:
                        retest_idx = k
                        break
                fresh_break = j >= len(bars) - 5
                fresh_retest = retest_idx >= len(bars) - 4
                base = 3 if col == "GREEN" else 2
                name = "GREEN churn" if col == "GREEN" else "YELLOW low-volume test"
                if retest_idx >= 0 and fresh_retest:
                    return {
                        "side": direction, "strength": base + 1, "level": level,
                        "break_idx": j, "retest_idx": retest_idx,
                        "text": f"{name} {'high' if direction == 'BUY' else 'low'} close-break + retest confirmed",
                    }
                if fresh_break:
                    watch = {
                        "side": direction + "_WATCH", "strength": base, "level": level, "break_idx": j,
                        "text": f"{name} close-break done — WAIT retest of {level:.2f} before entry",
                    }
                return None

            if c["c"] > tb["h"]:
                broken = True
                s = mk("BUY", tb["h"])
                if s and s["strength"] >= best["strength"]:
                    best = s
                break
            if c["c"] < tb["l"]:
                broken = True
                s = mk("SELL", tb["l"])
                if s and s["strength"] >= best["strength"]:
                    best = s
                break
        if not broken and i >= len(bars) - 6:
            armed = {"color": col, "hi": tb["h"], "lo": tb["l"], "age": len(bars) - 1 - i}

    if best["side"] == "WAIT" and watch:
        best = {**watch, "watch": True}
    if best["side"] == "WAIT" and armed:
        best = {
            **best,
            "text": (
                f"{armed['color']} bar ARMED — close above {armed['hi']:.2f} = BUY watch, "
                f"close below {armed['lo']:.2f} = SELL watch. Entry only after retest."
            ),
            "armed": armed,
        }
    for i in range(max(0, len(bv) - 3), len(bv)):
        if bv[i]["color"] == "MAGENTA" and i != best.get("break_idx") and i != best.get("retest_idx"):
            return {
                "side": "EXIT", "strength": 3,
                "text": "MAGENTA Climax+Churn — reversal/exit risk, no fresh entry",
                "armed": None,
            }
    return best


# ─── Session engine (Asia/London/US break + BV confirm) ───

def _session_phase(ts_ms: int) -> str:
    h = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).hour
    if 0 <= h < 7:
        return "ASIA"
    if 7 <= h < 13:
        return "LONDON"
    if 13 <= h < 16:
        return "US OPEN"
    if 16 <= h < 20:
        return "US DECISION"
    return "OFF HOURS"


def _bv_confirms_break(side: str, bv_color: str | None, vr: float) -> bool:
    if not bv_color:
        return False
    if side == "BUY":
        if bv_color == "WHITE":
            return False
        return bv_color in ("RED", "MAGENTA") or (bv_color == "GREEN" and vr > 1.1) or (vr > 1.7 and bv_color != "WHITE")
    if side == "SELL":
        if bv_color == "RED":
            return False
        return bv_color in ("WHITE", "MAGENTA") or (bv_color == "GREEN" and vr > 1.1) or (vr > 1.7 and bv_color != "RED")
    return False


def _session_engine(bars: list[dict], bv_colors: list[dict]) -> dict:
    if len(bars) < 160:
        phase = _session_phase(bars[-1]["t"]) if bars else _session_phase(int(datetime.now(timezone.utc).timestamp() * 1000))
        return {
            "state": "WAIT", "side": "WAIT", "vr": 1.0, "hi": 0.0, "lo": 0.0,
            "text": "not enough bars", "phase": phase, "bv_side": "WAIT", "bv_score": 0.0, "us_continue": False,
        }

    # Adapted from whale JS: JS anchors "today" on wall-clock now (fine for a
    # live feed where now ~= last bar). We anchor on the LAST BAR's own date
    # so this also works correctly against stored/offline data.
    last_bar_dt = datetime.fromtimestamp(bars[-1]["t"] / 1000, tz=timezone.utc)
    day0 = last_bar_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day0_ms = int(day0.timestamp() * 1000)

    ts_to_idx = {b["t"]: idx for idx, b in enumerate(bars)}

    asia, london, us = [], [], []
    for c in bars:
        h = datetime.fromtimestamp(c["t"] / 1000, tz=timezone.utc).hour
        if c["t"] >= day0_ms and 0 <= h < 7:
            asia.append(c)
        if c["t"] >= day0_ms and 7 <= h < 13:
            london.append(c)
        if c["t"] >= day0_ms and 13 <= h < 20:
            us.append(c)
    if len(asia) < 3:
        asia = bars[-160:-80]
    if len(london) < 1:
        london = bars[-80:-30]
    if len(us) < 1:
        us = bars[-30:]

    hi = max(x["h"] for x in asia)
    lo = min(x["l"] for x in asia)
    av = _avg([x["v"] or 0.0 for x in asia]) or 1.0

    broke_up = broke_dn = False
    break_vol = 0.0
    break_index = -1
    break_side = "WAIT"
    for c in london:
        idx = ts_to_idx.get(c["t"], -1)
        if c["h"] > hi and not broke_up:
            broke_up, break_vol, break_index, break_side = True, c["v"] or 0.0, idx, "BUY"
        if c["l"] < lo and not broke_dn:
            broke_dn, break_vol, break_index, break_side = True, c["v"] or 0.0, idx, "SELL"

    current = bars[-1]
    cp = current["c"]
    vr = (break_vol / av) if break_vol else 1.0
    break_bv_color = bv_colors[break_index]["color"] if 0 <= break_index < len(bv_colors) else None
    london_bv_confirm = _bv_confirms_break(break_side, break_bv_color, vr)

    us_count = 0
    for c in us[-12:]:
        idx = ts_to_idx.get(c["t"], -1)
        col = bv_colors[idx]["color"] if 0 <= idx < len(bv_colors) else None
        r = (c["v"] or 0.0) / av
        if break_side == "BUY" and c["c"] > hi and _bv_confirms_break("BUY", col, r):
            us_count += 1
        if break_side == "SELL" and c["c"] < lo and _bv_confirms_break("SELL", col, r):
            us_count += 1
    us_continue = us_count >= 1

    bv_score = 0.0
    if london_bv_confirm:
        bv_score += 0.55
    if us_continue:
        bv_score += 0.35
    if break_bv_color == "YELLOW":
        bv_score -= 0.25
    bv_score = _clamp(bv_score, 0.0, 1.0)

    state, side, text = "INSIDE RANGE", "WAIT", "London has no clear break."
    if broke_up and cp <= hi:
        state, side, text = "LONDON FAKE BREAK UP", "SELL", "Broke Asia high, returned inside."
    elif broke_dn and cp >= lo:
        state, side, text = "LONDON FAKE BREAK DOWN", "BUY", "Broke Asia low, returned inside."
    elif broke_up and cp > hi and london_bv_confirm:
        state, side, text = "LONDON REAL BREAK UP", "BUY", "Break up + BV confirm."
    elif broke_dn and cp < lo and london_bv_confirm:
        state, side, text = "LONDON REAL BREAK DOWN", "SELL", "Break down + BV confirm."
    elif broke_up and cp > hi:
        state, side, text = "WEAK BREAK UP", "WAIT", "Break up, no BV confirm yet."
    elif broke_dn and cp < lo:
        state, side, text = "WEAK BREAK DOWN", "WAIT", "Break down, no BV confirm yet."

    bv_side = break_side if london_bv_confirm else "WAIT"
    return {
        "state": state, "side": side, "vr": vr, "hi": hi, "lo": lo, "cp": cp, "text": text,
        "phase": _session_phase(bars[-1]["t"]), "bv_side": bv_side, "bv_score": bv_score, "us_continue": us_continue,
    }


def _session_gate(phase: str, cfg: dict) -> dict:
    f = cfg.get("session_filter", "NONE")
    if f == "NONE":
        return {"ok": True, "text": "No session filter"}
    if f == "KILLZONE":
        ok = phase in ("LONDON", "US OPEN", "US DECISION")
        return {"ok": ok, "text": "London/US killzone allowed" if ok else "Blocked: outside London/US killzone"}
    if f == "NO_OFFHOURS":
        ok = phase != "OFF HOURS"
        return {"ok": ok, "text": "Session allowed" if ok else "Blocked: off-hours liquidity"}
    return {"ok": True, "text": "Session auto allowed"}


# ─── Quick trigger (multi-TF alignment check) ───

def _quick_dynamic(tf_bars: dict[str, list[dict]], tfs: list[str]) -> dict:
    states = [(tf, _trend(tf_bars.get(tf, []))) for tf in tfs]
    if all(tr == "BULL" for _, tr in states):
        return {"side": "BUY", "text": "/".join(tfs) + " bull"}
    if all(tr == "BEAR" for _, tr in states):
        return {"side": "SELL", "text": "/".join(tfs) + " bear"}
    return {"side": "WAIT", "text": ", ".join(f"{tf} {tr}" for tf, tr in states)}


# ─── Agent Pressure (real 60-Agents engine, not whale's simplified proxy) ───

def _agent_pressure(entry_bars: list[dict], session_bars: list[dict], symbol: str, timeframe: str) -> dict:
    source_bars = entry_bars if len(entry_bars) >= 60 else session_bars
    if len(source_bars) < 30:
        return {"pressure": 0.0, "chop_flag": False, "chop_pct": 0.0, "agents": {"status": "not_enough_data"}}
    df = _bars_to_df(source_bars)
    result = SixtyAgentsEngine().analyze(df, symbol=symbol, timeframe=timeframe)
    pressure = _clamp(float(result.get("score", 0.0)), -1.0, 1.0)
    noise_conf = float(result.get("groups", {}).get("noise", {}).get("confidence", 0.0))
    chop_flag = noise_conf >= 65.0
    return {"pressure": pressure, "chop_flag": chop_flag, "chop_pct": noise_conf, "agents": result}


# ─── Confluence scoring (the 100-point weighted score, per side) ───

def _score_side(direction: str, ctx: dict) -> dict:
    cfg = ctx["cfg"]
    rows: list[dict] = []
    total = 0.0
    hits = 0
    opposite = "BEAR" if direction == "BUY" else "BULL"

    # HTF Trend (25)
    if ctx["big"]["allow"] == direction:
        p = 25
    elif ctx["big"]["allow"] == "SMALL":
        p = 10
    else:
        p = 0
    det = f"{cfg['htf_a']} {ctx['htf_a']} / {cfg['htf_b']} {ctx['htf_b']}"
    if ctx["htf_a"] == opposite and ctx["htf_b"] == opposite:
        det += " — hard conflict"
    rows.append({"name": f"HTF Trend ({cfg['htf_a']}/{cfg['htf_b']})", "pts": p, "max": 25, "det": det})
    total += p
    if p >= 12:
        hits += 1

    # BV Retest Trigger (25)
    trig = ctx["trig"]
    if trig["side"] == direction:
        b = 25 if trig["strength"] >= 4 else 21 if trig["strength"] == 3 else 16
    elif trig["side"] == direction + "_WATCH":
        b = 10
    else:
        b = 0
    rows.append({"name": f"Better Volume Retest ({cfg['entry']})", "pts": b, "max": 25, "det": trig["text"]})
    total += b
    if b >= 16:
        hits += 1

    # Session Engine (19)
    sess = ctx["sess"]
    s = 0
    if sess["side"] == direction:
        s = 12
        if sess["bv_score"] >= 0.45 or sess["us_continue"]:
            s = 19
    if not ctx["session_gate"]["ok"]:
        s = 0
    rows.append({
        "name": "Session Engine", "pts": s, "max": 19,
        "det": f"{sess['phase']} · {sess['state']} · {ctx['session_gate']['text']}",
    })
    total += s
    if s >= 12:
        hits += 1

    # Agent Pressure (19)
    pressure = ctx["agents"]["pressure"]
    pside = "BUY" if pressure > 0.18 else "SELL" if pressure < -0.18 else "WAIT"
    pr = max(8, round(19 * min(1.0, abs(pressure) / 0.6))) if pside == direction else 0
    if ctx["agents"]["chop_flag"]:
        pr = round(pr / 2)
    det_pr = f"{pressure:.2f}"
    if ctx["agents"]["chop_flag"]:
        det_pr += f" · CHOP {ctx['agents']['chop_pct']:.0f}% halves it"
    rows.append({"name": "Agent Pressure", "pts": pr, "max": 19, "det": det_pr})
    total += pr
    if pr >= 10:
        hits += 1

    # Quick Trigger (12)
    qq = 12 if ctx["q"]["side"] == direction else 0
    rows.append({"name": f"Quick Trigger ({'/'.join(cfg['quick'])})", "pts": qq, "max": 12, "det": ctx["q"]["text"]})
    total += qq
    if qq >= 12:
        hits += 1

    return {"dir": direction, "total": total, "hits": hits, "rows": rows}


# ─── Top-level engine ───

class ConfluenceEngine:
    """Confluence scoring engine. Elliott Wave is NOT part of this score by design."""

    def analyze(self, mode: str = "SWING", symbol: str = "XAUUSD") -> dict[str, Any]:
        cfg = dict(MODE_PRESETS.get(mode, MODE_PRESETS["SWING"]))

        needed_tfs = {cfg["entry"], cfg["htf_a"], cfg["htf_b"], cfg["session_tf"], *cfg["quick"]}
        tf_bars = {tf: _load_timeframe_bars(tf, symbol) for tf in needed_tfs}

        entry_bars = tf_bars.get(cfg["entry"], [])
        if len(entry_bars) < 40:
            return {
                "status": "error", "mode": mode,
                "message": f"Not enough {cfg['entry']} candles for confluence scoring. Download data first.",
            }

        entry_bars = entry_bars[-500:]
        session_bars = tf_bars.get(cfg["session_tf"], [])[-500:]
        htf_a_bars = tf_bars.get(cfg["htf_a"], [])[-300:]
        htf_b_bars = tf_bars.get(cfg["htf_b"], [])[-300:]

        htf_a = _trend(htf_a_bars)
        htf_b = _trend(htf_b_bars)
        big = _big_permission(htf_a, htf_b)

        bv_entry = _better_volume_series(entry_bars, 20, True)
        bv_session = _better_volume_series(session_bars, 20, True) if session_bars else []
        sess = (
            _session_engine(session_bars, bv_session) if session_bars else
            {"state": "WAIT", "side": "WAIT", "phase": "OFF HOURS", "bv_score": 0.0, "us_continue": False}
        )
        session_gate = _session_gate(sess["phase"], cfg)
        trig = _bv_trigger(entry_bars, bv_entry, signal_scan_distance(cfg["entry"]))
        agents = _agent_pressure(entry_bars, session_bars, symbol, cfg["entry"])
        q = _quick_dynamic(tf_bars, cfg["quick"])

        ctx = {
            "cfg": cfg, "htf_a": htf_a, "htf_b": htf_b, "big": big,
            "sess": sess, "session_gate": session_gate, "trig": trig,
            "agents": agents, "q": q,
        }

        s_buy = _score_side("BUY", ctx)
        s_sell = _score_side("SELL", ctx)
        win = s_buy if s_buy["total"] >= s_sell["total"] else s_sell
        margin = abs(s_buy["total"] - s_sell["total"])

        side, tier, reason = "WAIT", "No setup", ""
        if not session_gate["ok"]:
            reason = f"{session_gate['text']}. Best side {win['dir']} score {win['total']}; session filter blocks action."
        elif win["total"] >= cfg["score"] and win["hits"] >= cfg["hits"] and margin >= cfg["margin"]:
            side = f"CONFLUENCE {win['dir']}"
            tier = f"ACTIONABLE — {win['hits']}/5 factors, {cfg['label']}"
            reason = f"{win['hits']}/5 factors {win['dir']}, score {win['total']}, margin {margin}."
        elif win["total"] >= cfg["score"] - 15 and win["hits"] >= 2 and margin >= max(8, cfg["margin"] - 5):
            side = f"{win['dir']} WATCH"
            tier = "WATCH — building, not confirmed"
            reason = (
                f"{win['hits']}/5 factors lean {win['dir']}, score {win['total']}. "
                "Need retest/score/session alignment for full entry."
            )
            if trig["side"] == "EXIT":
                reason += " MAGENTA exit risk."
        else:
            reason = f"Best side {win['dir']} only scores {win['total']} with {win['hits']}/5 factors (margin {margin})."
            if trig["side"] == "EXIT":
                reason += " MAGENTA bar — reversal risk."
            reason += " No confluence."

        return {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "mode": mode,
            "mode_label": cfg["label"],
            "side": side,
            "tier": tier,
            "reason": reason,
            "score": {"buy": s_buy["total"], "sell": s_sell["total"], "margin": margin, "winner": win["dir"]},
            "factors": {"buy": s_buy["rows"], "sell": s_sell["rows"]},
            "htf": {cfg["htf_a"]: htf_a, cfg["htf_b"]: htf_b, "permission": big},
            "session": sess,
            "session_gate": session_gate,
            "bv_trigger": trig,
            "quick_trigger": q,
            "agent_pressure": {
                "pressure": agents["pressure"], "chop_flag": agents["chop_flag"],
                "chop_pct": agents.get("chop_pct", 0.0),
            },
            "notes": [
                "Elliott Wave is intentionally excluded from this score (see CLAUDE.md).",
                "M1 timeframe is not available in stored data; SCALP/INTRADAY quick-trigger substitutes M5.",
                "H4 and W1 bars are resampled from 1h/1d parquet data (no native H4/W1 store).",
            ],
        }


def build_confluence(mode: str = "SWING", symbol: str = "XAUUSD") -> dict[str, Any]:
    return ConfluenceEngine().analyze(mode=mode, symbol=symbol)
