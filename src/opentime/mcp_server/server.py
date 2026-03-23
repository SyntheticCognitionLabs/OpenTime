from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import Context, FastMCP

from opentime.core.clock import ClockService
from opentime.core.events import EventTracker
from opentime.core.stats import DurationStats
from opentime.db.connection import close_database, open_database


@dataclass
class AppContext:
    clock: ClockService
    events: EventTracker
    stats: DurationStats


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    db_path = os.environ.get("OPENTIME_DB_PATH", "opentime.db")
    agent_id = os.environ.get("OPENTIME_AGENT_ID", "default")
    conn = open_database(db_path)
    try:
        yield AppContext(
            clock=ClockService(),
            events=EventTracker(conn, agent_id),
            stats=DurationStats(conn, agent_id),
        )
    finally:
        close_database(conn)


mcp = FastMCP(
    "OpenTime",
    instructions=(
        "OpenTime gives you temporal awareness. Use these tools PROACTIVELY on every task:\n"
        "1. Call event_task_start at the beginning of every task — save the correlation_id.\n"
        "2. Call event_task_end when done — pass the correlation_id to pair start/end.\n"
        "3. Before setting timeouts, call stats_recommend_timeout for a data-driven value.\n"
        "4. When choosing between approaches, call stats_compare_approaches.\n"
        "5. Use consistent task_type names (e.g. 'code_generation', 'debugging', 'test_run').\n"
        "Do NOT wait to be asked — track time automatically on all tasks."
    ),
    lifespan=app_lifespan,
)


def _ctx(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context


def _serialize_metadata(metadata: str | dict | None) -> str | None:
    if isinstance(metadata, dict):
        return json.dumps(metadata)
    return metadata


# ── Clock tools ──────────────────────────────────────────────────────────────


@mcp.tool()
def clock_now(ctx: Context) -> dict:
    """Get the current UTC wall-clock time. Use this to know what time it is right now."""
    app = _ctx(ctx)
    return {"now": app.clock.now(), "unix": app.clock.now_unix()}


@mcp.tool()
def clock_elapsed_since(timestamp: str, ctx: Context) -> dict:
    """Get how many seconds have elapsed since the given ISO 8601 timestamp."""
    app = _ctx(ctx)
    return {"elapsed_seconds": round(app.clock.elapsed_since(timestamp), 3), "since": timestamp}


# ── Stopwatch tools ──────────────────────────────────────────────────────────


@mcp.tool()
def stopwatch_start(name: str, ctx: Context) -> dict:
    """Start a named stopwatch to time an operation."""
    app = _ctx(ctx)
    started_at = app.clock.start_stopwatch(name)
    return {"name": name, "started_at": started_at}


@mcp.tool()
def stopwatch_read(name: str, ctx: Context) -> dict:
    """Read a running stopwatch without stopping it."""
    app = _ctx(ctx)
    elapsed = app.clock.read_stopwatch(name)
    return {"name": name, "elapsed_seconds": round(elapsed, 3), "is_running": True}


@mcp.tool()
def stopwatch_stop(name: str, ctx: Context) -> dict:
    """Stop a named stopwatch and get the final elapsed time."""
    app = _ctx(ctx)
    elapsed = app.clock.stop_stopwatch(name)
    return {"name": name, "elapsed_seconds": round(elapsed, 3), "is_running": False}


@mcp.tool()
def stopwatch_list(ctx: Context) -> dict:
    """List all stopwatches and their current state."""
    app = _ctx(ctx)
    return {"stopwatches": app.clock.list_stopwatches()}


@mcp.tool()
def stopwatch_delete(name: str, ctx: Context) -> dict:
    """Delete a named stopwatch."""
    app = _ctx(ctx)
    app.clock.delete_stopwatch(name)
    return {"deleted": name}


# ── Event tools ──────────────────────────────────────────────────────────────


def _event_to_dict(e) -> dict:
    return {
        "id": e.id,
        "event_type": e.event_type,
        "task_type": e.task_type,
        "timestamp": e.timestamp,
        "metadata": e.metadata,
        "correlation_id": e.correlation_id,
    }


@mcp.tool()
def event_record(event_type: str, ctx: Context, task_type: str | None = None, metadata: str | None = None) -> dict:
    """Record a timestamped event. Use event_type to classify it (e.g., 'message_sent', 'subprocess_launched')."""
    app = _ctx(ctx)
    event = app.events.record_event(event_type, task_type=task_type, metadata=_serialize_metadata(metadata))
    return {"event": _event_to_dict(event)}


@mcp.tool()
def event_task_start(task_type: str, ctx: Context, metadata: str | None = None) -> dict:
    """Record that a task has started. Returns a correlation_id — pass it to event_task_end to pair them."""
    app = _ctx(ctx)
    event = app.events.record_task_start(task_type, metadata=_serialize_metadata(metadata))
    return {"event": _event_to_dict(event), "correlation_id": event.correlation_id}


@mcp.tool()
def event_task_end(
    task_type: str, ctx: Context, correlation_id: str | None = None, metadata: str | None = None,
) -> dict:
    """Record that a task has ended. Pass the correlation_id from event_task_start for correct pairing."""
    app = _ctx(ctx)
    event = app.events.record_task_end(task_type, metadata=_serialize_metadata(metadata), correlation_id=correlation_id)
    return {"event": _event_to_dict(event)}


@mcp.tool()
def event_list(
    ctx: Context,
    event_type: str | None = None,
    task_type: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict:
    """Query recorded events with optional filters."""
    app = _ctx(ctx)
    events = app.events.get_events(event_type=event_type, task_type=task_type, since=since, limit=limit)
    return {"events": [_event_to_dict(e) for e in events]}


@mcp.tool()
def event_get(event_id: str, ctx: Context) -> dict:
    """Get a single event by its ID."""
    app = _ctx(ctx)
    event = app.events.get_event(event_id)
    if event is None:
        return {"event": None}
    return {"event": _event_to_dict(event)}


@mcp.tool()
def event_active_tasks(ctx: Context, task_type: str | None = None) -> dict:
    """List tasks that have been started but not yet ended."""
    app = _ctx(ctx)
    events = app.events.get_active_tasks(task_type=task_type)
    return {"active_tasks": [_event_to_dict(e) for e in events]}


# ── Stats tools ──────────────────────────────────────────────────────────────


def _summary_to_dict(s) -> dict:
    return {
        "task_type": s.task_type,
        "count": s.count,
        "mean_seconds": s.mean_seconds,
        "median_seconds": s.median_seconds,
        "p95_seconds": s.p95_seconds,
        "min_seconds": s.min_seconds,
        "max_seconds": s.max_seconds,
    }


@mcp.tool()
def stats_duration(task_type: str, ctx: Context) -> dict:
    """Get duration statistics (mean, median, p95) for a task type.
    Only works if you've recorded paired task_start/task_end events."""
    app = _ctx(ctx)
    summary = app.stats.summarize(task_type)
    if summary is None:
        return {"summary": None, "message": f"No completed tasks found for type '{task_type}'"}
    return {"summary": _summary_to_dict(summary)}


@mcp.tool()
def stats_list_task_types(ctx: Context) -> dict:
    """List all task types that have recorded events."""
    app = _ctx(ctx)
    return {"task_types": app.stats.list_task_types()}


@mcp.tool()
def stats_all(ctx: Context) -> dict:
    """Get duration statistics for all known task types."""
    app = _ctx(ctx)
    summaries = app.stats.summarize_all()
    return {"summaries": [_summary_to_dict(s) for s in summaries]}


@mcp.tool()
def stats_recommend_timeout(
    task_type: str, ctx: Context, percentile: float = 0.95, safety_margin: float = 1.2,
) -> dict:
    """Recommend a timeout for a task type based on historical durations.
    Uses the given percentile (default p95) with a safety margin (default 20% buffer)."""
    app = _ctx(ctx)
    result = app.stats.recommend_timeout(task_type, percentile=percentile, safety_margin=safety_margin)
    if result is None:
        return {"recommendation": None, "message": f"No completed tasks found for type '{task_type}'"}
    return {"recommendation": result}


@mcp.tool()
def stats_check_timeout(
    task_type: str, elapsed_seconds: float, timeout_seconds: float, ctx: Context,
) -> dict:
    """Check if a running task is at risk of exceeding its timeout, based on historical durations."""
    app = _ctx(ctx)
    result = app.stats.check_timeout_risk(task_type, elapsed_seconds, timeout_seconds)
    if result is None:
        return {"risk": None, "message": f"No completed tasks found for type '{task_type}'"}
    return {"risk": result}


@mcp.tool()
def stats_compare_approaches(approaches: str, ctx: Context) -> dict:
    """Compare multiple approaches to find the fastest based on your historical task durations.

    Pass approaches as a JSON string: a list of objects, each with "name" (string) and
    "steps" (list of {"task_type": string, "estimated_seconds": number}).

    Steps with historical data get their estimates replaced with your actual median duration.
    Returns approaches ranked fastest-first with a recommendation."""
    app = _ctx(ctx)
    parsed = json.loads(approaches)
    return app.stats.compare_approaches(parsed)


# ── Entry point ──────────────────────────────────────────────────────────────


def run():
    mcp.run()


if __name__ == "__main__":
    run()
