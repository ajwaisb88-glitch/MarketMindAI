"""
Global Money Flow — a separate engine with its own read (never feeds the
confluence/trade score).

Flow math is the honest proxy: daily dollar volume signed by price direction,
summed over N days, in $B. It is NOT reported fund flow (that data costs money)
— it is "how many dollars traded, pushing which way". The stablecoin row is the
exception: that is REAL mint/burn from circulating-supply change.

Tree: asset class -> instruments. Header carries VIX / 10Y / gold.
Proven signal: risk_off_vix — 5d money OUT of stocks + INTO bonds with VIX > 20.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import requests

from .connectors.binance import BinanceConnector

logger = logging.getLogger("marketmind.moneyflow")
_bc = BinanceConnector()
_TIMEOUT = 12

# instrument tree (label, ticker)
_STOCKS = [("S&P 500 · SPY", "SPY"), ("NASDAQ · QQQ", "QQQ"), ("DOW · DIA", "DIA")]
_BONDS = [("20Y TREAS · TLT", "TLT"), ("7-10Y · IEF", "IEF")]
_COMMODITIES = [("GOLD · GLD", "GLD"), ("SILVER · SLV", "SLV")]
_CRYPTO = [("BTC", "btc"), ("ETH", "eth")]
_MEME = [("DOGE", "doge"), ("SHIB", "shib")]
_HEADER = ["^VIX", "^TNX"]
# currency bus (row 1 of the flow tree)
_CCY = [("US DOLLAR · DXY", "DX-Y.NYB"), ("EUR · USD", "EURUSD=X"), ("USD · JPY", "USDJPY=X")]

_PROXY = "Proxy: dollar volume signed by price direction — not reported fund flow."


def signed_dollar_flow(closes, volumes, days: int = 1) -> float:
    """Dollar volume signed by price direction, in $B."""
    if len(closes) < 2:
        return 0.0
    total = 0.0
    for i in range(max(1, len(closes) - days), len(closes)):
        if closes[i - 1]:
            sign = 1.0 if closes[i] >= closes[i - 1] else -1.0
            total += sign * closes[i] * (volumes[i] or 0.0)
    return total / 1e9


def _yahoo_batch(tickers: list[str]) -> dict:
    """One batched download for every Yahoo ticker → {ticker: {closes, volumes, price, chg_pct}}."""
    out: dict[str, dict] = {}
    try:
        import yfinance as yf
        data = yf.download(tickers, period="1mo", interval="1d", progress=False,
                           auto_adjust=True, group_by="ticker", threads=True)
        for t in tickers:
            try:
                d = data[t] if len(tickers) > 1 else data
                closes = d["Close"].dropna().tolist()
                vols = d["Volume"].fillna(0).tolist() if "Volume" in d else [0] * len(closes)
                if not closes:
                    continue
                chg = ((closes[-1] - closes[-2]) / closes[-2] * 100) if len(closes) > 1 and closes[-2] else 0.0
                out[t] = {"closes": closes, "volumes": vols, "price": closes[-1], "chg_pct": chg}
            except Exception:
                continue
    except Exception as exc:  # noqa: BLE001
        logger.warning("yahoo batch failed: %s", exc)
    return out


def _binance_series(asset: str) -> dict:
    k = _bc.klines(asset, "1d", 10)
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
            "price": round(d.get("price", 0.0), 2), "chg_pct": round(d.get("chg_pct", 0.0), 2)}


def _class(cid: str, label: str, kids: list[dict], note: str) -> dict:
    f1 = sum(k["flow_1d_b"] for k in kids)
    f5 = sum(k["flow_5d_b"] for k in kids)
    return {"id": cid, "label": label, "flow_1d_b": round(f1, 2), "flow_5d_b": round(f5, 2),
            "direction": "IN" if f1 > 0 else "OUT" if f1 < 0 else "FLAT",
            "children": kids, "evidence": note}


def _stablecoins() -> dict:
    """REAL mint/burn from DefiLlama circulating-supply change."""
    try:
        r = requests.get("https://stablecoins.llama.fi/stablecoincharts/all", timeout=_TIMEOUT)
        pts = r.json() if r.status_code == 200 else []
        if len(pts) < 6:
            return {"f1": 0.0, "f5": 0.0}

        def tot(p):
            v = p.get("totalCirculatingUSD") or {}
            return sum(float(x) for x in v.values()) if isinstance(v, dict) else 0.0

        cur, d1, d5 = tot(pts[-1]), tot(pts[-2]), tot(pts[-6])
        return {"f1": (cur - d1) / 1e9, "f5": (cur - d5) / 1e9}
    except Exception as exc:  # noqa: BLE001
        logger.warning("stablecoin flow failed: %s", exc)
        return {"f1": 0.0, "f5": 0.0}


def fetch_fred_liquidity() -> dict:
    """REAL Fed net liquidity = WALCL − RRP − TGA (weekly Δ), in $B.

    Reads the key from the FRED_API_KEY environment variable — never hard-coded
    and never committed. Returns {} when no key is set, so the caller falls back
    to the yield/dollar proxy.
    """
    key = os.getenv("FRED_API_KEY", "").strip()
    if not key or "your_fred" in key:
        return {}
    try:
        from fredapi import Fred
        fred = Fred(api_key=key)
        s: dict[str, dict] = {}
        for name, sid in [("walcl", "WALCL"), ("rrp", "RRPONTSYD"),
                          ("tga", "WTREGEN"), ("m2", "M2SL")]:
            ser = fred.get_series(sid).dropna()
            s[name] = {"now": float(ser.iloc[-1]), "prev": float(ser.iloc[-2])}
        # WALCL and TGA are in $M, RRP and M2 already in $B — normalise to $B
        net_now = s["walcl"]["now"] / 1e3 - s["rrp"]["now"] - s["tga"]["now"] / 1e3
        net_prev = s["walcl"]["prev"] / 1e3 - s["rrp"]["prev"] - s["tga"]["prev"] / 1e3
        return {
            "net_liquidity_b": round(net_now, 1),
            "net_liquidity_chg_b": round(net_now - net_prev, 1),
            "m2_chg_b": round(s["m2"]["now"] - s["m2"]["prev"], 1),
            "rrp_b": round(s["rrp"]["now"], 1),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("FRED liquidity fetch failed: %s", exc)
        return {}


def _fmt(b: float) -> str:
    return f"{'+' if b >= 0 else '-'}${abs(b):.2f}b"


def build_warnings(liquidity: dict, classes: list[dict], regime: str,
                   vix: float, proven: dict, fred: dict) -> list[dict]:
    """Turn the flow picture into explicit warnings — what is going on and what it means.

    Levels: high (act on it), watch (keep an eye), info (context).
    """
    w: list[dict] = []
    by = {c["id"]: c for c in classes}

    # 1) flows running against the liquidity backdrop — the big one
    if liquidity.get("dir") == "down" and regime == "RISK-ON":
        amt = f"{liquidity['flow_b']:+,.1f}B" if liquidity.get("flow_b") is not None else "this week"
        w.append({"level": "high", "title": "Flows are fighting the liquidity backdrop",
                  "detail": f"Fed liquidity drained {amt} while money piles into risk assets. "
                            "Rallies bought into tightening liquidity are the ones that reverse hardest — "
                            "size positions for a backdrop that is not supporting them."})
    elif liquidity.get("dir") == "up" and regime == "RISK-OFF":
        w.append({"level": "watch", "title": "Money hiding despite easing liquidity",
                  "detail": "Liquidity is being added but flows are defensive — something is worrying "
                            "participants beyond the Fed. Watch for a catalyst."})

    # 2) the RRP shock absorber
    rrp = (fred or {}).get("rrp_b")
    if rrp is not None and rrp < 50:
        w.append({"level": "high", "title": "Reverse-repo buffer is empty",
                  "detail": f"RRP is ${rrp:,.0f}B. That facility absorbed drains for two years; with it "
                            "gone, further liquidity drains hit market liquidity directly instead of "
                            "being cushioned. Fragility is higher than the index level suggests."})

    # 3) today vs the week — bounce or trend
    for c in classes:
        f1, f5 = c["flow_1d_b"], c["flow_5d_b"]
        if f1 * f5 < 0 and abs(f5) >= 5 and abs(f5) > abs(f1):
            w.append({"level": "watch",
                      "title": f"{c['label']}: today is against the week",
                      "detail": f"Today {_fmt(f1)} but the week is {_fmt(f5)}. A green day inside a red "
                                "week is a bounce until proven otherwise — do not read it as a trend change."})

    # 4) rotation *inside* a class (children disagreeing)
    for c in classes:
        kids = [k for k in c.get("children", []) if abs(k["flow_1d_b"]) > 1]
        pos = [k for k in kids if k["flow_1d_b"] > 0]
        neg = [k for k in kids if k["flow_1d_b"] < 0]
        if pos and neg:
            top, bot = max(pos, key=lambda k: k["flow_1d_b"]), min(neg, key=lambda k: k["flow_1d_b"])
            w.append({"level": "watch",
                      "title": f"{c['label']}: rotation inside the class, not broad buying",
                      "detail": f"{top['label']} {_fmt(top['flow_1d_b'])} while {bot['label']} "
                                f"{_fmt(bot['flow_1d_b'])}. The class total hides a switch between "
                                "instruments — this is positioning, not fresh money."})

    # 5) dry powder
    st = by.get("stablecoins")
    if st and st["flow_1d_b"] < 0:
        w.append({"level": "watch", "title": "Stablecoin supply shrinking",
                  "detail": f"Mint/burn is {_fmt(st['flow_1d_b'])} — real dollars leaving the crypto "
                            "ecosystem, not just rotating. Less dry powder to bid."})

    # 6) the proven signal
    if proven.get("active"):
        w.append({"level": "high", "title": "PROVEN SIGNAL ACTIVE — fear pattern on",
                  "detail": "5d money out of stocks + into bonds with VIX > 20. This is the only rule "
                            "that passed both out-of-sample halves; historically constructive for gold."})

    # 7) complacency
    if vix and vix < 15 and regime == "RISK-ON":
        w.append({"level": "info", "title": "Low volatility with risk-on flows",
                  "detail": f"VIX {vix:.0f}. Cheap hedges — protection costs little while everyone is comfortable."})

    if not w:
        w.append({"level": "info", "title": "Nothing unusual in the flows",
                  "detail": "Liquidity, flows and volatility broadly agree. No divergence worth acting on."})
    return w


# Money flow is slow-moving daily data drawn from several live sources (~10-13s
# to compute). Cache it so the UI is instant after the first build, and warm it
# in the background at startup so the first view never waits.
_FLOW_TTL = float(os.getenv("MARKETMIND_MONEYFLOW_TTL_SEC", "180"))
_flow_cache: dict = {"ts": 0.0, "data": None}
_flow_lock = threading.Lock()


def get_flow(force: bool = False) -> dict:
    """Cached money-flow tree — computes at most once per _FLOW_TTL seconds."""
    now = time.time()
    if not force and _flow_cache["data"] and (now - _flow_cache["ts"]) < _FLOW_TTL:
        return _flow_cache["data"]
    with _flow_lock:                       # collapse concurrent first-hits into one build
        if not force and _flow_cache["data"] and (time.time() - _flow_cache["ts"]) < _FLOW_TTL:
            return _flow_cache["data"]
        data = build_flow()
        _flow_cache["data"] = data
        _flow_cache["ts"] = time.time()
        return data


def warm_flow() -> None:
    """Pre-compute the flow in a background thread (called at startup)."""
    def _bg():
        try:
            get_flow(force=True)
            logger.info("money flow warmed")
        except Exception as exc:  # noqa: BLE001
            logger.warning("money flow warm failed: %s", exc)
    threading.Thread(target=_bg, daemon=True).start()


def build_flow() -> dict:
    """Full money-flow tree + regime, rotation, risk balance and the proven signal."""
    ytick = [t for _, t in _STOCKS + _BONDS + _COMMODITIES + _CCY] + _HEADER
    y = _yahoo_batch(ytick)

    classes = [
        _class("stocks", "STOCKS", [_node(l, y.get(t, {})) for l, t in _STOCKS], f"Equity ETFs. {_PROXY}"),
        _class("bonds", "BONDS", [_node(l, y.get(t, {})) for l, t in _BONDS], f"Treasury ETFs. {_PROXY}"),
        _class("commodities", "COMMODITIES", [_node(l, y.get(t, {})) for l, t in _COMMODITIES], f"Metals ETFs. {_PROXY}"),
        _class("crypto", "CRYPTO", [_node(l, _binance_series(a)) for l, a in _CRYPTO], f"Binance real volume. {_PROXY}"),
        _class("meme", "MEME", [_node(l, _binance_series(a)) for l, a in _MEME],
               f"Gamble money — extreme risk appetite, no fundamentals. {_PROXY}"),
    ]
    st = _stablecoins()
    classes.append({"id": "stablecoins", "label": "STABLECOIN",
                    "flow_1d_b": round(st["f1"], 2), "flow_5d_b": round(st["f5"], 2),
                    "direction": "IN" if st["f1"] > 0 else "OUT" if st["f1"] < 0 else "FLAT",
                    "children": [],
                    "evidence": "REAL mint/burn — circulating-supply change. Minting = dry powder entering."})

    by = {c["id"]: c for c in classes}
    risk_in = sum(by.get(k, {}).get("flow_1d_b", 0.0) for k in ("stocks", "crypto", "meme"))
    safe_in = sum(by.get(k, {}).get("flow_1d_b", 0.0) for k in ("bonds", "commodities"))
    if risk_in > 0 and risk_in > safe_in:
        regime, rnote = "RISK-ON", "Money is chasing risk — stocks/crypto taking the inflow."
    elif safe_in > 0 and safe_in > risk_in:
        regime, rnote = "RISK-OFF", "Money is hiding — bonds/metals taking the inflow."
    else:
        regime, rnote = "MIXED", "No clean rotation — flows are fighting each other."

    ranked = sorted(classes, key=lambda c: c["flow_1d_b"], reverse=True)
    rotation = {"to": ranked[0]["label"], "from": ranked[-1]["label"]}

    vix = y.get("^VIX", {}).get("price", 0.0) or 0.0
    tnx = y.get("^TNX", {}).get("price", 0.0) or 0.0

    # ── PROVEN SIGNAL: risk_off_vix (validated on both 5y halves in the monster backtest) ──
    ro_active = (by["stocks"]["flow_5d_b"] < 0 and by["bonds"]["flow_5d_b"] > 0 and vix > 20)
    proven = {
        "name": "risk_off_vix",
        "active": bool(ro_active),
        "condition": "5d money OUT of stocks + INTO bonds, with VIX > 20",
        "vix_now": round(vix, 1),
        "note": ("FEAR PATTERN ON — the validated risk-off setup is active; historically constructive for gold."
                 if ro_active else
                 f"Fear pattern OFF (VIX {vix:.0f}). This is the only rule that passed both out-of-sample halves."),
        "checks": {
            "stocks_5d_out": by["stocks"]["flow_5d_b"] < 0,
            "bonds_5d_in": by["bonds"]["flow_5d_b"] > 0,
            "vix_above_20": vix > 20,
        },
    }

    story = []
    for c in classes:
        verb = "coming INTO" if c["flow_1d_b"] > 0 else "LEAVING" if c["flow_1d_b"] < 0 else "flat in"
        story.append(f"{c['label']}: money is {verb} it today ({_fmt(c['flow_1d_b'])}, week {_fmt(c['flow_5d_b'])}).")

    # ── row 1: currency bus ──
    currencies = []
    for label, t in _CCY:
        d = y.get(t, {})
        if not d:
            continue
        chg = d.get("chg_pct", 0.0)
        currencies.append({"id": t, "label": label, "price": round(d.get("price", 0.0), 4),
                           "chg_pct": round(chg, 2),
                           "state": "strengthening" if chg > 0 else "weakening" if chg < 0 else "flat"})

    # ── row 0: global liquidity — REAL Fed net liquidity when a FRED key is set ──
    dxy_chg = next((c["chg_pct"] for c in currencies if "DXY" in c["label"]), 0.0)
    tnx_chg = y.get("^TNX", {}).get("chg_pct", 0.0)
    fred = fetch_fred_liquidity()
    if fred:
        chg = fred["net_liquidity_chg_b"]
        liquidity = {
            "label": "FED NET LIQUIDITY",
            "sub": f"${fred['net_liquidity_b']:,.0f}B net · RRP ${fred['rrp_b']:,.0f}B · M2 Δ{fred['m2_chg_b']:+,.0f}B",
            "dir": "up" if chg > 0 else "down",
            "flow_b": chg,
            "source": "fred",
            "evidence": [
                f"REAL Fed net liquidity = WALCL − RRP − TGA = ${fred['net_liquidity_b']:,.0f}B.",
                f"Weekly change {chg:+,.1f}B — {'liquidity being ADDED (easing)' if chg > 0 else 'liquidity being DRAINED (tightening)'}.",
                f"Reverse repo ${fred['rrp_b']:,.0f}B · M2 weekly Δ {fred['m2_chg_b']:+,.0f}B.",
                "Source: FRED (WALCL, RRPONTSYD, WTREGEN, M2SL).",
            ],
        }
    else:
        easing = (tnx_chg < 0 and dxy_chg <= 0)
        liquidity = {
            "label": "GLOBAL LIQUIDITY",
            "sub": f"10Y {tnx:.2f}% ({tnx_chg:+.2f}%) · DXY ({dxy_chg:+.2f}%)",
            "dir": "up" if easing else "down",
            "flow_b": None,
            "source": "proxy",
            "evidence": ["PROXY: falling yields + softer dollar = easing conditions.",
                         "Set FRED_API_KEY for real net liquidity (Fed balance sheet − RRP − TGA)."],
        }

    return {
        "regime": regime, "regime_note": rnote,
        "net_flow_b": round(sum(c["flow_1d_b"] for c in classes), 2),
        "risk_in_b": round(risk_in, 2), "safe_in_b": round(safe_in, 2),
        "vix": round(vix, 1), "tnx": round(tnx, 2),
        "liquidity": liquidity, "currencies": currencies,
        "rotation": rotation, "classes": classes, "proven": proven,
        "warnings": build_warnings(liquidity, classes, regime, vix, proven, fred),
        "story": story, "caveat": _PROXY,
    }
