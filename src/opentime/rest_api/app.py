from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from opentime import __version__
from opentime.core.clock import ClockService
from opentime.core.events import EventTracker
from opentime.core.stats import DurationStats
from opentime.db.connection import close_database, open_database

# Module-level state initialized via lifespan
_clock: ClockService
_events: EventTracker
_stats: DurationStats
_conn = None


def _serialize_metadata(metadata: str | dict | None) -> str | None:
    if isinstance(metadata, dict):
        return json.dumps(metadata)
    return metadata


class EventCreateRequest(BaseModel):
    event_type: str
    task_type: str | None = None
    metadata: str | dict | None = None


class TaskStartRequest(BaseModel):
    task_type: str
    metadata: str | dict | None = None


class TaskEndRequest(BaseModel):
    task_type: str
    correlation_id: str | None = None
    metadata: str | dict | None = None


class ApproachStep(BaseModel):
    task_type: str
    estimated_seconds: float


class Approach(BaseModel):
    name: str
    steps: list[ApproachStep]


class CompareApproachesRequest(BaseModel):
    approaches: list[Approach]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _clock, _events, _stats, _conn
    db_path = os.environ.get("OPENTIME_DB_PATH", "opentime.db")
    agent_id = os.environ.get("OPENTIME_AGENT_ID", "default")
    _conn = open_database(db_path)
    _clock = ClockService()
    _events = EventTracker(_conn, agent_id)
    _stats = DurationStats(_conn, agent_id)
    yield
    if _conn is not None:
        close_database(_conn)


app = FastAPI(title="OpenTime", version=__version__, lifespan=lifespan)


def _event_to_dict(e) -> dict:
    return {
        "id": e.id,
        "event_type": e.event_type,
        "task_type": e.task_type,
        "timestamp": e.timestamp,
        "metadata": e.metadata,
        "correlation_id": e.correlation_id,
    }


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


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


# ── Clock ────────────────────────────────────────────────────────────────────


@app.get("/clock/now")
def api_clock_now():
    return {"now": _clock.now(), "unix": _clock.now_unix()}


@app.get("/clock/elapsed")
def api_clock_elapsed(since: str = Query(..., description="ISO 8601 timestamp")):
    return {"elapsed_seconds": round(_clock.elapsed_since(since), 3), "since": since}


# ── Stopwatches ──────────────────────────────────────────────────────────────


@app.post("/stopwatch/{name}/start")
def api_stopwatch_start(name: str):
    started_at = _clock.start_stopwatch(name)
    return {"name": name, "started_at": started_at}


@app.get("/stopwatch/{name}")
def api_stopwatch_read(name: str):
    try:
        elapsed = _clock.read_stopwatch(name)
    except KeyError as err:
        raise HTTPException(status_code=404, detail=f"No stopwatch named '{name}'") from err
    return {"name": name, "elapsed_seconds": round(elapsed, 3), "is_running": True}


@app.post("/stopwatch/{name}/stop")
def api_stopwatch_stop(name: str):
    try:
        elapsed = _clock.stop_stopwatch(name)
    except KeyError as err:
        raise HTTPException(status_code=404, detail=f"No stopwatch named '{name}'") from err
    return {"name": name, "elapsed_seconds": round(elapsed, 3), "is_running": False}


@app.get("/stopwatches")
def api_stopwatch_list():
    return {"stopwatches": _clock.list_stopwatches()}


@app.delete("/stopwatch/{name}")
def api_stopwatch_delete(name: str):
    try:
        _clock.delete_stopwatch(name)
    except KeyError as err:
        raise HTTPException(status_code=404, detail=f"No stopwatch named '{name}'") from err
    return {"deleted": name}


# ── Events ───────────────────────────────────────────────────────────────────


@app.post("/events")
def api_event_record(req: EventCreateRequest):
    event = _events.record_event(req.event_type, task_type=req.task_type, metadata=_serialize_metadata(req.metadata))
    return {"event": _event_to_dict(event)}


@app.post("/events/task-start")
def api_event_task_start(req: TaskStartRequest):
    event = _events.record_task_start(req.task_type, metadata=_serialize_metadata(req.metadata))
    return {"event": _event_to_dict(event), "correlation_id": event.correlation_id}


@app.post("/events/task-end")
def api_event_task_end(req: TaskEndRequest):
    event = _events.record_task_end(
        req.task_type, metadata=_serialize_metadata(req.metadata), correlation_id=req.correlation_id,
    )
    return {"event": _event_to_dict(event)}


# NOTE: /events/active MUST be before /events/{event_id} to avoid path collision
@app.get("/events/active")
def api_event_active_tasks(task_type: str | None = None):
    events = _events.get_active_tasks(task_type=task_type)
    return {"active_tasks": [_event_to_dict(e) for e in events]}


@app.get("/events")
def api_event_list(
    event_type: str | None = None,
    task_type: str | None = None,
    since: str | None = None,
    limit: int = Query(50, ge=1, le=1000),
):
    events = _events.get_events(event_type=event_type, task_type=task_type, since=since, limit=limit)
    return {"events": [_event_to_dict(e) for e in events]}


@app.get("/events/{event_id}")
def api_event_get(event_id: str):
    event = _events.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found")
    return {"event": _event_to_dict(event)}


# ── Stats ────────────────────────────────────────────────────────────────────


@app.get("/stats/durations/{task_type}")
def api_stats_duration(task_type: str):
    summary = _stats.summarize(task_type)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"No completed tasks found for type '{task_type}'")
    return {"summary": _summary_to_dict(summary)}


@app.get("/stats/task-types")
def api_stats_task_types():
    return {"task_types": _stats.list_task_types()}


@app.get("/stats/durations")
def api_stats_all():
    summaries = _stats.summarize_all()
    return {"summaries": [_summary_to_dict(s) for s in summaries]}


@app.get("/stats/recommend-timeout/{task_type}")
def api_stats_recommend_timeout(
    task_type: str,
    percentile: float = Query(0.95, ge=0.0, le=1.0),
    safety_margin: float = Query(1.2, ge=1.0),
):
    result = _stats.recommend_timeout(task_type, percentile=percentile, safety_margin=safety_margin)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No completed tasks found for type '{task_type}'")
    return {"recommendation": result}


@app.get("/stats/check-timeout/{task_type}")
def api_stats_check_timeout(
    task_type: str,
    elapsed_seconds: float = Query(..., ge=0.0),
    timeout_seconds: float = Query(..., gt=0.0),
):
    result = _stats.check_timeout_risk(task_type, elapsed_seconds, timeout_seconds)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No completed tasks found for type '{task_type}'")
    return {"risk": result}


@app.post("/stats/compare-approaches")
def api_stats_compare_approaches(req: CompareApproachesRequest):
    approaches = [a.model_dump() for a in req.approaches]
    return _stats.compare_approaches(approaches)


# ── Entry point ──────────────────────────────────────────────────────────────


def main():
    import uvicorn

    host = os.environ.get("OPENTIME_HOST", "127.0.0.1")
    port = int(os.environ.get("OPENTIME_PORT", "8080"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
