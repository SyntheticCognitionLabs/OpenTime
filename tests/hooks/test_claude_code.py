"""Tests for the Claude Code hook script."""

import json

from opentime.db.connection import open_database
from opentime.db.queries import select_events
from opentime.hooks.claude_code import handle_post_tool_use, handle_pre_tool_use, handle_stop


def _make_hook_data(**overrides):
    """Build a minimal hook event data dict."""
    base = {
        "session_id": "test-session-123",
        "cwd": "/home/test/project",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hello"},
        "tool_use_id": "toolu_test_001",
    }
    base.update(overrides)
    return base


def test_pre_tool_use_records_task_start():
    conn = open_database(None)
    data = _make_hook_data(tool_name="Bash", tool_input={"command": "pytest -v"})

    handle_pre_tool_use(conn, "test-agent", data)

    events = select_events(conn, "test-agent")
    assert len(events) == 1
    event = events[0]
    assert event[2] == "task_start"  # event_type
    assert event[3] == "tool:Bash"  # task_type
    assert event[6] == "toolu_test_001"  # correlation_id

    meta = json.loads(event[5])
    assert meta["session_id"] == "test-session-123"
    assert meta["description"] == "pytest -v"
    conn.close()


def test_post_tool_use_records_task_end():
    conn = open_database(None)
    data = _make_hook_data(hook_event_name="PostToolUse", tool_name="Edit")

    handle_post_tool_use(conn, "test-agent", data)

    events = select_events(conn, "test-agent")
    assert len(events) == 1
    event = events[0]
    assert event[2] == "task_end"
    assert event[3] == "tool:Edit"
    assert event[6] == "toolu_test_001"
    conn.close()


def test_pre_and_post_pair_by_correlation_id():
    """PreToolUse and PostToolUse share the same correlation_id (tool_use_id)."""
    conn = open_database(None)
    tool_use_id = "toolu_paired_001"
    pre_data = _make_hook_data(tool_name="Write", tool_use_id=tool_use_id)
    post_data = _make_hook_data(hook_event_name="PostToolUse", tool_name="Write", tool_use_id=tool_use_id)

    handle_pre_tool_use(conn, "test-agent", pre_data)
    handle_post_tool_use(conn, "test-agent", post_data)

    events = select_events(conn, "test-agent", limit=10)
    assert len(events) == 2

    # Both should have the same correlation_id
    correlation_ids = {e[6] for e in events}
    assert correlation_ids == {tool_use_id}

    # One start, one end
    event_types = {e[2] for e in events}
    assert event_types == {"task_start", "task_end"}
    conn.close()


def test_stop_records_agent_stop():
    conn = open_database(None)
    data = {
        "session_id": "test-session-456",
        "cwd": "/home/test/project",
        "hook_event_name": "Stop",
        "stop_hook_active": True,
        "last_assistant_message": "Done!",
    }

    handle_stop(conn, "test-agent", data)

    events = select_events(conn, "test-agent")
    assert len(events) == 1
    event = events[0]
    assert event[2] == "agent_stop"
    assert event[3] == "conversation_turn"
    assert event[6] is None  # no correlation_id for stop events
    conn.close()


def test_different_tool_types():
    """Verify task_type is set correctly for various tools."""
    conn = open_database(None)

    tools = [
        ("Read", {"file_path": "/foo/bar.py"}, "/foo/bar.py"),
        ("Grep", {"pattern": "def main"}, "def main"),
        ("Glob", {"pattern": "**/*.py"}, "**/*.py"),
        ("Agent", {"description": "explore codebase"}, "explore codebase"),
    ]

    for i, (tool_name, tool_input, _expected_desc) in enumerate(tools):
        data = _make_hook_data(tool_name=tool_name, tool_input=tool_input, tool_use_id=f"toolu_{i}")
        handle_pre_tool_use(conn, "test-agent", data)

    events = select_events(conn, "test-agent", limit=20)
    assert len(events) == 4

    task_types = {e[3] for e in events}
    assert task_types == {"tool:Read", "tool:Grep", "tool:Glob", "tool:Agent"}
    conn.close()


def test_metadata_includes_session_and_cwd():
    conn = open_database(None)
    data = _make_hook_data(session_id="sess-abc", cwd="/projects/opentime")

    handle_pre_tool_use(conn, "test-agent", data)

    events = select_events(conn, "test-agent")
    meta = json.loads(events[0][5])
    assert meta["session_id"] == "sess-abc"
    assert meta["cwd"] == "/projects/opentime"
    conn.close()


def test_truncates_long_descriptions():
    conn = open_database(None)
    long_cmd = "x" * 500
    data = _make_hook_data(tool_input={"command": long_cmd})

    handle_pre_tool_use(conn, "test-agent", data)

    events = select_events(conn, "test-agent")
    meta = json.loads(events[0][5])
    assert len(meta["description"]) == 203  # 200 + "..."
    assert meta["description"].endswith("...")
    conn.close()
