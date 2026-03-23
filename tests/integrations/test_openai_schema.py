"""Tests for the OpenAI function calling schema and dispatcher."""

import json
from unittest.mock import MagicMock, patch

import pytest

from opentime.integrations.openai_schema import (
    OPENTIME_FUNCTIONS,
    get_opentime_functions,
    handle_function_call,
)


def test_get_opentime_functions_returns_list():
    funcs = get_opentime_functions()
    assert isinstance(funcs, list)
    assert len(funcs) == 8


def test_function_schema_structure():
    for f in OPENTIME_FUNCTIONS:
        assert f["type"] == "function"
        func = f["function"]
        assert "name" in func
        assert "description" in func
        assert "parameters" in func
        params = func["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params


def test_all_function_names_unique():
    names = [f["function"]["name"] for f in OPENTIME_FUNCTIONS]
    assert len(names) == len(set(names))


def test_required_params_exist_in_properties():
    for f in OPENTIME_FUNCTIONS:
        func = f["function"]
        props = func["parameters"]["properties"]
        required = func["parameters"]["required"]
        for r in required:
            assert r in props, f"{func['name']}: required param '{r}' not in properties"


def test_get_opentime_functions_returns_copy():
    funcs1 = get_opentime_functions()
    funcs1.append({"extra": True})
    funcs2 = get_opentime_functions()
    assert len(funcs2) == 8


def test_handle_function_call_unknown_function():
    with pytest.raises(ValueError, match="Unknown function"):
        handle_function_call("nonexistent", {})


def _mock_urlopen(status=200, body=None):
    """Create a mock for urllib.request.urlopen."""
    if body is None:
        body = {"ok": True}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(body).encode("utf-8")
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


@patch("opentime.integrations.openai_schema.urllib.request.urlopen")
def test_handle_clock_now(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(body={"now": "2026-01-01T00:00:00+00:00", "unix": 1.0})
    result = handle_function_call("opentime_clock_now", {})
    assert result == {"now": "2026-01-01T00:00:00+00:00", "unix": 1.0}

    req = mock_urlopen.call_args[0][0]
    assert req.full_url == "http://localhost:8080/clock/now"
    assert req.method == "GET"


@patch("opentime.integrations.openai_schema.urllib.request.urlopen")
def test_handle_task_start(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(body={"event": {}, "correlation_id": "abc"})
    result = handle_function_call("opentime_task_start", {"task_type": "coding"})
    assert result["correlation_id"] == "abc"

    req = mock_urlopen.call_args[0][0]
    assert req.full_url == "http://localhost:8080/events/task-start"
    assert req.method == "POST"
    body = json.loads(req.data)
    assert body["task_type"] == "coding"


@patch("opentime.integrations.openai_schema.urllib.request.urlopen")
def test_handle_task_end_with_correlation_id(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen()
    handle_function_call("opentime_task_end", {"task_type": "coding", "correlation_id": "abc123"})

    req = mock_urlopen.call_args[0][0]
    body = json.loads(req.data)
    assert body["correlation_id"] == "abc123"


@patch("opentime.integrations.openai_schema.urllib.request.urlopen")
def test_handle_get_stats(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(body={"summary": {"count": 5}})
    handle_function_call("opentime_get_stats", {"task_type": "coding"})

    req = mock_urlopen.call_args[0][0]
    assert "/stats/durations/coding" in req.full_url
    assert req.method == "GET"


@patch("opentime.integrations.openai_schema.urllib.request.urlopen")
def test_handle_recommend_timeout_with_params(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen()
    handle_function_call(
        "opentime_recommend_timeout",
        {"task_type": "coding", "percentile": 0.9, "safety_margin": 1.5},
    )

    req = mock_urlopen.call_args[0][0]
    assert "recommend-timeout/coding" in req.full_url
    assert "percentile=0.9" in req.full_url
    assert "safety_margin=1.5" in req.full_url


@patch("opentime.integrations.openai_schema.urllib.request.urlopen")
def test_handle_check_timeout(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen()
    handle_function_call(
        "opentime_check_timeout",
        {"task_type": "coding", "elapsed_seconds": 30.0, "timeout_seconds": 60.0},
    )

    req = mock_urlopen.call_args[0][0]
    assert "check-timeout/coding" in req.full_url
    assert "elapsed_seconds=30.0" in req.full_url


@patch("opentime.integrations.openai_schema.urllib.request.urlopen")
def test_handle_compare_approaches(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen()
    approaches = [{"name": "A", "steps": [{"task_type": "coding", "estimated_seconds": 100}]}]
    handle_function_call("opentime_compare_approaches", {"approaches": approaches})

    req = mock_urlopen.call_args[0][0]
    assert req.method == "POST"
    body = json.loads(req.data)
    assert body["approaches"] == approaches


@patch("opentime.integrations.openai_schema.urllib.request.urlopen")
def test_handle_active_tasks_with_filter(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen()
    handle_function_call("opentime_active_tasks", {"task_type": "coding"})

    req = mock_urlopen.call_args[0][0]
    assert "task_type=coding" in req.full_url


@patch("opentime.integrations.openai_schema.urllib.request.urlopen")
def test_handle_custom_base_url(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen()
    handle_function_call("opentime_clock_now", {}, base_url="http://myhost:9090")

    req = mock_urlopen.call_args[0][0]
    assert req.full_url == "http://myhost:9090/clock/now"
