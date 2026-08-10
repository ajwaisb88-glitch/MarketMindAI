"""Separated 60 Agents engine for XAUUSD Monster Outlook.

Agent groups:
- 20 Momentum agents: follow short/medium thrust and structure breaks.
- 20 Reverter agents: detect stretch/exhaustion and mean reversion risk.
- 10 Noise agents: detect chop/unclean market and reduce confidence.
- 10 Whale agents: read volume/body/wick/sweep behavior.

This file is intentionally independent from Elliott Wave, Better Volume and cTrader.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import tanh, sqrt, isfinite
from typing import Any

try:
    import polars as pl
except Exception:  # pragma: no cover - keeps module importable in docs/builds
    pl = None  # type: ignore


@dataclass(slots=True)
class AgentVote:
    name: str
    group: str
    sentiment: float   # -1 sell ... +1 buy
    confidence: float  # 0 weak ... 1 strong
    reason: str


class SixtyAgentsEngine:
    """Deterministic 60-agent sentiment engine.

    Output is a dictionary so Flask JSON can return it directly.
    """

    def __init__(self) -> None:
        self.momentum_count = 20
        self.reverter_count = 20
        self.noise_count = 10
        self.whale_count = 10

    def analyze(self, df: Any, symbol: str = "XAUUSD", timeframe: str = "5min") -> dict[str, Any]:
        rows = _rows(df)
        if len(rows) < 30:
            return {
                "status": "not_enough_data",
                "symbol": symbol,
                "timeframe": timeframe,
                "score": 0.0,
                "bias": "WAIT",
                "confidence": 0,
                "summary": "Need at least 30 candles for 60 Agents engine.",
                "groups": {},
                "agents": [],
            }

        metrics = _metrics(rows)
        votes: list[AgentVote] = []
        votes.extend(self._momentum_agents(metrics))
        votes.extend(self._reverter_agents(metrics))
        votes.extend(self._noise_agents(metrics))
        votes.extend(self._whale_agents(metrics))

        # Confidence-weighted score. Noise agents vote against trading confidence by design.
        weighted = sum(v.sentiment * max(v.confidence, 0.0) for v in votes)
        weights = sum(max(v.confidence, 0.0) for v in votes) or 1.0
        score = max(-1.0, min(1.0, weighted / weights))

        buy_votes = sum(1 for v in votes if v.sentiment > 0.12)
        sell_votes = sum(1 for v in votes if v.sentiment < -0.12)
        wait_votes = len(votes) - buy_votes - sell_votes
        alignment = max(buy_votes, sell_votes) / max(len(votes), 1)
        confidence = int(round(min(100.0, (abs(score) * 70.0) + (alignment * 30.0))))

        if score >= 0.20 and confidence >= 48:
            bias = "BUY"
        elif score <= -0.20 and confidence >= 48:
            bias = "SELL"
        else:
            bias = "WAIT"

        groups = _group_summary(votes)
        return {
            "status": "ok",
            "symbol": symbol,
            "timeframe": timeframe,
            "score": round(score, 3),
            "bias": bias,
            "confidence": confidence,
            "votes": {"buy": buy_votes, "sell": sell_votes, "wait": wait_votes, "total": len(votes)},
            "groups": groups,
            "summary": _summary_text(bias, score, confidence, groups),
            "agents": [{"name": v.name, "group": v.group, "sentiment": v.sentiment, "confidence": v.confidence, "reason": v.reason} for v in votes],
            "metrics": {k: _round(v) for k, v in metrics.items() if isinstance(v, (int, float)) and isfinite(float(v))},
        }

    def _momentum_agents(self, m: dict[str, float]) -> list[AgentVote]:
        votes: list[AgentVote] = []
        configs = [
            ("M01", "5-candle thrust", m["roc_5"] / max(m["atr"], 0.01)),
            ("M02", "10-candle thrust", m["roc_10"] / max(m["atr"], 0.01)),
            ("M03", "20-candle thrust", m["roc_20"] / max(m["atr"], 0.01)),
            ("M04", "EMA fast/slow slope", m["ema_diff"] / max(m["atr"], 0.01)),
            ("M05", "close near high/low", (m["close_location"] - 0.5) * 2.0),
            ("M06", "breakout pressure", m["breakout_score"]),
            ("M07", "higher close sequence", m["close_sequence"]),
            ("M08", "range expansion direction", m["range_expansion"] * m["candle_direction"]),
            ("M09", "body pressure", m["body_pressure"]),
            ("M10", "ATR trend impulse", m["atr_impulse"]),
        ]
        # Duplicate the logic family with slightly lower confidence to make 20 distinct agents.
        configs = configs + [(name.replace("M0", "M1") if name.startswith("M0") else name + "b", reason + " secondary", val * 0.85) for name, reason, val in configs]
        for idx, (name, reason, raw) in enumerate(configs[:20], start=1):
            sentiment = tanh(raw / 1.75)
            conf = min(1.0, 0.35 + abs(sentiment) * 0.55 + m["trend_quality"] * 0.10)
            votes.append(AgentVote(name=f"M{idx:02d}", group="Momentum", sentiment=round(sentiment, 3), confidence=round(conf, 3), reason=reason))
        return votes

    def _reverter_agents(self, m: dict[str, float]) -> list[AgentVote]:
        votes: list[AgentVote] = []
        stretch = m["z_close"]
        wick_reversal = m["lower_wick_ratio"] - m["upper_wick_ratio"]
        configs = [
            ("R01", "price stretched from mean", -stretch),
            ("R02", "distance from rolling mid", -m["dist_mid"]),
            ("R03", "upper/lower wick reversal", wick_reversal * 2.0),
            ("R04", "exhaustion after 5 candles", -m["roc_5"] / max(m["atr"], 0.01) if abs(m["roc_5"]) > m["atr"] else 0.0),
            ("R05", "failed follow-through", -m["failed_follow"]),
            ("R06", "overextended close location", -(m["close_location"] - 0.5) * 1.5 if abs(stretch) > 0.8 else 0.0),
            ("R07", "volume exhaustion", -m["candle_direction"] * max(m["volume_ratio"] - 1.2, 0.0)),
            ("R08", "range exhaustion", -m["candle_direction"] * max(m["range_ratio"] - 1.2, 0.0)),
            ("R09", "mean magnet", -m["ema_diff"] / max(m["atr"], 0.01) * 0.7),
            ("R10", "opposite wick pressure", wick_reversal),
        ]
        configs = configs + [(name + "b", reason + " secondary", val * 0.80) for name, reason, val in configs]
        for idx, (_, reason, raw) in enumerate(configs[:20], start=1):
            sentiment = tanh(raw / 2.0)
            conf = min(1.0, 0.30 + abs(sentiment) * 0.60 + max(m["volume_ratio"] - 1.0, 0.0) * 0.06)
            votes.append(AgentVote(name=f"R{idx:02d}", group="Reverter", sentiment=round(sentiment, 3), confidence=round(conf, 3), reason=reason))
        return votes

    def _noise_agents(self, m: dict[str, float]) -> list[AgentVote]:
        votes: list[AgentVote] = []
        chop = m["chop_score"]
        # Noise agents intentionally reduce conviction. They vote close to zero or opposite of weak thrust.
        base_against = -m["candle_direction"] * chop * 0.25
        configs = [
            "inside/range chop", "small candle body", "low ATR impulse", "mixed closes", "low volume",
            "mid-range close", "overlapping candles", "no clean breakout", "flat EMA", "weak structure",
        ]
        for idx, reason in enumerate(configs, start=1):
            sentiment = tanh(base_against / 1.5)
            conf = min(0.85, 0.20 + chop * 0.65)
            votes.append(AgentVote(name=f"N{idx:02d}", group="Noise", sentiment=round(sentiment, 3), confidence=round(conf, 3), reason=reason))
        return votes

    def _whale_agents(self, m: dict[str, float]) -> list[AgentVote]:
        votes: list[AgentVote] = []
        whale_abs_buy = m["absorption_buy"]
        whale_dist_sell = m["distribution_sell"]
        raw_whale = whale_abs_buy - whale_dist_sell
        configs = [
            ("W01", "absorption buy pressure", whale_abs_buy),
            ("W02", "distribution sell pressure", -whale_dist_sell),
            ("W03", "high volume close location", (m["close_location"] - 0.5) * 2.0 * m["volume_ratio"]),
            ("W04", "body/result versus effort", m["effort_result"]),
            ("W05", "sweep and rejection", m["sweep_rejection"]),
            ("W06", "climax candle direction", m["climax_direction"]),
            ("W07", "wick absorption", m["wick_absorption"]),
            ("W08", "volume thrust", m["volume_thrust"]),
            ("W09", "smart money balance", raw_whale),
            ("W10", "session handover impulse", m["session_impulse"]),
        ]
        for idx, (_, reason, raw) in enumerate(configs, start=1):
            sentiment = tanh(raw / 1.7)
            conf = min(1.0, 0.40 + abs(sentiment) * 0.45 + max(m["volume_ratio"] - 1.0, 0.0) * 0.08)
            votes.append(AgentVote(name=f"W{idx:02d}", group="Whale", sentiment=round(sentiment, 3), confidence=round(conf, 3), reason=reason))
        return votes


def _rows(df: Any) -> list[dict[str, Any]]:
    if df is None:
        return []
    try:
        if hasattr(df, "to_dicts"):
            return df.select(["open", "high", "low", "close", "volume"]).to_dicts()
    except Exception:
        try:
            return df.to_dicts()
        except Exception:
            return []
    if isinstance(df, list):
        return [r for r in df if isinstance(r, dict)]
    return []


def _metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    closes = [_f(r.get("close")) for r in rows]
    opens = [_f(r.get("open")) for r in rows]
    highs = [_f(r.get("high")) for r in rows]
    lows = [_f(r.get("low")) for r in rows]
    vols = [_f(r.get("volume")) for r in rows]

    last_close, last_open, last_high, last_low = closes[-1], opens[-1], highs[-1], lows[-1]
    ranges = [max(h - l, 0.0001) for h, l in zip(highs, lows)]
    bodies = [abs(c - o) for c, o in zip(closes, opens)]
    atr = _atr(highs, lows, closes, 14)
    ma20 = _mean(closes[-20:])
    sd20 = _std(closes[-20:]) or 0.0001
    ema_fast = _ema(closes[-10:], 8)
    ema_slow = _ema(closes[-30:], 21)
    vol20 = _mean(vols[-20:]) or 1.0
    range20 = _mean(ranges[-20:]) or 0.0001

    body = abs(last_close - last_open)
    candle_dir = 1.0 if last_close > last_open else -1.0 if last_close < last_open else 0.0
    upper_wick = max(last_high - max(last_close, last_open), 0.0)
    lower_wick = max(min(last_close, last_open) - last_low, 0.0)
    rng = max(last_high - last_low, 0.0001)
    close_location = (last_close - last_low) / rng

    recent_high = max(highs[-20:-1])
    recent_low = min(lows[-20:-1])
    breakout_score = 0.0
    if last_close > recent_high:
        breakout_score = min(2.0, (last_close - recent_high) / max(atr, 0.01))
    elif last_close < recent_low:
        breakout_score = -min(2.0, (recent_low - last_close) / max(atr, 0.01))

    close_sequence = sum(1 for i in range(-5, 0) if closes[i] > closes[i - 1]) - sum(1 for i in range(-5, 0) if closes[i] < closes[i - 1])
    close_sequence /= 5.0

    volume_ratio = vols[-1] / max(vol20, 1.0)
    range_ratio = ranges[-1] / max(range20, 0.0001)
    body_ratio = body / rng
    body_pressure = candle_dir * body_ratio * 2.0
    trend_quality = abs(ema_fast - ema_slow) / max(atr, 0.01)
    trend_quality = min(1.0, trend_quality)
    chop_score = 1.0 - min(1.0, (abs(ema_fast - ema_slow) + abs(closes[-1] - closes[-10])) / max(atr * 3.0, 0.01))

    # Better volume style whale proxies.
    absorption_buy = 0.0
    distribution_sell = 0.0
    if volume_ratio >= 1.5 and body_ratio <= 0.45:
        if close_location >= 0.60:
            absorption_buy = min(2.0, volume_ratio * (close_location + lower_wick / rng))
        if close_location <= 0.40:
            distribution_sell = min(2.0, volume_ratio * ((1.0 - close_location) + upper_wick / rng))

    sweep_rejection = 0.0
    if len(rows) >= 3:
        prev_high = highs[-3]
        prev_low = lows[-3]
        sweep_high = highs[-2] > prev_high and closes[-2] < prev_high and closes[-1] < closes[-2]
        sweep_low = lows[-2] < prev_low and closes[-2] > prev_low and closes[-1] > closes[-2]
        sweep_rejection = -1.5 if sweep_high else 1.5 if sweep_low else 0.0

    return {
        "last_close": last_close,
        "atr": atr,
        "roc_5": closes[-1] - closes[-6],
        "roc_10": closes[-1] - closes[-11],
        "roc_20": closes[-1] - closes[-21],
        "ema_diff": ema_fast - ema_slow,
        "close_location": close_location,
        "breakout_score": breakout_score,
        "close_sequence": close_sequence,
        "range_expansion": min(2.0, range_ratio - 1.0),
        "candle_direction": candle_dir,
        "body_pressure": body_pressure,
        "atr_impulse": (closes[-1] - closes[-4]) / max(atr, 0.01),
        "z_close": (last_close - ma20) / sd20,
        "dist_mid": (last_close - ma20) / max(atr, 0.01),
        "upper_wick_ratio": upper_wick / rng,
        "lower_wick_ratio": lower_wick / rng,
        "failed_follow": _failed_follow(highs, lows, closes),
        "volume_ratio": volume_ratio,
        "range_ratio": range_ratio,
        "trend_quality": trend_quality,
        "chop_score": max(0.0, min(1.0, chop_score)),
        "absorption_buy": absorption_buy,
        "distribution_sell": distribution_sell,
        "effort_result": candle_dir * (volume_ratio - max(body_ratio, 0.05)),
        "sweep_rejection": sweep_rejection,
        "climax_direction": candle_dir * max(volume_ratio - 1.8, 0.0) * max(range_ratio - 1.1, 0.0),
        "wick_absorption": (lower_wick - upper_wick) / rng * max(volume_ratio - 1.0, 0.0),
        "volume_thrust": candle_dir * max(volume_ratio - 1.0, 0.0),
        "session_impulse": (closes[-1] - closes[-13]) / max(atr * sqrt(12), 0.01) if len(closes) > 13 else 0.0,
    }


def _failed_follow(highs: list[float], lows: list[float], closes: list[float]) -> float:
    if len(closes) < 4:
        return 0.0
    prev_break_high = highs[-2] > max(highs[-8:-2]) if len(highs) >= 8 else highs[-2] > highs[-3]
    prev_break_low = lows[-2] < min(lows[-8:-2]) if len(lows) >= 8 else lows[-2] < lows[-3]
    if prev_break_high and closes[-1] < closes[-2]:
        return -1.0
    if prev_break_low and closes[-1] > closes[-2]:
        return 1.0
    return 0.0


def _group_summary(votes: list[AgentVote]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for group in ("Momentum", "Reverter", "Noise", "Whale"):
        g = [v for v in votes if v.group == group]
        weights = sum(v.confidence for v in g) or 1.0
        score = sum(v.sentiment * v.confidence for v in g) / weights
        buy = sum(1 for v in g if v.sentiment > 0.12)
        sell = sum(1 for v in g if v.sentiment < -0.12)
        wait = len(g) - buy - sell
        out[group.lower()] = {
            "score": round(max(-1.0, min(1.0, score)), 3),
            "bias": "BUY" if score > 0.15 else "SELL" if score < -0.15 else "WAIT",
            "confidence": int(round(min(100, abs(score) * 100))),
            "votes": {"buy": buy, "sell": sell, "wait": wait, "total": len(g)},
        }
    return out


def _summary_text(bias: str, score: float, confidence: int, groups: dict[str, dict[str, Any]]) -> str:
    mom = groups.get("momentum", {}).get("bias", "WAIT")
    rev = groups.get("reverter", {}).get("bias", "WAIT")
    whale = groups.get("whale", {}).get("bias", "WAIT")
    noise = groups.get("noise", {}).get("confidence", 0)
    if bias == "WAIT":
        return f"WAIT: 60 Agents not aligned. Momentum={mom}, Reverter={rev}, Whale={whale}, Noise risk={noise}%."
    return f"{bias}: 60 Agents score {score:+.2f}, confidence {confidence}%. Momentum={mom}, Reverter={rev}, Whale={whale}."


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    trs: list[float] = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    recent = trs[-period:] if trs else [1.5]
    return _mean(recent) or 1.5


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    ema = values[0]
    for value in values[1:]:
        ema = alpha * value + (1.0 - alpha) * ema
    return ema


def _mean(values: list[float]) -> float:
    values = [v for v in values if isfinite(float(v))]
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if not values:
        return 0.0
    mu = _mean(values)
    return sqrt(sum((v - mu) ** 2 for v in values) / max(len(values), 1))


def _f(value: Any, default: float = 0.0) -> float:
    try:
        val = float(value)
        return val if isfinite(val) else default
    except Exception:
        return default


def _round(value: float) -> float:
    try:
        return round(float(value), 4)
    except Exception:
        return 0.0
