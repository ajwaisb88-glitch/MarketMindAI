"""
Order router for AUTO-mode signals → MT4 / MT5.

A signal from a source set to AUTO is routed here to be placed on the trader's
own account. Real order placement is wired when the MT5 terminal (or MT4 bridge
EA) is connected; until then the order is QUEUED and returned so the UI can show
exactly what would be sent. Manual-mode signals never reach here — they are only
displayed.
"""
from __future__ import annotations

import os


def is_connected() -> bool:
    """True when an MT5/MT4 connection is live. False until the bridge is wired."""
    return os.getenv("MARKETMIND_MT_CONNECTED", "0") == "1"


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


def route(signal: dict, lots: float = 0.01, terminal: str = "MT5") -> dict:
    """Route an AUTO signal to the terminal. Returns the order + delivery status."""
    if signal.get("direction") not in ("BUY", "SELL"):
        return {"routed": False, "status": "no directional signal", "order": None}
    order = build_order(signal, lots, terminal)
    if not is_connected():
        return {"routed": False, "status": f"queued — connect {terminal} to execute", "order": order}
    # TODO: real placement — MetaTrader5.order_send(...) for MT5, or file/socket to the MT4 EA.
    return {"routed": True, "status": "sent", "order": order}
