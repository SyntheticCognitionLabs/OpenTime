"""OpenAI function calling schemas and dispatcher for OpenTime.

Zero additional dependencies — uses only Python's standard library.
Works with OpenAI GPT-4/GPT-4o, Assistants API, and Google Gemini
function declarations (same schema format).

Usage::

    from opentime.integrations.openai_schema import get_opentime_functions, handle_function_call

    # Pass schemas to the model
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=get_opentime_functions(),
    )

    # Dispatch function calls to the OpenTime REST API
    for tool_call in response.choices[0].message.tool_calls:
        result = handle_function_call(
            tool_call.function.name,
            json.loads(tool_call.function.arguments),
        )
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_DEFAULT_BASE_URL = "http://localhost:8080"

OPENTIME_FUNCTIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "opentime_clock_now",
            "description": "Get the current UTC time as ISO 8601 and Unix timestamp.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opentime_task_start",
            "description": (
                "Start timing a task. Returns a correlation_id that must be passed "
                "to opentime_task_end when the task completes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {
                        "type": "string",
                        "description": "The type of task being started (e.g. 'code_generation', 'web_search')",
                    },
                    "metadata": {"type": "string", "description": "Optional JSON metadata string"},
                },
                "required": ["task_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opentime_task_end",
            "description": "End a timed task. Pass the same task_type and the correlation_id from opentime_task_start.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {"type": "string", "description": "The type of task being ended"},
                    "correlation_id": {
                        "type": "string",
                        "description": "The correlation_id returned by opentime_task_start",
                    },
                    "metadata": {"type": "string", "description": "Optional JSON metadata string"},
                },
                "required": ["task_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opentime_active_tasks",
            "description": "List all tasks that have been started but not yet ended.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {"type": "string", "description": "Optional filter by task type"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opentime_get_stats",
            "description": "Get duration statistics (mean, median, p95, min, max) for a task type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {"type": "string", "description": "The task type to get statistics for"},
                },
                "required": ["task_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opentime_recommend_timeout",
            "description": "Recommend a timeout for a task type based on historical durations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {"type": "string", "description": "The task type to recommend a timeout for"},
                    "percentile": {
                        "type": "number",
                        "description": "Which percentile to use (0.0-1.0, default 0.95)",
                    },
                    "safety_margin": {
                        "type": "number",
                        "description": "Safety multiplier (e.g. 1.2 = 20% buffer, default 1.2)",
                    },
                },
                "required": ["task_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opentime_check_timeout",
            "description": "Check if a running task is at risk of exceeding its timeout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {"type": "string", "description": "The task type to check against"},
                    "elapsed_seconds": {
                        "type": "number",
                        "description": "How many seconds the task has been running",
                    },
                    "timeout_seconds": {"type": "number", "description": "The timeout threshold in seconds"},
                },
                "required": ["task_type", "elapsed_seconds", "timeout_seconds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opentime_compare_approaches",
            "description": (
                "Compare multiple approaches using historical task duration data. "
                "Returns approaches ranked fastest-first with adjusted durations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "approaches": {
                        "type": "array",
                        "description": "List of approaches to compare",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Name of this approach"},
                                "steps": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "task_type": {"type": "string"},
                                            "estimated_seconds": {"type": "number"},
                                        },
                                        "required": ["task_type", "estimated_seconds"],
                                    },
                                },
                            },
                            "required": ["name", "steps"],
                        },
                    },
                },
                "required": ["approaches"],
            },
        },
    },
]


# ── Dispatcher ───────────────────────────────────────────────────────────────


def _build_body_task_start(args: dict) -> dict:
    body: dict[str, Any] = {"task_type": args["task_type"]}
    if args.get("metadata"):
        body["metadata"] = args["metadata"]
    return body


def _build_body_task_end(args: dict) -> dict:
    body: dict[str, Any] = {"task_type": args["task_type"]}
    if args.get("correlation_id"):
        body["correlation_id"] = args["correlation_id"]
    if args.get("metadata"):
        body["metadata"] = args["metadata"]
    return body


def _build_params_active(args: dict) -> dict | None:
    if args.get("task_type"):
        return {"task_type": args["task_type"]}
    return None


def _build_params_timeout(args: dict) -> dict | None:
    params: dict[str, Any] = {}
    if "percentile" in args:
        params["percentile"] = args["percentile"]
    if "safety_margin" in args:
        params["safety_margin"] = args["safety_margin"]
    return params or None


def _build_params_check(args: dict) -> dict:
    return {"elapsed_seconds": args["elapsed_seconds"], "timeout_seconds": args["timeout_seconds"]}


def _build_body_compare(args: dict) -> dict:
    return {"approaches": args["approaches"]}


# (method, path_template, body_builder, params_builder)
_ROUTES: dict[str, tuple[str, str, Any, Any]] = {
    "opentime_clock_now": ("GET", "/clock/now", None, None),
    "opentime_task_start": ("POST", "/events/task-start", _build_body_task_start, None),
    "opentime_task_end": ("POST", "/events/task-end", _build_body_task_end, None),
    "opentime_active_tasks": ("GET", "/events/active", None, _build_params_active),
    "opentime_get_stats": ("GET", "/stats/durations/{task_type}", None, None),
    "opentime_recommend_timeout": ("GET", "/stats/recommend-timeout/{task_type}", None, _build_params_timeout),
    "opentime_check_timeout": ("GET", "/stats/check-timeout/{task_type}", None, _build_params_check),
    "opentime_compare_approaches": ("POST", "/stats/compare-approaches", _build_body_compare, None),
}


def get_opentime_functions() -> list[dict[str, Any]]:
    """Return all OpenTime function definitions in OpenAI's function calling format.

    These definitions work with OpenAI function calling (GPT-4, GPT-4o),
    OpenAI Assistants API, Google Gemini function declarations, and any
    framework that uses JSON Schema for tool definitions.
    """
    return [f.copy() for f in OPENTIME_FUNCTIONS]


def handle_function_call(
    name: str,
    arguments: dict[str, Any],
    base_url: str = _DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Dispatch an OpenAI-style function call to the OpenTime REST API.

    Args:
        name: The function name from the model's response.
        arguments: The parsed arguments dict from the model's response.
        base_url: The OpenTime REST API base URL.

    Returns:
        The JSON response from the REST API as a dict.

    Raises:
        ValueError: If the function name is not recognized.
        RuntimeError: If the REST API returns an error.
    """
    if name not in _ROUTES:
        raise ValueError(f"Unknown function: {name}. Known functions: {sorted(_ROUTES)}")

    method, path_template, body_builder, params_builder = _ROUTES[name]

    # Fill path placeholders from arguments
    path = path_template
    for key, value in list(arguments.items()):
        placeholder = "{" + key + "}"
        if placeholder in path:
            path = path.replace(placeholder, str(value))

    url = base_url.rstrip("/") + path

    # Build query params for GET requests
    if params_builder:
        params = params_builder(arguments)
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

    # Build and execute request
    if method == "POST" and body_builder:
        data = json.dumps(body_builder(arguments)).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
    else:
        req = urllib.request.Request(url, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenTime API error {e.code}: {body}") from e
