# Streamlit Integration Guide

Design reference for the `cortex_agents_client.st` subpackage.

---

## The Streamlit rerun problem

Streamlit reruns the entire Python script on every user interaction. This means:

1. Objects created at the top of the script (client, thread) are re-instantiated on every rerun unless stored in `st.session_state`.
2. Streaming responses cannot be re-streamed — what was streamed on a previous run must be replayed from stored data.
3. Rich content types (tables, charts, thinking) must be rendered identically from session state on every rerun.

The `cortex_agents_client.st` subpackage solves all three problems.

---

## Session state layout

```
st.session_state:
  _ca_client   → CortexAgentsClient    (created once, reused across reruns)
  _ca_thread   → Thread                (created once, reused across reruns)
  _ca_messages → list[StoredMessage]   (grows with each conversation turn)
```

All keys are prefixed with `_ca_` to avoid collisions with user-defined session state. Custom keys can be passed to `init_session()`.

---

## StoredMessage schema

Every conversation turn is stored as a `StoredMessage` dataclass. This is the canonical unit of history.

```python
@dataclass
class StoredMessage:
    role: str                  # "user" or "assistant"
    text: str                  # Final assembled text (may contain [^N] citation markers)
    thinking: str | None       # Agent reasoning (None if model didn't think)
    is_elicitation: bool       # True when the agent is asking the user a clarifying question
    tables: list[TableEvent]   # SQL result grids, in order of appearance
    charts: list[ChartEvent]   # Vega-Lite specs, in order of appearance
    annotations: list[TextAnnotationEvent]  # Citations (matched to [^N] markers)
    tool_executions: list[tuple[ToolUseEvent, ToolResultEvent | None]]
    warnings: list[WarningEvent]
    error: ErrorEvent | None
    analyst_sql: dict[str, str]    # tool_use_id → SQL string (for debugging)
    verified_tool_uses: set[str]   # tool_use_ids whose results were verified
    tool_result_text: dict[str, str]  # tool_use_id → plain-text result summary
    text_segments: list[str]       # text split at table/chart boundaries (for ordered replay)
    content_blocks: list[tuple[str, int]]  # ordered sequence: ('text'|'table'|'chart', index)
    attachments: list[Any]         # Uploaded files / audio from the user turn
    pending_permission: ToolUseEvent | None  # Tool awaiting user approval
    suggested_queries: list[str]   # Suggested follow-up questions from the agent
    message_id: int | None         # Thread message ID from metadata event
```

`StoredMessage` captures everything needed to re-render the message identically on any subsequent rerun. The `content_blocks` field preserves the interleaved arrival order of text, tables, and charts so that replay produces the same visual layout as the original streaming render.

---

## Rendering strategy

There are two code paths that must produce identical output:

### Path 1: Streaming (new message)

Called during the active generation of a new assistant turn. Uses `st.empty()` for progressive text updates.

```python
with st.chat_message("assistant"):
    stored = render_streaming_response(thread.chat(agent_path, message), st)
append_message(stored)
```

Internal implementation:
1. Create `text_placeholder = container.empty()`.
2. Accumulate `TextDeltaEvent.text` strings → update `text_placeholder.markdown(accumulated_text + " :shimmer[▌]")`.
3. On `TextEvent`: replace placeholder with final text (removes cursor).
4. On `ThinkingDeltaEvent` (if `show_thinking=True`): write into expander.
5. On `ToolUseEvent`: open `st.status(f"Using {name}...")`.
6. On `ToolResultStatusEvent`: update status text.
7. On `ToolResultEvent`: close status as complete or error.
8. On `TableEvent`: `container.dataframe(result_set_to_dataframe(event))`.
9. On `ChartEvent`: `container.vega_lite_chart(json.loads(event.chart_spec))`.
10. On `WarningEvent`: `container.warning(event.message)`.
11. On `ErrorEvent`: `container.error(...)`, stop consuming.
12. On `SuggestedQueriesEvent`: store queries on `StoredMessage` (rendered separately by chatbot).
13. On `MetadataEvent`: store internally (not rendered).
14. Return assembled `StoredMessage`.

### Path 2: History replay (rerun)

Called for every existing message on every Streamlit rerun.

```python
for msg in get_messages():
    with st.chat_message(msg.role):
        render_stored_message(msg, st)
```

`render_stored_message()` applies the same elements in the same order:
1. Thinking expander (if `thinking` is set and `show_thinking=True`).
2. Tool status expanders with SQL (for each tool execution).
3. Tool result text for each tool execution (if any).
4. **Interleaved content** (text segments, tables, charts) in arrival order using `content_blocks`. Falls back to sequential text→tables→charts for legacy messages without `content_blocks`.
5. Citations / Sources expander (if annotations present, deduplicated by doc_id+text).
6. Warnings via `st.warning()`.
7. Error via `st.error()`.
8. Pending permission notice via `st.warning()` (if a tool required approval).

### Suggested follow-up queries

Suggestion pills are rendered **only for the last assistant message** and **outside** `st.chat_message()`. This is handled by `_render_last_suggestions()` in `chatbot.py`, not by the per-message rendering functions.

- During streaming: `SuggestedQueriesEvent` is captured on `StoredMessage.suggested_queries`.
- After streaming: `st.rerun()` triggers a fresh render cycle.
- On rerun: `_render_last_suggestions()` checks the last message for suggestions and renders them with `st.pills` under a "Suggested questions" label.
- On select: an `on_change` callback stores the query in `st.session_state["_ca_pending_suggestion"]` and clears the pill, and the query is submitted as the next user message on the rerun.
- Stale suggestions from older messages are intentionally not shown.

### Empty response fallback

When the stream completes with no visible content (no text, tables, charts, errors, warnings, or pending permissions), the renderer displays a warning: "The agent returned an empty response. Try rephrasing your question." This prevents an empty assistant bubble from confusing users.

### CSS targeting via widget keys

Both `render_streaming_response` and `render_stored_message` accept an optional `key_prefix` parameter. When provided, widgets that accept Streamlit's `key` parameter get stable CSS classes (`.st-key-{prefix}-thinking`, `.st-key-{prefix}-sources`, `.st-key-{prefix}-table-{i}`, `.st-key-{prefix}-chart-{i}`).

`StreamlitChatbot` passes `key_prefix` automatically using the pattern `{css_prefix}-{msg_index}` where `css_prefix` is derived from `session_key_prefix` (leading underscore stripped). Manual integration users can pass `key_prefix` explicitly for custom CSS targeting.

### Known limitation: stop does not cancel the agent run

`StreamlitChatbot` passes `submit_mode="stop"` to `st.chat_input`, so while a response
streams the send button becomes a stop button. Pressing it stops the Streamlit script
only. The agent run keeps executing in Snowflake until it finishes and is billed in full,
and its answer is not shown. The user's message stays in the history without a reply, and
the thread stays on its last completed message. Suggestions selected as pills do not go
through the chat input, so those runs show no stop button.

Cancelling the run server-side needs `cancel_run(run_id)` to be called when the user
presses stop. The core client supports cancellation — `background=True`, `stream_run()`
and `cancel_run()` are all available and verified live — but none of it is wired into
`render_streaming_response` or `StreamlitChatbot`, because Streamlit only processes widget
clicks on a rerun and the script is blocked inside the streaming loop for exactly the
period in which the user would press stop. See the "Cancel in-progress streaming
request" section of `docs/roadmap.md` for the attempted designs and why each was set aside.

---

## Minimal Streamlit app

```python
# app.py
import streamlit as st
from cortex_agents_client.st import StreamlitChatbot

bot = StreamlitChatbot(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
)
bot.render()
```

---

## Manual integration pattern

For users who want fine-grained control:

```python
# app.py
import streamlit as st
from cortex_agents_client.st.session import init_session, get_messages, append_message
from cortex_agents_client.st.render import render_stored_message, render_streaming_response

client, thread = init_session(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    origin_application="my_app",
)

st.title("Revenue Assistant")

# Replay history
for msg in get_messages():
    with st.chat_message(msg.role):
        render_stored_message(msg, st)

# Accept new input
if prompt := st.chat_input("Ask about revenue..."):
    # Show user message
    with st.chat_message("user"):
        st.markdown(prompt)
    from cortex_agents_client.models.thread import StoredMessage
    append_message(StoredMessage(role="user", text=prompt))

    # Stream assistant response
    with st.chat_message("assistant"):
        stored = render_streaming_response(
            thread.chat("MY_DB.MY_SCHEMA.MY_AGENT", prompt),
            container=st,
            show_thinking=False,
            show_tool_status=True,
        )
    append_message(stored)
```

---

## Secrets configuration

`.streamlit/secrets.toml`:
```toml
SNOWFLAKE_ACCOUNT_URL = "https://myorg-myaccount.snowflakecomputing.com"
SNOWFLAKE_PAT = "v2:..."
```

The agent path is not a secret — hardcode it directly in your app.

---

## Streamlit-in-Snowflake (SiS) notes

The Cortex Agents API is **not supported** from SiS apps using **warehouse runtime**. Use **container runtime** for SiS deployments. For external Streamlit (running outside Snowflake), any runtime works.

When running in container runtime, use `SiSContainerAuth()` — credentials are injected automatically by Snowflake. The `account_url` is available via `account_url_from_env()`.

---

## Thread lifecycle decisions

| Scenario | Recommended approach |
|---|---|
| Single-page app, one conversation per session | `init_session()` creates thread once; same thread persists for the session lifetime |
| Multi-conversation app | Call `reset_thread()` to clear history and create a new thread |
| Resuming a previous conversation | Store `thread.thread_id` in a persistent store; use `client.get_thread(thread_id, parent_message_id=last_assistant_id)` |
| Branching conversation | `thread.fork(at_message_id=N)` creates a new Thread branched from message N |
