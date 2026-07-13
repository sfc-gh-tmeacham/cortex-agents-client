# Live Integration Tests

End-to-end tests that run against a real Snowflake account. They are gated behind
`@pytest.mark.live` and skipped by default in CI.

---

## Prerequisites

### 1 — Snowflake account access

You need a Snowflake account with:
- A role (`app_owner_role` in the seed scripts — substitute your own) with
  `CREATE CORTEX AGENT`, `CREATE CORTEX SEARCH SERVICE`, and `CREATE TABLE` on the
  target database/schema
- A PAT token for that role (generate in Snowsight under
  **Governance & security → Users & roles → your user → Programmatic access tokens**)

### 2 — Seed the test environment

Run the seed scripts in order. Adjust the database, schema, warehouse, and role names
to match your account:

```bash
# 1. Create the minimal LLM-only agent (required for all live tests)
snow sql -f tests/live/seed/01_minimal_agent.sql

# 2. Create the test corpus table and Cortex Search service
snow sql -f tests/live/seed/02_search_service.sql

# 3. Create the full Cortex Search agent (required for test_runs_full.py)
snow sql -f tests/live/seed/03_full_agent.sql
```

The Cortex Search service targets `TARGET_LAG = '1 minute'` — wait at least one minute
after running `02_search_service.sql` before running `test_runs_full.py`, so the index
is populated.

---

## Environment variables

| Variable | Required for | Description |
|---|---|---|
| `SNOWFLAKE_ACCOUNT_URL` | All tests | `https://myorg-myaccount.snowflakecomputing.com` |
| `SNOWFLAKE_PAT` | All tests | PAT token for `app_owner_role` |
| `LIVE_AGENT_MINIMAL` | All tests | Fully-qualified path to the minimal agent, e.g. `live_test_db.live_test_schema.minimal_agent` |
| `LIVE_AGENT_FULL` | `test_runs_full.py` only | Fully-qualified path to the full agent. Tests in that file are automatically skipped if this variable is absent. |

---

## Running the tests

```bash
# Minimal tests only (test_auth, test_threads, test_runs)
SNOWFLAKE_ACCOUNT_URL="https://myorg-myaccount.snowflakecomputing.com" \
SNOWFLAKE_PAT="v2:..." \
LIVE_AGENT_MINIMAL="live_test_db.live_test_schema.minimal_agent" \
  uv run pytest tests/live/ -m live -v

# Full suite (includes Cortex Search tool-use tests)
SNOWFLAKE_ACCOUNT_URL="https://myorg-myaccount.snowflakecomputing.com" \
SNOWFLAKE_PAT="v2:..." \
LIVE_AGENT_MINIMAL="live_test_db.live_test_schema.minimal_agent" \
LIVE_AGENT_FULL="live_test_db.live_test_schema.full_agent" \
  uv run pytest tests/live/ -m live -v

# Single file
  uv run pytest tests/live/test_auth.py -m live -v
```

To run all tests *except* live:

```bash
uv run pytest tests/ -m "not live" -v
```

---

## Thread cleanup

Each test creates threads tagged `origin_application='live_test'` and deletes them on
teardown (best-effort). If a test run is interrupted (e.g. `Ctrl+C`), leaked threads
can be swept with:

```bash
SNOWFLAKE_ACCOUNT_URL="https://..." SNOWFLAKE_PAT="v2:..." \
  uv run python tests/live/seed/cleanup_leaked_threads.py
```

---

## Test files

| File | Agent | What it tests |
|---|---|---|
| `test_auth.py` | minimal | PAT auth success; bad token → `AuthError`; missing agent → `AgentNotFoundError` |
| `test_threads.py` | minimal | Create, get, list, delete, fork, latest_context |
| `test_runs.py` | minimal | Streaming events, ResponseEvent status, TextEvent, MetadataEvent, token usage, non-streaming run, multi-turn |
| `test_runs_full.py` | full | ToolUseEvent, ToolResultEvent, TextAnnotationEvent, citation doc_id/title |
