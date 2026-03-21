# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenTime is an open-source Python framework that gives AI agents temporal awareness and time-effort estimation. Agents connect via MCP server or REST API to track time, record events, learn per-agent duration statistics, get timeout recommendations, and compare approaches using historical data.

**Remote:** https://github.com/transparentai-tech/OpenTime.git

## Development Commands

```bash
# Setup
python3 -m venv .venv && .venv/bin/pip install -e ".[all]"

# Tests
.venv/bin/pytest                          # full suite (109 tests)
.venv/bin/pytest tests/core/ -v           # core logic only
.venv/bin/pytest tests/db/ -v             # database layer only
.venv/bin/pytest tests/mcp_server/ -v     # MCP server tools
.venv/bin/pytest tests/rest_api/ -v       # REST API endpoints
.venv/bin/pytest tests/hooks/ -v          # hooks integration
.venv/bin/pytest tests/core/test_clock.py::test_stopwatch_start_stop  # single test

# Lint
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/

# Run servers
.venv/bin/python -m opentime.mcp_server.server   # MCP server (stdio)
.venv/bin/python -m opentime.rest_api.app         # REST API (http://127.0.0.1:8080)
```

## Architecture

```
MCP Server / REST API        ← thin wrappers, no business logic
        │
        ▼
┌───────────────────────┐
│   ClockService        │  ← stateless, in-memory stopwatches
│   EventTracker        │──► db.queries ──► SQLite (per-agent)
│   DurationStats       │──► db.queries ──► SQLite (per-agent)
└───────────────────────┘
```

- **Core layer** (`src/opentime/core/`) contains all business logic, fully decoupled from transport
- **DB layer** (`src/opentime/db/`) handles SQLite schema, connections, migrations, and parameterized queries
- **MCP server** (`src/opentime/mcp_server/server.py`) exposes 21 tools via FastMCP with lifespan-managed state
- **REST API** (`src/opentime/rest_api/app.py`) mirrors MCP tools as FastAPI endpoints
- **Hooks** (`src/opentime/hooks/claude_code.py`) provides passive tracking for Claude Code via PreToolUse/PostToolUse/Stop hooks
- Both integration layers instantiate the same core service objects — core never imports from mcp_server or rest_api

## MCP Tools (21 total)

**Clock:** `clock_now`, `clock_elapsed_since`
**Stopwatch:** `stopwatch_start`, `stopwatch_read`, `stopwatch_stop`, `stopwatch_list`, `stopwatch_delete`
**Events:** `event_record`, `event_task_start`, `event_task_end`, `event_list`, `event_get`, `event_active_tasks`
**Stats:** `stats_duration`, `stats_list_task_types`, `stats_all`, `stats_recommend_timeout`, `stats_check_timeout`, `stats_compare_approaches`

## Key Design Decisions

- Per-agent SQLite with `check_same_thread=False` (needed for FastAPI's thread pool)
- Config via env vars: `OPENTIME_DB_PATH`, `OPENTIME_AGENT_ID`, `OPENTIME_HOST`, `OPENTIME_PORT`
- `mcp` SDK is the only hard dependency; FastAPI is optional (`pip install opentime[rest]`)
- Event duration pairing uses correlation IDs (auto-generated on task_start), with chronological zip as fallback for legacy data without correlation IDs
- Schema migrations are incremental (`MIGRATIONS` dict in `schema.py`, applied automatically in `open_database()`)
- MCP tools and REST endpoints serialize dict metadata to JSON strings before passing to core
- Tests use in-memory SQLite (`:memory:`) via `db_conn` fixture in `tests/conftest.py`
