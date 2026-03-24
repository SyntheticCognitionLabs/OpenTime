# OpenTime

**Temporal awareness and time-effort estimation for AI agents.**

[![PyPI version](https://badge.fury.io/py/opentime.svg)](https://pypi.org/project/opentime/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docs](https://img.shields.io/badge/docs-syntheticcognitionlabs.github.io-blue)](https://syntheticcognitionlabs.github.io/OpenTime/)

**[Documentation](https://syntheticcognitionlabs.github.io/OpenTime/)** | **[PyPI](https://pypi.org/project/opentime/)** | **[GitHub](https://github.com/SyntheticCognitionLabs/OpenTime)**

---

## The Problem

AI agents have no concept of time. Their time intuition comes from LLM training data calibrated to **human speed**, not agent speed. This causes real problems:

- **Bad timeouts**: An agent sets a 60-minute timeout on a download that takes 65 minutes. It times out at 98% completion, losing all progress and doubling the total time.
- **Wrong decisions**: An agent chooses a 23-hour approach over a 9-hour approach because it estimates coding time at human speed — but the coding portion takes minutes, not hours, for an agent.
- **No self-awareness**: An agent has no idea how long it actually takes to complete tasks, how long it's been running, or when the last user interaction was.

## The Solution

OpenTime gives any AI agent the ability to:

- **Track time** — wall clock, elapsed time, stopwatches
- **Record events** — task start/end with automatic correlation IDs for overlapping tasks
- **Learn duration estimates** — per-agent, per-task-type statistics (mean, median, p95)
- **Get timeout recommendations** — "Based on your history, set a 45-second timeout for this task"
- **Compare approaches** — "The 'hard way' actually saves 17 hours given your coding speed"
- **Passive tracking** — automatically record tool usage durations via hooks (no agent action needed)

Each agent builds its own time-task database over time, learning its actual capabilities rather than relying on human-calibrated estimates.

## Installation

```bash
pip install opentime
```

With REST API support:
```bash
pip install opentime[rest]
```

## Integration Options

OpenTime works with any AI agent through multiple interfaces:

| Interface | Best For | Requires Agent Awareness? |
|-----------|----------|--------------------------|
| **MCP Server** | Claude Code, Claude Desktop, Cursor, Windsurf, Cline | Yes (agent calls tools) |
| **REST API** | Custom agents, any HTTP client | Yes (agent calls endpoints) |
| **Docker** | Any environment — no Python install needed | Yes (agent calls endpoints) |
| **LangChain** | LangChain / LangGraph agents | Yes (native tools) |
| **OpenAI / Gemini** | GPT-4, Assistants, Gemini function calling | Yes (function schemas) |
| **OpenAPI Spec** | Any framework with OpenAPI support | Yes (auto-discovered) |
| **Hooks** | Claude Code passive tracking | No (fully automatic) |

### Option 1: MCP Server

For any MCP-compatible client (Claude Code, Claude Desktop, Cursor, Windsurf, etc.):

```json
{
  "mcpServers": {
    "opentime": {
      "command": "opentime-mcp",
      "env": {
        "OPENTIME_DB_PATH": "~/.opentime/agent.db",
        "OPENTIME_AGENT_ID": "my-agent"
      }
    }
  }
}
```

The agent gets access to 21 tools for time tracking, event recording, and duration statistics.

### Option 2: Docker (Recommended for Quick Start)

No Python environment needed — just Docker:

```bash
# One command to start
docker compose up -d

# Or without compose
docker run -d -p 8080:8080 -v opentime-data:/data opentime:latest
```

The REST API is immediately available at `http://localhost:8080` with Swagger docs at `http://localhost:8080/docs`.

To build from source:
```bash
git clone https://github.com/SyntheticCognitionLabs/OpenTime.git
cd OpenTime
docker compose up -d
```

### Option 3: REST API (pip install)

For any agent that can make HTTP calls — ChatGPT custom actions, Gemini function calling, LangChain tools, AutoGPT, CrewAI, or your own agents:

```bash
# Start the server
opentime-rest
# Or with custom settings
OPENTIME_DB_PATH=~/.opentime/agent.db OPENTIME_AGENT_ID=my-agent opentime-rest
```

The API runs at `http://127.0.0.1:8080` with interactive docs at `/docs` (Swagger UI).

**Example: Record a task and get stats**

```bash
# Start a task
curl -X POST http://localhost:8080/events/task-start \
  -H "Content-Type: application/json" \
  -d '{"task_type": "code_generation"}'
# Returns: {"event": {...}, "correlation_id": "abc123..."}

# End the task (pass the correlation_id back)
curl -X POST http://localhost:8080/events/task-end \
  -H "Content-Type: application/json" \
  -d '{"task_type": "code_generation", "correlation_id": "abc123..."}'

# Get duration statistics
curl http://localhost:8080/stats/durations/code_generation
# Returns: {"summary": {"count": 15, "mean_seconds": 8.2, "median_seconds": 7.5, ...}}

# Get a timeout recommendation
curl http://localhost:8080/stats/recommend-timeout/code_generation
# Returns: {"recommendation": {"recommended_seconds": 18.6, "percentile": 0.95, ...}}
```

### Option 4: Passive Hooks (Claude Code)

For fully automatic time tracking with zero agent involvement:

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "",
      "hooks": [{"type": "command", "command": "python -m opentime.hooks.claude_code"}]
    }],
    "PostToolUse": [{
      "matcher": "",
      "hooks": [{"type": "command", "command": "python -m opentime.hooks.claude_code"}]
    }],
    "Stop": [{
      "hooks": [{"type": "command", "command": "python -m opentime.hooks.claude_code"}]
    }]
  }
}
```

Every tool call is automatically timed and recorded. Query the data later:

```python
from opentime.db.connection import open_database
from opentime.core.stats import DurationStats

conn = open_database("~/.opentime/claude-code.db")
stats = DurationStats(conn, "claude-code")

# How long do Bash commands take?
print(stats.summarize("tool:Bash"))

# How long do file edits take?
print(stats.summarize("tool:Edit"))
```

### Option 5: LangChain Integration

For LangChain / LangGraph agents:

```bash
pip install opentime[langchain]
```

```python
from opentime.integrations.langchain import get_opentime_tools

tools = get_opentime_tools()  # base_url defaults to http://localhost:8080
agent = create_react_agent(llm, tools)
```

Provides 8 LangChain-compatible tools with full `args_schema` for structured tool calling. Start the REST API server first (`opentime-rest` or `docker compose up -d`).

### Option 6: OpenAI / Gemini Function Calling

For OpenAI GPT-4, Assistants API, or Google Gemini — zero additional dependencies:

```python
import json
from opentime.integrations.openai_schema import get_opentime_functions, handle_function_call

# Pass function schemas to the model
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
```

### Option 7: OpenAPI Spec (Universal)

Any framework that supports OpenAPI can auto-discover all endpoints:

```
http://localhost:8080/openapi.json
```

Use it with ChatGPT custom GPT actions, AutoGPT, CrewAI, or any framework with OpenAPI tool discovery.

## Agent Prompt Templates

For agents to use OpenTime proactively (without being asked), add the OpenTime instructions to your agent's system prompt:

```python
from opentime.prompts import get_system_prompt

# For MCP-connected agents (Claude Code, Cursor, etc.)
prompt = get_system_prompt("mcp")

# For OpenAI function calling or Gemini
prompt = get_system_prompt("openai")

# For agents calling the REST API directly
prompt = get_system_prompt("rest_api", base_url="http://localhost:8080")

# Append to your agent's system prompt
system_prompt = f"You are a helpful assistant.\n\n{prompt}"
```

The prompts instruct the agent to:
- Track every task with `task_start` / `task_end` and correlation IDs
- Check `recommend_timeout` before setting any timeout or deadline
- Use `compare_approaches` when choosing between methods
- Use consistent `task_type` names for accurate statistics

Available modes: `"mcp"`, `"function_calling"`, `"openai"`, `"gemini"`, `"rest_api"`, `"rest"`

## MCP Tools Reference

**Clock** (2 tools)
| Tool | Description |
|------|-------------|
| `clock_now` | Current UTC time as ISO 8601 |
| `clock_elapsed_since` | Seconds elapsed since a timestamp |

**Stopwatch** (5 tools)
| Tool | Description |
|------|-------------|
| `stopwatch_start` | Start a named stopwatch |
| `stopwatch_read` | Read elapsed time without stopping |
| `stopwatch_stop` | Stop and get final elapsed time |
| `stopwatch_list` | List all stopwatches |
| `stopwatch_delete` | Delete a stopwatch |

**Events** (6 tools)
| Tool | Description |
|------|-------------|
| `event_record` | Record a generic timestamped event |
| `event_task_start` | Start a task (returns correlation_id) |
| `event_task_end` | End a task (pass correlation_id to pair) |
| `event_list` | Query events with filters |
| `event_get` | Get a single event by ID |
| `event_active_tasks` | List started-but-not-ended tasks |

**Statistics** (6 tools)
| Tool | Description |
|------|-------------|
| `stats_duration` | Duration stats (mean, median, p95) for a task type |
| `stats_list_task_types` | List all task types with data |
| `stats_all` | Stats for all task types |
| `stats_recommend_timeout` | Recommend a timeout based on historical durations |
| `stats_check_timeout` | Check if a running task is at risk of timeout |
| `stats_compare_approaches` | Compare approaches using actual historical speed |

## REST API Endpoints

All MCP tools are mirrored as REST endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/clock/now` | Current time |
| GET | `/clock/elapsed?since=` | Elapsed time |
| POST | `/stopwatch/{name}/start` | Start stopwatch |
| GET | `/stopwatch/{name}` | Read stopwatch |
| POST | `/stopwatch/{name}/stop` | Stop stopwatch |
| GET | `/stopwatches` | List stopwatches |
| DELETE | `/stopwatch/{name}` | Delete stopwatch |
| POST | `/events` | Record event |
| POST | `/events/task-start` | Start task |
| POST | `/events/task-end` | End task |
| GET | `/events/active` | Active tasks |
| GET | `/events` | List events |
| GET | `/events/{id}` | Get event |
| GET | `/stats/durations/{task_type}` | Duration stats |
| GET | `/stats/task-types` | List task types |
| GET | `/stats/durations` | All stats |
| GET | `/stats/recommend-timeout/{task_type}` | Timeout recommendation |
| GET | `/stats/check-timeout/{task_type}` | Timeout risk check |
| POST | `/stats/compare-approaches` | Compare approaches |

## Configuration

OpenTime is configured via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENTIME_DB_PATH` | `opentime.db` | Path to the SQLite database file |
| `OPENTIME_AGENT_ID` | `default` | Unique identifier for this agent |
| `OPENTIME_HOST` | `127.0.0.1` | REST API host |
| `OPENTIME_PORT` | `8080` | REST API port |

## Architecture

```
MCP Server / REST API        <- thin wrappers, no business logic
        |
        v
+------------------------+
|   ClockService         |  <- stateless, in-memory stopwatches
|   EventTracker         |--> db.queries --> SQLite (per-agent)
|   DurationStats        |--> db.queries --> SQLite (per-agent)
+------------------------+
```

- **Core layer** (`opentime.core`) — all business logic, fully decoupled from transport
- **DB layer** (`opentime.db`) — SQLite schema, connections, migrations, parameterized queries
- **MCP server** (`opentime.mcp_server`) — FastMCP tool registrations with lifespan-managed state
- **REST API** (`opentime.rest_api`) — FastAPI endpoints mirroring MCP tools
- **Hooks** (`opentime.hooks`) — passive tracking integrations (Claude Code)

## Development

```bash
# Setup
git clone https://github.com/SyntheticCognitionLabs/OpenTime.git
cd OpenTime
python3 -m venv .venv && .venv/bin/pip install -e ".[all]"

# Tests
.venv/bin/pytest -v                    # 109 tests

# Lint
.venv/bin/ruff check src/ tests/
```

## License

MIT
