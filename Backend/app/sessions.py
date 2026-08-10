"""Session / volume-timing map in Dubai time (UTC+4).

Where volume actually unloads across the trading day, from the trader's Dubai
clock. Two kinds of event:
  * FIX  — a scheduled, mechanical event (auction, settlement, data release).
           Volume must print; these are the reliable ones.
  * FLOW — a behavioural tendency (desks arriving, stop runs). Real but softer.

Every event's time is defined in its OWN market timezone and converted to Dubai
with zoneinfo, so summer/winter DST is handled automatically (Dubai itself has no
DST; London/New-York-derived times shift an hour in winter, Tokyo never moves).

For XAUUSD the gold clock (LBMA AM/PM fixes, COMEX settlement) matters more than
the FX session names, so gold events are flagged and given their own slab windows.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DUBAI = ZoneInfo("Asia/Dubai")
_LON, _NY, _TOK, _SHA = (ZoneInfo("Europe/London"), ZoneInfo("America/New_York"),
                         ZoneInfo("Asia/Tokyo"), ZoneInfo("Asia/Shanghai"))

# name, tz, hour, minute, type, gold?, session, window-text, weekday (None=Mon-Fri, int=that weekday)
_SCHEDULE = [
    ("Tokyo cash open", _TOK, 9, 0, "FLOW", False, "Asia", None, None),
    ("Tokyo fix (TTM rate)", _TOK, 9, 55, "FIX", False, "Asia", "09:55 JST — reverses fast", None),
    ("Shanghai Gold Exchange open", _SHA, 9, 30, "FLOW", True, "Asia", None, None),
    ("Tokyo close", _TOK, 15, 0, "FLOW", False, "Asia", None, None),
    ("London open", _LON, 8, 0, "FLOW", False, "London", "first 90m = the directional burst", None),
    ("LBMA Platinum/Palladium AM", _LON, 9, 45, "FIX", False, "London", None, None),
    ("LBMA Gold AM auction", _LON, 10, 30, "FIX", True, "London", "physically-settled gold fix", None),
    ("LBMA Silver auction", _LON, 12, 0, "FIX", True, "London", None, None),
    ("COMEX floor open", _NY, 8, 20, "FIX", True, "Pre-NY", "US metals desks come live", None),
    ("US 08:30 data (NFP/CPI/PPI)", _NY, 8, 30, "FIX", False, "Pre-NY", "highest-volume minute on data days", None),
    ("LBMA Platinum/Palladium PM", _LON, 14, 0, "FIX", False, "Pre-NY", None, None),
    ("NYSE / index cash open", _NY, 9, 30, "FIX", False, "New York", "London–NY overlap peak", None),
    ("US 10:00 data (ISM/JOLTS)", _NY, 10, 0, "FIX", False, "New York", None, None),
    ("EIA crude inventories", _NY, 10, 30, "FIX", False, "New York", "moves WTI hard", 2),   # Wednesday
    ("LBMA Gold PM auction", _LON, 15, 0, "FIX", True, "New York", "the more-traded gold fix", None),
    ("WMR 4pm fix", _LON, 16, 0, "FIX", False, "London Close", "15:57:30–16:02:30 window; usually reverts", None),
    ("London session close", _LON, 17, 0, "FLOW", False, "London Close", None, None),
    ("COMEX gold settlement", _NY, 13, 30, "FIX", True, "Commodities", "13:29–13:30 ET — clean gold pulse", None),
    ("NYMEX WTI settlement", _NY, 14, 30, "FIX", False, "Commodities", "14:28–14:30 ET VWAP", None),
    ("API crude", _NY, 16, 30, "FIX", False, "Commodities", None, 1),   # Tuesday
    ("NYSE closing imbalance", _NY, 15, 50, "FIX", False, "US Close", None, None),
    ("NYSE closing auction", _NY, 16, 0, "FIX", False, "US Close", "~7% of NYSE daily volume in one print", None),
]


def _instances_for(target, now):
    """All scheduled events landing on the Dubai calendar date `target`."""
    out = []
    for (name, tz, hh, mm, typ, gold, session, note, wd) in _SCHEDULE:
        for off in (-1, 0, 1):                       # cover tz rollover across midnight
            d = target + timedelta(days=off)
            src = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
            dub = src.astimezone(DUBAI)
            if dub.date() != target:
                continue
            wkday = src.weekday()
            if wd is None and wkday > 4:              # default: weekdays only
                continue
            if wd is not None and wkday != wd:
                continue
            out.append({
                "event": name, "type": typ, "gold": gold, "session": session,
                "note": note, "dubai_time": dub.strftime("%H:%M"),
                "when_utc": dub.astimezone(timezone.utc).isoformat(),
                "past": dub < now, "mins_away": round((dub - now).total_seconds() / 60),
            })
    out.sort(key=lambda e: e["when_utc"])
    return out


def _current_sessions(now):
    """Which named sessions are live right now (source-market business hours)."""
    lon = now.astimezone(_LON); ny = now.astimezone(_NY); tok = now.astimezone(_TOK)
    lon_m, ny_m, tok_m = lon.hour * 60 + lon.minute, ny.hour * 60 + ny.minute, tok.hour * 60 + tok.minute
    active = []
    wk = lambda t: t.weekday() <= 4
    if wk(tok) and 9 * 60 <= tok_m < 15 * 60:
        active.append("Asia")
    if wk(lon) and 8 * 60 <= lon_m < 17 * 60:
        active.append("London")
    if wk(ny) and 7 * 60 <= ny_m < 9 * 60 + 30:
        active.append("Pre-NY")
    if wk(ny) and 9 * 60 + 30 <= ny_m < 16 * 60:
        active.append("New York")
    if "London" in active and "New York" in active:
        active.append("Overlap (prime)")
    return active


def _slab(center_iso, before=10, after=5):
    c = datetime.fromisoformat(center_iso)
    s, e = c - timedelta(minutes=before), c + timedelta(minutes=after)
    return {"start": s.astimezone(DUBAI).strftime("%H:%M"), "end": e.astimezone(DUBAI).strftime("%H:%M")}


# ── institutional-window classifier (the "WHEN" half of Time × BetterVolume) ──
# Each window: liquidity + the PDF's expected behaviour + whether it's tradeable.
# Behaviour: REVERSAL (sweep+reclaim), CONTINUATION (ride the move), FADE (fix
# reverts), SHOCK (data — usually stand aside), AVOID (thin/prep only).
WINDOWS = {
    "LONDON_OPEN":  {"label": "London Open (judas)", "liquidity": "HIGH", "behavior": "REVERSAL",
                     "tradeable": True, "note": "First 90m — sweep the Asian range then reverse."},
    "NY_OVERLAP":   {"label": "London–NY Overlap", "liquidity": "HIGH", "behavior": "CONTINUATION",
                     "tradeable": True, "note": "Highest liquidity, cleanest fills — ride the London direction."},
    "DATA_SHOCK":   {"label": "US 08:30 data window", "liquidity": "HIGH", "behavior": "SHOCK",
                     "tradeable": False, "note": "Data spike whipsaws — stand aside, trade the 2nd move."},
    "WMR_FIX":      {"label": "WMR 4pm fix", "liquidity": "HIGH", "behavior": "FADE",
                     "tradeable": False, "note": "Forced flow reverts — mark it, trade the reaction (backtest: no entry edge)."},
    "COMEX_SETTLE": {"label": "COMEX gold settlement", "liquidity": "MED", "behavior": "FADE",
                     "tradeable": False, "note": "Obligation-driven pulse — mark the level, don't enter on it."},
    "GOLD_FIX":     {"label": "LBMA gold fix", "liquidity": "MED", "behavior": "REVERSAL",
                     "tradeable": True, "note": "Scheduled gold auction — the best backtested window."},
    "LONDON":       {"label": "London midday", "liquidity": "MED", "behavior": "CONTINUATION",
                     "tradeable": False, "note": "Post-open midday drift — low quality (PDF + backtest). Prime windows are London Open & NY overlap."},
    "ASIA":         {"label": "Asia (range-build)", "liquidity": "LOW", "behavior": "AVOID",
                     "tradeable": False, "note": "Thin — builds the range London raids. Prepare, don't trade."},
    "DEAD":         {"label": "Low-liquidity hours", "liquidity": "LOW", "behavior": "AVOID",
                     "tradeable": False, "note": "Tokyo lunch / post-fix drift / deep US afternoon — thin."},
    "OFF":          {"label": "Weekend — closed", "liquidity": "LOW", "behavior": "AVOID",
                     "tradeable": False, "note": "Market closed."},
}


def _window_key(now):
    """Classify the current institutional window using each market's own clock
    (so summer/winter DST is automatic). Most-specific windows win."""
    dub = now.astimezone(DUBAI)
    if dub.weekday() > 4 and not (dub.weekday() == 6 and dub.hour >= 2):
        return "OFF"
    lon, ny, tok = now.astimezone(_LON), now.astimezone(_NY), now.astimezone(_TOK)
    lm, nm, tm = lon.hour * 60 + lon.minute, ny.hour * 60 + ny.minute, tok.hour * 60 + tok.minute
    if abs(nm - (8 * 60 + 30)) <= 8:                      # 08:30 ET data ±8m
        return "DATA_SHOCK"
    if (13 * 60 + 25) <= nm <= (13 * 60 + 35):            # COMEX gold settle 13:29–13:30 ET
        return "COMEX_SETTLE"
    if abs(lm - 16 * 60) <= 6:                            # WMR 4pm fix ±6m
        return "WMR_FIX"
    if abs(lm - (10 * 60 + 30)) <= 7 or abs(lm - 15 * 60) <= 7:   # LBMA AM 10:30 / PM 15:00
        return "GOLD_FIX"
    if lon.weekday() <= 4 and (8 * 60) <= lm < (9 * 60 + 30):     # London open first 90m
        return "LONDON_OPEN"
    if ny.weekday() <= 4 and (9 * 60 + 30) <= nm < (11 * 60):     # NY open first 90m (overlap)
        return "NY_OVERLAP"
    if lon.weekday() <= 4 and (8 * 60) <= lm < (17 * 60):         # rest of London
        return "LONDON"
    if tok.weekday() <= 4 and (9 * 60) <= tm < (15 * 60):         # Tokyo cash
        if (11 * 60 + 30) <= tm < (12 * 60 + 30):                 # Tokyo lunch trough
            return "DEAD"
        return "ASIA"
    return "DEAD"


def current_window(now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    key = _window_key(now)
    return {"window": key, **WINDOWS[key]}


def get_sessions() -> dict:
    now = datetime.now(timezone.utc).astimezone(DUBAI)
    today = now.date()
    events = _instances_for(today, now)

    # next scheduled FIX (and next gold FIX) — search forward up to 5 days for weekends/holidays
    nxt_fix = nxt_gold = None
    for off in range(0, 6):
        day = today + timedelta(days=off)
        for e in _instances_for(day, now):
            if e["past"] or e["type"] != "FIX":
                continue
            if nxt_fix is None:
                nxt_fix = e
            if nxt_gold is None and e["gold"]:
                nxt_gold = e
        if nxt_fix and nxt_gold:
            break

    active = _current_sessions(now)
    market_open = now.weekday() <= 4 or (now.weekday() == 6 and now.hour >= 1)  # rough FX week

    # dynamic gold slabs around today's real gold-event times (DST-correct)
    gold_slabs = []
    for e in events:
        if e["gold"] and e["type"] == "FIX":
            sl = _slab(e["when_utc"])
            gold_slabs.append({"event": e["event"], "start": sl["start"], "end": sl["end"], "past": e["past"]})

    lon = now.astimezone(_LON)
    return {
        "dubai_time": now.strftime("%H:%M"), "dubai_date": today.isoformat(),
        "weekday": now.strftime("%A"), "market_open": market_open,
        "is_summer": bool(lon.dst()), "utc_now": datetime.now(timezone.utc).isoformat(),
        "current_sessions": active,
        "primary_session": (active[-1] if active else ("Weekend — markets closed" if not market_open else "Between sessions")),
        "next_fix": nxt_fix, "next_gold_fix": nxt_gold,
        "events": events, "gold_slabs": gold_slabs,
        "note": ("Summer (London BST / New York EDT). Winter shifts London/NY events one hour later in Dubai; Tokyo never moves."
                 if bool(lon.dst()) else
                 "Winter (London GMT / New York EST). London/NY events are one hour later in Dubai than summer; Tokyo never moves."),
        "caveat": "Volume marks the level — the reaction is the trade. Most fixes and settlements revert; wait for the sweep + reclaim.",
    }
