# cortex-agents-client — Project Context

Python client library for the Snowflake Cortex Agents REST API, plus a
high-level Streamlit chatbot component (`cortex_agents_client.st`).

---

## Package structure

```
cortex_agents_client/
├── auth.py            # PATAuth, JWTAuth, OAuthAuth, SiSContainerAuth, AuthProvider, account_url_from_env
├── client.py          # CortexAgentsClient, Thread (primary entry points)
├── exceptions.py      # CortexAgentError, AuthError, CortexPermissionError, CortexTimeoutError,
│                      # NotFoundError, AgentNotFoundError, ThreadNotFoundError,
│                      # RateLimitError, ServerError, RunError;
│                      # deprecated aliases: PermissionError, TimeoutError
├── http.py            # HttpClient (httpx-based, auth header injection)
├── sse.py             # SSE stream parser, event_from_sse() factory
├── models/
│   ├── agent.py      # Agent, Tool, ToolSpec, AgentProfile, AgentInstructions, BudgetConfig
│   ├── events.py      # 18 typed SSE event dataclasses (17 API types + UnknownEvent)
│   └── thread.py      # StoredMessage, ThreadDetail, ThreadMessage, ThreadMetadata
├── resources/
│   ├── agents.py      # AgentsResource (CRUD for agent objects)
│   ├── runs.py        # RunsResource — agent:run endpoint, streaming + non-streaming
│   └── threads.py     # ThreadsResource (thread CRUD)
└── st/
    ├── chatbot.py     # StreamlitChatbot — drop-in full-page or embedded chat component
    ├── render.py      # render_streaming_response(), render_stored_message(), helpers
    └── session.py     # st.session_state helpers: init_session, sis_init_session, get_messages, append_message
```

---

## Key design decisions

### Two rendering paths that produce identical output
`render_streaming_response()` renders live SSE events as they arrive.
`render_stored_message()` replays a `StoredMessage` from session state on every
Streamlit rerun. Both must produce the same visual output — always keep them in sync.

### Thread management
`Thread` auto-tracks `parent_message_id` by watching for `MetadataEvent(role="assistant")`.
Callers never manage message IDs manually. `init_session()` in `session.py` stores the
thread in `st.session_state` so it survives reruns.

### Session state key prefix
Every `StreamlitChatbot` uses a `session_key_prefix` (default `_ca`) to namespace its
session state keys (`_ca_client`, `_ca_thread`, `_ca_messages`, `_ca_input`, `_ca_pending_perm`). Change the
prefix to run multiple chatbots on one page without collisions.
Keys include: `{prefix}_client`, `{prefix}_thread`, `{prefix}_messages`,
`{prefix}_input`, `{prefix}_pending_perm`, `{prefix}_agent_spec`, `{prefix}_pending_suggestion`.

### Streamlit version requirement: ≥ 1.59
Required for:
- `st.chat_input` in any container (embedded mode, replaces old `st.form` workaround)
- `accept_file` / `accept_audio` params on `st.chat_input`
- `key` param on `st.chat_input` (needed for embedded mode placement)
- `st.column_config.MarkdownColumn` — applied to all `object`-dtype columns in Analyst result dataframes

---

## Platform notes

### macOS ARM64 (Apple Silicon) — PyArrow mimalloc SIGSEGV

**Symptom:** Streamlit crashes with `SIGSEGV / Segmentation fault: 11` immediately
after rendering a table result. The crash occurs inside PyArrow's mimalloc memory
allocator (`mi_heap_main → mi_thread_init → _mi_malloc_generic`) when pandas
converts a result set via Arrow.

**Affects:** macOS ARM64 only. Not reproducible on Linux or macOS x86_64.

**Fix:** Set two env vars **inline in the shell command** before Python loads:
```bash
ARROW_DEFAULT_MEMORY_POOL=system MALLOC_NANO_ZONE=0 uv run streamlit run streamlit_demo/app.py
```

> **Important:** Streamlit 1.59 removed support for the `[env]` section in
> `config.toml`. The env vars **must** be set in the shell before launch —
> setting them inside Python after PyArrow has already been imported is too late.

These are no-ops on other platforms and do not affect correctness.

**Upstream issues:**
- [microsoft/mimalloc#343](https://github.com/microsoft/mimalloc/issues/343) — root cause: mimalloc `mi_tls_slot()` segfault on ARM64
- [apache/arrow#41696](https://github.com/apache/arrow/issues/41696) — PyArrow tracking issue; `ARROW_DEFAULT_MEMORY_POOL=system` suggested by maintainers as the workaround

---

## Known bugs fixed this session

### LaTeX rendering of dollar signs (`render.py`)
Streamlit's markdown renderer treats `$...$` as inline LaTeX delimiters.
Agent responses with currency amounts like `$452K ... $381K` would render as
italicised math. Fix: `escape_dollars()` regex `\$(?=\d)` escapes `$` before
digits at all `st.markdown()` call sites for agent text. Does NOT affect genuine
LaTeX (which starts with letters or `\`).

### Reasoning expander content duplicated (`render.py`)
`ThinkingDeltaEvent` blocks stream into a `thinking_placeholder.markdown(accumulated)`
call inside a compact `st.expander`. The final `ThinkingEvent` carries the same full
text. Calling `.markdown()` a second time on a placeholder inside a compact expander
adds a NEW element instead of replacing — resulting in the text appearing twice.
Fix: `pass` in the `ThinkingEvent` handler when `thinking_placeholder is not None`;
the deltas have already rendered the complete text.

### Streaming element order (tables/charts positioned correctly)
`text_placeholder` was created eagerly at the top of `render_streaming_response()`,
which meant tables and charts arriving mid-stream were always pushed below the text.
Fix: lazy `text_placeholder` creation — sealed when a table/chart arrives so post-table
text gets its own placeholder below the interleaved element.

### Reasoning expander pushed below text during streaming
Same root cause: `text_placeholder` created eagerly occupied the top slot. Fix:
placeholder created lazily, so the thinking expander (which arrives first) gets
the top position naturally.

---

## Recent feature additions

### `system_execute_sql` (Apr 2026 API change)
Cortex Analyst now emits `ToolUseEvent` with `type="system_execute_sql"` instead of
`cortex_analyst_text_to_sql`. SQL is in `event.input["sql"]`. `AnalystDeltaEvent` is
deprecated. The client handles both old and new formats.

### `SuggestedQueriesEvent`
New event type `response.suggested_queries`. Parsed into `SuggestedQueriesEvent` with
a `queries: list[str]` field. Stored on `StoredMessage.suggested_queries`.

### Suggested questions UI
`_render_suggested_queries()` renders compact tertiary buttons. Shown:
- On new threads: agent's `sample_questions` (from agent spec, first 5)
- After responses: `suggested_queries` from the last assistant message
Clicking submits the query as the next user prompt via `st.rerun()`.

### SQL in tool expander
When `show_tool_status=True`, the status expander for `system_execute_sql` tools
displays the generated SQL via `st.code(sql, language="sql")` — matching CoWork.

---

## File and audio attachments — current state and roadmap

`StreamlitChatbot` accepts `accept_file`, `accept_audio`, `file_type` params.
Files are displayed in the user bubble and stored in `StoredMessage.attachments`
for rerun replay. **They are NOT forwarded to the agent.**

The Cortex Agents Run API `MessageContentItem` schema only defines `text` as a
user-input content type. Snowflake CoWork supports file upload by first staging
the file on the user's personal Snowflake stage, then referencing it — this
staging step is internal to CoWork and not exposed in the public REST API.

The `extra_content` parameter on `Thread.chat()` is the intended extension point
for when the API publishes a file/document content type. See `docs/roadmap.md`
for the full implementation plan.

---

## Testing

```bash
# Install all dev dependencies
uv sync --extra dev --extra streamlit --extra jwt

# Run all non-live tests
uv run pytest tests/ -m "not live" -v

# Run the interactive demo (no Snowflake account needed)
# Note: env vars required on macOS ARM64 — see Platform notes above
ARROW_DEFAULT_MEMORY_POOL=system MALLOC_NANO_ZONE=0 uv run streamlit run streamlit_demo/app.py
```

Tests: 239 passing, 1 skipped (`tests/` tree below):
```
tests/
├── unit/          # core client, auth, SSE parsing, event models
├── streamlit/     # StreamlitChatbot, render functions, session helpers (mocked st)
├── integration/   # mocked HTTP tests via pytest-httpx; no Snowflake account required
└── fixtures/      # shared SSE event payloads
```

`streamlit_demo/` at the project root contains the interactive demo app
(not part of the pytest suite):
```
streamlit_demo/
├── app.py         # interactive Streamlit demo (no credentials needed)
└── mock_thread.py # pre-canned SSE streams for all scenarios
```

The demo app has a scenario selector covering: Simple text, Thinking,
Cortex Analyst (SQL + table), Web search (citations), Kitchen sink
(tools + tables + charts), Elicitation, Error. All scenarios include
suggested follow-up queries. Toggle "Show reasoning", file attachments,
voice input from the sidebar.

---

## Auth providers

| Class | Use case |
|---|---|
| `PATAuth(token)` | External apps; pass token string or `"v2:..."` |
| `JWTAuth(account, user, private_key_path)` | Key-pair auth; requires `[jwt]` extra |
| `OAuthAuth(token)` | OAuth Bearer token |
| `SiSContainerAuth()` | Streamlit-in-Snowflake container runtime; re-reads `/snowflake/session/token` per request |

For SiS (Workspaces), `account_url` is derived from the `SNOWFLAKE_HOST` env var
via `account_url_from_env()`.

---

## Docs

| File | Contents |
|---|---|
| `docs/api_spec.md` | REST API endpoint reference |
| `docs/event_types.md` | All 17 SSE event types and their fields |
| `docs/streamlit_guide.md` | Streamlit integration design reference |
| `docs/test_plan.md` | Test coverage plan and strategy |
| `docs/roadmap.md` | Planned features; file/audio attachment implementation plan |

---

## Examples

| File | Description |
|---|---|
| `examples/streamlit_app.py` | Minimal full-page chatbot |
| `examples/embedded_chat.py` | Column layout + dialog overlay patterns |
| `examples/multi_turn.py` | Programmatic multi-turn conversation |
| `examples/sis_app.py` | Streamlit-in-Snowflake container deployment |
| `examples/SIS_QUICKSTART.md` | SiS quickstart — full-page, embedded, and dialog patterns with EAI setup |
