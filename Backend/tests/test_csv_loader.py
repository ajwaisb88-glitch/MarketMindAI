"""Tests for the OHLC CSV loader."""

import os

import numpy as np
import pytest

from app import csv_loader, strategies

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SAMPLE = os.path.join(DATA_DIR, "sample_xauusd_daily.csv")


def test_investing_format_with_bom_and_commas():
    text = (
        '﻿"Date","Price","Open","High","Low","Vol.","Change %"\n'
        '"07/22/2026","4,166.10","4,081.17","4,166.10","4,076.98","","2.09%"\n'
        '"07/21/2026","4,080.96","4,010.30","4,087.00","3,999.48","","1.86%"\n'
        '"07/20/2026","4,006.31","4,003.71","4,040.56","3,982.51","","-0.28%"\n'
    )
    h, l, c = csv_loader.load_ohlc_csv(text)
    assert len(c) == 3
    # newest-first input must be reversed to oldest-first
    assert c[0] == pytest.approx(4006.31)
    assert c[-1] == pytest.approx(4166.10)
    assert np.all(h >= c) and np.all(c >= l)


def test_dukascopy_iso_timestamp_format():
    # dukascopy-node CSV: timestamp,open,high,low,close,volume (oldest-first)
    text = (
        "timestamp,open,high,low,close,volume\n"
        "2025-01-01T00:00:00.000Z,2620,2635,2610,2630,1500\n"
        "2025-01-02T00:00:00.000Z,2630,2650,2625,2645,1800\n"
        "2025-01-03T00:00:00.000Z,2645,2660,2640,2655,1700\n"
    )
    h, l, c = csv_loader.load_ohlc_csv(text)
    assert list(c) == [2630, 2645, 2655]   # order preserved (already oldest-first)
    assert h[1] == 2650 and l[1] == 2625


def test_dukascopy_epoch_ms_timestamp():
    text = (
        "timestamp,open,high,low,close,volume\n"
        "1735689600000,2620,2635,2610,2630,1500\n"
        "1735776000000,2630,2650,2625,2645,1800\n"
    )
    _, _, c = csv_loader.load_ohlc_csv(text)
    assert list(c) == [2630, 2645]


def test_generic_ohlc_oldest_first_kept():
    text = (
        "Date,Open,High,Low,Close\n"
        "2025-01-01,10,11,9,10.5\n"
        "2025-01-02,10.5,12,10,11.5\n"
    )
    h, l, c = csv_loader.load_ohlc_csv(text)
    assert c[0] == pytest.approx(10.5)   # already oldest-first, not reversed
    assert c[-1] == pytest.approx(11.5)


def test_missing_close_column_raises():
    with pytest.raises(ValueError):
        csv_loader.load_ohlc_csv("Date,Open,High,Low\n2025-01-01,1,2,0.5\n")


def test_real_sample_loads_and_is_chronological():
    if not os.path.exists(SAMPLE):
        pytest.skip("sample CSV not present")
    with open(SAMPLE, encoding="utf-8") as f:
        h, l, c = csv_loader.load_ohlc_csv(f.read())
    assert len(c) > 300
    # gold rose over the sample window: oldest < newest
    assert c[0] < c[-1]
    assert np.all(h >= l)


def test_strategy_runs_on_real_sample():
    if not os.path.exists(SAMPLE):
        pytest.skip("sample CSV not present")
    with open(SAMPLE, encoding="utf-8") as f:
        h, l, c = csv_loader.load_ohlc_csv(f.read())
    bt = strategies.backtest(h, l, c, strategies.longterm_signal, warmup=210, max_hold=30)
    assert bt["trades"] > 0
    assert 0.0 <= bt["win_rate"] <= 1.0
