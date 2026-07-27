"""Economic News Radar — upcoming high-impact US events and their gold impact.

Key-free and honest: the event *dates* are computed from the real US release
schedule (NFP = first Friday, CPI mid-month, jobless claims every Thursday, FOMC
from the published 2026 meeting calendar). The impact score, gold direction bias,
mechanism and typical move are MarketMind/Monster's backtested reference values —
analysis, not a live data feed, and labelled as such.

Times are US Eastern; we surface a UTC timestamp so the UI can count down in the
viewer's local time. No forecast/actual numbers are invented here.
"""
from __future__ import annotations

import calendar as _cal
from datetime import date, datetime, timedelta, timezone

# US Eastern is UTC-4 in summer (EDT). Good enough for a countdown; the UI shows
# the viewer's local time. 08:30 ET -> 12:30 UTC, 14:00 ET -> 18:00 UTC.
_ET_OFFSET_H = 4

# The Fed's 2026 FOMC statement days (second day of each meeting).
_FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
              "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]

# name, impact 1-10, gold bias, "hot print ->" gold move, mechanism, typical pips,
# historical win-rate, schedule spec, ET time.
_EVENTS = [
    ("CPI m/m", 10, "BEARISH", "GOLD ↓↓", "Inflation ↑ → real yields rise → hawkish Fed → gold falls", 245, 0.72, ("range", 10, 15), "08:30"),
    ("Core CPI m/m", 10, "BEARISH", "GOLD ↓↓", "Sticky core inflation → hawkish Fed → gold falls", 210, 0.68, ("range", 10, 15), "08:30"),
    ("FOMC Statement", 10, "MIXED", "CONTEXT", "Hawkish → gold ↓ · Dovish → gold ↑", 380, 0.55, ("fomc",), "14:00"),
    ("Fed Rate Decision", 9, "MIXED", "GOLD ↓", "Rate HIKE → gold ↓ · Rate CUT → gold ↑", 320, 0.58, ("fomc",), "14:00"),
    ("NFP (Payrolls)", 9, "BEARISH", "GOLD ↓↓", "Strong jobs → wage inflation → hawkish Fed → gold falls", 185, 0.72, ("nth", 4, 1), "08:30"),
    ("Unemployment Rate", 7, "BULLISH", "GOLD ↑↑", "Higher unemployment → recession fear → gold soars (safe haven)", 160, 0.62, ("nth", 4, 1), "08:30"),
    ("PCE m/m", 8, "BEARISH", "GOLD ↓↓", "Fed's preferred inflation gauge ↑ → cut odds ↓ → gold falls", 155, 0.65, ("range", 25, 30), "08:30"),
    ("ISM Manufacturing PMI", 7, "BEARISH", "GOLD ↓", "Factory strength → risk-on → gold falls", 120, 0.62, ("nth", 0, 1), "10:00"),
    ("GDP q/q", 7, "BEARISH", "GOLD ↓", "Growth ↑ → fewer cuts → gold falls (unless recession fear flips it)", 140, 0.60, ("range", 25, 30), "08:30"),
    ("ISM Services PMI", 6, "BEARISH", "GOLD ↓", "Services strong → less safe-haven demand", 85, 0.58, ("nth", 2, 1), "10:00"),
    ("Retail Sales m/m", 6, "BEARISH", "GOLD ↓", "Consumer spending ↑ → USD strength → gold falls", 95, 0.58, ("range", 14, 18), "08:30"),
    ("Consumer Confidence", 5, "BEARISH", "GOLD ↓", "Confident consumers → growth → less gold demand", 75, 0.55, ("range", 25, 30), "10:00"),
    ("Initial Jobless Claims", 4, "BULLISH", "GOLD ↑", "More layoffs → weaker labor → safe-haven bid → gold up", 45, 0.48, ("weekly", 3), "08:30"),
]


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    c = _cal.monthcalendar(year, month)
    hits = [w[weekday] for w in c if w[weekday] != 0]
    return date(year, month, hits[min(n - 1, len(hits) - 1)])


def _to_weekday(d: date) -> date:
    while d.weekday() > 4:      # roll Sat/Sun back to Friday
        d -= timedelta(days=1)
    return d


def _next_date(spec: tuple, today: date) -> date | None:
    kind = spec[0]
    if kind == "fomc":
        for iso in _FOMC_2026:
            d = date.fromisoformat(iso)
            if d >= today:
                return d
        return None
    if kind == "weekly":                       # next given weekday (>= today)
        wd = spec[1]
        ahead = (wd - today.weekday()) % 7
        return today + timedelta(days=ahead)
    # monthly specs: try this month then the next two
    for off in range(3):
        ym = today.year * 12 + today.month - 1 + off
        y, m = ym // 12, ym % 12 + 1
        if kind == "nth":
            d = _nth_weekday(y, m, spec[1], spec[2])
        else:                                   # range(lo, hi) → mid, nudged to a weekday
            lo, hi = spec[1], spec[2]
            hi = min(hi, _cal.monthrange(y, m)[1])
            d = _to_weekday(date(y, m, (lo + hi) // 2))
        if d >= today:
            return d
    return None


def _when_utc(d: date, et_time: str) -> str:
    hh, mm = (int(x) for x in et_time.split(":"))
    dt = datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone.utc) + timedelta(hours=_ET_OFFSET_H)
    return dt.isoformat()


def get_news(days: int = 21) -> dict:
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=days)
    events = []
    for (name, impact, bias, hot, mech, pips, wr, spec, et) in _EVENTS:
        d = _next_date(spec, today)
        if not d or d > horizon:
            continue
        events.append({
            "event": name, "impact": impact, "bias": bias,
            "hot_print_means": hot, "mechanism": mech,
            "avg_move_pips": pips, "win_rate": round(wr * 100),
            "date": d.isoformat(), "day": d.strftime("%a %b %d"),
            "et_time": et + " ET", "when_utc": _when_utc(d, et),
            "days_away": (d - today).days,
        })
    events.sort(key=lambda e: (e["date"], -e["impact"]))

    high = [e for e in events if e["impact"] >= 8]
    nxt = min(high or events, key=lambda e: e["when_utc"], default=None)

    # this-week gold lean from high-impact events in the next 7 days
    soon = [e for e in events if e["days_away"] <= 7 and e["impact"] >= 6]
    bear = sum(1 for e in soon if e["bias"] == "BEARISH")
    bull = sum(1 for e in soon if e["bias"] == "BULLISH")
    lean = "NEUTRAL"
    if bear > bull:
        lean = "GOLD HEADWIND"
    elif bull > bear:
        lean = "GOLD TAILWIND"

    return {
        "asof": today.isoformat(),
        "events": events,
        "next_high_impact": nxt,
        "week_lean": lean,
        "week_note": (f"{len(soon)} major event(s) in the next 7 days — "
                      f"{bear} lean gold-down, {bull} lean gold-up."
                      if soon else "No major US events in the next 7 days."),
        "caveat": "Dates are the real US release schedule; impact, bias and typical move "
                  "are backtested reference values, not a live forecast.",
    }
