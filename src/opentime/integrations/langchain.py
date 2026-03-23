"""LangChain tool integration for OpenTime.

Provides 8 LangChain-compatible tools that wrap the OpenTime REST API.

Usage::

    from opentime.integrations.langchain import get_opentime_tools

    tools = get_opentime_tools()  # base_url defaults to http://localhost:8080
    agent = create_react_agent(llm, tools)

Requires: ``pip install opentime[langchain]``
"""

from __future__ import annotations

try:
    from langchain_core.tools import BaseTool
except ImportError as e:
    raise ImportError(
        "LangChain integration requires langchain-core. Install with: pip install opentime[langchain]"
    ) from e

import json
from typing import Any

import httpx
from pydantic import BaseModel, Field, PrivateAttr

_DEFAULT_BASE_URL = "http://localhost:8080"


# ── Input schemas ────────────────────────────────────────────────────────────


class EmptyInput(BaseModel):
    pass


class TaskStartInput(BaseModel):
    task_type: str = Field(description="The type of task being started (e.g. 'code_generation', 'web_search')")
    metadata: str | None = Field(default=None, description="Optional JSON metadata string")


class TaskEndInput(BaseModel):
    task_type: str = Field(description="The type of task being ended")
    correlation_id: str | None = Field(default=None, description="The correlation_id from opentime_task_start")
    metadata: str | None = Field(default=None, description="Optional JSON metadata string")


class TaskTypeInput(BaseModel):
    task_type: str = Field(description="The task type to query")


class OptionalTaskTypeInput(BaseModel):
    task_type: str | None = Field(default=None, description="Optional filter by task type")


class RecommendTimeoutInput(BaseModel):
    task_type: str = Field(description="The task type to recommend a timeout for")
    percentile: float = Field(default=0.95, description="Percentile to use (0.0-1.0)")
    safety_margin: float = Field(default=1.2, description="Safety multiplier (e.g. 1.2 = 20% buffer)")


class CheckTimeoutInput(BaseModel):
    task_type: str = Field(description="The task type to check against")
    elapsed_seconds: float = Field(description="How many seconds the task has been running")
    timeout_seconds: float = Field(description="The timeout threshold in seconds")


class CompareApproachesInput(BaseModel):
    approaches: str = Field(
        description=(
            'JSON array of approaches, each with "name" and "steps". '
            'Steps have "task_type" and "estimated_seconds".'
        )
    )


# ── Base tool ────────────────────────────────────────────────────────────────


class OpenTimeBaseTool(BaseTool):
    """Base class for OpenTime LangChain tools."""

    base_url: str = _DEFAULT_BASE_URL
    _client: httpx.Client | None = PrivateAttr(default=None)

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self.base_url, timeout=30.0)
        return self._client

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self.client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json_body: dict | None = None) -> dict:
        resp = self.client.post(path, json=json_body)
        resp.raise_for_status()
        return resp.json()


# ── Tools ────────────────────────────────────────────────────────────────────


class OpenTimeClockNow(OpenTimeBaseTool):
    name: str = "opentime_clock_now"
    description: str = "Get the current UTC time. Returns ISO 8601 timestamp and Unix timestamp."
    args_schema: type[BaseModel] = EmptyInput

    def _run(self) -> str:
        return json.dumps(self._get("/clock/now"))


class OpenTimeTaskStart(OpenTimeBaseTool):
    name: str = "opentime_task_start"
    description: str = (
        "Start timing a task. Pass a task_type (e.g. 'code_generation', 'web_search'). "
        "Returns a correlation_id you must pass to opentime_task_end when the task completes."
    )
    args_schema: type[BaseModel] = TaskStartInput

    def _run(self, task_type: str, metadata: str | None = None) -> str:
        body: dict[str, Any] = {"task_type": task_type}
        if metadata:
            body["metadata"] = metadata
        return json.dumps(self._post("/events/task-start", json_body=body))


class OpenTimeTaskEnd(OpenTimeBaseTool):
    name: str = "opentime_task_end"
    description: str = (
        "End a timed task. Pass the same task_type and the correlation_id from opentime_task_start."
    )
    args_schema: type[BaseModel] = TaskEndInput

    def _run(self, task_type: str, correlation_id: str | None = None, metadata: str | None = None) -> str:
        body: dict[str, Any] = {"task_type": task_type}
        if correlation_id:
            body["correlation_id"] = correlation_id
        if metadata:
            body["metadata"] = metadata
        return json.dumps(self._post("/events/task-end", json_body=body))


class OpenTimeActiveTasks(OpenTimeBaseTool):
    name: str = "opentime_active_tasks"
    description: str = "List all tasks that have been started but not yet ended."
    args_schema: type[BaseModel] = OptionalTaskTypeInput

    def _run(self, task_type: str | None = None) -> str:
        params = {"task_type": task_type} if task_type else None
        return json.dumps(self._get("/events/active", params=params))


class OpenTimeGetStats(OpenTimeBaseTool):
    name: str = "opentime_get_stats"
    description: str = (
        "Get duration statistics (mean, median, p95, min, max) for a task type. "
        "Only works after you have completed at least one task of that type."
    )
    args_schema: type[BaseModel] = TaskTypeInput

    def _run(self, task_type: str) -> str:
        return json.dumps(self._get(f"/stats/durations/{task_type}"))


class OpenTimeRecommendTimeout(OpenTimeBaseTool):
    name: str = "opentime_recommend_timeout"
    description: str = (
        "Get a recommended timeout for a task type based on historical durations. "
        "Uses p95 with a 20% safety margin by default."
    )
    args_schema: type[BaseModel] = RecommendTimeoutInput

    def _run(self, task_type: str, percentile: float = 0.95, safety_margin: float = 1.2) -> str:
        return json.dumps(self._get(
            f"/stats/recommend-timeout/{task_type}",
            params={"percentile": percentile, "safety_margin": safety_margin},
        ))


class OpenTimeCheckTimeout(OpenTimeBaseTool):
    name: str = "opentime_check_timeout"
    description: str = (
        "Check if a running task is at risk of exceeding its timeout, based on historical durations."
    )
    args_schema: type[BaseModel] = CheckTimeoutInput

    def _run(self, task_type: str, elapsed_seconds: float, timeout_seconds: float) -> str:
        return json.dumps(self._get(
            f"/stats/check-timeout/{task_type}",
            params={"elapsed_seconds": elapsed_seconds, "timeout_seconds": timeout_seconds},
        ))


class OpenTimeCompareApproaches(OpenTimeBaseTool):
    name: str = "opentime_compare_approaches"
    description: str = (
        "Compare multiple approaches to a problem using historical task duration data. "
        "Pass approaches as a JSON string with a list of objects, each with 'name' and 'steps'."
    )
    args_schema: type[BaseModel] = CompareApproachesInput

    def _run(self, approaches: str) -> str:
        parsed = json.loads(approaches)
        return json.dumps(self._post("/stats/compare-approaches", json_body={"approaches": parsed}))


# ── Convenience ──────────────────────────────────────────────────────────────


_TOOL_CLASSES = [
    OpenTimeClockNow,
    OpenTimeTaskStart,
    OpenTimeTaskEnd,
    OpenTimeActiveTasks,
    OpenTimeGetStats,
    OpenTimeRecommendTimeout,
    OpenTimeCheckTimeout,
    OpenTimeCompareApproaches,
]


def get_opentime_tools(base_url: str = _DEFAULT_BASE_URL) -> list[BaseTool]:
    """Return all OpenTime tools configured to talk to the given REST API base URL.

    Usage::

        from opentime.integrations.langchain import get_opentime_tools
        tools = get_opentime_tools()
        agent = create_react_agent(llm, tools)
    """
    return [cls(base_url=base_url) for cls in _TOOL_CLASSES]
