# cortex_agents_client.st — Streamlit Integration

Drop-in Streamlit components for Snowflake Cortex Agents. Copy the parent
`cortex_agents_client/` folder into your project and install the dependencies
listed below.

---

## Dependencies

```
streamlit>=1.44
pandas
requests
```

For voice/microphone support (optional):

```
streamlit>=1.44
```

---

## Secrets configuration

Create `.streamlit/secrets.toml` in your project root:

```toml
SNOWFLAKE_ACCOUNT_URL = "https://myorg-myaccount.snowflakecomputing.com"
SNOWFLAKE_PAT         = "v2:local:..."
```

`SNOWFLAKE_PAT` is a Programmatic Access Token. Generate one in Snowsight under
**Governance & security → Users & roles → your user → Programmatic access tokens**.

The agent path (`DB.SCHEMA.MY_AGENT`) is not sensitive — hardcode it directly in
your app code.

---

## Quickstart — drop-in chatbot

```python
# app.py
import streamlit as st
from cortex_agents_client.st import StreamlitChatbot

bot = StreamlitChatbot(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    agent_path="MY_DATABASE.MY_SCHEMA.MY_AGENT",
)
bot.render()
```

Run with:

```bash
streamlit run app.py
```

---

## StreamlitChatbot

### Full-page mode (default)

`st.chat_input` is pinned to the bottom of the page. The "New conversation"
button appears in the sidebar.

```python
bot = StreamlitChatbot(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    agent_path="MY_DATABASE.MY_SCHEMA.MY_AGENT",
    show_thinking=True,         # show agent reasoning expander
    show_tool_status=True,      # show tool spinners during execution
    new_conversation_button=True,
    input_placeholder="Ask a question...",
    origin_application="my_app",   # optional label for monitoring
)
bot.render()
```

### Embedded mode

Fits inside any Streamlit container — a column, `st.dialog`, `st.sidebar`,
`st.expander`, etc. Uses a fixed-height scrollable message area and an inline
`st.chat_input` (requires Streamlit ≥ 1.59).

```python
# Two-column layout: dashboard left, chat right
dash_col, chat_col = st.columns([2, 1])
with dash_col:
    st.write("Your dashboard content")
with chat_col:
    bot = StreamlitChatbot(
        account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
        auth=st.secrets["SNOWFLAKE_PAT"],
        agent_path="MY_DATABASE.MY_SCHEMA.MY_AGENT",
        mode="embedded",
        height=500,
    )
    bot.render()
```

```python
# Modal dialog
@st.dialog("Ask the agent", width="large")
def open_chat():
    StreamlitChatbot(
        account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
        auth=st.secrets["SNOWFLAKE_PAT"],
        agent_path="MY_DATABASE.MY_SCHEMA.MY_AGENT",
        mode="embedded",
        height=400,
    ).render()

if st.button("Open chat", icon=":material/chat:"):
    open_chat()
```

### File and audio attachments

```python
bot = StreamlitChatbot(
    ...,
    accept_file="multiple",       # True / "multiple" / "directory"
    file_type=["pdf", "csv"],     # None accepts all types
    accept_audio=True,            # microphone button
)
```

### Multiple chatbots on one page

Each instance must use a unique `session_key_prefix` to keep their session
state isolated:

```python
bot1 = StreamlitChatbot(..., agent_path="DB.SCHEMA.AGENT_A", session_key_prefix="_bot1")
bot2 = StreamlitChatbot(..., agent_path="DB.SCHEMA.AGENT_B", session_key_prefix="_bot2")
```

### Client-side tool execution

For tools with `client_side_execute=True`, provide a `tool_executor` callable:

```python
from cortex_agents_client.models.events import ToolUseEvent

def my_executor(event: ToolUseEvent) -> list[dict]:
    # inspect event.name and event.input, run the tool, return results
    return [{"type": "json", "json": {"result": "value"}}]

bot = StreamlitChatbot(..., tool_executor=my_executor)
```

---

## Manual integration

For fine-grained control over the UI:

```python
import streamlit as st
from cortex_agents_client.st import (
    init_session,
    get_messages,
    append_message,
    render_stored_message,
    render_streaming_response,
    escape_dollars,
)
from cortex_agents_client.models.thread import StoredMessage

# Initialise once per session (idempotent — safe to call on every rerun)
client, thread = init_session(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    origin_application="my_app",
)

st.title("Revenue Assistant")

# Replay conversation history on every rerun
for msg in get_messages():
    with st.chat_message(msg.role):
        render_stored_message(msg, st)

# Accept new user input
if prompt := st.chat_input("Ask about revenue..."):
    with st.chat_message("user"):
        st.markdown(escape_dollars(prompt))
    append_message(StoredMessage(role="user", text=prompt))

    with st.chat_message("assistant"):
        stored = render_streaming_response(
            thread.chat("MY_DATABASE.MY_SCHEMA.MY_AGENT", prompt),
            container=st,
            show_thinking=False,
            show_tool_status=True,
        )
    append_message(stored)
```

### `escape_dollars(text)`

Wrap any user-supplied text before passing it to `st.markdown()` to prevent
Streamlit from interpreting `$N` patterns as LaTeX:

```python
st.markdown(escape_dollars(user_text))
```

`render_streaming_response` and `render_stored_message` call this internally.
You only need it when rendering text yourself.

---

## Session state helpers

| Function | Description |
|---|---|
| `init_session(account_url, auth, ...)` | Creates client + thread on first call; returns cached objects on reruns |
| `sis_init_session(agent_path, ...)` | Same as `init_session` but reads credentials from SiS container environment |
| `get_messages(key="_ca_messages")` | Returns the current `list[StoredMessage]` |
| `append_message(msg, key="_ca_messages")` | Appends a message to history |
| `reset_thread(account_url, auth, ...)` | Clears history and starts a new thread |

---

## Thread lifecycle

| Scenario | Approach |
|---|---|
| Single conversation per session | `init_session()` once — thread persists for the browser session |
| Start over | `reset_thread()` — clears history and creates a new thread |
| Resume a previous conversation | Store `thread.thread_id`; call `client.get_thread(thread_id, parent_message_id=last_id)` |
| Branch a conversation | `thread.fork(at_message_id=N)` |

---

## Authentication options

Pass a PAT token string directly, or use an `AuthProvider` from
`cortex_agents_client.auth`:

```python
from cortex_agents_client.auth import PATAuth, JWTAuth, OAuthAuth

# PAT (simplest — no username needed)
auth = PATAuth("v2:local:...")
# or just pass the token string directly

# Key-pair / JWT
auth = JWTAuth(account="myorg-myaccount", user="MY_USER", private_key=key_bytes)

# OAuth (you supply the token; the library uses it as a Bearer token)
auth = OAuthAuth(oauth_token)
```

### Streamlit-in-Snowflake (container runtime)

The Cortex Agents API requires **container runtime** — it is not available in
warehouse runtime SiS apps.

```python
from cortex_agents_client.st import sis_init_session

client, thread = sis_init_session(agent_path="MY_DATABASE.MY_SCHEMA.MY_AGENT")
```

`sis_init_session` reads the injected container token and host automatically.

---

## macOS note (ARM64)

If Streamlit crashes with a segfault when rendering DataFrames on Apple Silicon,
add this to `.streamlit/config.toml`:

```toml
[env]
ARROW_DEFAULT_MEMORY_POOL = "system"
MALLOC_NANO_ZONE = "0"
```

This is a known PyArrow mimalloc allocator issue on macOS ARM64 and has no
impact on deployed apps running on Linux.
