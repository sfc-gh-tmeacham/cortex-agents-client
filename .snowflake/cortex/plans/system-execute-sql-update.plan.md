---
name: "system-execute-sql-update"
created: "2026-07-13T20:35:18.271Z"
status: pending
---

# Plan: Update library for `system_execute_sql` + Live test raw capture

## Context

As of Apr 13, 2026, the Cortex Agents API replaced `cortex_analyst_text_to_sql` tool use/result blocks with `system_execute_sql`. The library currently only extracts SQL from `AnalystDeltaEvent` (event type `response.tool_result.analyst.delta`), which is no longer emitted. SQL now arrives in `ToolUseEvent.input["sql"]` when `ToolUseEvent.type == "system_execute_sql"`.

Additionally, the live tests don't capture the raw SSE stream — when tests fail, we can't see what the API actually returned without re-running with curl.

## Changes

### 1. Extract SQL from `system_execute_sql` ToolUseEvents

**Files**: `cortex_agents_client/resources/runs.py`, `cortex_agents_client/st/render.py`

In `runs.py` (stream\_and\_collect, \~line 482-488), after handling `ToolUseEvent`:

```python
elif isinstance(event, ToolUseEvent):
    result.tool_uses.append(event)
    # New: extract SQL from system_execute_sql (Apr 2026+ Cortex Analyst)
    if event.type == "system_execute_sql" and event.input.get("sql"):
        result.analyst_sql[event.tool_use_id] = event.input["sql"]
```

In `render.py` (\~line 330-334), similarly extract and store SQL from `system_execute_sql` ToolUseEvents so the Streamlit UI can display the generated SQL.

### 2. Update docstrings in `events.py`

Update `ToolUseEvent` docstring (line 292) to document `"system_execute_sql"` as the current Cortex Analyst tool type, noting the old `"cortex_analyst_text_to_sql"` is deprecated.

Update `AnalystDeltaEvent` docstring (line 426) to note this event is deprecated as of Apr 2026 and kept only for backward compatibility with older deployments.

### 3. Keep `AnalystDeltaEvent` (no removal)

The SSE parser still maps `response.tool_result.analyst.delta` → `AnalystDeltaEvent`. Keep this path alive for backward compatibility. No functional changes needed — just docstring updates.

### 4. Warehouse issue

The agent spec already has `execution_environment.warehouse: cac_live_wh`, but the API isn't using it for the new `system_execute_sql` tool type. This appears to be an upstream issue. For now:

- Document the workaround (set `DEFAULT_WAREHOUSE` on the user) in `tests/live/README.md`
- The library doesn't need changes for this — it's a server-side issue

### 5. Raw SSE capture in live tests

**New file**: `tests/live/conftest.py` additions

Add a fixture that wraps `thread.chat()` to capture both raw (event\_type, payload) pairs and parsed events. On test failure, dump the raw SSE to a JSON file in `tests/live/captures/` for post-mortem analysis. Optionally always capture when `LIVE_DUMP_EVENTS=1`.

Implementation approach:

- Add a `CapturedStream` wrapper class that tees the event iterator
- Store raw payloads on the `live_thread` fixture
- Use a pytest hook (`pytest_runtest_makereport`) to write captures on failure

### 6. Run full live suite to confirm

After all changes, re-run `tests/live/` to verify the analyst tests pass with the library extracting SQL from the new event shape.
