---
name: "live-integration-testing"
created: "2026-07-13T16:11:12.954Z"
status: pending
---

# Plan: Live Integration Testing

## Overview

Add a real end-to-end test suite in `tests/live/` that runs against a live Snowflake account. Tests are gated behind `@pytest.mark.live` and skipped unless the required env vars are present. Manual execution only for now.

---

## Seed infrastructure

Two agents are required. The seed SQL lives in `tests/live/seed/`.

### Agent 1 — minimal (LLM only)

Used for smoke tests, auth tests, thread lifecycle, streaming/non-streaming, and multi-turn. No tools — responds with plain text.

```sql
-- tests/live/seed/01_minimal_agent.sql
CREATE CORTEX AGENT IF NOT EXISTS live_test_db.live_test_schema.minimal_agent
  INSTRUCTIONS = (
    SYSTEM = 'You are a test assistant. Respond to any input with a short acknowledgement of 10 words or fewer.'
  );
GRANT USAGE ON CORTEX AGENT live_test_db.live_test_schema.minimal_agent TO ROLE app_owner_role;
```

### Agent 2 — full (Cortex Search)

Used to exercise ToolUseEvent, ToolResultEvent, TextAnnotationEvent, and citation rendering. Requires a Cortex Search service populated with a small known corpus (10–20 documents so assertions are deterministic).

```sql
-- tests/live/seed/02_search_service.sql
CREATE TABLE live_test_db.live_test_schema.docs (id INT, title VARCHAR, body VARCHAR);
INSERT INTO ... -- small fixed corpus

CREATE CORTEX SEARCH SERVICE live_test_db.live_test_schema.doc_search
  ON body ATTRIBUTES title
  WAREHOUSE = live_test_wh
  TARGET_LAG = '1 minute'
  AS SELECT id, title, body FROM live_test_db.live_test_schema.docs;

-- tests/live/seed/03_full_agent.sql
CREATE CORTEX AGENT IF NOT EXISTS live_test_db.live_test_schema.full_agent
  INSTRUCTIONS = (SYSTEM = 'Answer using the search tool.')
  TOOLS = [{"tool_spec": {"type": "cortex_search", "name": "DocSearch"}}]
  TOOL_RESOURCES = {
    "DocSearch": {
      "search_service": "live_test_db.live_test_schema.doc_search",
      "title_column": "title",
      "id_column": "id"
    }
  };
GRANT USAGE ON CORTEX AGENT live_test_db.live_test_schema.full_agent TO ROLE app_owner_role;
```

---

## Environment variables

| Variable                | Required         | Description                                      |
| ----------------------- | ---------------- | ------------------------------------------------ |
| `SNOWFLAKE_ACCOUNT_URL` | Yes              | `https://myorg-myaccount.snowflakecomputing.com` |
| `SNOWFLAKE_PAT`         | Yes              | PAT token for `app_owner_role`                   |
| `LIVE_AGENT_MINIMAL`    | Yes              | `live_test_db.live_test_schema.minimal_agent`    |
| `LIVE_AGENT_FULL`       | Yes (full tests) | `live_test_db.live_test_schema.full_agent`       |

Tests requiring `LIVE_AGENT_FULL` are skipped with `pytest.skip()` if the var is absent — minimal tests always run when the core three vars are present.

---

## File structure

```
tests/live/
├── __init__.py
├── conftest.py           — fixtures
├── seed/
│   ├── 01_minimal_agent.sql
│   ├── 02_search_service.sql
│   └── 03_full_agent.sql
├── test_auth.py          — auth smoke tests + error paths
├── test_threads.py       — thread CRUD, fork, latest_context
├── test_runs.py          — streaming, non-streaming, multi-turn (minimal agent)
├── test_runs_full.py     — tool use, citations (full agent)
└── README.md             — setup instructions
```

---

## conftest.py design

```python
ORIGIN_APP = "live_test"  # used as origin_application for all test threads

@pytest.fixture(scope="session")
def live_client():
    url = os.environ.get("SNOWFLAKE_ACCOUNT_URL") or pytest.skip("SNOWFLAKE_ACCOUNT_URL not set")
    pat = os.environ.get("SNOWFLAKE_PAT")         or pytest.skip("SNOWFLAKE_PAT not set")
    return CortexAgentsClient(url, pat)

@pytest.fixture(scope="session")
def agent_path_minimal():
    return os.environ.get("LIVE_AGENT_MINIMAL") or pytest.skip("LIVE_AGENT_MINIMAL not set")

@pytest.fixture(scope="session")
def agent_path_full():
    return os.environ.get("LIVE_AGENT_FULL") or pytest.skip("LIVE_AGENT_FULL not set")

@pytest.fixture
def live_thread(live_client):
    """Creates a thread tagged with origin_application='live_test'; deletes it on teardown."""
    thread = live_client.create_thread(origin_application=ORIGIN_APP)
    yield thread
    try:
        live_client.threads.delete(thread.thread_id)
    except Exception:
        pass  # best-effort; sweep script handles leaks
```

---

## Test cases

### test\_auth.py

- `test_pat_auth_succeeds` — `client.agents.list()` returns without raising
- `test_bad_token_raises_auth_error` — `CortexAgentsClient(url, "bad_token").agents.list()` raises `AuthError`
- `test_missing_agent_raises_not_found` — `thread.chat("DB.S.DOES_NOT_EXIST", "hi")` raises `AgentNotFoundError`

### test\_threads.py

- `test_create_and_delete` — create thread, assert `thread_id` is non-empty, delete, verify gone
- `test_list_filtered_by_origin` — create 2 threads with `origin_application=ORIGIN_APP`, list with same filter, assert both appear
- `test_get_thread` — `client.get_thread(thread_id)` returns same ID
- `test_fork` — chat once, fork at that message\_id, assert new thread has different ID
- `test_latest_context` — chat once, call `thread.latest_context()`, assert returns list

### test\_runs.py (minimal agent)

- `test_streaming_yields_text_delta` — chat, assert at least one `TextDeltaEvent` is yielded
- `test_streaming_ends_with_response_event` — assert last event is `ResponseEvent` with `status="completed"`
- `test_non_streaming_run_returns_text` — `client.run(agent, prompt)` returns `RunResult` with non-empty `.text`
- `test_multi_turn_uses_parent_message_id` — second `thread.chat()` succeeds without raising

### test\_runs\_full.py (Cortex Search agent)

- `test_tool_use_event_emitted` — chat with a query that should trigger search, assert `ToolUseEvent` in events
- `test_tool_result_event_emitted` — assert `ToolResultEvent` follows the `ToolUseEvent`
- `test_citation_annotation_emitted` — assert at least one `TextAnnotationEvent` in events

---

## Cleanup script

`tests/live/seed/cleanup_leaked_threads.py` — lists all threads with `origin_application="live_test"` and deletes them. Run manually after a test run that was interrupted:

```bash
SNOWFLAKE_ACCOUNT_URL=... SNOWFLAKE_PAT=... uv run python tests/live/seed/cleanup_leaked_threads.py
```

---

## Running the tests

```bash
# Minimal tests only
SNOWFLAKE_ACCOUNT_URL="https://..." SNOWFLAKE_PAT="v2:..." LIVE_AGENT_MINIMAL="DB.S.AGENT" \
  uv run pytest tests/live/ -m live -v

# Full suite (requires full agent)
SNOWFLAKE_ACCOUNT_URL="https://..." SNOWFLAKE_PAT="v2:..." \
  LIVE_AGENT_MINIMAL="DB.S.MINIMAL" LIVE_AGENT_FULL="DB.S.FULL" \
  uv run pytest tests/live/ -m live -v
```

---

## pytest.ini / pyproject.toml marker

```toml
[tool.pytest.ini_options]
markers = [
    "live: marks tests as requiring a real Snowflake account (deselect with -m 'not live')",
]
```
