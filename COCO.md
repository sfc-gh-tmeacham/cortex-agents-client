# cortex-agents-client — Project Context

Python client library for the Snowflake Cortex Agents REST API, plus a
high-level Streamlit chatbot component (`cortex_agents_client.st`).

---

## Package structure

```
cortex_agents_client/
├── auth.py            # PATAuth, JWTAuth, OAuthAuth, SiSContainerAuth
├── client.py          # CortexAgentsClient, Thread (primary entry points)
├── exceptions.py      # CortexAgentError, RunError
├── http.py            # HttpClient (httpx-based, auth header injection)
├── sse.py             # SSE stream parser, event_from_sse() factory
├── models/
│   ├── events.py      # 15+ typed SSE event dataclasses (TextDeltaEvent, ThinkingEvent, ...)
│   └── thread.py      # StoredMessage, ThreadMessage, ThreadMetadata
├── resources/
│   ├── agents.py      # AgentsResource (CRUD for agent objects)
│   ├── runs.py        # RunsResource — agent:run endpoint, streaming + non-streaming
│   └── threads.py     # ThreadsResource (thread CRUD)
└── st/
    ├── chatbot.py     # StreamlitChatbot — drop-in full-page or embedded chat component
    ├── render.py      # render_streaming_response(), render_stored_message(), helpers
    └── session.py     # st.session_state helpers: init_session, get_messages, append_message
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
session state keys (`_ca_client`, `_ca_thread`, `_ca_messages`, `_ca_input`). Change the
prefix to run multiple chatbots on one page without collisions.

### Streamlit version requirement: ≥ 1.59
Required for:
- `st.skeleton()` — shown as a loading placeholder before the first text token arrives
- `st.chat_input` in any container (embedded mode, replaces old `st.form` workaround)
- `accept_file` / `accept_audio` params on `st.chat_input`
- `st.column_config.MarkdownColumn` — applied to all `object`-dtype columns in Analyst result dataframes

---

## Known bugs fixed this session

### LaTeX rendering of dollar signs (`render.py`)
Streamlit's markdown renderer treats `$...$` as inline LaTeX delimiters.
Agent responses with currency amounts like `$452K ... $381K` would render as
italicised math. Fix: `_escape_dollars()` regex `\$(?=\d)` escapes `$` before
digits at all `st.markdown()` call sites for agent text. Does NOT affect genuine
LaTeX (which starts with letters or `\`).

### Reasoning expander content duplicated (`render.py`)
`ThinkingDeltaEvent` blocks stream into a `thinking_placeholder.markdown(accumulated)`
call inside a compact `st.expander`. The final `ThinkingEvent` carries the same full
text. Calling `.markdown()` a second time on a placeholder inside a compact expander
adds a NEW element instead of replacing — resulting in the text appearing twice.
Fix: `pass` in the `ThinkingEvent` handler when `thinking_placeholder is not None`;
the deltas have already rendered the complete text.

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
uv run streamlit run tests/demo/app.py
```

Tests: 163 passing, 1 skipped (`tests/` tree below):
```
tests/
├── unit/          # core client, auth, SSE parsing, event models
├── streamlit/     # StreamlitChatbot, render functions (mocked st)
├── integration/   # round-trip tests against a real Snowflake account (mark: live)
├── fixtures/      # shared SSE event payloads
└── demo/
    ├── app.py         # interactive Streamlit demo (no credentials needed)
    └── mock_thread.py # pre-canned SSE streams for all scenarios
```

The demo app has a scenario selector covering: Simple text, Thinking,
Kitchen sink (tools + tables + charts), Elicitation, Error. Toggle
"Show reasoning", file attachments, voice input from the sidebar.

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
| `docs/event_types.md` | All 15+ SSE event types and their fields |
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
