# streamlit_cortex_agents.chat — Streamlit Integration

Drop-in Streamlit components for Snowflake Cortex Agents. Copy the parent
`streamlit_cortex_agents/` folder into your project.

---

## Streamlit-in-Snowflake (container runtime)

> The Cortex Agents API requires **container runtime**. It is not available in
> warehouse runtime SiS apps.

### Installation

Copy the `streamlit_cortex_agents/` folder into your Streamlit app directory in Workspaces so it sits alongside your `app.py`:

```
my_streamlit_app/
├── streamlit-app.py
├── pyproject.toml
└── streamlit_cortex_agents/
    ├── __init__.py
    ├── auth.py
    ├── exceptions.py
    ├── http.py
    ├── sse.py
    ├── models/
    │   ├── __init__.py
    │   ├── agent.py
    │   ├── events.py
    │   └── thread.py
    ├── resources/
    │   ├── __init__.py
    │   ├── agents.py
    │   ├── runs.py
    │   └── threads.py
    └── st/
        ├── __init__.py
        ├── chatbot.py
        ├── render.py
        └── session.py
```

### Dependencies

Place a `pyproject.toml` in your app's source directory. uv resolves
dependencies at deploy time from PyPI:

```toml
[project]
name = "streamlit-app"
requires-python = "~=3.11.0"
version = "0.0.1"
description = ""
dependencies = [
    "streamlit[snowflake]>=1.64",
    "pandas",
    "requests",
    "httpx",
]

[tool.setuptools.packages.find]
include = ["streamlit_cortex_agents*"]

[tool.uv]
constraint-dependencies = ["numba>=0.56.0"]
exclude-newer = "7 days"

[tool.uv.exclude-newer-package]
streamlit = false
```

Streamlit is pre-installed in the SiS container image — add it explicitly only
if you need a newer version than the image provides.

### External Access Integrations (required)

Container runtime apps cannot make outbound network calls without an EAI. You
need **two**:

**1 — Cortex Agents API** (allows the app to call the Agents REST API). Requires ACCOUNTADMIN.

Network rules are schema-level objects — store them in a dedicated schema. The example below uses `common_db.security`; substitute your own database and schema.

First, get your account's correct hostnames (handles underscores → hyphens automatically):

```sql
SELECT LISTAGG('''' || REPLACE(host, '_', '-') || '''', ', ') AS allowlist
FROM (
    SELECT VALUE:host::VARCHAR AS host
    FROM TABLE(FLATTEN(INPUT => PARSE_JSON(SYSTEM$ALLOWLIST())))
    WHERE VALUE:type::VARCHAR IN ('SNOWFLAKE_DEPLOYMENT','SNOWFLAKE_DEPLOYMENT_REGIONLESS')
    UNION ALL
    SELECT VALUE:host::VARCHAR AS host
    FROM TABLE(FLATTEN(INPUT => PARSE_JSON(SYSTEM$ALLOWLIST_PRIVATELINK())))
    WHERE VALUE:type::VARCHAR IN ('SNOWFLAKE_DEPLOYMENT','SNOWFLAKE_DEPLOYMENT_REGIONLESS')
);
```

Then create the network rule using the hostnames from the query above:

```sql
USE ROLE ACCOUNTADMIN;

CREATE OR REPLACE NETWORK RULE common_db.security.cortex_agents_api_rule
  TYPE       = HOST_PORT
  MODE       = EGRESS
  VALUE_LIST = ('xy12345.us-east-1.snowflakecomputing.com',
                'myorg-myaccount.snowflakecomputing.com',
                'xy12345.us-east-1.privatelink.snowflakecomputing.com',
                'myorg-myaccount.privatelink.snowflakecomputing.com');  -- ← paste your allowlist result

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION cortex_agents_api_eai
  ALLOWED_NETWORK_RULES = (common_db.security.cortex_agents_api_rule)
  ENABLED = TRUE;

GRANT USAGE ON INTEGRATION cortex_agents_api_eai TO ROLE app_owner_role;
```

> **Note:** If your account name contains underscores (e.g. `my_account01`), always use
> the hyphenated form in `VALUE_LIST` (e.g. `my-account01`). The `SYSTEM$ALLOWLIST()`
> query handles this automatically via the `REPLACE` call.

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
  MAIN_FILE                    = 'streamlit-app.py'
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
from streamlit_cortex_agents.client.auth import SiSContainerAuth, account_url_from_env
```

### Quickstart

#### Full-page mode

```python
# streamlit-app.py — Full-page chatbot (chat input pinned to bottom)
import streamlit as st
from streamlit_cortex_agents.chat import StreamlitChatbot
from streamlit_cortex_agents.client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = "MY_DB.MY_SCHEMA.MY_AGENT"  # ← swap this

StreamlitChatbot(
    account_url=account_url_from_env(),
    auth=SiSContainerAuth(),
    agent_path=AGENT_PATH,
    show_thinking=True,
    show_tool_status=True,
    new_conversation_button=True,
    input_placeholder="Ask a question...",
).render()
```

#### Embedded mode (two-column layout)

```python
# streamlit-app.py — Dashboard + chat side by side
import streamlit as st
from streamlit_cortex_agents.chat import StreamlitChatbot
from streamlit_cortex_agents.client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = "MY_DB.MY_SCHEMA.MY_AGENT"  # ← swap this

st.set_page_config(layout="wide")
st.title("Revenue Dashboard")

dash_col, chat_col = st.columns([2, 1])

with dash_col:
    st.metric("Total Revenue", "$1.41M", "+18% vs Q4")
    st.metric("Total Orders", "5,492", "+12% vs Q4")

with chat_col:
    st.subheader("Ask the agent")
    StreamlitChatbot(
        account_url=account_url_from_env(),
        auth=SiSContainerAuth(),
        agent_path=AGENT_PATH,
        mode="embedded",
        height=500,
        show_thinking=True,
        show_tool_status=True,
        new_conversation_button=True,
        session_key_prefix="_emb",
    ).render()
```

#### Embedded mode (dialog popup)

The dialog must be driven by a **session state flag** so it persists across the
reruns triggered by the chatbot internally. Use `dismissible=False` to prevent
the dialog from closing when the user clicks outside it, and render the dialog
call **at the end of the script** (after all other content).

```python
# streamlit-app.py — Chat opens in a modal dialog that stays open across reruns
import streamlit as st
from streamlit_cortex_agents.chat import StreamlitChatbot
from streamlit_cortex_agents.client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = "MY_DB.MY_SCHEMA.MY_AGENT"  # ← swap this

st.set_page_config(layout="wide")

# --- State flag to keep dialog open across reruns ---
if "chat_dialog_open" not in st.session_state:
    st.session_state.chat_dialog_open = False

# Pre-seed messages so st.chat_input renders on the first dialog open.
st.session_state.setdefault("_dlg_messages", [])

@st.dialog("Ask the agent", width="large", dismissible=False, icon=":material/smart_toy:")
def _chat_dialog():
    with st.container(horizontal_alignment="right"):
        if st.button("Close", icon=":material/close:", type="tertiary"):
            st.session_state.chat_dialog_open = False
            st.rerun()
    StreamlitChatbot(
        account_url=account_url_from_env(),
        auth=SiSContainerAuth(),
        agent_path=AGENT_PATH,
        mode="embedded",
        # Fill the window; 440px covers the title, the Close and
        # New conversation buttons, suggestions and the chat input.
        height="calc(100vh - 440px)",
        show_thinking=True,
        show_tool_status=True,
        new_conversation_button=True,
        session_key_prefix="_dlg",
    ).render()

# --- Page content ---
st.title("My App")
# ... your dashboard, charts, metrics, etc. ...

if st.button("Open chat", icon=":material/chat:", type="primary"):
    st.session_state.chat_dialog_open = True

# --- Open dialog at the end (must be after all other content) ---
if st.session_state.chat_dialog_open:
    _chat_dialog()
```

### Manual integration

```python
import streamlit as st
from streamlit_cortex_agents.chat import (
    sis_init_session,
    get_messages,
    append_message,
    render_stored_message,
    render_streaming_response,
    escape_dollars,
)
from streamlit_cortex_agents.client.models.thread import StoredMessage

client, thread = sis_init_session(origin_application="my_sis_app")

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
streamlit>=1.64
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
from streamlit_cortex_agents.chat import StreamlitChatbot

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
from streamlit_cortex_agents.chat import (
    init_session,
    get_messages,
    append_message,
    render_stored_message,
    render_streaming_response,
    escape_dollars,
)
from streamlit_cortex_agents.client.models.thread import StoredMessage

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

Pass an `AuthProvider` from `streamlit_cortex_agents.client.auth` instead of a raw PAT
string when you need key-pair or OAuth:

```python
from streamlit_cortex_agents.client.auth import PATAuth, JWTAuth, OAuthAuth

# PAT — equivalent to passing the token string directly
auth = PATAuth("v2:local:...")

# Key-pair / JWT
auth = JWTAuth(account="myorg-myaccount", user="MY_USER", private_key_path="/path/to/rsa_key.p8")

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
`st.expander`, etc. Uses a scrollable message area and an inline
`st.chat_input`. `height` is pixels as an `int`, or a CSS height string such
as `"calc(100vh - 300px)"`. A string lets the chat fill an `st.dialog`, which
has no height option of its own; it relies on Streamlit's internal DOM
(verified on 1.64).

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
        mode="embedded", height="calc(100vh - 300px)",
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
from streamlit_cortex_agents.client.models.events import ToolUseEvent

def my_executor(event: ToolUseEvent) -> list[dict]:
    return [{"type": "json", "json": {"result": "value"}}]

bot = StreamlitChatbot(..., tool_executor=my_executor)
```

### Multi-tenancy

`variables` sends session attributes with every run so row access policies can
filter per tenant. Pass a mapping, or a callable that is invoked once per
prompt:

```python
bot = StreamlitChatbot(..., variables=lambda: {"region": tenant_for(st.context.user.email)})
```

Values default to immutable session attributes. See the main README's
"Multi-tenancy (session attributes)" section for the row access policy side.

### Suggested follow-up queries

When the agent returns `response.suggested_queries` events, the chatbot automatically renders them as `st.pills` below the last assistant message. Clicking a suggestion submits it as the next user prompt.

- Suggestions are only shown for the **most recent** assistant message (stale suggestions are hidden).
- No configuration is needed — if the API returns suggestions, they appear automatically.
- The session state key `_ca_pending_suggestion` is used internally to pass the clicked query. Selecting a pill clears it, so the same suggestion can be picked again.

### CSS targeting via widget keys

All rendered widgets receive stable `key` values that produce `.st-key-*` CSS
classes in the DOM. Use these to style individual elements with
`st.markdown(unsafe_allow_html=True)` or a custom stylesheet.

Key pattern: `{css_prefix}-{msg_index}-{widget_type}` where `css_prefix` is
derived from `session_key_prefix` (leading underscore stripped).

| Widget | Key format | CSS class |
|---|---|---|
| Thinking expander | `{css_prefix}-{i}-thinking` | `.st-key-ca-{i}-thinking` |
| Table dataframe | `{css_prefix}-{i}-table-{n}` | `.st-key-ca-{i}-table-0` |
| Chart container | `{css_prefix}-{i}-chart-{n}` | `.st-key-ca-{i}-chart-0` |
| Sources expander | `{css_prefix}-{i}-sources` | `.st-key-ca-{i}-sources` |

Default `session_key_prefix` is `"_ca"` → `css_prefix` = `"ca"`.

Manual integration users can pass `key_prefix` directly to
`render_streaming_response` and `render_stored_message` for custom targeting.

---

## Session state helpers

| Function | Description |
|---|---|
| `init_session(account_url, auth, ...)` | Creates client + thread on first call; returns cached objects on reruns |
| `sis_init_session(origin_application, ...)` | Same as `init_session` but reads credentials from SiS container environment |
| `get_messages(key="_ca_messages")` | Returns the current `list[StoredMessage]` |
| `append_message(msg, key="_ca_messages")` | Appends a message to history |
| `reset_thread(*, client_key=..., thread_key=..., messages_key=..., origin_application=None)` | Clears history and starts a new thread, reusing the client already in session state |

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
ARROW_DEFAULT_MEMORY_POOL=system MALLOC_NANO_ZONE=0 uv run streamlit run app.py
```

> **Note:** Streamlit 1.59 removed support for the `[env]` section in
> `config.toml`. The env vars must be in the shell — setting them in Python
> code is too late because PyArrow is already loaded by that point.

This is a known PyArrow mimalloc allocator issue on macOS ARM64 and has no
impact on deployed apps running on Linux. See upstream issues:
[microsoft/mimalloc#343](https://github.com/microsoft/mimalloc/issues/343),
[apache/arrow#41696](https://github.com/apache/arrow/issues/41696).
