[← Back to README](../README.md) · See also: [Streamlit guide](streamlit_guide.md) · [Streamlit-in-Snowflake](sis.md) · [Python API](python_api.md) · [Event Types](event_types.md) · [REST API Spec](api_spec.md)

# Reference

## `CortexAgentsClient` parameters

| Parameter | Required | Default | Description |
|---|---|---|---|
| `account_url` | Yes | — | `https://myorg-myaccount.snowflakecomputing.com` |
| `auth` | Yes | — | `AuthProvider` instance or PAT string (auto-wrapped as `PATAuth`) |
| `timeout` | No | `120.0` | Read timeout in seconds — max silence between SSE events. Increase for slow agents. |
| `default_database` | No | `None` | Default database — avoids repeating it in every `thread.chat()` call |
| `default_schema` | No | `None` | Default schema |
| `origin_application` | No | `None` | Label attached to threads for monitoring (max 16 bytes) |
| `role` | No | `None` | Snowflake role sent as `X-Snowflake-Role`. Note that Cortex Agents derives tool permissions from the user's **default** role regardless of this header. |

## `CortexAgentChat` parameters

`account_url`, `auth`, and `agent_path` are always required. `agent_path` is not sensitive — hardcode it directly.

| Parameter | Required | Default | Description |
|---|---|---|---|
| `account_url` | Yes | — | Snowflake account URL |
| `auth` | Yes | — | Auth provider or PAT string |
| `agent_path` | Yes | — | `DB.SCHEMA.AGENT` |
| `mode` | No | `"fullpage"` | `"fullpage"` or `"embedded"` |
| `height` | No | `450` | Message area height: px as an `int`, or a CSS height string such as `"calc(100vh - 300px)"` — `embedded` mode only |
| `show_thinking` | No | `True` | Show agent reasoning as steps in the reasoning timeline |
| `show_tool_status` | No | `True` | Show tool calls as steps in the reasoning timeline |
| `new_conversation_button` | No | `True` | Show "New conversation" button |
| `origin_application` | No | `None` | Thread label for monitoring (max 16 bytes) |
| `input_placeholder` | No | `"Ask a question..."` | Chat input placeholder |
| `session_key_prefix` | No | `"_ca"` | `st.session_state` key prefix — change when running multiple bots on one page |
| `default_database` | No | `None` | Default database |
| `default_schema` | No | `None` | Default schema |
| `accept_file` | No | `False` | `True`, `"multiple"`, `"directory"`, or `False`. Attachments are displayed and replayed but **not forwarded to the agent** |
| `accept_audio` | No | `False` | Enable microphone input. Recordings are displayed and replayed but **not forwarded to the agent** |
| `file_type` | No | `None` | Allowed extensions, e.g. `["pdf","csv"]` — only applies when `accept_file` is set; `None` = all types |
| `tool_executor` | No | `None` | Callable for client-side tool execution |
| `variables` | No | `None` | Session attributes for multi-tenancy: a mapping, or a callable returning one, called once per prompt |

## CSS targeting via widget keys

Widgets rendered by the chatbot are assigned stable keys that generate `.st-key-*` CSS classes. Use these to style specific elements without relying on Streamlit's internal DOM structure.

**Key format:** `.st-key-{prefix}-{msg_index}-{element}[-{item_index}]`

Where `prefix` is the `session_key_prefix` with the leading underscore stripped (default: `ca`), and `msg_index` is the 0-based position in the message history.

| Element | CSS class pattern | Example |
|---------|-------------------|---------|
| Reasoning timeline (thinking and tool steps) | `.st-key-ca-{msg}-thinking` | `.st-key-ca-1-thinking` |
| Verified-query step | `.st-key-ca-{msg}-verified-step-{tool_use_id}` | `.st-key-ca-2-verified-step-toolu_01` |
| Sources expander | `.st-key-ca-{msg}-sources` | `.st-key-ca-3-sources` |
| Table (dataframe) | `.st-key-ca-{msg}-table-{i}` | `.st-key-ca-3-table-0` |
| Chart (vega-lite) | `.st-key-ca-{msg}-chart-{i}` | `.st-key-ca-3-chart-0` |

**Example — custom styling for all tables:**

```python
import streamlit as st

st.html("""
<style>
[class*="st-key-ca-"][class*="-table-"] { border: 2px solid #29B5E8; border-radius: 8px; }
[class*="st-key-ca-"][class*="-sources"] { opacity: 0.8; }
</style>
""")
```

**Note:** `st.status`, `st.markdown`, `st.warning`, `st.caption`, and `st.info` do not accept `key` parameters in Streamlit — those elements cannot be targeted via this mechanism. The reasoning timeline is an `st.status`, so its key is set on an `st.container` that wraps it.

## Secrets and environment variables

### External Streamlit — `.streamlit/secrets.toml`

| Auth method | Key | Description |
|---|---|---|
| PAT *(recommended)* | `SNOWFLAKE_ACCOUNT_URL` | `https://myorg-myaccount.snowflakecomputing.com` |
| PAT | `SNOWFLAKE_PAT` | Programmatic Access Token (`v2:...`) |
| JWT | `SNOWFLAKE_ACCOUNT_URL` | Account URL — the key file path is passed in code, not stored in secrets |
| OAuth | `SNOWFLAKE_ACCOUNT_URL` | Account URL |
| OAuth | `SNOWFLAKE_OAUTH_TOKEN` | OAuth bearer token |

### Streamlit-in-Snowflake (container runtime)

No `.streamlit/secrets.toml` needed. Snowflake injects credentials automatically:

| Variable / path | Injected by | Read by |
|---|---|---|
| `SNOWFLAKE_HOST` env var | Snowflake | `account_url_from_env()` |
| `/snowflake/session/token` file | Snowflake (auto-refreshed) | `SiSContainerAuth()` |

### Plain Python scripts and live tests — environment variables

| Variable | Auth method | Description |
|---|---|---|
| `SNOWFLAKE_ACCOUNT_URL` | All | Account URL with `https://` scheme |
| `SNOWFLAKE_PAT` | PAT | Programmatic Access Token |
| `SNOWFLAKE_AGENT_PATH` | All | `DB.SCHEMA.AGENT` — not sensitive; used as a convenience variable in examples and live tests |

## Running tests

```bash
# Install with dev dependencies
uv sync --extra dev --extra jwt

# Unit tests
uv run pytest tests/unit/ -v

# Integration tests (mocked HTTP, no real credentials needed)
uv run pytest tests/integration/ -v

# Streamlit render tests (mocked Streamlit context)
uv run pytest tests/streamlit/ -v

# All tests except live — this is the default, so a bare `uv run pytest` is equivalent.
# Live tests are deselected via addopts so a bare run never hits the network.
uv run pytest tests/ -m "not live" -v

# Coverage report
uv run pytest tests/unit/ tests/integration/ --cov=streamlit_cortex_agents --cov-report=term-missing

# Live tests (requires real Snowflake credentials)
SNOWFLAKE_ACCOUNT_URL="https://..." SNOWFLAKE_PAT="v2:..." SNOWFLAKE_AGENT_PATH="DB.SC.AGENT" \
  uv run pytest tests/live/ -m live -v
```

For live test details (agent seed scripts, environment variables, markers, teardown), see [tests/live/README.md](../tests/live/README.md).

## Demo app

A fully interactive demo app is included at `examples/demo/`. It exercises all event types and layout modes without a Snowflake account — responses come from pre-canned event streams in `examples/demo/mock_thread.py`.

```bash
# No credentials needed. The env vars avoid a PyArrow crash on macOS ARM64.
ARROW_DEFAULT_MEMORY_POOL=system MALLOC_NANO_ZONE=0 uv run streamlit run examples/demo/app.py
```

## Architecture

```
src/streamlit_cortex_agents/
├── __init__.py               Re-exports every public name from chat/ and client/
├── chat/
│   ├── chatbot.py            CortexAgentChat (drop-in component)
│   ├── session.py            init_session(), sis_init_session(), reset_thread(), get_messages()
│   └── render.py             render_streaming_response(), render_stored_message(), result_set_to_dataframe(), escape_dollars()
└── client/
    ├── core.py               CortexAgentsClient (top-level facade), Thread (stateful)
    ├── auth.py               PATAuth, JWTAuth, OAuthAuth, SiSContainerAuth, AuthProvider, account_url_from_env
    ├── http.py               HttpClient (httpx wrapper, error mapping)
    ├── sse.py                SSE parser + event factory (17 API types + UnknownEvent)
    ├── exceptions.py         Typed exceptions
    ├── models/
    │   ├── agent.py          Agent, Tool, ToolSpec, etc.
    │   ├── thread.py         ThreadMetadata, ThreadDetail, ThreadMessage, StoredMessage
    │   └── events.py         All 18 SSE event dataclasses (17 API types + UnknownEvent)
    └── resources/
        ├── agents.py         AgentsResource (CRUD + feedback)
        ├── threads.py        ThreadsResource (CRUD + pagination + compaction)
        └── runs.py           RunsResource (stream, run, stream_run, cancel_run, stream_and_collect)
```

**Component diagram**

```
┌──────────────────────────────────────────────────────────────────┐
│                     Application Layer                            │
│  Streamlit app / Python script / Notebook                        │
└──────────────────┬──────────────────────────────┬────────────────┘
                   │                              │
        ┌──────────▼──────────┐        ┌──────────▼───────────────┐
        │  CortexAgentsClient │        │    CortexAgentChat       │
        │  (client/core.py)   │        │    (chat/chatbot.py)     │
        │  + Thread wrapper   │        │    fullpage / embedded   │
        └─────────┬───────────┘        └──────────┬───────────────┘
                  │                               │  uses session.py + render.py
         ┌────────┼──────────┐                    │
         ▼        ▼          ▼                    │
  AgentsResource  ThreadsResource  RunsResource ◄─┘
  (agents.py)   (threads.py)     (runs.py)
         │        │          │
         └────────┼──────────┘
                  ▼
           HttpClient (http.py)
           ├── request() → JSON REST calls
           └── stream()  → SSE streaming
                  │
           AuthProvider (auth.py)
           ├── PATAuth
           ├── JWTAuth
           ├── OAuthAuth
           └── SiSContainerAuth
                  │
                  ▼
        Snowflake Cortex Agents REST API
        (myorg-myaccount.snowflakecomputing.com)
```

**Design principles**

- **Layered**: HTTP → resources → client facade → optional Streamlit layer
- **Typed events**: 17 event dataclasses; `UnknownEvent` catches future API additions without breaking callers
- **Stateful threads**: `Thread` tracks `parent_message_id` so callers never manage it manually; `fork()` enables branching
- **Auth pluggability**: `AuthProvider` ABC with four concrete implementations; plain strings auto-wrap as `PATAuth`
- **Two-path rendering**: live streaming path (`render_streaming_response`) and history replay path (`render_stored_message`) produce equivalent output
- **No external dependencies for core**: only `httpx`; `cryptography`+`PyJWT` are optional for JWT auth; `streamlit`+`pandas` are optional for the UI layer

**SSE event pipeline (streaming path)**

```
HTTP response body
    → HttpClient.stream() → iter_lines()
    → parse_sse_stream()  → (event_type, payload) tuples
    → event_from_sse()    → typed SSEEvent subclasses
    → RunsResource.stream() → Iterator[SSEEvent]
    → Thread.chat()         → Iterator[SSEEvent] (+ parent_message_id tracking)
    → render_streaming_response() → Streamlit UI elements + StoredMessage
```

## Notes

- **Timeout**: Default read timeout is 120 seconds (2 minutes). This controls the maximum silence between SSE data chunks — not the total request duration. Connection pooling is disabled to prevent stale connections from hanging in long-lived sessions. Increase the timeout for agents with very long processing times.
- **Unknown event types**: Yielded as `UnknownEvent` (never raise) for forward-compatibility with new Snowflake tools.
- **Thread compaction**: Use `client.threads.latest_context(thread_id)` to get the most recent summary + subsequent messages when resuming long conversations.
