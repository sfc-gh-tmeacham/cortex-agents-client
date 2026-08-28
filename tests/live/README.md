# Live Integration Tests

End-to-end tests that run against a real Snowflake account. They are gated behind
`@pytest.mark.live` and skipped by default in CI.

---

## Prerequisites

### 1 — Snowflake account access

You need a Snowflake account with:
- A role (`app_owner_role` in the seed scripts — substitute your own) with
  `CREATE AGENT`, `CREATE CORTEX SEARCH SERVICE`, `CREATE SEMANTIC VIEW`, and `CREATE TABLE` on the
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

# 4. Create the sales table and semantic view (required for test_runs_analyst.py)
snow sql -f tests/live/seed/04_semantic_view.sql

# 5. Create the Cortex Analyst agent (required for test_runs_analyst.py)
snow sql -f tests/live/seed/05_analyst_agent.sql

# 6. Create the web search agent (required for test_runs_web.py)
#    Requires web search enabled at the account level first — see below.
snow sql -f tests/live/seed/06_web_search_agent.sql
```

The Cortex Search service targets `TARGET_LAG = '1 minute'` — wait at least one minute
after running `02_search_service.sql` before running `test_runs_full.py`, so the index
is populated.

**Web search prerequisite**: An ACCOUNTADMIN must enable web search before running
`test_runs_web.py`:
> Snowsight → AI & ML → Agents → Settings → Web search toggle → ON

---

## Environment variables

| Variable | Required for | Description |
|---|---|---|
| `SNOWFLAKE_ACCOUNT_URL` | All tests | `https://myorg-myaccount.snowflakecomputing.com`. **If your account identifier contains an underscore, use the regional URL instead** (e.g. `https://hha81106.us-east-1.snowflakecomputing.com`). An underscore is not a valid DNS label, so `httpx` rejects the certificate with `CERTIFICATE_VERIFY_FAILED: Hostname mismatch`. `curl` is more lenient, so a working `curl` does not prove the URL works for the client. |
| `SNOWFLAKE_PAT` | All tests | PAT token for `app_owner_role` |
| `LIVE_AGENT_MINIMAL` | All tests | Fully-qualified path to the minimal agent, e.g. `cac_live_db.cac_live_schema.minimal_agent` |
| `LIVE_AGENT_FULL` | `test_runs_full.py` only | Fully-qualified path to the Cortex Search agent. Tests in that file are automatically skipped if this variable is absent. |
| `LIVE_AGENT_ANALYST` | `test_runs_analyst.py` only | Fully-qualified path to the Cortex Analyst agent. Tests in that file are automatically skipped if absent. |
| `LIVE_AGENT_WEB` | `test_runs_web.py` only | Fully-qualified path to the web search agent. Tests in that file are automatically skipped if absent. Requires web search enabled at account level. |
| `LIVE_SLOW` | `TestRunExpiryWindow` only | Set to `1` to run the ~6 minute run-expiry test in `test_runs_async.py`. Skipped otherwise. |
| `LIVE_TIMEOUT` | Optional, all tests | Client read timeout in seconds (default `120`). Raise to `300` for the Cortex Analyst suite, which can be slow. Also used as the `AppTest` script timeout. |
| `LIVE_APPTEST_AGENT` | Set automatically | Used internally by `test_streamlit_live.py` to point the AppTest app at a non-default agent. Do not set by hand. |

---

## Before you run: two things that will bite you

**1. Teardown is destructive.** The autouse `_teardown_live_objects` fixture drops
`CAC_LIVE_DB`, `cac_live_schema`, and `cac_live_wh` at the end of every session. If your
seeded agents already exist and you want to keep them, always run with
`LIVE_SKIP_TEARDOWN=1`.

**2. Agents use the caller's default role and warehouse.** Not the session role. The user
needs `DEFAULT_ROLE` and `DEFAULT_WAREHOUSE` set, and that default role needs USAGE on the
agent. Check with `DESCRIBE USER <name>` and `SHOW GRANTS ON AGENT <path>`. A seed script's
`GRANT USAGE ... TO ROLE app_owner_role` does nothing for you if your default role is
something else.

**3. Check the tool execution warehouse is resumable.** The Analyst agent runs its SQL on
`CAC_LIVE_WH`. If that warehouse is SUSPENDED with `AUTO_RESUME = false`, agent queries can
never start and the suite hangs with no output and no error — it looks exactly like a client
bug. Verify with:

```sql
SHOW WAREHOUSES LIKE 'CAC_LIVE_WH';   -- want state STARTED or auto_resume true
ALTER WAREHOUSE CAC_LIVE_WH SET AUTO_RESUME = TRUE;
ALTER WAREHOUSE CAC_LIVE_WH RESUME IF SUSPENDED;
```

**4. Run live suites in the background, never the foreground.** A streaming test can take
minutes. If you start one in the foreground of an agent shell, the next command sends SIGINT
and kills the run mid-stream, which is easily misread as a hang in the client. Redirect to a
log file and poll it.

Also note: a PAT cannot be used to mint another PAT for the same user
(`099413 (38002)`). If your connection authenticates with a PAT, create the token from
Snowsight or from a password/keypair connection.

---

## Running the tests

```bash
# Minimal tests only (test_auth, test_threads, test_runs)
SNOWFLAKE_ACCOUNT_URL="https://myorg-myaccount.snowflakecomputing.com" \
SNOWFLAKE_PAT="v2:..." \
LIVE_AGENT_MINIMAL="cac_live_db.cac_live_schema.minimal_agent" \
  uv run pytest tests/live/ -m live -v

# Full suite (includes Cortex Search, Cortex Analyst, and web search tests)
SNOWFLAKE_ACCOUNT_URL="https://myorg-myaccount.snowflakecomputing.com" \
SNOWFLAKE_PAT="v2:..." \
LIVE_AGENT_MINIMAL="cac_live_db.cac_live_schema.minimal_agent" \
LIVE_AGENT_FULL="cac_live_db.cac_live_schema.full_agent" \
LIVE_AGENT_ANALYST="cac_live_db.cac_live_schema.analyst_agent" \
LIVE_AGENT_WEB="cac_live_db.cac_live_schema.web_agent" \
  uv run pytest tests/live/ -m live -v

# Single file
  uv run pytest tests/live/test_auth.py -m live -v
```

To run all tests *except* live:

```bash
uv run pytest tests/ -m "not live" -v
```

---

## Object cleanup

All Snowflake objects created by the seed scripts are **dropped automatically** when
the test session ends. The session fixture runs the DROP statements in
`seed/teardown.sql` via the SQL REST API after all tests complete.

To skip teardown (e.g. for debugging):

```bash
LIVE_SKIP_TEARDOWN=1 uv run pytest tests/live/ -m live -v
```

If a test session is interrupted before teardown runs, use either of these:

```bash
# Re-run the teardown script directly
SNOWFLAKE_ACCOUNT_URL="https://..." SNOWFLAKE_PAT="v2:..." \
  uv run python tests/live/seed/teardown.py

# Sweep any leaked threads (separate from objects)
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
| `test_runs_full.py` | full (Cortex Search) | ToolUseEvent, ToolResultEvent, TextAnnotationEvent, citation doc_id/title |
| `test_runs_analyst.py` | analyst (Cortex Analyst) | ToolUseEvent (`system_execute_sql`, `system_agentic_semantic_context`), SQL via `ToolUseEvent.input["sql"]`, `verified_query_used`, non-empty text |
| `test_runs_web.py` | web (web_search) | ToolUseEvent (web_search), ToolResultEvent status, non-empty text response |
| `test_runs_async.py` | minimal | Background runs, `stream_run` reconnect, `starting_after` cursor, `sequence_number`, `cancel_run` plus its 409, `Thread.chat(background=True)`, lite-run `models` object, `orchestration` budget, `X-Snowflake-Role` (including a negative case), and the 5-minute expiry window (`LIVE_SLOW=1`) |
| `test_streamlit_live.py` | minimal, analyst | Drives `apps/live_chat_app.py` with `streamlit.testing.v1.AppTest` against a real agent: initial render, a full turn, absence of internal artefacts in the output, second-turn history replay, and dataframe rendering for an Analyst answer |
| `test_agents.py` | disposable | Agent CRUD lifecycle — create, get, update, list with `like`, delete, `createMode` (`errorIfExists` and `orReplace`), `ifExists`, plus agent-level and request-level feedback |

### Why the Streamlit live test exists

Everything in `tests/streamlit/` mocks Streamlit with `MagicMock`, so the real render pipeline
never executes. That is the gap the `[DONE]` sentinel defect fell through: a spurious
`UnknownEvent` was handed to the renderer on every turn and no test could see it. The AppTest
suite runs the actual script against live payloads.

### Disposable objects

`test_agents.py` creates agents named `cac_live_crud_<uuid8>` and drops each one in a fixture
`finally` block. The uuid suffix prevents collisions between concurrent runs, which also means
they cannot be listed in `teardown.sql`. After a hard kill, sweep them by prefix:

```bash
SNOWFLAKE_ACCOUNT_URL="https://..." SNOWFLAKE_PAT="v2:..." \
  uv run python tests/live/seed/cleanup_leaked_agents.py
```

### Model names are deployment-specific

`test_runs_async.py` uses `models={"orchestration": "auto"}` rather than a named model.
Availability varies by account — the `claude-4-sonnet` name used in the public API examples
is rejected on some deployments with a 400 that lists the available models. Do not hardcode
a model name in a portable test.
