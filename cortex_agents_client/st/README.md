# cortex_agents_client.st — Streamlit Integration

Drop-in Streamlit components for Snowflake Cortex Agents. Copy the parent
`cortex_agents_client/` folder into your project.

---

## Streamlit-in-Snowflake (container runtime)

> The Cortex Agents API requires **container runtime**. It is not available in
> warehouse runtime SiS apps.

### Dependencies

Place a `pyproject.toml` in your app's source directory. uv resolves
dependencies at deploy time from PyPI:

```toml
[project]
name = "my-app"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "streamlit>=1.59",  # omit if the image version is sufficient
    "pandas",
    "requests",
]
```

Streamlit is pre-installed in the SiS container image — add it explicitly only
if you need a newer version than the image provides.

### External Access Integrations (required)

Container runtime apps cannot make outbound network calls without an EAI. You
need **two**:

**1 — Cortex Agents API** (allows the app to call the Agents REST API). Requires ACCOUNTADMIN.

Network rules are schema-level objects — store them in a dedicated schema. The example below uses `common_db.security`; substitute your own database and schema. Replace `myorg-myaccount` with your account identifier (`SELECT CURRENT_ACCOUNT()`):

```sql
USE ROLE ACCOUNTADMIN;

CREATE OR REPLACE NETWORK RULE common_db.security.cortex_agents_api_rule
  TYPE       = HOST_PORT
  MODE       = EGRESS
  VALUE_LIST = ('myorg-myaccount.snowflakecomputing.com');

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION cortex_agents_api_eai
  ALLOWED_NETWORK_RULES = (common_db.security.cortex_agents_api_rule)
  ENABLED = TRUE;

GRANT USAGE ON INTEGRATION cortex_agents_api_eai TO ROLE app_owner_role;
```

> If your app and agent live in different accounts, add both hosts to
> `VALUE_LIST`:
> ```sql
> VALUE_LIST = (
>   'myorg-appaccount.snowflakecomputing.com',
>   'myorg-agentaccount.snowflakecomputing.com'
> );
> ```

**2 — PyPI** (allows uv to install packages from PyPI at deploy time). Snowflake provides a managed network rule. Requires ACCOUNTADMIN:

```sql
USE ROLE ACCOUNTADMIN;

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION pypi_eai
  ALLOWED_NETWORK_RULES = (snowflake.external_access.pypi_rule)
  ENABLED = TRUE;

GRANT USAGE ON INTEGRATION pypi_eai TO ROLE app_owner_role;
```

**Attach both EAIs to your Streamlit object:**

Via Snowsight Workspaces: click **Deploy → Network tab** and select both
integrations.

Via SQL:

```sql
CREATE OR REPLACE STREAMLIT my_db.my_schema.my_app
  FROM '@my_stage/app'
  MAIN_FILE                    = 'app.py'
  RUNTIME_NAME                 = 'SYSTEM$ST_CONTAINER_RUNTIME_PY3_11'
  COMPUTE_POOL                 = my_compute_pool
  QUERY_WAREHOUSE              = 'MY_WH'
  EXTERNAL_ACCESS_INTEGRATIONS = (cortex_agents_api_eai, pypi_eai);
```

To add EAIs to an already-deployed app:

```sql
ALTER STREAMLIT my_db.my_schema.my_app
  SET EXTERNAL_ACCESS_INTEGRATIONS = (cortex_agents_api_eai, pypi_eai);
```

### Authentication

Snowflake injects the session token automatically into the container. No
`.streamlit/secrets.toml` and no PAT required. Use `SiSContainerAuth()` and
`account_url_from_env()`:

```python
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env
```

### Quickstart

```python
# app.py
import streamlit as st
from cortex_agents_client.st import StreamlitChatbot
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

StreamlitChatbot(
    account_url=account_url_from_env(),
    auth=SiSContainerAuth(),
    agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
).render()
```

### Manual integration

```python
import streamlit as st
from cortex_agents_client.st import (
    sis_init_session,
    get_messages,
    append_message,
    render_stored_message,
    render_streaming_response,
    escape_dollars,
)
from cortex_agents_client.models.thread import StoredMessage

client, thread = sis_init_session(agent_path="MY_DB.MY_SCHEMA.MY_AGENT")

st.title("Revenue Assistant")

for msg in get_messages():
    with st.chat_message(msg.role):
        render_stored_message(msg, st)

if prompt := st.chat_input("Ask about revenue..."):
    with st.chat_message("user"):
        st.markdown(escape_dollars(prompt))
    append_message(StoredMessage(role="user", text=prompt))

    with st.chat_message("assistant"):
        stored = render_streaming_response(
            thread.chat("MY_DB.MY_SCHEMA.MY_AGENT", prompt),
            container=st,
            show_thinking=False,
            show_tool_status=True,
        )
    append_message(stored)
```

`sis_init_session` calls `SiSContainerAuth()` and `account_url_from_env()`
internally — it is the one-liner equivalent of `init_session` for SiS.

---

## External Streamlit

### Dependencies

Add to `requirements.txt`:

```
streamlit>=1.59
pandas
requests
```

### Secrets configuration

Create `.streamlit/secrets.toml` in your project root:

```toml
SNOWFLAKE_ACCOUNT_URL = "https://myorg-myaccount.snowflakecomputing.com"
SNOWFLAKE_PAT         = "v2:local:..."
```

`SNOWFLAKE_PAT` is a Programmatic Access Token. Generate one in Snowsight under
**Governance & security → Users & roles → your user → Programmatic access tokens**.

The agent path is not sensitive — hardcode it directly in your app code.

### Quickstart

```python
# app.py
import streamlit as st
from cortex_agents_client.st import StreamlitChatbot

StreamlitChatbot(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
).render()
```

Run with:

```bash
streamlit run app.py
```

### Manual integration

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

client, thread = init_session(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    origin_application="my_app",
)

st.title("Revenue Assistant")

for msg in get_messages():
    with st.chat_message(msg.role):
        render_stored_message(msg, st)

if prompt := st.chat_input("Ask about revenue..."):
    with st.chat_message("user"):
        st.markdown(escape_dollars(prompt))
    append_message(StoredMessage(role="user", text=prompt))

    with st.chat_message("assistant"):
        stored = render_streaming_response(
            thread.chat("MY_DB.MY_SCHEMA.MY_AGENT", prompt),
            container=st,
            show_thinking=False,
            show_tool_status=True,
        )
    append_message(stored)
```

### Other auth options

Pass an `AuthProvider` from `cortex_agents_client.auth` instead of a raw PAT
string when you need key-pair or OAuth:

```python
from cortex_agents_client.auth import PATAuth, JWTAuth, OAuthAuth

# PAT — equivalent to passing the token string directly
auth = PATAuth("v2:local:...")

# Key-pair / JWT
auth = JWTAuth(account="myorg-myaccount", user="MY_USER", private_key=key_bytes)

# OAuth (you supply the already-obtained bearer token)
auth = OAuthAuth(oauth_token)
```

---

## StreamlitChatbot options

These apply to both deployment environments.

### Full-page mode (default)

`st.chat_input` is pinned to the bottom of the page. The "New conversation"
button appears in the sidebar.

```python
bot = StreamlitChatbot(
    account_url=...,
    auth=...,
    agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
    show_thinking=True,
    show_tool_status=True,
    new_conversation_button=True,
    input_placeholder="Ask a question...",
    origin_application="my_app",
)
bot.render()
```

### Embedded mode

Fits inside any Streamlit container — a column, `st.dialog`, `st.sidebar`,
`st.expander`, etc. Uses a fixed-height scrollable message area and an inline
`st.chat_input`.

```python
# Two-column layout
dash_col, chat_col = st.columns([2, 1])
with dash_col:
    st.write("Your dashboard content")
with chat_col:
    StreamlitChatbot(
        account_url=..., auth=..., agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
        mode="embedded", height=500,
    ).render()
```

```python
# Modal dialog
@st.dialog("Ask the agent", width="large")
def open_chat():
    StreamlitChatbot(
        account_url=..., auth=..., agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
        mode="embedded", height=400,
    ).render()

if st.button("Open chat", icon=":material/chat:"):
    open_chat()
```

### File and audio attachments

```python
bot = StreamlitChatbot(
    ...,
    accept_file="multiple",   # True / "multiple" / "directory"
    file_type=["pdf", "csv"], # None accepts all types
    accept_audio=True,        # microphone button
)
```

### Multiple chatbots on one page

```python
bot1 = StreamlitChatbot(..., agent_path="DB.SCHEMA.AGENT_A", session_key_prefix="_bot1")
bot2 = StreamlitChatbot(..., agent_path="DB.SCHEMA.AGENT_B", session_key_prefix="_bot2")
```

### Client-side tool execution

```python
from cortex_agents_client.models.events import ToolUseEvent

def my_executor(event: ToolUseEvent) -> list[dict]:
    return [{"type": "json", "json": {"result": "value"}}]

bot = StreamlitChatbot(..., tool_executor=my_executor)
```

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
| Single conversation per session | `init_session()` / `sis_init_session()` once — thread persists for the browser session |
| Start over | `reset_thread()` — clears history and creates a new thread |
| Resume a previous conversation | Store `thread.thread_id`; call `client.get_thread(thread_id, parent_message_id=last_id)` |
| Branch a conversation | `thread.fork(at_message_id=N)` |

---

## `escape_dollars(text)`

Wrap user-supplied text before passing it to `st.markdown()` to prevent
Streamlit from interpreting `$N` patterns as LaTeX:

```python
st.markdown(escape_dollars(user_text))
```

`render_streaming_response` and `render_stored_message` call this internally.
You only need it when rendering text yourself.

---

## macOS note (ARM64)

If Streamlit crashes with a segfault when rendering DataFrames on Apple Silicon,
set two env vars **inline in the shell command** before Python loads:

```bash
ARROW_DEFAULT_MEMORY_POOL=system MALLOC_NANO_ZONE=0 streamlit run app.py
# or with uv:
ARROW_DEFAULT_MEMORY_POOL=system MALLOC_NANO_ZERO=0 uv run streamlit run app.py
```

> **Note:** Streamlit 1.59 removed support for the `[env]` section in
> `config.toml`. The env vars must be in the shell — setting them in Python
> code is too late because PyArrow is already loaded by that point.

This is a known PyArrow mimalloc allocator issue on macOS ARM64 and has no
impact on deployed apps running on Linux.
