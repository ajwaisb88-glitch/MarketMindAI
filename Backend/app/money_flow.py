"""
Crypto Money Flow — a separate engine with its own read (never feeds the trade
score). Binance-only for speed (Yahoo dropped — it was slow); Fed liquidity from
FRED; real stablecoin mint/burn from DefiLlama.

Flow math is the honest proxy: daily dollar volume signed by price direction, in
$B — "how many dollars traded, pushing which way". The stablecoin row is REAL
mint/burn (circulating-supply change = actual dry powder entering or leaving).

Every node carries a plain-English "explain" line so a student can read it.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from .connectors.binance import BinanceConnector

logger = logging.getLogger("marketmind.moneyflow")
_bc = BinanceConnector()
_TIMEOUT = 12

# Binance universe (all verified live). label -> symbol
_MAJORS = [("BTC", "btc"), ("ETH", "eth"), ("BNB", "BNBUSDT"),
           ("SOL", "SOLUSDT"), ("XRP", "XRPUSDT")]
_ALTS = [("ADA", "ADAUSDT"), ("AVAX", "AVAXUSDT"), ("LINK", "LINKUSDT")]
_MEME = [("DOGE", "doge"), ("SHIB", "SHIBUSDT"), ("PEPE", "PEPEUSDT"),
         ("FLOKI", "FLOKIUSDT"), ("WIF", "WIFUSDT"), ("BONK", "BONKUSDT")]
_GOLD = [("PAX GOLD", "gold")]

_PROXY = "Flow = a day's dollar trading, signed by whether price rose or fell. Not reported fund flow."


def signed_dollar_flow(closes, volumes, days: int = 1) -> float:
    if len(closes) < 2:
        return 0.0
    total = 0.0
    for i in range(max(1, len(closes) - days), len(closes)):
        if closes[i - 1]:
            sign = 1.0 if closes[i] >= closes[i - 1] else -1.0
            total += sign * closes[i] * (volumes[i] or 0.0)
    return total / 1e9


def _series(symbol: str) -> dict:
    k = _bc.klines(symbol, "1d", 10)
    if not k or len(k) < 2:
        return {}
    closes = [b["close"] for b in k]
    vols = [b["volume"] for b in k]
    chg = ((closes[-1] - closes[-2]) / closes[-2] * 100) if closes[-2] else 0.0
    return {"closes": closes, "volumes": vols, "price": closes[-1], "chg_pct": chg}


def _node(label: str, d: dict) -> dict:
    f1 = signed_dollar_flow(d.get("closes", []), d.get("volumes", []), 1)
    f5 = signed_dollar_flow(d.get("closes", []), d.get("volumes", []), 5)
    return {"label": label, "flow_1d_b": round(f1, 3), "flow_5d_b": round(f5, 3),
            "price": round(d.get("price", 0.0), 6), "chg_pct": round(d.get("chg_pct", 0.0), 2)}


def _class(cid: str, label: str, kids: list[dict], evidence: str, explain: str) -> dict:
    f1 = sum(k["flow_1d_b"] for k in kids)
    f5 = sum(k["flow_5d_b"] for k in kids)
    return {"id": cid, "label": label, "flow_1d_b": round(f1, 2), "flow_5d_b": round(f5, 2),
            "direction": "IN" if f1 > 0 else "OUT" if f1 < 0 else "FLAT",
            "children": kids, "evidence": evidence, "explain": explain}


def _series_map(pairs: list[tuple]) -> dict:
    """Fetch every symbol's series in parallel (fast first build)."""
    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for (label, sym), d in zip(pairs, ex.map(lambda p: _series(p[1]), pairs)):
            out[label] = d
    return out


# FRED is weekly data and DefiLlama is daily — cache them long so money-flow
# refreshes only re-hit fast Binance prices.
_slow_cache: dict = {}


def _slow_cached(key: str, ttl: float, fetch):
    hit = _slow_cache.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    val = fetch()
    if val:  # don't cache an empty/failed result
        _slow_cache[key] = (time.time(), val)
    return val


def _stablecoins() -> dict:
    def _fetch():
        try:
            r = requests.get("https://stablecoins.llama.fi/stablecoincharts/all", timeout=_TIMEOUT)
            pts = r.json() if r.status_code == 200 else []
            if len(pts) < 6:
                return {}

            def tot(p):
                v = p.get("totalCirculatingUSD") or {}
                return sum(float(x) for x in v.values()) if isinstance(v, dict) else 0.0

            cur, d1, d5 = tot(pts[-1]), tot(pts[-2]), tot(pts[-6])
            return {"f1": (cur - d1) / 1e9, "f5": (cur - d5) / 1e9}
        except Exception as exc:  # noqa: BLE001
            logger.warning("stablecoin flow failed: %s", exc)
            return {}
    return _slow_cached("stables", 600, _fetch) or {"f1": 0.0, "f5": 0.0}


def fetch_fred_liquidity() -> dict:
    key = os.getenv("FRED_API_KEY", "").strip()
    if not key or "your_fred" in key:
        return {}

    def _fetch():
        try:
            from fredapi import Fred
            fred = Fred(api_key=key)
            ids = [("walcl", "WALCL"), ("rrp", "RRPONTSYD"), ("tga", "WTREGEN"), ("m2", "M2SL")]

            def one(item):
                ser = fred.get_series(item[1]).dropna()
                return item[0], {"now": float(ser.iloc[-1]), "prev": float(ser.iloc[-2])}

            with ThreadPoolExecutor(max_workers=4) as ex:   # 4 requests in parallel
                s = dict(ex.map(one, ids))
            net_now = s["walcl"]["now"] / 1e3 - s["rrp"]["now"] - s["tga"]["now"] / 1e3
            net_prev = s["walcl"]["prev"] / 1e3 - s["rrp"]["prev"] - s["tga"]["prev"] / 1e3
            return {"net_liquidity_b": round(net_now, 1), "net_liquidity_chg_b": round(net_now - net_prev, 1),
                    "m2_chg_b": round(s["m2"]["now"] - s["m2"]["prev"], 1), "rrp_b": round(s["rrp"]["now"], 1)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("FRED liquidity fetch failed: %s", exc)
            return {}
    return _slow_cached("fred", 1800, _fetch)   # weekly data — cache 30 min


def _fmt(b: float) -> str:
    return f"{'+' if b >= 0 else '-'}${abs(b):.2f}b"


def build_warnings(liquidity, classes, regime, proven, fred) -> list[dict]:
    w = []
    by = {c["id"]: c for c in classes}

    if liquidity.get("dir") == "down" and regime == "RISK-ON":
        amt = f"{liquidity['flow_b']:+,.1f}B" if liquidity.get("flow_b") is not None else "this week"
        w.append({"level": "high", "title": "Buyers are fighting the Fed",
                  "detail": f"The Fed drained {amt} of money from the system this week, but crypto is being "
                            "bought anyway. When the tide is going out, rallies tend to snap back hardest — "
                            "keep your size small.",
                  "explain": "Think of the Fed as the tap filling the pool. The tap is off, but people keep "
                             "jumping in. Fun for now, but the water level is dropping."})

    rrp = (fred or {}).get("rrp_b")
    if rrp is not None and rrp < 50:
        w.append({"level": "high", "title": "The market's safety cushion is gone",
                  "detail": f"The Fed's reverse-repo buffer is down to ${rrp:,.0f}B. It soaked up shocks for two "
                            "years; now that it's empty, any further drain hits the market directly.",
                  "explain": "It's like a car with no airbag left. Fine while the road is smooth — but a bump "
                             "now hurts a lot more than it used to."})

    st = by.get("stable")
    if st and st["flow_1d_b"] < 0:
        w.append({"level": "watch", "title": "Dry powder is shrinking",
                  "detail": f"Stablecoins are being burned ({_fmt(st['flow_1d_b'])}) — real dollars leaving crypto, "
                            "not just moving around. Less cash on the sidelines to push prices up.",
                  "explain": "Stablecoins are the 'cash' waiting to buy coins. Less cash waiting = fewer buyers "
                             "in reserve."})
    elif st and st["flow_1d_b"] > 0.5:
        w.append({"level": "info", "title": "Dry powder building",
                  "detail": f"Stablecoins minted (+{_fmt(st['flow_1d_b'])[2:]}) — fresh cash entering crypto, "
                            "waiting to be deployed. A tailwind if it starts buying.",
                  "explain": "New 'cash' just arrived on the sidelines. It hasn't bought yet — but it can."})

    meme = by.get("meme")
    if meme and meme["flow_1d_b"] > 0 and meme["flow_1d_b"] > by.get("majors", {}).get("flow_1d_b", 0):
        w.append({"level": "watch", "title": "Gamble money is leading",
                  "detail": "Meme coins are pulling in more than the majors today — a sign of stretched, "
                            "speculative risk appetite. Late-stage rallies often look like this.",
                  "explain": "When the riskiest, silliest coins run hardest, the crowd is greedy. Great fun, "
                             "but it's often near the top, not the bottom."})

    for c in classes:
        f1, f5 = c["flow_1d_b"], c["flow_5d_b"]
        if f1 * f5 < 0 and abs(f5) >= 3 and abs(f5) > abs(f1):
            w.append({"level": "watch", "title": f"{c['label']}: today fights the week",
                      "detail": f"Today {_fmt(f1)} but the week is {_fmt(f5)}. A green day inside a red week is a "
                                "bounce until proven otherwise — not a trend change yet.",
                      "explain": "One good day doesn't undo a bad week. Wait for the week to turn too before "
                                 "believing it."})

    if proven.get("active"):
        w.append({"level": "high", "title": "Fear pattern is ON",
                  "detail": "Money is leaving risk and hiding in safety with volatility high — the validated "
                            "risk-off setup. Historically kind to gold.",
                  "explain": "When everyone runs for the exits at once, gold usually gets the hug."})

    if not w:
        w.append({"level": "info", "title": "Nothing unusual today",
                  "detail": "Liquidity, flows and dry powder broadly agree. No divergence worth acting on.",
                  "explain": "Calm seas. Nothing is screaming for your attention right now."})
    return w


# ── caching / warm ─────────────────────────────────
_FLOW_TTL = float(os.getenv("MARKETMIND_MONEYFLOW_TTL_SEC", "60"))
_flow_cache: dict = {"ts": 0.0, "data": None}
_flow_lock = threading.Lock()


def get_flow(force: bool = False) -> dict:
    now = time.time()
    if not force and _flow_cache["data"] and (now - _flow_cache["ts"]) < _FLOW_TTL:
        return _flow_cache["data"]
    with _flow_lock:
        if not force and _flow_cache["data"] and (time.time() - _flow_cache["ts"]) < _FLOW_TTL:
            return _flow_cache["data"]
        data = build_flow()
        _flow_cache["data"] = data
        _flow_cache["ts"] = time.time()
        return data


def warm_flow() -> None:
    def _bg():
        try:
            get_flow(force=True)
            logger.info("money flow warmed")
        except Exception as exc:  # noqa: BLE001
            logger.warning("money flow warm failed: %s", exc)
    threading.Thread(target=_bg, daemon=True).start()


def build_flow() -> dict:
    """Crypto money-flow tree — Binance + Fed liquidity + real stablecoin mint/burn."""
    ser = _series_map(_MAJORS + _ALTS + _MEME + _GOLD)

    majors = _class("majors", "MAJORS", [_node(l, ser.get(l, {})) for l, _ in _MAJORS],
                    f"BTC/ETH/BNB/SOL/XRP — real Binance volume. {_PROXY}",
                    "The blue chips of crypto. Where the big, 'serious' money goes.")
    alts = _class("alts", "ALTS / L1", [_node(l, ser.get(l, {})) for l, _ in _ALTS],
                  f"Layer-1 alts. {_PROXY}",
                  "Smaller, riskier bets than the majors — they run hard when the crowd feels bold.")
    meme = _class("meme", "MEME", [_node(l, ser.get(l, {})) for l, _ in _MEME],
                  f"Pure speculation, no fundamentals. {_PROXY}",
                  "Gamble money. Measures how greedy and risk-hungry the crowd is right now.")
    gold = _class("gold", "GOLD", [_node(l, ser.get(l, {})) for l, _ in _GOLD],
                  f"PAX Gold (tokenised gold). {_PROXY}",
                  "The safe haven. Money hides here when people get scared.")

    st = _stablecoins()
    stable = {"id": "stable", "label": "STABLECOIN", "flow_1d_b": round(st["f1"], 2),
              "flow_5d_b": round(st["f5"], 2), "children": [],
              "direction": "IN" if st["f1"] > 0 else "OUT" if st["f1"] < 0 else "FLAT",
              "evidence": "REAL mint/burn — change in circulating supply (DefiLlama).",
              "explain": "The 'cash' of crypto. Minting = new money arriving; burning = money leaving."}

    classes = [majors, alts, meme, gold, stable]
    by = {c["id"]: c for c in classes}

    risk_in = by["majors"]["flow_1d_b"] + by["alts"]["flow_1d_b"] + by["meme"]["flow_1d_b"]
    safe_in = by["gold"]["flow_1d_b"] + max(0.0, by["stable"]["flow_1d_b"])
    if risk_in > 0 and risk_in > safe_in:
        regime, rnote = "RISK-ON", "Money is chasing risk — majors, alts and memes taking the inflow."
    elif safe_in > risk_in:
        regime, rnote = "RISK-OFF", "Defensive — money into gold and the stablecoin sidelines."
    else:
        regime, rnote = "MIXED", "No clean rotation — flows are split."

    ranked = sorted(classes, key=lambda c: c["flow_1d_b"], reverse=True)
    rotation = {"to": ranked[0]["label"], "from": ranked[-1]["label"]}

    # currency-bus row repurposed as the crypto "pulse": BTC / ETH / SOL
    pulse = []
    for lbl in ("BTC", "ETH", "SOL"):
        d = ser.get(lbl, {})
        if d:
            chg = d.get("chg_pct", 0.0)
            pulse.append({"id": lbl, "label": lbl, "price": round(d.get("price", 0.0), 2),
                          "chg_pct": round(chg, 2),
                          "state": "rising" if chg > 0 else "falling" if chg < 0 else "flat"})

    fred = fetch_fred_liquidity()
    if fred:
        chg = fred["net_liquidity_chg_b"]
        liquidity = {
            "label": "FED NET LIQUIDITY", "source": "fred", "dir": "up" if chg > 0 else "down",
            "flow_b": chg, "sub": f"${fred['net_liquidity_b']:,.0f}B net · RRP ${fred['rrp_b']:,.0f}B · M2 Δ{fred['m2_chg_b']:+,.0f}B",
            "evidence": [f"Real Fed net liquidity = ${fred['net_liquidity_b']:,.0f}B; weekly change {chg:+,.1f}B "
                         f"({'adding — easing' if chg > 0 else 'draining — tightening'}).",
                         f"Reverse repo ${fred['rrp_b']:,.0f}B · M2 weekly Δ {fred['m2_chg_b']:+,.0f}B.",
                         "Source: FRED (WALCL, RRPONTSYD, WTREGEN, M2SL)."],
            "explain": "This is the tide for ALL risk assets. Rising = more money in the system (good for crypto); "
                       "falling = money being pulled out (a headwind).",
        }
    else:
        liquidity = {"label": "FED LIQUIDITY", "source": "proxy", "dir": "up", "flow_b": None,
                     "sub": "set FRED_API_KEY for real data",
                     "evidence": ["Set FRED_API_KEY for real Fed net liquidity (WALCL − RRP − TGA)."],
                     "explain": "The tide for all risk assets. Add a free FRED key to see the real number."}

    # proven risk-off signal: gold inflow + stablecoins minting (fear = cash + gold)
    proven = {"name": "risk_off_crypto",
              "active": bool(by["gold"]["flow_1d_b"] > 0 and by["stable"]["flow_1d_b"] > 0
                             and risk_in < 0),
              "condition": "money leaving risk coins while gold + stablecoins take inflow",
              "checks": {"risk coins OUT": risk_in < 0, "gold IN": by["gold"]["flow_1d_b"] > 0,
                         "stables minting": by["stable"]["flow_1d_b"] > 0}}

    story = []
    for c in classes:
        verb = "coming INTO" if c["flow_1d_b"] > 0 else "LEAVING" if c["flow_1d_b"] < 0 else "flat in"
        story.append(f"{c['label']}: money is {verb} it today ({_fmt(c['flow_1d_b'])}, week {_fmt(c['flow_5d_b'])}).")

    student = (f"In plain English: the Fed's money tide is {'rising' if liquidity['dir'] == 'up' else 'going out'}, "
               f"and crypto is currently {regime.replace('-', ' ').lower()}. "
               f"Money is rotating out of {rotation['from']} and into {rotation['to']}.")

    return {
        "regime": regime, "regime_note": rnote,
        "net_flow_b": round(sum(c["flow_1d_b"] for c in classes), 2),
        "risk_in_b": round(risk_in, 2), "safe_in_b": round(safe_in, 2),
        "liquidity": liquidity, "currencies": pulse,
        "rotation": rotation, "classes": classes, "proven": proven,
        "warnings": build_warnings(liquidity, classes, regime, proven, fred),
        "story": story, "student_summary": student, "caveat": _PROXY,
        "asof": int(time.time()),
    }
