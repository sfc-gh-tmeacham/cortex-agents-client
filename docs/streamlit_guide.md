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
    attachments: list[Any]         # Uploaded files / audio from the user turn
    pending_permission: ToolUseEvent | None  # Tool awaiting user approval
    message_id: int | None         # Thread message ID from metadata event
```

`StoredMessage` captures everything needed to re-render the message identically on any subsequent rerun.

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
12. On `MetadataEvent`: store internally (not rendered).
13. Return assembled `StoredMessage`.

### Path 2: History replay (rerun)

Called for every existing message on every Streamlit rerun.

```python
for msg in get_messages():
    with st.chat_message(msg.role):
        render_stored_message(msg, st)
```

`render_stored_message()` applies the same elements in the same order:
1. Thinking expander (if `thinking` is set and `show_thinking=True`).
2. Tool result text for each tool execution (if any).
3. Main text via `st.markdown(text)`, or `st.info(text)` when `is_elicitation=True`.
4. Citations / Sources expander (if annotations present).
5. Tables via `st.dataframe()`.
6. Charts via `st.vega_lite_chart()`.
7. Warnings via `st.warning()`.
8. Error via `st.error()`.
9. Pending permission notice via `st.warning()` (if a tool required approval).

---

## Minimal Streamlit app

```python
# app.py
import streamlit as st
from cortex_agents_client.st import StreamlitChatbot

bot = StreamlitChatbot(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    agent_path=st.secrets["AGENT_PATH"],
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
    agent_path = st.secrets["AGENT_PATH"]
    with st.chat_message("assistant"):
        stored = render_streaming_response(
            thread.chat(agent_path, prompt),
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
AGENT_PATH = "MY_DB.MY_SCHEMA.MY_AGENT"
```

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
