from opentime.db import queries


def test_insert_and_select_event(db_conn):
    queries.insert_event(db_conn, "evt1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None)
    rows = queries.select_events(db_conn, "agent-a")
    assert len(rows) == 1
    assert rows[0][0] == "evt1"
    assert rows[0][2] == "task_start"
    assert rows[0][3] == "coding"


def test_select_event_by_id(db_conn):
    queries.insert_event(db_conn, "evt2", "agent-a", "task_end", "coding", "2026-01-01T00:01:00+00:00", None)
    row = queries.select_event_by_id(db_conn, "evt2")
    assert row is not None
    assert row[0] == "evt2"

    missing = queries.select_event_by_id(db_conn, "nonexistent")
    assert missing is None


def test_select_events_filtered(db_conn):
    queries.insert_event(db_conn, "e1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None)
    queries.insert_event(db_conn, "e2", "agent-a", "task_end", "coding", "2026-01-01T00:01:00+00:00", None)
    queries.insert_event(db_conn, "e3", "agent-a", "message_sent", None, "2026-01-01T00:02:00+00:00", None)

    starts = queries.select_events(db_conn, "agent-a", event_type="task_start")
    assert len(starts) == 1
    assert starts[0][0] == "e1"

    coding = queries.select_events(db_conn, "agent-a", task_type="coding")
    assert len(coding) == 2


def test_select_events_since(db_conn):
    queries.insert_event(db_conn, "e1", "agent-a", "task_start", "x", "2026-01-01T00:00:00+00:00", None)
    queries.insert_event(db_conn, "e2", "agent-a", "task_start", "x", "2026-01-02T00:00:00+00:00", None)

    recent = queries.select_events(db_conn, "agent-a", since="2026-01-01T12:00:00+00:00")
    assert len(recent) == 1
    assert recent[0][0] == "e2"


def test_select_events_limit(db_conn):
    for i in range(10):
        queries.insert_event(db_conn, f"e{i}", "agent-a", "task_start", "x", f"2026-01-01T00:{i:02d}:00+00:00", None)

    limited = queries.select_events(db_conn, "agent-a", limit=3)
    assert len(limited) == 3


def test_compute_task_durations(db_conn):
    queries.insert_event(db_conn, "s1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None)
    queries.insert_event(db_conn, "e1", "agent-a", "task_end", "coding", "2026-01-01T00:00:10+00:00", None)
    queries.insert_event(db_conn, "s2", "agent-a", "task_start", "coding", "2026-01-01T00:01:00+00:00", None)
    queries.insert_event(db_conn, "e2", "agent-a", "task_end", "coding", "2026-01-01T00:01:30+00:00", None)

    durations = queries.compute_task_durations(db_conn, "agent-a", "coding")
    assert len(durations) == 2
    assert durations[0] == 10.0
    assert durations[1] == 30.0


def test_distinct_task_types(db_conn):
    queries.insert_event(db_conn, "e1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None)
    queries.insert_event(db_conn, "e2", "agent-a", "task_start", "download", "2026-01-01T00:01:00+00:00", None)
    queries.insert_event(db_conn, "e3", "agent-a", "message_sent", None, "2026-01-01T00:02:00+00:00", None)

    types = queries.distinct_task_types(db_conn, "agent-a")
    assert set(types) == {"coding", "download"}


def test_insert_event_with_correlation_id(db_conn):
    queries.insert_event(db_conn, "e1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None, "cid-1")
    row = queries.select_event_by_id(db_conn, "e1")
    assert row[6] == "cid-1"  # correlation_id is the 7th column


def test_compute_task_durations_with_correlation_ids(db_conn):
    """Two overlapping tasks of the same type, correctly paired by correlation_id."""
    # Task A: starts at :00, ends at :20 → 20s
    queries.insert_event(
        db_conn, "s1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None, "cid-a"
    )
    # Task B: starts at :05, ends at :10 → 5s (overlaps with A)
    queries.insert_event(
        db_conn, "s2", "agent-a", "task_start", "coding", "2026-01-01T00:00:05+00:00", None, "cid-b"
    )
    queries.insert_event(
        db_conn, "e2", "agent-a", "task_end", "coding", "2026-01-01T00:00:10+00:00", None, "cid-b"
    )
    queries.insert_event(
        db_conn, "e1", "agent-a", "task_end", "coding", "2026-01-01T00:00:20+00:00", None, "cid-a"
    )

    durations = queries.compute_task_durations(db_conn, "agent-a", "coding")
    assert sorted(durations) == [5.0, 20.0]


def test_compute_task_durations_legacy_fallback(db_conn):
    """Events without correlation_ids still pair chronologically."""
    queries.insert_event(db_conn, "s1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None)
    queries.insert_event(db_conn, "e1", "agent-a", "task_end", "coding", "2026-01-01T00:00:10+00:00", None)

    durations = queries.compute_task_durations(db_conn, "agent-a", "coding")
    assert durations == [10.0]


def test_compute_task_durations_mixed(db_conn):
    """Mix of correlated and uncorrelated events."""
    # Correlated pair: 15s
    queries.insert_event(
        db_conn, "s1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None, "cid-x"
    )
    queries.insert_event(
        db_conn, "e1", "agent-a", "task_end", "coding", "2026-01-01T00:00:15+00:00", None, "cid-x"
    )
    # Uncorrelated pair: 10s
    queries.insert_event(db_conn, "s2", "agent-a", "task_start", "coding", "2026-01-01T00:01:00+00:00", None)
    queries.insert_event(db_conn, "e2", "agent-a", "task_end", "coding", "2026-01-01T00:01:10+00:00", None)

    durations = queries.compute_task_durations(db_conn, "agent-a", "coding")
    assert sorted(durations) == [10.0, 15.0]


def test_select_active_tasks(db_conn):
    # Active task (started, not ended)
    queries.insert_event(
        db_conn, "s1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None, "cid-1"
    )
    # Completed task (started and ended)
    queries.insert_event(
        db_conn, "s2", "agent-a", "task_start", "coding", "2026-01-01T00:01:00+00:00", None, "cid-2"
    )
    queries.insert_event(
        db_conn, "e2", "agent-a", "task_end", "coding", "2026-01-01T00:01:30+00:00", None, "cid-2"
    )

    active = queries.select_active_tasks(db_conn, "agent-a")
    assert len(active) == 1
    assert active[0][6] == "cid-1"  # correlation_id

    # Filter by task_type
    queries.insert_event(
        db_conn, "s3", "agent-a", "task_start", "download", "2026-01-01T00:02:00+00:00", None, "cid-3"
    )
    active_coding = queries.select_active_tasks(db_conn, "agent-a", task_type="coding")
    assert len(active_coding) == 1
    active_all = queries.select_active_tasks(db_conn, "agent-a")
    assert len(active_all) == 2


# ── Cross-agent query tests ─────────────────────────────────────────────────


def test_select_events_cross_agent(db_conn):
    """agent_id=None returns events from all agents."""
    queries.insert_event(db_conn, "e1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None)
    queries.insert_event(db_conn, "e2", "agent-b", "task_start", "coding", "2026-01-01T00:01:00+00:00", None)

    # Per-agent
    assert len(queries.select_events(db_conn, "agent-a")) == 1

    # Cross-agent
    all_events = queries.select_events(db_conn, None)
    assert len(all_events) == 2


def test_compute_task_durations_cross_agent(db_conn):
    """agent_id=None computes durations across all agents."""
    queries.insert_event(db_conn, "s1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None, "cid-a")
    queries.insert_event(db_conn, "e1", "agent-a", "task_end", "coding", "2026-01-01T00:00:10+00:00", None, "cid-a")
    queries.insert_event(db_conn, "s2", "agent-b", "task_start", "coding", "2026-01-01T00:01:00+00:00", None, "cid-b")
    queries.insert_event(db_conn, "e2", "agent-b", "task_end", "coding", "2026-01-01T00:01:20+00:00", None, "cid-b")

    # Per-agent
    assert len(queries.compute_task_durations(db_conn, "agent-a", "coding")) == 1

    # Cross-agent
    durations = queries.compute_task_durations(db_conn, None, "coding")
    assert len(durations) == 2
    assert sorted(durations) == [10.0, 20.0]


def test_distinct_task_types_cross_agent(db_conn):
    queries.insert_event(db_conn, "e1", "agent-a", "task_start", "coding", "2026-01-01T00:00:00+00:00", None)
    queries.insert_event(db_conn, "e2", "agent-b", "task_start", "testing", "2026-01-01T00:01:00+00:00", None)

    # Per-agent
    assert queries.distinct_task_types(db_conn, "agent-a") == ["coding"]

    # Cross-agent
    types = queries.distinct_task_types(db_conn, None)
    assert set(types) == {"coding", "testing"}


def test_distinct_agents(db_conn):
    queries.insert_event(db_conn, "e1", "agent-a", "test", None, "2026-01-01T00:00:00+00:00", None)
    queries.insert_event(db_conn, "e2", "agent-b", "test", None, "2026-01-01T00:01:00+00:00", None)
    queries.insert_event(db_conn, "e3", "agent-c", "test", None, "2026-01-01T00:02:00+00:00", None)

    agents = queries.distinct_agents(db_conn)
    assert agents == ["agent-a", "agent-b", "agent-c"]
