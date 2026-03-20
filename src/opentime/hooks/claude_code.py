"""Claude Code hook for passive OpenTime time tracking.

Reads hook event JSON from stdin and writes events directly to SQLite.
No REST API or MCP server needed — just a direct database write.

Usage in .claude/settings.json or .claude/settings.local.json:

{
  "hooks": {
    "PreToolUse": [{
      "matcher": "",
      "hooks": [{"type": "command", "command": ".venv/bin/python -m opentime.hooks.claude_code"}]
    }],
    "PostToolUse": [{
      "matcher": "",
      "hooks": [{"type": "command", "command": ".venv/bin/python -m opentime.hooks.claude_code"}]
    }],
    "Stop": [{
      "hooks": [{"type": "command", "command": ".venv/bin/python -m opentime.hooks.claude_code"}]
    }]
  }
}
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from opentime.db.connection import open_database
from opentime.db.queries import insert_event


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _truncate(s: str, maxlen: int = 200) -> str:
    return s[:maxlen] + "..." if len(s) > maxlen else s


def _metadata_dict(data: dict, **extra: str) -> str:
    """Build a JSON metadata string from hook data plus extras."""
    meta = {}
    if data.get("session_id"):
        meta["session_id"] = data["session_id"]
    if data.get("cwd"):
        meta["cwd"] = data["cwd"]
    meta.update(extra)
    return json.dumps(meta)


def handle_pre_tool_use(conn, agent_id: str, data: dict) -> None:
    """Record a task_start event when a tool begins execution."""
    tool_name = data.get("tool_name", "unknown")
    tool_use_id = data.get("tool_use_id", uuid.uuid4().hex)
    tool_input = data.get("tool_input", {})

    # Build a short description of what the tool is doing
    description = ""
    if tool_name == "Bash":
        description = _truncate(tool_input.get("command", ""))
    elif tool_name in ("Read", "Write", "Edit"):
        description = tool_input.get("file_path", "")
    elif tool_name in ("Grep", "Glob"):
        description = tool_input.get("pattern", "")
    elif tool_name == "Agent":
        description = tool_input.get("description", "")

    insert_event(
        conn,
        event_id=uuid.uuid4().hex,
        agent_id=agent_id,
        event_type="task_start",
        task_type=f"tool:{tool_name}",
        timestamp=_timestamp(),
        metadata=_metadata_dict(data, description=description),
        correlation_id=tool_use_id,
    )


def handle_post_tool_use(conn, agent_id: str, data: dict) -> None:
    """Record a task_end event when a tool finishes execution."""
    tool_name = data.get("tool_name", "unknown")
    tool_use_id = data.get("tool_use_id", uuid.uuid4().hex)

    insert_event(
        conn,
        event_id=uuid.uuid4().hex,
        agent_id=agent_id,
        event_type="task_end",
        task_type=f"tool:{tool_name}",
        timestamp=_timestamp(),
        metadata=_metadata_dict(data),
        correlation_id=tool_use_id,
    )


def handle_stop(conn, agent_id: str, data: dict) -> None:
    """Record an agent_stop event when the agent finishes responding."""
    insert_event(
        conn,
        event_id=uuid.uuid4().hex,
        agent_id=agent_id,
        event_type="agent_stop",
        task_type="conversation_turn",
        timestamp=_timestamp(),
        metadata=_metadata_dict(data),
    )


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return

    event_name = data.get("hook_event_name")
    if event_name not in ("PreToolUse", "PostToolUse", "Stop"):
        return

    db_path = os.environ.get("OPENTIME_DB_PATH", str(Path.home() / ".opentime" / "claude-code.db"))
    agent_id = os.environ.get("OPENTIME_AGENT_ID", "claude-code")

    try:
        conn = open_database(os.path.expanduser(db_path))
    except Exception:
        return

    try:
        if event_name == "PreToolUse":
            handle_pre_tool_use(conn, agent_id, data)
        elif event_name == "PostToolUse":
            handle_post_tool_use(conn, agent_id, data)
        elif event_name == "Stop":
            handle_stop(conn, agent_id, data)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
