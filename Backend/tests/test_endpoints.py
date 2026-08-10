"""Tests for API endpoint behaviour that has real logic (the grade filter).

Calls the async route functions directly with explicit args so no HTTP client
(httpx/TestClient) is required.
"""

import asyncio

from app.main import manipulation, manipulation_scan


def _run(coro):
    return asyncio.run(coro)


def test_min_grade_filter_returns_qualifying_setup():
    r = _run(manipulation(asset="btc", min_grade="A1", seed=1, max_scans=100))
    assert r["filtered"]["found"] is True
    from app.manipulation import grade_rank
    assert grade_rank(r["grade"]) >= grade_rank("A1")
    assert r["trade_plan"] is not None


def test_min_grade_filter_reports_not_found_for_impossible_grade():
    # eurusd cannot reach A+ (tradability ~0), so the filter must give up honestly.
    r = _run(manipulation(asset="eurusd", min_grade="A+", seed=1, max_scans=40))
    assert r["filtered"]["found"] is False
    assert r["filtered"]["scans"] == 40


def test_no_filter_returns_single_window():
    # min_grade=None is the HTTP default; passed explicitly here because a direct
    # call doesn't resolve FastAPI Query defaults.
    r = _run(manipulation(asset="btc", seed=1, min_grade=None))
    assert "filtered" not in r
    assert r["asset"] == "btc"


def test_scan_endpoint_lists_all_assets_with_grades():
    r = _run(manipulation_scan(seed=3))
    assert len(r["scan"]) == len(r["assets"])
    assert all("grade" in row for row in r["scan"])
