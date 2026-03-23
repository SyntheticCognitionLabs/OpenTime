"""Tests for the LangChain tool integration."""

import json

import httpx
import pytest

from opentime.integrations.langchain import (
    OpenTimeCheckTimeout,
    OpenTimeClockNow,
    OpenTimeCompareApproaches,
    OpenTimeGetStats,
    OpenTimeRecommendTimeout,
    OpenTimeTaskEnd,
    OpenTimeTaskStart,
    get_opentime_tools,
)

# ── Mock transport ───────────────────────────────────────────────────────────


def _mock_transport(request: httpx.Request) -> httpx.Response:
    """Route requests to mock responses."""
    path = request.url.path

    if path == "/clock/now":
        return httpx.Response(200, json={"now": "2026-01-01T00:00:00+00:00", "unix": 1735689600.0})

    if path == "/events/task-start":
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "event": {"id": "e1", "event_type": "task_start", "task_type": body["task_type"],
                       "timestamp": "2026-01-01T00:00:00+00:00", "metadata": None, "correlation_id": "cid-mock"},
            "correlation_id": "cid-mock",
        })

    if path == "/events/task-end":
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "event": {"id": "e2", "event_type": "task_end", "task_type": body["task_type"],
                       "timestamp": "2026-01-01T00:00:01+00:00", "metadata": None,
                       "correlation_id": body.get("correlation_id")},
        })

    if path == "/events/active":
        return httpx.Response(200, json={"active_tasks": []})

    if path.startswith("/stats/durations/"):
        return httpx.Response(200, json={"summary": {"task_type": "coding", "count": 5,
                                                       "mean_seconds": 10.0, "median_seconds": 9.0,
                                                       "p95_seconds": 15.0, "min_seconds": 5.0, "max_seconds": 18.0}})

    if path.startswith("/stats/recommend-timeout/"):
        return httpx.Response(200, json={"recommendation": {"recommended_seconds": 18.0, "sample_count": 5}})

    if path.startswith("/stats/check-timeout/"):
        return httpx.Response(200, json={"risk": {"at_risk": False, "elapsed_seconds": 5.0}})

    if path == "/stats/compare-approaches":
        return httpx.Response(200, json={"approaches": [], "recommendation": "A", "savings_vs_worst": 0})

    return httpx.Response(404, json={"detail": "Not found"})


@pytest.fixture
def mock_client():
    return httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(_mock_transport))


def _tool_with_mock(tool_cls, mock_client):
    """Create a tool instance and inject the mock client."""
    tool = tool_cls(base_url="http://testserver")
    tool._client = mock_client
    return tool


# ── Tool discovery tests ────────────────────────────────────────────────────


def test_get_opentime_tools_returns_correct_count():
    tools = get_opentime_tools()
    assert len(tools) == 8


def test_get_opentime_tools_custom_base_url():
    tools = get_opentime_tools(base_url="http://myhost:9090")
    for t in tools:
        assert t.base_url == "http://myhost:9090"


def test_tool_names_are_unique():
    tools = get_opentime_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names))


def test_tool_descriptions_are_nonempty():
    tools = get_opentime_tools()
    for t in tools:
        assert t.description, f"{t.name} has empty description"


def test_all_tools_have_args_schema():
    tools = get_opentime_tools()
    for t in tools:
        assert t.args_schema is not None, f"{t.name} missing args_schema"


# ── Functional tests ────────────────────────────────────────────────────────


def test_clock_now(mock_client):
    tool = _tool_with_mock(OpenTimeClockNow, mock_client)
    result = json.loads(tool._run())
    assert "now" in result
    assert "unix" in result


def test_task_start(mock_client):
    tool = _tool_with_mock(OpenTimeTaskStart, mock_client)
    result = json.loads(tool._run(task_type="coding"))
    assert result["correlation_id"] == "cid-mock"
    assert result["event"]["task_type"] == "coding"


def test_task_end(mock_client):
    tool = _tool_with_mock(OpenTimeTaskEnd, mock_client)
    result = json.loads(tool._run(task_type="coding", correlation_id="cid-123"))
    assert result["event"]["correlation_id"] == "cid-123"


def test_get_stats(mock_client):
    tool = _tool_with_mock(OpenTimeGetStats, mock_client)
    result = json.loads(tool._run(task_type="coding"))
    assert result["summary"]["count"] == 5


def test_recommend_timeout(mock_client):
    tool = _tool_with_mock(OpenTimeRecommendTimeout, mock_client)
    result = json.loads(tool._run(task_type="coding"))
    assert result["recommendation"]["recommended_seconds"] == 18.0


def test_check_timeout(mock_client):
    tool = _tool_with_mock(OpenTimeCheckTimeout, mock_client)
    result = json.loads(tool._run(task_type="coding", elapsed_seconds=5.0, timeout_seconds=60.0))
    assert result["risk"]["at_risk"] is False


def test_compare_approaches(mock_client):
    tool = _tool_with_mock(OpenTimeCompareApproaches, mock_client)
    approaches = json.dumps([{"name": "A", "steps": [{"task_type": "coding", "estimated_seconds": 100}]}])
    result = json.loads(tool._run(approaches=approaches))
    assert result["recommendation"] == "A"


# ── Cross-validation ────────────────────────────────────────────────────────


def test_langchain_and_openai_schemas_match():
    """LangChain tools and OpenAI schemas expose the same function names."""
    from opentime.integrations.openai_schema import get_opentime_functions

    lc_names = {t.name for t in get_opentime_tools()}
    oai_names = {f["function"]["name"] for f in get_opentime_functions()}
    assert lc_names == oai_names
