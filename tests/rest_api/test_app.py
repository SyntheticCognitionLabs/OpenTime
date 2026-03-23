"""Tests for the REST API using FastAPI's TestClient."""

import pytest
from fastapi.testclient import TestClient

from opentime.core.clock import ClockService
from opentime.db.connection import open_database
from opentime.rest_api import app as app_module
from opentime.rest_api.app import app


@pytest.fixture(autouse=True)
def setup_app_state():
    """Initialize module-level state used by the REST API endpoints."""
    conn = open_database(None)
    app_module._clock = ClockService()
    app_module._conn = conn
    app_module._default_agent_id = "rest-test-agent"
    yield
    conn.close()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_dashboard(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "OpenTime" in resp.text
    assert "agent-select" in resp.text


def test_clock_now(client):
    resp = client.get("/clock/now")
    assert resp.status_code == 200
    data = resp.json()
    assert "now" in data
    assert "unix" in data


def test_clock_elapsed(client):
    resp = client.get("/clock/elapsed", params={"since": "2020-01-01T00:00:00+00:00"})
    assert resp.status_code == 200
    assert resp.json()["elapsed_seconds"] > 0


def test_stopwatch_flow(client):
    # Start
    resp = client.post("/stopwatch/test-sw/start")
    assert resp.status_code == 200
    assert resp.json()["name"] == "test-sw"

    # Read
    resp = client.get("/stopwatch/test-sw")
    assert resp.status_code == 200
    assert resp.json()["is_running"] is True

    # Stop
    resp = client.post("/stopwatch/test-sw/stop")
    assert resp.status_code == 200
    assert resp.json()["is_running"] is False

    # List
    resp = client.get("/stopwatches")
    assert resp.status_code == 200
    assert len(resp.json()["stopwatches"]) == 1

    # Delete
    resp = client.delete("/stopwatch/test-sw")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == "test-sw"


def test_stopwatch_not_found(client):
    resp = client.get("/stopwatch/nonexistent")
    assert resp.status_code == 404


def test_event_lifecycle(client):
    # Create
    resp = client.post("/events", json={"event_type": "message_sent", "metadata": '{"to": "user"}'})
    assert resp.status_code == 200
    event_id = resp.json()["event"]["id"]

    # List
    resp = client.get("/events")
    assert resp.status_code == 200
    assert len(resp.json()["events"]) == 1

    # Get by ID
    resp = client.get(f"/events/{event_id}")
    assert resp.status_code == 200
    assert resp.json()["event"]["id"] == event_id

    # Not found
    resp = client.get("/events/nonexistent")
    assert resp.status_code == 404


def test_task_start_end(client):
    resp = client.post("/events/task-start", json={"task_type": "coding"})
    assert resp.status_code == 200
    assert resp.json()["event"]["event_type"] == "task_start"
    assert resp.json()["correlation_id"] is not None

    cid = resp.json()["correlation_id"]
    resp = client.post("/events/task-end", json={"task_type": "coding", "correlation_id": cid})
    assert resp.status_code == 200
    assert resp.json()["event"]["event_type"] == "task_end"
    assert resp.json()["event"]["correlation_id"] == cid


def test_stats_flow(client):
    # No data yet
    resp = client.get("/stats/durations/coding")
    assert resp.status_code == 404

    # Record task pair with correlation_id
    start = client.post("/events/task-start", json={"task_type": "coding"})
    cid = start.json()["correlation_id"]
    client.post("/events/task-end", json={"task_type": "coding", "correlation_id": cid})

    # Now stats should work
    resp = client.get("/stats/durations/coding")
    assert resp.status_code == 200
    assert resp.json()["summary"]["count"] == 1

    # Task types
    resp = client.get("/stats/task-types")
    assert resp.status_code == 200
    assert "coding" in resp.json()["task_types"]

    # All stats
    resp = client.get("/stats/durations")
    assert resp.status_code == 200
    assert len(resp.json()["summaries"]) == 1


def test_events_with_filters(client):
    client.post("/events", json={"event_type": "task_start", "task_type": "coding"})
    client.post("/events", json={"event_type": "task_end", "task_type": "coding"})
    client.post("/events", json={"event_type": "message_sent"})

    # Filter by event_type
    resp = client.get("/events", params={"event_type": "task_start"})
    assert len(resp.json()["events"]) == 1

    # Filter by task_type
    resp = client.get("/events", params={"task_type": "coding"})
    assert len(resp.json()["events"]) == 2

    # Limit
    resp = client.get("/events", params={"limit": 1})
    assert len(resp.json()["events"]) == 1


def test_active_tasks_endpoint(client):
    start = client.post("/events/task-start", json={"task_type": "coding"})
    cid = start.json()["correlation_id"]

    resp = client.get("/events/active")
    assert resp.status_code == 200
    assert len(resp.json()["active_tasks"]) == 1
    assert resp.json()["active_tasks"][0]["correlation_id"] == cid

    # End the task
    client.post("/events/task-end", json={"task_type": "coding", "correlation_id": cid})
    resp = client.get("/events/active")
    assert len(resp.json()["active_tasks"]) == 0


def test_active_tasks_filter_by_type(client):
    client.post("/events/task-start", json={"task_type": "coding"})
    client.post("/events/task-start", json={"task_type": "download"})

    resp = client.get("/events/active", params={"task_type": "coding"})
    assert len(resp.json()["active_tasks"]) == 1


def test_event_create_dict_metadata(client):
    """Metadata passed as a JSON object should be stored as a JSON string."""
    resp = client.post("/events", json={"event_type": "test", "metadata": {"key": "value"}})
    assert resp.status_code == 200
    assert resp.json()["event"]["metadata"] == '{"key": "value"}'


def _create_task_pairs(client, task_type, count):
    """Helper: create count start/end pairs."""
    for _ in range(count):
        start = client.post("/events/task-start", json={"task_type": task_type})
        cid = start.json()["correlation_id"]
        client.post("/events/task-end", json={"task_type": task_type, "correlation_id": cid})


def test_recommend_timeout(client):
    _create_task_pairs(client, "coding", 5)

    resp = client.get("/stats/recommend-timeout/coding")
    assert resp.status_code == 200
    rec = resp.json()["recommendation"]
    assert rec["sample_count"] == 5
    assert rec["recommended_seconds"] > 0


def test_recommend_timeout_custom_params(client):
    _create_task_pairs(client, "coding", 5)

    resp = client.get("/stats/recommend-timeout/coding", params={"percentile": 0.5, "safety_margin": 1.5})
    assert resp.status_code == 200
    assert resp.json()["recommendation"]["percentile"] == 0.5
    assert resp.json()["recommendation"]["safety_margin"] == 1.5


def test_recommend_timeout_no_data(client):
    resp = client.get("/stats/recommend-timeout/nonexistent")
    assert resp.status_code == 404


def test_check_timeout(client):
    _create_task_pairs(client, "coding", 5)

    resp = client.get("/stats/check-timeout/coding", params={"elapsed_seconds": 5.0, "timeout_seconds": 60.0})
    assert resp.status_code == 200
    risk = resp.json()["risk"]
    assert risk["elapsed_seconds"] == 5.0
    assert risk["timeout_seconds"] == 60.0
    assert "at_risk" in risk


def test_check_timeout_no_data(client):
    resp = client.get("/stats/check-timeout/nonexistent", params={"elapsed_seconds": 5.0, "timeout_seconds": 60.0})
    assert resp.status_code == 404


def test_compare_approaches(client):
    _create_task_pairs(client, "coding", 5)

    resp = client.post("/stats/compare-approaches", json={
        "approaches": [
            {"name": "A", "steps": [{"task_type": "coding", "estimated_seconds": 3600}]},
            {"name": "B", "steps": [{"task_type": "unknown", "estimated_seconds": 100}]},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["approaches"]) == 2
    assert data["recommendation"] is not None

    # B (100s unknown) should be fastest since coding durations are near-zero in tests
    # but A's coding has historical data
    approach_a = next(a for a in data["approaches"] if a["name"] == "A")
    assert approach_a["steps"][0]["has_historical_data"] is True


def test_compare_approaches_empty(client):
    resp = client.post("/stats/compare-approaches", json={"approaches": []})
    assert resp.status_code == 200
    assert resp.json()["approaches"] == []


# ── Multi-agent tests ────────────────────────────────────────────────────────


def test_x_agent_id_header(client):
    """Events are recorded under the agent specified by X-Agent-ID header."""
    client.post(
        "/events/task-start",
        json={"task_type": "coding"},
        headers={"X-Agent-ID": "agent-alice"},
    )
    client.post(
        "/events/task-start",
        json={"task_type": "coding"},
        headers={"X-Agent-ID": "agent-bob"},
    )

    # Each agent sees only their own events
    resp = client.get("/events", headers={"X-Agent-ID": "agent-alice"})
    assert len(resp.json()["events"]) == 1

    resp = client.get("/events", headers={"X-Agent-ID": "agent-bob"})
    assert len(resp.json()["events"]) == 1


def test_default_agent_id_without_header(client):
    """Without X-Agent-ID header, uses the default agent_id from env var."""
    client.post("/events/task-start", json={"task_type": "coding"})

    resp = client.get("/events", headers={"X-Agent-ID": "rest-test-agent"})
    assert len(resp.json()["events"]) == 1


def test_list_agents(client):
    client.post("/events", json={"event_type": "test"}, headers={"X-Agent-ID": "agent-a"})
    client.post("/events", json={"event_type": "test"}, headers={"X-Agent-ID": "agent-b"})
    client.post("/events", json={"event_type": "test"}, headers={"X-Agent-ID": "agent-c"})

    resp = client.get("/agents")
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert set(agents) >= {"agent-a", "agent-b", "agent-c"}


def test_cross_agent_stats(client):
    """agent_id=* returns stats aggregated across all agents."""
    # Agent A: coding takes 10s
    start = client.post("/events/task-start", json={"task_type": "coding"}, headers={"X-Agent-ID": "agent-a"})
    cid = start.json()["correlation_id"]
    client.post(
        "/events/task-end", json={"task_type": "coding", "correlation_id": cid},
        headers={"X-Agent-ID": "agent-a"},
    )

    # Agent B: coding takes ~0s (same task type, different agent)
    start = client.post("/events/task-start", json={"task_type": "coding"}, headers={"X-Agent-ID": "agent-b"})
    cid = start.json()["correlation_id"]
    client.post(
        "/events/task-end", json={"task_type": "coding", "correlation_id": cid},
        headers={"X-Agent-ID": "agent-b"},
    )

    # Cross-agent stats should include both
    resp = client.get("/stats/durations/coding", params={"agent_id": "*"})
    assert resp.status_code == 200
    assert resp.json()["summary"]["count"] == 2

    # Per-agent stats should include only one
    resp = client.get("/stats/durations/coding", params={"agent_id": "agent-a"})
    assert resp.status_code == 200
    assert resp.json()["summary"]["count"] == 1


def test_cross_agent_task_types(client):
    client.post("/events/task-start", json={"task_type": "coding"}, headers={"X-Agent-ID": "agent-a"})
    client.post("/events/task-start", json={"task_type": "testing"}, headers={"X-Agent-ID": "agent-b"})

    resp = client.get("/stats/task-types", params={"agent_id": "*"})
    assert resp.status_code == 200
    assert set(resp.json()["task_types"]) >= {"coding", "testing"}


def test_cross_agent_recommend_timeout(client):
    """Timeout recommendation works with agent_id=*."""
    for agent in ["agent-a", "agent-b"]:
        start = client.post("/events/task-start", json={"task_type": "coding"}, headers={"X-Agent-ID": agent})
        cid = start.json()["correlation_id"]
        client.post(
            "/events/task-end", json={"task_type": "coding", "correlation_id": cid},
            headers={"X-Agent-ID": agent},
        )

    resp = client.get("/stats/recommend-timeout/coding", params={"agent_id": "*"})
    assert resp.status_code == 200
    assert resp.json()["recommendation"]["sample_count"] == 2
