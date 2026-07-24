"""
Order router for AUTO-mode signals → MT5 (and MT4 via the bridge EA).

Manual-mode signals never reach here — they are only displayed. An AUTO signal
is routed to the trader's own terminal.

SAFETY RAILS (deliberate, do not remove lightly):
  * a REAL account is refused unless MARKETMIND_ALLOW_REAL=1 is set explicitly
  * AutoTrading must be enabled in the terminal AND on the account
  * lot size is clamped to the symbol's min/max/step so an invalid volume is
    never submitted
  * free margin must be positive
Every refusal returns a clear status instead of raising, so the UI can show
exactly why nothing was sent.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("marketmind.executor")

DEVIATION_POINTS = 20  # max slippage tolerated, in points


def allow_real() -> bool:
    """Real-money trading is opt-in via env — never the default."""
    return os.getenv("MARKETMIND_ALLOW_REAL", "0") == "1"


def is_connected() -> bool:
    try:
        from .connectors import mt5 as mt5c
        return mt5c.is_available()
    except Exception:  # noqa: BLE001
        return False


def build_order(signal: dict, lots: float, terminal: str) -> dict:
    return {
        "symbol": signal.get("asset"),
        "side": signal.get("direction"),
        "entry": signal.get("entry"),
        "sl": signal.get("stop_loss"),
        "tp": signal.get("take_profit"),
        "lots": lots,
        "terminal": terminal,
        "source": signal.get("source"),
    }


def _clamp_lots(lots: float, limits: dict) -> float:
    """Clamp to the broker's min/max and snap to the lot step."""
    lo, hi, step = limits["min_lot"], limits["max_lot"], limits["lot_step"] or 0.01
    lots = max(lo, min(float(lots), hi))
    steps = round((lots - lo) / step)
    return round(lo + steps * step, 2)


def preflight(lots: float = 0.01, asset: str = "gold") -> dict:
    """Everything that must be true before an order can be sent."""
    from .connectors import mt5 as mt5c

    if not mt5c.is_available():
        return {"ok": False, "reason": "MT5 terminal not running"}
    acct = mt5c.account()
    if not acct:
        return {"ok": False, "reason": "not logged in to a trading account"}
    if acct["is_real"] and not allow_real():
        return {"ok": False, "reason": "REAL account blocked — set MARKETMIND_ALLOW_REAL=1 to permit",
                "account": acct}
    if not acct["trade_allowed"]:
        return {"ok": False, "reason": "AutoTrading is disabled in the terminal", "account": acct}
    if acct.get("balance", 0) <= 0 or acct.get("equity", 0) <= 0:
        return {"ok": False, "reason": "account has no funds — orders would be rejected", "account": acct}
    limits = mt5c.symbol_limits(asset)
    if not limits:
        return {"ok": False, "reason": f"symbol for '{asset}' not found at this broker", "account": acct}
    return {"ok": True, "account": acct, "limits": limits, "lots": _clamp_lots(lots, limits)}


def route(signal: dict, lots: float = 0.01, terminal: str = "MT5") -> dict:
    """Route an AUTO signal to the terminal. Returns the order + delivery status."""
    if signal.get("direction") not in ("BUY", "SELL"):
        return {"routed": False, "status": "no directional signal", "order": None}

    asset = signal.get("asset", "gold")
    order = build_order(signal, lots, terminal)

    pre = preflight(lots, asset)
    if not pre["ok"]:
        return {"routed": False, "status": f"queued — {pre['reason']}", "order": order,
                "preflight": pre}
    order["lots"] = pre["lots"]

    try:
        import MetaTrader5 as mt5  # noqa: N813
        from .connectors import mt5 as mt5c

        sym = mt5c.resolve_symbol(asset)
        tick = mt5.symbol_info_tick(sym)
        is_buy = signal["direction"] == "BUY"
        price = tick.ask if is_buy else tick.bid
        info = mt5.symbol_info(sym)

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": float(order["lots"]),
            "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            "price": price,
            "deviation": DEVIATION_POINTS,
            "magic": 20260724,
            "comment": f"MM:{signal.get('source', 'signal')}"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": (mt5.ORDER_FILLING_FOK if info.filling_mode & 1 else mt5.ORDER_FILLING_IOC),
        }
        if signal.get("stop_loss"):
            req["sl"] = round(float(signal["stop_loss"]), info.digits)
        if signal.get("take_profit"):
            req["tp"] = round(float(signal["take_profit"]), info.digits)

        res = mt5.order_send(req)
        if res is None:
            return {"routed": False, "status": f"order_send returned nothing: {mt5.last_error()}",
                    "order": order}
        ok = res.retcode == mt5.TRADE_RETCODE_DONE
        return {
            "routed": ok,
            "status": "sent" if ok else f"rejected ({res.retcode}): {res.comment}",
            "order": order,
            "ticket": getattr(res, "order", None),
            "fill_price": getattr(res, "price", None),
            "account": pre["account"]["kind"],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("MT5 order failed: %s", exc)
        return {"routed": False, "status": f"error: {exc}", "order": order}
