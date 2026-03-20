"""Tests for MCP server tools via direct function calls with a mock context."""

from unittest.mock import MagicMock

import pytest

from opentime.core.clock import ClockService
from opentime.core.events import EventTracker
from opentime.core.stats import DurationStats
from opentime.db.connection import open_database
from opentime.mcp_server.server import (
    AppContext,
    clock_elapsed_since,
    clock_now,
    event_active_tasks,
    event_get,
    event_list,
    event_record,
    event_task_end,
    event_task_start,
    stats_all,
    stats_check_timeout,
    stats_compare_approaches,
    stats_duration,
    stats_list_task_types,
    stats_recommend_timeout,
    stopwatch_delete,
    stopwatch_list,
    stopwatch_start,
    stopwatch_stop,
)


@pytest.fixture
def app_context():
    conn = open_database(None)
    ctx = AppContext(
        clock=ClockService(),
        events=EventTracker(conn, "mcp-test-agent"),
        stats=DurationStats(conn, "mcp-test-agent"),
    )
    yield ctx
    conn.close()


@pytest.fixture
def mock_ctx(app_context):
    """Mock MCP Context that provides AppContext via request_context.lifespan_context."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_context
    return ctx


def test_clock_now(mock_ctx):
    result = clock_now(mock_ctx)
    assert "now" in result
    assert "unix" in result
    assert isinstance(result["unix"], float)


def test_clock_elapsed_since(mock_ctx):
    result = clock_elapsed_since("2020-01-01T00:00:00+00:00", mock_ctx)
    assert "elapsed_seconds" in result
    assert result["elapsed_seconds"] > 0
    assert result["since"] == "2020-01-01T00:00:00+00:00"


def test_stopwatch_lifecycle(mock_ctx):
    start_result = stopwatch_start("test-sw", mock_ctx)
    assert start_result["name"] == "test-sw"
    assert "started_at" in start_result

    stop_result = stopwatch_stop("test-sw", mock_ctx)
    assert stop_result["name"] == "test-sw"
    assert stop_result["elapsed_seconds"] >= 0
    assert stop_result["is_running"] is False


def test_stopwatch_list_and_delete(mock_ctx):
    stopwatch_start("sw1", mock_ctx)
    stopwatch_start("sw2", mock_ctx)

    list_result = stopwatch_list(mock_ctx)
    assert len(list_result["stopwatches"]) == 2

    delete_result = stopwatch_delete("sw1", mock_ctx)
    assert delete_result["deleted"] == "sw1"

    list_result = stopwatch_list(mock_ctx)
    assert len(list_result["stopwatches"]) == 1


def test_event_record_and_list(mock_ctx):
    result = event_record("message_sent", mock_ctx, metadata='{"to": "user"}')
    assert result["event"]["event_type"] == "message_sent"
    assert result["event"]["id"] is not None

    list_result = event_list(mock_ctx)
    assert len(list_result["events"]) == 1


def test_event_task_start_end(mock_ctx):
    start = event_task_start("coding", mock_ctx)
    assert start["event"]["event_type"] == "task_start"
    assert start["event"]["task_type"] == "coding"
    assert start["correlation_id"] is not None

    cid = start["correlation_id"]
    end = event_task_end("coding", mock_ctx, correlation_id=cid)
    assert end["event"]["event_type"] == "task_end"
    assert end["event"]["correlation_id"] == cid


def test_event_get(mock_ctx):
    created = event_record("test", mock_ctx)
    event_id = created["event"]["id"]

    found = event_get(event_id, mock_ctx)
    assert found["event"] is not None
    assert found["event"]["id"] == event_id

    missing = event_get("nonexistent", mock_ctx)
    assert missing["event"] is None


def test_stats_duration(mock_ctx):
    # No data yet
    result = stats_duration("coding", mock_ctx)
    assert result["summary"] is None

    # Record a start/end pair with correlation_id
    start = event_task_start("coding", mock_ctx)
    cid = start["correlation_id"]
    event_task_end("coding", mock_ctx, correlation_id=cid)

    result = stats_duration("coding", mock_ctx)
    assert result["summary"] is not None
    assert result["summary"]["count"] == 1


def test_stats_list_task_types(mock_ctx):
    event_task_start("coding", mock_ctx)
    event_task_start("download", mock_ctx)

    result = stats_list_task_types(mock_ctx)
    assert set(result["task_types"]) == {"coding", "download"}


def test_stats_all(mock_ctx):
    start = event_task_start("coding", mock_ctx)
    event_task_end("coding", mock_ctx, correlation_id=start["correlation_id"])

    result = stats_all(mock_ctx)
    assert len(result["summaries"]) == 1
    assert result["summaries"][0]["task_type"] == "coding"


def test_event_task_start_returns_correlation_id(mock_ctx):
    result = event_task_start("coding", mock_ctx)
    assert "correlation_id" in result
    assert result["correlation_id"] is not None
    assert result["event"]["correlation_id"] == result["correlation_id"]


def test_event_active_tasks(mock_ctx):
    start = event_task_start("coding", mock_ctx)
    cid = start["correlation_id"]

    active = event_active_tasks(mock_ctx)
    assert len(active["active_tasks"]) == 1
    assert active["active_tasks"][0]["correlation_id"] == cid

    event_task_end("coding", mock_ctx, correlation_id=cid)
    active = event_active_tasks(mock_ctx)
    assert len(active["active_tasks"]) == 0


def test_event_record_dict_metadata(mock_ctx):
    """Metadata passed as a dict should be serialized to JSON string."""
    # Simulate what happens when MCP client sends a dict
    result = event_record("test", mock_ctx, metadata='{"key": "value"}')
    assert result["event"]["metadata"] == '{"key": "value"}'


def test_stats_recommend_timeout(mock_ctx):
    # Record some task pairs (durations will be ~0s since start/end are near-instant)
    for _ in range(5):
        start = event_task_start("coding", mock_ctx)
        event_task_end("coding", mock_ctx, correlation_id=start["correlation_id"])

    result = stats_recommend_timeout("coding", mock_ctx)
    assert result["recommendation"] is not None
    assert result["recommendation"]["sample_count"] == 5
    assert result["recommendation"]["recommended_seconds"] >= 0


def test_stats_recommend_timeout_no_data(mock_ctx):
    result = stats_recommend_timeout("nonexistent", mock_ctx)
    assert result["recommendation"] is None


def test_stats_check_timeout(mock_ctx):
    for _ in range(3):
        start = event_task_start("coding", mock_ctx)
        event_task_end("coding", mock_ctx, correlation_id=start["correlation_id"])

    result = stats_check_timeout("coding", 5.0, 60.0, mock_ctx)
    assert result["risk"] is not None
    assert result["risk"]["elapsed_seconds"] == 5.0
    assert result["risk"]["timeout_seconds"] == 60.0
    assert "at_risk" in result["risk"]


def test_stats_check_timeout_no_data(mock_ctx):
    result = stats_check_timeout("nonexistent", 5.0, 60.0, mock_ctx)
    assert result["risk"] is None


def test_stats_compare_approaches(mock_ctx):
    import json

    # Record some task pairs for "coding"
    for _ in range(3):
        start = event_task_start("coding", mock_ctx)
        event_task_end("coding", mock_ctx, correlation_id=start["correlation_id"])

    approaches = json.dumps([
        {"name": "A", "steps": [{"task_type": "coding", "estimated_seconds": 3600}]},
        {"name": "B", "steps": [{"task_type": "unknown", "estimated_seconds": 100}]},
    ])

    result = stats_compare_approaches(approaches, mock_ctx)
    assert len(result["approaches"]) == 2
    assert result["recommendation"] is not None

    # The approach with "coding" should have historical data
    approach_a = next(a for a in result["approaches"] if a["name"] == "A")
    assert approach_a["steps"][0]["has_historical_data"] is True
