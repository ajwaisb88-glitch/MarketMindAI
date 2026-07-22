"""Tests for the FMP data adapter — focused on safe behaviour without a key.

Live network calls are never made in tests; we only verify symbol mapping and
that everything fails soft when FMP_API_KEY is absent.
"""

import os

from app import fmp_client


def test_symbol_mapping_from_profiles():
    assert fmp_client.fmp_symbol("xauusd") == "XAUUSD"
    assert fmp_client.fmp_symbol("btc") == "BTCUSD"
    assert fmp_client.fmp_symbol("doge") == "DOGEUSD"
    assert fmp_client.fmp_symbol("totally_unknown") is None  # default profile fmp=None


def test_no_key_means_not_configured(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    assert fmp_client.api_key() is None
    assert fmp_client.is_configured() is False


def test_blank_key_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "   ")
    assert fmp_client.is_configured() is False


def test_fetches_return_none_without_key(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    assert fmp_client.get_quote("btc") is None
    assert fmp_client.get_ohlc("btc", intraday=False) is None
    assert fmp_client.get_ohlc("xauusd", intraday=True) is None


def test_configured_when_key_present(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "dummy_key_value")
    assert fmp_client.is_configured() is True
    assert fmp_client.api_key() == "dummy_key_value"
