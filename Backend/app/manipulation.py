"""Market-manipulation / spoofing detection engine for MarketMind AI.

Implements the "spoofing radar" concept: from a limit-order-book snapshot plus a
short window of order-flow events it produces

  * order-book imbalance          (bid vs ask resting size)
  * cancel-to-trade ratio         (spoof orders are placed then pulled)
  * depth asymmetry / phantom liq (size sitting away from mid that vanishes)
  * a spoofing probability 0..100 (Bayesian fusion of the above signals)
  * a SPOOF / SHEEP / WHALE sentiment triangle
  * the perpetual funding rate

The order book here is *simulated* and fully deterministic given a seed, so the
whole thing runs offline and in CI. ``OrderBookFeed`` is the single seam where a
real exchange websocket (e.g. Binance depth + aggTrade) would be plugged in:
feed real ``OrderBookSnapshot`` / ``FlowEvent`` objects and every detector below
works unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from .quant import bayes_posterior, hawkes_intensity

Side = Literal["bid", "ask"]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class OrderBookSnapshot:
    """A single L2 snapshot: price levels and resting sizes for both sides."""
    bid_prices: np.ndarray
    bid_sizes: np.ndarray
    ask_prices: np.ndarray
    ask_sizes: np.ndarray
    ts: float = 0.0

    @property
    def mid(self) -> float:
        return float((self.bid_prices[0] + self.ask_prices[0]) / 2.0)

    @property
    def spread(self) -> float:
        return float(self.ask_prices[0] - self.bid_prices[0])


@dataclass
class FlowEvent:
    """An order-flow event over the observation window."""
    ts: float
    side: Side
    action: Literal["add", "cancel", "trade"]
    size: float
    distance_ticks: float  # distance of the order from mid, in ticks


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def order_book_imbalance(snap: OrderBookSnapshot, depth: int = 5) -> float:
    """Volume imbalance in [-1, 1] over the top ``depth`` levels.

        I = (sum bid_size - sum ask_size) / (sum bid_size + sum ask_size)

    +1 = all resting size on the bid (buy pressure), -1 = all on the ask.
    """
    b = float(snap.bid_sizes[:depth].sum())
    a = float(snap.ask_sizes[:depth].sum())
    total = a + b
    return 0.0 if total == 0 else (b - a) / total


def cancel_trade_ratio(events: list[FlowEvent]) -> float:
    """Ratio of cancelled size to traded size in the window.

    Spoofers post large orders they never intend to fill, so a high ratio of
    cancellations to actual trades is a classic spoofing tell.
    """
    cancelled = sum(e.size for e in events if e.action == "cancel")
    traded = sum(e.size for e in events if e.action == "trade")
    return float(cancelled / traded) if traded > 0 else float(cancelled)


def phantom_liquidity(events: list[FlowEvent], near_ticks: float = 3.0) -> float:
    """Fraction of *added-then-cancelled* size that sat away from the touch.

    Genuine liquidity clusters near the mid; layered spoof walls sit a few ticks
    back so they influence perception without much fill risk. Returns the share
    of cancelled size that was resting beyond ``near_ticks`` from the mid.
    """
    far_cancel = sum(e.size for e in events if e.action == "cancel" and e.distance_ticks > near_ticks)
    all_cancel = sum(e.size for e in events if e.action == "cancel")
    return float(far_cancel / all_cancel) if all_cancel > 0 else 0.0


def cancel_burst_intensity(events: list[FlowEvent], now: float, beta: float = 4.0) -> float:
    """Self-exciting intensity of cancellations (Hawkes) at time ``now``.

    Spoof cancellations arrive in tight bursts when the fake wall is pulled; a
    Hawkes intensity spikes on that clustering far more than a Poisson count
    would. Baseline mu and jump alpha are normalised per unit size.
    """
    cancel_times = [e.ts for e in events if e.action == "cancel"]
    if not cancel_times:
        return 0.0
    return hawkes_intensity(now, cancel_times, mu=0.5, alpha=1.0, beta=beta)


# ---------------------------------------------------------------------------
# Spoofing probability — Bayesian fusion
# ---------------------------------------------------------------------------

@dataclass
class SpoofingReport:
    probability: int                 # 0..100, the "98/100" gauge
    posterior: float                 # P(spoof | evidence) in [0,1]
    imbalance: float
    cancel_trade_ratio: float
    phantom_liquidity: float
    cancel_burst: float
    funding_rate: float
    sentiment: dict[str, float]      # SPOOF / SHEEP / WHALE weights, sum to 1
    label: str                       # human-readable verdict
    pressure_side: str | None = None # side the spoof wall sits on ("bid"/"ask")
    predicted_move: int = 0          # +1 up / -1 down / 0 none — the scalp direction
    features: dict[str, float] = field(default_factory=dict)


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-x))


def spoof_pressure_side(events: list[FlowEvent], near_ticks: float = 3.0) -> str | None:
    """Which side carries the phantom wall — the far, cancelled resting size.

    A spoof wall on the bid fakes demand/support; when it is pulled the price
    tends to fall (predicted move down). A wall on the ask does the reverse.
    Returns None when there is no clear far-cancelled size on either side.
    """
    bid_far = sum(e.size for e in events
                  if e.action == "cancel" and e.side == "bid" and e.distance_ticks > near_ticks)
    ask_far = sum(e.size for e in events
                  if e.action == "cancel" and e.side == "ask" and e.distance_ticks > near_ticks)
    if bid_far == 0 and ask_far == 0:
        return None
    return "bid" if bid_far >= ask_far else "ask"


def spoofing_probability(
    snap: OrderBookSnapshot,
    events: list[FlowEvent],
    funding_rate: float = 0.0,
    prior: float = 0.15,
) -> SpoofingReport:
    """Fuse order-book + flow features into a spoofing probability 0..100.

    A per-feature likelihood ratio feeds Bayes' theorem
    (``P(H|E) = P(E|H)P(H)/P(E)``). Each feature maps to P(E|spoof) vs
    P(E|~spoof) through a logistic response, the independent likelihoods are
    multiplied, and the posterior is turned into the 0..100 gauge.
    """
    imb = order_book_imbalance(snap)
    ctr = cancel_trade_ratio(events)
    phantom = phantom_liquidity(events)
    burst = cancel_burst_intensity(events, now=max((e.ts for e in events), default=0.0) + 1e-6)

    # Feature -> P(evidence | spoof), P(evidence | not spoof).
    # Strong one-sided imbalance, high cancel/trade, far phantom size and
    # bursty cancels all raise the spoof likelihood.
    lik_spoof = 1.0
    lik_norm = 1.0

    def contribute(score: float):
        nonlocal lik_spoof, lik_norm
        p_spoof = _logistic(score)
        lik_spoof *= max(p_spoof, 1e-6)
        lik_norm *= max(1.0 - p_spoof, 1e-6)

    contribute(2.5 * abs(imb) - 1.0)        # lopsided book
    contribute(1.4 * (ctr - 2.0))           # cancels >> trades
    contribute(3.0 * (phantom - 0.5))       # size parked away from touch
    contribute(0.9 * (burst - 2.0))         # bursty cancellations

    evidence = lik_spoof * prior + lik_norm * (1.0 - prior)
    posterior = bayes_posterior(lik_spoof, prior, evidence=evidence)
    probability = int(round(posterior * 100))

    sentiment = _sentiment_triangle(imb, ctr, phantom, snap, events)
    label = (
        "POSSIBLE SPOOFING" if probability >= 70
        else "ELEVATED" if probability >= 40
        else "CLEAN"
    )
    pressure_side = spoof_pressure_side(events)
    # Wall on the bid fakes support -> fade it (expect price down), and vice versa.
    predicted_move = 0 if pressure_side is None else (-1 if pressure_side == "bid" else 1)

    return SpoofingReport(
        probability=probability,
        posterior=float(posterior),
        imbalance=round(imb, 4),
        cancel_trade_ratio=round(ctr, 4),
        phantom_liquidity=round(phantom, 4),
        cancel_burst=round(burst, 4),
        funding_rate=round(funding_rate, 6),
        sentiment=sentiment,
        label=label,
        pressure_side=pressure_side,
        predicted_move=predicted_move,
        features={
            "imbalance": round(imb, 4),
            "cancel_trade_ratio": round(ctr, 4),
            "phantom_liquidity": round(phantom, 4),
            "cancel_burst": round(burst, 4),
        },
    )


def _sentiment_triangle(
    imbalance: float,
    ctr: float,
    phantom: float,
    snap: OrderBookSnapshot,
    events: list[FlowEvent],
) -> dict[str, float]:
    """Three-way market-character weights, normalised to sum to 1.

      * SPOOF — manipulation footprint (cancels, phantom walls)
      * SHEEP — retail/momentum chasing (trades following imbalance)
      * WHALE — large genuine resting size executing patiently
    """
    traded = sum(e.size for e in events if e.action == "trade")
    added = sum(e.size for e in events if e.action == "add")
    top_size = float(snap.bid_sizes[0] + snap.ask_sizes[0])
    avg_size = float((snap.bid_sizes.sum() + snap.ask_sizes.sum()) / (len(snap.bid_sizes) + len(snap.ask_sizes)))

    spoof = 2.0 * phantom + 0.4 * min(ctr, 5.0)
    sheep = 1.2 * abs(imbalance) + 0.6 * (traded / (added + 1e-9))
    whale = 1.5 * (top_size / (avg_size + 1e-9) - 1.0)

    raw = np.array([max(spoof, 0.0), max(sheep, 0.0), max(whale, 0.0)]) + 1e-6
    w = raw / raw.sum()
    return {"SPOOF": round(float(w[0]), 3), "SHEEP": round(float(w[1]), 3), "WHALE": round(float(w[2]), 3)}


# ---------------------------------------------------------------------------
# Simulated order-book feed (deterministic; the real-feed seam)
# ---------------------------------------------------------------------------

# Per-asset market profiles so the radar runs on every instrument in the app,
# each with a realistic price, tick size and default scalp width. ``crypto``
# marks perpetuals that carry a funding rate. Anything not listed falls back to
# DEFAULT_PROFILE, so the engine never fails on an unknown symbol.
# ``fmp`` is the Financial Modeling Prep symbol used to pull real prices/bars for
# that instrument; ``class`` groups the universe (crypto / meme / stable / forex /
# metal / energy / index). Stablecoins are pegged so they carry a tiny scalp width
# and naturally grade NO-TRADE — that is the honest read, not a bug.
MARKET_PROFILES: dict[str, dict] = {
    # majors — crypto
    "btc":    {"mid": 60000.0, "tick": 0.5,     "crypto": True,  "scalp_move_pct": 0.30, "class": "crypto",  "fmp": "BTCUSD"},
    "eth":    {"mid": 3000.0,  "tick": 0.05,    "crypto": True,  "scalp_move_pct": 0.35, "class": "crypto",  "fmp": "ETHUSD"},
    # meme coins
    "doge":   {"mid": 0.15,    "tick": 0.00001, "crypto": True,  "scalp_move_pct": 0.50, "class": "meme",    "fmp": "DOGEUSD"},
    "shib":   {"mid": 2.5e-5,  "tick": 1e-9,    "crypto": True,  "scalp_move_pct": 0.60, "class": "meme",    "fmp": "SHIBUSD"},
    "pepe":   {"mid": 1.2e-5,  "tick": 1e-10,   "crypto": True,  "scalp_move_pct": 0.70, "class": "meme",    "fmp": "PEPEUSD"},
    # stablecoins (pegged — effectively untradable for signals)
    "usdt":   {"mid": 1.0,     "tick": 0.0001,  "crypto": True,  "scalp_move_pct": 0.03, "class": "stable",  "fmp": "USDTUSD"},
    "usdc":   {"mid": 1.0,     "tick": 0.0001,  "crypto": True,  "scalp_move_pct": 0.03, "class": "stable",  "fmp": "USDCUSD"},
    # metals
    "gold":   {"mid": 2400.0,  "tick": 0.1,     "crypto": False, "scalp_move_pct": 0.40, "class": "metal",   "fmp": "GCUSD"},
    "xauusd": {"mid": 2400.0,  "tick": 0.01,    "crypto": False, "scalp_move_pct": 0.40, "class": "metal",   "fmp": "XAUUSD"},
    "silver": {"mid": 30.0,    "tick": 0.005,   "crypto": False, "scalp_move_pct": 0.40, "class": "metal",   "fmp": "SIUSD"},
    "xagusd": {"mid": 30.0,    "tick": 0.001,   "crypto": False, "scalp_move_pct": 0.40, "class": "metal",   "fmp": "XAGUSD"},
    # energy
    "oil":    {"mid": 80.0,    "tick": 0.01,    "crypto": False, "scalp_move_pct": 0.45, "class": "energy",  "fmp": "CLUSD"},
    # forex
    "eurusd": {"mid": 1.08,    "tick": 0.00001, "crypto": False, "scalp_move_pct": 0.10, "class": "forex",   "fmp": "EURUSD"},
    "gbpusd": {"mid": 1.27,    "tick": 0.00001, "crypto": False, "scalp_move_pct": 0.12, "class": "forex",   "fmp": "GBPUSD"},
    "usdjpy": {"mid": 157.0,   "tick": 0.001,   "crypto": False, "scalp_move_pct": 0.12, "class": "forex",   "fmp": "USDJPY"},
    "audusd": {"mid": 0.66,    "tick": 0.00001, "crypto": False, "scalp_move_pct": 0.12, "class": "forex",   "fmp": "AUDUSD"},
    # indices
    "sp500":  {"mid": 5500.0,  "tick": 0.25,    "crypto": False, "scalp_move_pct": 0.25, "class": "index",   "fmp": "^GSPC"},
    "nasdaq": {"mid": 19000.0, "tick": 0.25,    "crypto": False, "scalp_move_pct": 0.30, "class": "index",   "fmp": "^IXIC"},
}
DEFAULT_PROFILE = {"mid": 100.0, "tick": 0.01, "crypto": False, "scalp_move_pct": 0.30,
                   "class": "other", "fmp": None}


def market_profile(asset: str) -> dict:
    """Look up an asset's market profile, falling back to a safe default."""
    return MARKET_PROFILES.get(asset.lower(), DEFAULT_PROFILE)


# ---------------------------------------------------------------------------
# Signal grading — A+ / A1 / A / B / C / D / F
# ---------------------------------------------------------------------------
# A grade fuses two independent things a trader actually cares about:
#   * conviction  — how strongly the radar thinks this is real manipulation
#                   (the 0..100 spoof probability), and
#   * tradability — whether the asset's scalp geometry keeps the edge after
#                   leverage & fees. A tight-scalp instrument (FX majors) needs
#                   huge leverage, so its fee drag guts even a high-conviction
#                   signal — the "gold at 0.2%" lesson, generalised.
# Ladder (highest first): A+ elite, A1 excellent, A strong, B good, C fair,
# D weak, F avoid. "NO-TRADE" is returned when there is no actionable signal.

_GRADE_BANDS: list[tuple[float, str]] = [
    (86.0, "A+"), (74.0, "A1"), (62.0, "A"), (48.0, "B"),
    (34.0, "C"), (20.0, "D"), (0.0, "F"),
]


def _letter(score: float) -> str:
    for threshold, grade in _GRADE_BANDS:
        if score >= threshold:
            return grade
    return "F"


def tradability_score(asset: str, risk: float = 0.05, fee_bps: float = 6.0,
                      max_leverage: float = 50.0) -> float:
    """0..100 structural score: how much of an edge survives this asset's fees.

    Leverage needed = risk / scalp_move, the round-trip fee is charged on that
    leveraged notional, and the score falls linearly with the resulting per-trade
    cost. Wide-scalp markets (low leverage) score high; tight FX majors score low.
    """
    move = market_profile(asset)["scalp_move_pct"] / 100.0
    lev = min(risk / move, max_leverage)
    cost_pct = (fee_bps / 1e4) * lev * 100.0
    return float(max(0.0, min(100.0, 100.0 - cost_pct * 38.0)))


def grade_signal(
    probability: int,
    asset: str,
    predicted_move: int,
    funding_rate: float = 0.0,
    min_conviction: int = 40,
) -> dict:
    """Grade one setup A+..F from detection conviction and asset tradability.

    Returns ``NO-TRADE`` when the radar sees no actionable manipulation
    (probability below ``min_conviction`` or no inferred direction) — a clean
    book is not a trade, however liquid the instrument.
    """
    trad = tradability_score(asset)
    if predicted_move == 0 or probability < min_conviction:
        return {
            "grade": "NO-TRADE",
            "score": 0.0,
            "conviction": int(probability),
            "tradability": round(trad, 1),
            "note": "no actionable manipulation signal",
        }
    # Tradability gates conviction: a strong signal on an un-tradable book is
    # capped, because the fees will eat the move.
    funding_penalty = min(abs(funding_rate) * 800.0, 8.0)
    score = probability * (0.45 + 0.55 * trad / 100.0) - funding_penalty
    score = float(max(0.0, min(100.0, score)))
    return {
        "grade": _letter(score),
        "score": round(score, 1),
        "conviction": int(probability),
        "tradability": round(trad, 1),
    }


_GRADE_RANK = {"A+": 6, "A1": 5, "A": 4, "B": 3, "C": 2, "D": 1, "F": 0, "NO-TRADE": -1}


def grade_rank(grade: str) -> int:
    """Numeric rank of a letter grade (higher is better); unknown -> -1."""
    return _GRADE_RANK.get(grade, -1)


def build_trade_plan(
    asset: str,
    mid: float,
    direction: str,
    payoff: float = 1.5,
    risk_per_trade: float = 0.05,
    trail_activate_r: float = 1.0,
    trail_distance_r: float = 0.5,
) -> dict:
    """Concrete entry / stop-loss / take-profit levels for a graded signal.

    The stop sits one scalp-move from entry (``scalp_move_pct`` of price); the
    fixed take-profit is ``payoff`` times that distance (the reward:risk ratio).
    A trailing take-profit is also given: it arms once price is ``trail_activate_r``
    R in profit and then trails ``trail_distance_r`` R behind the peak, so a runner
    keeps giving while a reversal still locks in profit. ``direction`` is
    "long" or "short"; leverage is implied by the scalp tightness.
    """
    move = market_profile(asset)["scalp_move_pct"] / 100.0
    r = move * mid                       # 1R in price terms
    lev = min(risk_per_trade / move, 50.0)
    if direction == "long":
        stop_loss = mid - r
        take_profit = mid + payoff * r
        trail_arm = mid + trail_activate_r * r
        sl_pct, tp_pct = -move, payoff * move
    elif direction == "short":
        stop_loss = mid + r
        take_profit = mid - payoff * r
        trail_arm = mid - trail_activate_r * r
        sl_pct, tp_pct = -move, payoff * move
    else:
        return {"direction": "flat", "note": "no directional signal — no trade plan"}

    def _round(x: float) -> float:
        # round to a sensible number of decimals for the asset's price scale
        digits = 6 if mid < 10 else 4 if mid < 100 else 2
        return round(float(x), digits)

    return {
        "direction": direction,
        "entry": _round(mid),
        "stop_loss": _round(stop_loss),
        "take_profit": _round(take_profit),
        "risk_reward": round(payoff, 2),
        "stop_pct": round(sl_pct * 100, 3),
        "take_profit_pct": round(tp_pct * 100, 3),
        "implied_leverage": round(lev, 2),
        "trailing_tp": {
            "arms_at": _round(trail_arm),
            "arms_at_r": trail_activate_r,
            "trail_distance_pct": round(trail_distance_r * move * 100, 3),
            "note": f"arm at +{trail_activate_r}R, then trail {trail_distance_r}R behind the peak",
        },
    }


def estimate_signals_per_day(
    asset: str = "btc",
    scan_interval_sec: float = 30.0,
    spoof_base_rate: float = 0.05,
    min_grade: str = "B",
    n: int = 8000,
    seed: int = 0,
) -> dict:
    """Estimate how many gradeable signals a day the radar would fire.

    Assumptions (all tunable — this is a projection, not live data):
      * the radar evaluates a fresh order-book window every ``scan_interval_sec``;
      * ``spoof_base_rate`` of windows contain genuine manipulation.
    It runs the detector + grader over ``n`` simulated windows, counts how many
    clear ``min_grade``, and scales by windows-per-day. Also breaks the count out
    by grade tier so you can see how many A+/A1 setups vs marginal ones to expect.
    """
    feed = OrderBookFeed.for_asset(asset, seed=seed)
    rng = np.random.default_rng(seed)
    by_grade = {"A+": 0, "A1": 0, "A": 0, "B": 0, "C": 0, "D": 0, "F": 0, "NO-TRADE": 0}
    fired = true_fire = false_fire = 0
    threshold = _GRADE_RANK.get(min_grade, 3)
    for _ in range(n):
        is_spoof = rng.random() < spoof_base_rate
        side: Side = "bid" if rng.random() < 0.5 else "ask"
        strength = float(rng.uniform(0.2, 1.0)) if is_spoof else None
        snap, events = feed.sample(spoof=is_spoof, side=side, strength=strength)
        r = spoofing_probability(snap, events, funding_rate=feed.funding_rate())
        g = grade_signal(r.probability, asset, r.predicted_move, r.funding_rate)
        by_grade[g["grade"]] += 1
        if _GRADE_RANK[g["grade"]] >= threshold:
            fired += 1
            if is_spoof:
                true_fire += 1
            else:
                false_fire += 1
    windows_per_day = 86400.0 / scan_interval_sec
    scale = windows_per_day / n
    per_day = {k: round(v * scale, 1) for k, v in by_grade.items()}
    precision = (true_fire / fired) if fired else 0.0
    return {
        "asset": asset.lower(),
        "scan_interval_sec": scan_interval_sec,
        "windows_per_day": int(windows_per_day),
        "spoof_base_rate": spoof_base_rate,
        "min_grade": min_grade,
        "fire_rate": round(fired / n, 4),
        "signals_per_day": round(fired * scale, 1),           # every fire, incl. false alarms
        "real_signals_per_day": round(true_fire * scale, 1),  # fires on genuine manipulation
        "false_alarms_per_day": round(false_fire * scale, 1),
        "precision": round(precision, 3),                     # share of fires that are real
        "by_grade_per_day": per_day,
    }


class OrderBookFeed:
    """Deterministic synthetic order book + flow generator.

    Produces a benign book most of the time and, when ``spoof`` is requested,
    layers a large phantom wall a few ticks from the mid and pulls it in a burst
    of cancellations — the exact behaviour the detector is meant to catch.

    Swap this class for a real exchange adapter that yields the same
    ``OrderBookSnapshot`` / ``FlowEvent`` objects and nothing downstream changes.
    """

    def __init__(self, mid: float = 30000.0, tick: float = 1.0, seed: int = 0,
                 asset: str | None = None, crypto: bool = True):
        self.mid = mid
        self.tick = tick
        self.asset = asset
        self.crypto = crypto
        self.rng = np.random.default_rng(seed)

    @classmethod
    def for_asset(cls, asset: str, seed: int = 0) -> "OrderBookFeed":
        """Build a feed configured for a specific instrument's price/tick."""
        p = market_profile(asset)
        return cls(mid=p["mid"], tick=p["tick"], seed=seed, asset=asset.lower(),
                   crypto=p["crypto"])

    def _base_book(self, mid: float, levels: int = 10) -> OrderBookSnapshot:
        bid_prices = mid - self.tick * (np.arange(levels) + 1)
        ask_prices = mid + self.tick * (np.arange(levels) + 1)
        # Genuine liquidity decays with distance from the touch.
        decay = np.exp(-0.15 * np.arange(levels))
        bid_sizes = self.rng.uniform(0.8, 1.2, levels) * 5.0 * decay
        ask_sizes = self.rng.uniform(0.8, 1.2, levels) * 5.0 * decay
        return OrderBookSnapshot(bid_prices, bid_sizes, ask_prices, ask_sizes, ts=0.0)

    def sample(
        self,
        spoof: bool,
        side: Side = "bid",
        strength: float | None = None,
    ) -> tuple[OrderBookSnapshot, list[FlowEvent]]:
        """Return one (snapshot, window-of-flow-events) pair.

        ``strength`` in [0, 1] controls how blatant a spoof is: weak spoofs use
        a smaller wall parked closer to the touch and pulled less abruptly, so
        their footprint overlaps with honest activity. When ``strength`` is None
        it is drawn uniformly, which is what makes the backtest a genuine test
        rather than a trivially separable one.
        """
        if strength is None:
            strength = float(self.rng.uniform(0.25, 1.0))
        snap = self._base_book(self.mid)
        events: list[FlowEvent] = []
        t = 0.0

        # Benign background flow: adds and trades near the touch.
        n_bg = int(self.rng.integers(8, 16))
        for _ in range(n_bg):
            t += float(self.rng.exponential(0.4))
            s: Side = "bid" if self.rng.random() < 0.5 else "ask"
            action = "trade" if self.rng.random() < 0.6 else "add"
            events.append(FlowEvent(t, s, action, float(self.rng.uniform(0.2, 1.0)),
                                    float(self.rng.uniform(0.0, 2.0))))

        if spoof:
            # Weak spoofs sit closer to the touch (2 ticks) with a smaller wall
            # and a looser cancel burst; strong spoofs sit ~5 ticks back with a
            # big wall pulled tightly.
            wall_level = int(round(2 + 3 * strength))
            wall_size = float(self.rng.uniform(8.0, 20.0) + 45.0 * strength)
            if side == "bid":
                snap.bid_sizes[wall_level] += wall_size
            else:
                snap.ask_sizes[wall_level] += wall_size
            events.append(FlowEvent(t + 0.05, side, "add", wall_size, float(wall_level + 1)))
            burst_t = t + float(self.rng.uniform(0.3, 0.8))
            n_cancel = int(self.rng.integers(3, 8))
            burst_scale = 0.05 + 0.25 * (1.0 - strength)  # weaker spoof = looser burst
            for _ in range(n_cancel):
                burst_t += float(self.rng.exponential(burst_scale))
                events.append(FlowEvent(burst_t, side, "cancel",
                                        wall_size / n_cancel, float(wall_level + 1)))
        else:
            # Honest cancellations near the touch.
            n_honest = int(self.rng.integers(0, 4))
            for _ in range(n_honest):
                t += float(self.rng.exponential(0.5))
                events.append(FlowEvent(t, "bid" if self.rng.random() < 0.5 else "ask",
                                        "cancel", float(self.rng.uniform(0.3, 1.5)),
                                        float(self.rng.uniform(0.0, 3.5))))
            # ~18% of clean windows are legitimate market-maker *repricing*: a
            # genuine order posted a few ticks back then cancelled in a burst as
            # the quote is chased. It looks spoof-like (far cancels, bursty) and
            # is the main source of realistic false positives.
            if self.rng.random() < 0.18:
                level = int(self.rng.integers(2, 5))
                size = float(self.rng.uniform(6.0, 18.0))
                s2: Side = "bid" if self.rng.random() < 0.5 else "ask"
                if s2 == "bid":
                    snap.bid_sizes[level] += size
                else:
                    snap.ask_sizes[level] += size
                events.append(FlowEvent(t + 0.1, s2, "add", size, float(level + 1)))
                bt = t + float(self.rng.uniform(0.4, 1.0))
                nc = int(self.rng.integers(2, 5))
                for _ in range(nc):
                    bt += float(self.rng.exponential(0.15))
                    events.append(FlowEvent(bt, s2, "cancel", size / nc, float(level + 1)))

        events.sort(key=lambda e: e.ts)
        return snap, events

    def funding_rate(self) -> float:
        """Synthetic 8h perpetual funding rate. Only crypto perps have funding."""
        if not self.crypto:
            return 0.0
        return float(self.rng.normal(0.0001, 0.0003))


def scan_assets(
    assets: list[str] | None = None,
    seed: int = 0,
    spoof: bool | None = None,
) -> list[dict]:
    """Run the spoofing radar across every requested asset and rank by risk.

    Each asset gets its own profile-configured feed, so the scan works uniformly
    for crypto, metals, FX and indices. Returns one compact report per asset,
    sorted by spoofing probability (highest first) — the "watchlist" view.
    """
    if assets is None:
        assets = list(MARKET_PROFILES.keys())
    reports: list[dict] = []
    for i, asset in enumerate(assets):
        feed = OrderBookFeed.for_asset(asset, seed=seed + i)
        is_spoof = (feed.rng.random() < 0.4) if spoof is None else spoof
        side: Side = "bid" if feed.rng.random() < 0.5 else "ask"
        snap, events = feed.sample(spoof=is_spoof, side=side)
        r = spoofing_probability(snap, events, funding_rate=feed.funding_rate())
        grade = grade_signal(r.probability, asset, r.predicted_move, r.funding_rate)
        direction = "long" if r.predicted_move > 0 else "short" if r.predicted_move < 0 else "flat"
        trade_plan = (
            build_trade_plan(asset, snap.mid, direction)
            if grade["grade"] != "NO-TRADE" and direction != "flat" else None
        )
        reports.append({
            "asset": asset.lower(),
            "grade": grade["grade"],
            "score": grade["score"],
            "conviction": grade["conviction"],
            "tradability": grade["tradability"],
            "probability": r.probability,
            "label": r.label,
            "pressure_side": r.pressure_side,
            "predicted_move": r.predicted_move,
            "direction": direction,
            "trade_plan": trade_plan,
            "funding_rate": r.funding_rate,
            "sentiment": r.sentiment,
            "mid": round(snap.mid, 6),
        })
    # Rank actionable, higher-graded setups first; NO-TRADE rows sink to the bottom.
    reports.sort(key=lambda d: (d["grade"] != "NO-TRADE", d["score"]), reverse=True)
    return reports
