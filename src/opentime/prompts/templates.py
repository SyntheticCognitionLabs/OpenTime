"""System prompt templates for AI agents using OpenTime.

Each template instructs the agent to proactively use OpenTime's time tracking
tools without being asked. The templates differ only in how the agent calls
the tools (MCP tools, function calls, or REST API).
"""

from __future__ import annotations

# ── Core instructions (shared across all integration modes) ──────────────────

_CORE_INSTRUCTIONS = """\
## Time Tracking with OpenTime

You have access to OpenTime, a time tracking and temporal awareness system. \
Use it proactively on EVERY task — do not wait to be asked.

### Rules

1. **Always track tasks.** Call task_start at the beginning of every distinct \
task and task_end when it completes. Save the correlation_id from task_start \
and pass it to task_end.

2. **Use descriptive task types.** Use consistent, descriptive task_type names \
like "code_generation", "debugging", "file_download", "test_run", "data_analysis", \
"web_search", "code_review", etc. Consistent naming enables accurate statistics.

3. **Check before setting timeouts.** Before setting any timeout, deadline, or \
wait duration, call recommend_timeout with the relevant task type. If you have \
no historical data yet, record the task so future runs will have data.

4. **Check running tasks.** If a task is taking longer than expected, call \
check_timeout to assess whether it is at risk of exceeding its timeout.

5. **Compare approaches by time.** When choosing between multiple approaches, \
call compare_approaches with estimated durations for each step. Your time \
estimates from training data are calibrated to human speed — your actual speed \
is very different. Let historical data correct your estimates.

6. **Check active tasks.** Call active_tasks periodically to see what you are \
currently tracking. End any tasks that have completed.

7. **Track everything, not just coding.** Track file downloads, API calls, \
test suites, build processes, deployments, searches — any operation with a \
meaningful duration.\
"""

# ── MCP-specific instructions ────────────────────────────────────────────────

_MCP_INSTRUCTIONS = """\
{core}

### Tool Names

- `event_task_start(task_type, metadata?)` — start a task, returns correlation_id
- `event_task_end(task_type, correlation_id?, metadata?)` — end a task
- `event_active_tasks(task_type?)` — list in-progress tasks
- `stats_duration(task_type)` — get duration statistics
- `stats_recommend_timeout(task_type, percentile?, safety_margin?)` — get timeout recommendation
- `stats_check_timeout(task_type, elapsed_seconds, timeout_seconds)` — check timeout risk
- `stats_compare_approaches(approaches)` — compare approaches by estimated time
- `clock_now()` — get current UTC time
- `stopwatch_start(name)` / `stopwatch_stop(name)` — quick timing

### Example

When starting a coding task:
1. Call `event_task_start("code_generation")` — save the correlation_id
2. Do the work
3. Call `event_task_end("code_generation", correlation_id=<saved_id>)`
4. Next time, `stats_recommend_timeout("code_generation")` will give you a \
data-driven timeout based on how long coding actually takes you.\
"""

# ── Function calling instructions (OpenAI / Gemini) ─────────────────────────

_FUNCTION_CALLING_INSTRUCTIONS = """\
{core}

### Available Functions

- `opentime_task_start(task_type, metadata?)` — start a task, returns correlation_id
- `opentime_task_end(task_type, correlation_id?, metadata?)` — end a task
- `opentime_active_tasks(task_type?)` — list in-progress tasks
- `opentime_get_stats(task_type)` — get duration statistics
- `opentime_recommend_timeout(task_type, percentile?, safety_margin?)` — get timeout recommendation
- `opentime_check_timeout(task_type, elapsed_seconds, timeout_seconds)` — check timeout risk
- `opentime_compare_approaches(approaches)` — compare approaches by estimated time
- `opentime_clock_now()` — get current UTC time

### Example

When starting a task:
1. Call `opentime_task_start` with `task_type: "code_generation"` — save the returned correlation_id
2. Do the work
3. Call `opentime_task_end` with `task_type: "code_generation"` and `correlation_id: <saved_id>`\
"""

# ── REST API instructions ────────────────────────────────────────────────────

_REST_API_INSTRUCTIONS = """\
{core}

### API Endpoints (base URL: {base_url})

- `POST /events/task-start` body: `{{"task_type": "..."}}` — returns correlation_id
- `POST /events/task-end` body: `{{"task_type": "...", "correlation_id": "..."}}` — end a task
- `GET /events/active` — list in-progress tasks
- `GET /stats/durations/<task_type>` — get duration statistics
- `GET /stats/recommend-timeout/<task_type>` — get timeout recommendation
- `GET /stats/check-timeout/<task_type>?elapsed_seconds=N&timeout_seconds=N` — check timeout risk
- `POST /stats/compare-approaches` body: `{{"approaches": [...]}}` — compare approaches
- `GET /clock/now` — get current UTC time

### Example

When starting a task:
1. POST to `/events/task-start` with `{{"task_type": "code_generation"}}` — save the correlation_id from the response
2. Do the work
3. POST to `/events/task-end` with `{{"task_type": "code_generation", "correlation_id": "<saved_id>"}}`\
"""

# ── Template registry ────────────────────────────────────────────────────────

_TEMPLATES = {
    "mcp": _MCP_INSTRUCTIONS,
    "function_calling": _FUNCTION_CALLING_INSTRUCTIONS,
    "openai": _FUNCTION_CALLING_INSTRUCTIONS,
    "gemini": _FUNCTION_CALLING_INSTRUCTIONS,
    "rest_api": _REST_API_INSTRUCTIONS,
    "rest": _REST_API_INSTRUCTIONS,
}


def get_system_prompt(
    mode: str = "mcp",
    base_url: str = "http://localhost:8080",
) -> str:
    """Get a system prompt snippet that instructs an AI agent to use OpenTime.

    Args:
        mode: Integration mode. One of:
            - "mcp" — for MCP-connected agents (Claude Code, Cursor, etc.)
            - "function_calling" / "openai" / "gemini" — for function calling agents
            - "rest_api" / "rest" — for agents calling the REST API directly
        base_url: REST API base URL (only used for "rest_api" mode).

    Returns:
        A string to append to the agent's system prompt.
    """
    if mode not in _TEMPLATES:
        raise ValueError(f"Unknown mode: {mode!r}. Choose from: {sorted(set(_TEMPLATES))}")
    template = _TEMPLATES[mode]
    return template.format(core=_CORE_INSTRUCTIONS, base_url=base_url)
