"""Tests for system prompt templates."""

import pytest

from opentime.prompts import get_system_prompt


def test_mcp_prompt_contains_tool_names():
    prompt = get_system_prompt("mcp")
    assert "event_task_start" in prompt
    assert "event_task_end" in prompt
    assert "stats_recommend_timeout" in prompt
    assert "stats_compare_approaches" in prompt
    assert "correlation_id" in prompt


def test_function_calling_prompt_contains_function_names():
    prompt = get_system_prompt("function_calling")
    assert "opentime_task_start" in prompt
    assert "opentime_task_end" in prompt
    assert "opentime_recommend_timeout" in prompt


def test_openai_alias():
    """'openai' mode should return the same as 'function_calling'."""
    assert get_system_prompt("openai") == get_system_prompt("function_calling")


def test_gemini_alias():
    """'gemini' mode should return the same as 'function_calling'."""
    assert get_system_prompt("gemini") == get_system_prompt("function_calling")


def test_rest_api_prompt_contains_endpoints():
    prompt = get_system_prompt("rest_api")
    assert "POST /events/task-start" in prompt
    assert "POST /events/task-end" in prompt
    assert "GET /stats/recommend-timeout" in prompt


def test_rest_api_prompt_includes_base_url():
    prompt = get_system_prompt("rest_api", base_url="http://myhost:9090")
    assert "http://myhost:9090" in prompt


def test_rest_alias():
    assert get_system_prompt("rest") == get_system_prompt("rest_api")


def test_all_modes_contain_core_rules():
    """All modes should contain the shared core instructions."""
    for mode in ["mcp", "function_calling", "rest_api"]:
        prompt = get_system_prompt(mode)
        assert "Always track tasks" in prompt
        assert "Check before setting timeouts" in prompt
        assert "Compare approaches by time" in prompt
        assert "correlation_id" in prompt


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown mode"):
        get_system_prompt("invalid_mode")


def test_prompts_are_nonempty_strings():
    for mode in ["mcp", "function_calling", "openai", "gemini", "rest_api", "rest"]:
        prompt = get_system_prompt(mode)
        assert isinstance(prompt, str)
        assert len(prompt) > 100
