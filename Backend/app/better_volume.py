"""
Better Volume — the Whale engine's 7-buffer bar classifier (MT4 BetterVolume 1.4
spec), ported to run on any OHLCV. Volume in = tick volume (MT4/MT5) or real
volume (Binance); the classifier treats both the same, as the indicator was
designed for tick volume.

Buffers: 0 Red (climax up) · 1 White (climax down) · 2 Yellow (low vol, filter
only) · 3 Green (churn/absorption) · 4 Magenta (climax churn) · 5 Neutral.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_COLORS = {0: "Red", 1: "White", 2: "Yellow", 3: "Green", 4: "Magenta", 5: "Neutral"}


@dataclass
class BVResult:
    buffer: int
    color: str
    direction: str        # BUY / SELL / NONE
    grade: str            # A+/A1/A/B/... (confidence from the setup)
    story: str
    volume_ratio: float
    range_ratio: float


def classify(highs, lows, closes, volumes, opens=None, lookback: int = 20) -> BVResult:
    """Classify the latest bar and derive a Better Volume signal."""
    highs, lows, closes, volumes = map(lambda a: np.asarray(a, float), (highs, lows, closes, volumes))
    n = len(closes)
    if n < lookback + 2:
        return BVResult(5, "Neutral", "NONE", "-", "insufficient bars", 1.0, 1.0)
    opens = np.asarray(opens, float) if opens is not None else np.concatenate([[closes[0]], closes[:-1]])

    rng = max(highs[-1] - lows[-1], 1e-9)
    body = abs(closes[-1] - opens[-1])
    body_ratio = body / rng
    up = closes[-1] > opens[-1]

    avg_vol = volumes[-lookback - 1:-1].mean() or 1.0
    avg_rng = np.maximum(highs[-lookback - 1:-1] - lows[-lookback - 1:-1], 1e-9).mean()
    vr = volumes[-1] / max(avg_vol, 1e-9)
    rr = rng / max(avg_rng, 1e-9)
    churn_score = vr / max(rr, 0.20)

    high_vol, very_high, low_vol = vr >= 1.5, vr >= 2.0, vr <= 0.65
    wide, narrow = rr >= 1.35, rr <= 0.85
    churn = high_vol and (narrow or body_ratio <= 0.42 or churn_score >= 1.80)

    if very_high and wide and churn:
        buf = 4
    elif low_vol:
        buf = 2
    elif churn:
        buf = 3
    elif high_vol and wide and up:
        buf = 0
    elif high_vol and wide and not up:
        buf = 1
    else:
        buf = 5

    # ── derive a directional signal from the buffer (whale rulebook) ──
    direction, grade, story = "NONE", "-", _COLORS[buf]
    if buf == 3:  # Green churn / absorption → trade with the close
        direction = "BUY" if up else "SELL"
        grade = "A" if churn_score >= 2.0 else "A1"
        story = "Green churn — smart-money absorption; go with the close on break+retest."
    elif buf == 0:  # Red climax up → exhaustion risk; fade only if rejected
        direction = "SELL" if body_ratio < 0.5 else "BUY"
        grade = "A1" if body_ratio < 0.5 else "A"
        story = "Red climax up — exhaustion if rejected below body, else continuation."
    elif buf == 1:  # White climax down → pressure/stopping clue
        direction = "BUY" if body_ratio < 0.5 else "SELL"
        grade = "A"
        story = "White climax down — stopping volume; watch for a turn."
    elif buf == 4:  # Magenta climax churn → strong fight, needs confluence
        direction = "BUY" if up else "SELL"
        grade = "A+"
        story = "Magenta climax churn — major smart-money fight; use only with confluence."
    elif buf == 2:
        story = "Yellow low volume — filter only, do not enter alone."

    return BVResult(buf, _COLORS[buf], direction, grade, story, round(float(vr), 2), round(float(rr), 2))
