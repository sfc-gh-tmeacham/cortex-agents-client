[← Back to README](../README.md) · See also: [Streamlit guide](streamlit_guide.md) · [Reference](reference.md) · [Python API](python_api.md)

# Streamlit-in-Snowflake (container runtime)

> **Container runtime is required.** The Cortex Agents API is not supported in warehouse runtime SiS apps.

This guide is the single home for deploying Cortex Agents chat in Streamlit-in-Snowflake (SiS) using the container runtime. It covers prerequisites, External Access Integrations (EAIs), authentication, three layout modes (full-page, embedded, dialog), manual integration, deployment methods (Workspaces and SQL/CLI), and RBAC/governance considerations.

For general Streamlit usage outside Snowflake, see the [Streamlit Integration Guide](streamlit_guide.md). For top-level project overview, see the [README](../README.md).

---

## Prerequisites — External Access Integrations

Container runtime apps cannot make outbound network calls without an External Access Integration (EAI). You need **two**:

1. **Cortex Agents API EAI** — allows the app to call the Agents REST API.
2. **PyPI EAI** — allows `uv` to install packages from PyPI at deploy time.

### Cortex Agents API EAI

Allows the app to call the Agents REST API. Creating integrations requires `ACCOUNTADMIN` (or a role with `CREATE INTEGRATION` privilege).

Network rules are schema-level objects — store them in a dedicated security schema. The example below uses `common_db.security`; substitute your own database and schema.

First, retrieve your account's correct hostnames (the query automatically handles converting underscores to hyphens):

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

Then create the network rule and integration using the hostnames returned by the query:

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

> **Note:** If your account name contains underscores (e.g. `my_account01`), always use the hyphenated form in `VALUE_LIST` (e.g. `my-account01`). The `SYSTEM$ALLOWLIST()` query handles this automatically via `REPLACE`.

> **Multi-account setup:** If your app and agent live in different accounts, add both account hosts to `VALUE_LIST`:
>
> ```sql
> VALUE_LIST = (
>   'myorg-appaccount.snowflakecomputing.com',
>   'myorg-agentaccount.snowflakecomputing.com'
> );
> ```

### PyPI EAI

Allows `uv` to install packages from PyPI at deploy time. Snowflake provides a managed network rule. Requires `ACCOUNTADMIN`:

```sql
USE ROLE ACCOUNTADMIN;

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION pypi_eai
  ALLOWED_NETWORK_RULES = (snowflake.external_access.pypi_rule)
  ENABLED = TRUE;

GRANT USAGE ON INTEGRATION pypi_eai TO ROLE app_owner_role;
```

---

## Authentication <a name="sis-authentication"></a>

Snowflake automatically injects two resources into every container runtime app:

| Resource | Purpose | How to use it |
|---|---|---|
| `SNOWFLAKE_HOST` env var | Account hostname | `account_url_from_env()` wraps it with `https://` |
| `/snowflake/session/token` file | Session OAuth token | `SiSContainerAuth()` re-reads it on every request |

No `.streamlit/secrets.toml` file is needed. Use `SiSContainerAuth()` — it re-reads the token file on every HTTP request so auto-refreshed tokens are picked up without restarting the app:

```python
from streamlit_cortex_agents.client.auth import SiSContainerAuth, account_url_from_env

account_url = account_url_from_env()   # https://<your-account>.snowflakecomputing.com
auth        = SiSContainerAuth()       # reads /snowflake/session/token on every request
```

---

## Quickstart — Three layout modes

CortexAgentChat supports three primary layout patterns in SiS:
- **Full-page**: Dedicated chat interface where the entire page is the assistant.
- **Embedded**: Chat lives alongside charts, tables, or metrics in dashboards.
- **Dialog**: Chat opens inside a modal popup on demand.

All three modes require **Streamlit ≥ 1.64** (`streamlit[snowflake]>=1.64`).

### Mode 1 — Full-page

The entire Streamlit page is the chatbot. The chat input is pinned to the bottom of the page, and the "New conversation" button appears in the sidebar.

```python
# sis_fullpage.py
import streamlit as st
from streamlit_cortex_agents.chat import CortexAgentChat
from streamlit_cortex_agents.client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = "MY_DB.MY_SCHEMA.MY_AGENT"  # not sensitive — hardcode your agent path

st.set_page_config(
    page_title="My Agent",
    page_icon=":material/smart_toy:",
    layout="wide",
)
st.title("My Agent")

CortexAgentChat(
    account_url=account_url_from_env(),
    auth=SiSContainerAuth(),
    agent_path=AGENT_PATH,
    show_thinking=st.sidebar.toggle("Show reasoning", value=True),
    show_tool_status=True,
    new_conversation_button=True,
    origin_application="sis_fullpage",
).render()
```

> See [`sis_app.py`](../examples/sis_app.py) for the complete reference application.

### Mode 2 — Embedded

The chatbot lives in a column alongside charts, tables, or other dashboard content.

Key points:
- `mode="embedded"` renders inside a scrollable container (`st.container(height=..., autoscroll=True)`). Default `height` is 450 pixels.
- Use unique `session_key_prefix` strings if you place multiple chatbots on the same page.
- Tables rendered alongside chat should use `width="stretch"` (replacing deprecated `use_container_width=True`).

```python
# sis_embedded.py
import streamlit as st
from streamlit_cortex_agents.chat import CortexAgentChat
from streamlit_cortex_agents.client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = "MY_DB.MY_SCHEMA.MY_AGENT"  # not sensitive — hardcode your agent path

st.set_page_config(page_title="Sales Dashboard", layout="wide")
st.title("Sales Dashboard")

col_metrics_a, col_metrics_b, col_metrics_c = st.columns(3)
col_metrics_a.metric("Revenue", "$1.2M", "+8%")
col_metrics_b.metric("Orders", "4,320", "+12%")
col_metrics_c.metric("Avg order value", "$278", "-2%")

st.divider()

dash_col, chat_col = st.columns([3, 2], gap="large")

with dash_col:
    st.subheader("Monthly revenue")
    st.bar_chart({"Q1": 100, "Q2": 120, "Q3": 115, "Q4": 140})

with chat_col:
    st.subheader(":material/smart_toy: Ask the agent")
    CortexAgentChat(
        account_url=account_url_from_env(),
        auth=SiSContainerAuth(),
        agent_path=AGENT_PATH,
        mode="embedded",
        height=500,
        session_key_prefix="_ca_dash",
        origin_application="sis_embedded",
    ).render()
```

### Mode 3 — Dialog

The chatbot opens in a modal dialog overlay when the user clicks a button.

Key points:
- This is `mode="embedded"` inside an `@st.dialog` decorator.
- The dialog must be driven by a **session state flag** so it persists across reruns triggered internally by the chatbot.
- Use `dismissible=False` to prevent the dialog from closing when clicking outside.
- Pre-seed the messages list (`st.session_state.setdefault("_dlg_messages", [])`) so `st.chat_input` renders on the first dialog open.
- Place the dialog invocation **at the end of the script**, after all page content.

```python
# sis_dialog.py
import streamlit as st
from streamlit_cortex_agents.chat import CortexAgentChat
from streamlit_cortex_agents.client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = "MY_DB.MY_SCHEMA.MY_AGENT"  # not sensitive — hardcode your agent path

st.set_page_config(page_title="Sales Dashboard", layout="wide")

# --- State flag to keep dialog open across reruns ---
if "chat_dialog_open" not in st.session_state:
    st.session_state.chat_dialog_open = False

# Pre-seed messages so st.chat_input renders on the first dialog open.
st.session_state.setdefault("_dlg_messages", [])

@st.dialog("Ask the agent", width="large", dismissible=False, icon=":material/smart_toy:")
def _chat_dialog() -> None:
    with st.container(horizontal_alignment="right"):
        if st.button("Close", icon=":material/close:", type="tertiary"):
            st.session_state.chat_dialog_open = False
            st.rerun()
    CortexAgentChat(
        account_url=account_url_from_env(),
        auth=SiSContainerAuth(),
        agent_path=AGENT_PATH,
        mode="embedded",
        height="calc(100vh - 440px)",
        show_thinking=True,
        show_tool_status=True,
        new_conversation_button=True,
        session_key_prefix="_dlg",
        origin_application="sis_dialog",
    ).render()

# --- Page content ---
st.title("Sales Dashboard")
st.bar_chart({"Q1": 100, "Q2": 120, "Q3": 115, "Q4": 140})
st.dataframe(
    {"Product": ["Widget A", "Widget B", "Widget C"], "Revenue": ["$248k", "$196k", "$130k"]},
    hide_index=True,
    width="stretch",
)

if st.button("Open chat", icon=":material/chat:", type="primary"):
    st.session_state.chat_dialog_open = True

# --- Open dialog at the end (must be after all other content) ---
if st.session_state.chat_dialog_open:
    _chat_dialog()
```

### Choosing a mode

| Mode | Use when | `mode=` | Requires |
|---|---|---|---|
| Full-page | The whole app is the chatbot | `"fullpage"` (default) | Streamlit ≥ 1.64 |
| Embedded | Chat lives alongside charts or tables | `"embedded"` | Streamlit ≥ 1.64 |
| Dialog | Chat is secondary; opened on demand | `"embedded"` inside `@st.dialog` | Streamlit ≥ 1.64 |

### Adding to an existing SiS app

If you already have a deployed SiS container runtime app, integration requires only:

1. Copy `src/streamlit_cortex_agents/` into the workspace root (or add to `pyproject.toml`).
2. Ensure both EAIs are attached to the Streamlit object.
3. Add the import and call `.render()` where the chat should appear:

```python
from streamlit_cortex_agents.chat import CortexAgentChat
from streamlit_cortex_agents.client.auth import SiSContainerAuth, account_url_from_env

CortexAgentChat(
    account_url=account_url_from_env(),
    auth=SiSContainerAuth(),
    agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
    mode="embedded",   # or "fullpage"
    height=500,
).render()
```

To attach EAIs to an existing app without recreating it:

```sql
ALTER STREAMLIT my_db.my_schema.my_app
  SET EXTERNAL_ACCESS_INTEGRATIONS = (cortex_agents_api_eai, pypi_eai);
```

---

## Drop-in chatbot

Minimal drop-in chatbot using defaults:

```python
# streamlit-app.py
from streamlit_cortex_agents.chat import CortexAgentChat
from streamlit_cortex_agents.client.auth import SiSContainerAuth, account_url_from_env

CortexAgentChat(
    account_url=account_url_from_env(),
    auth=SiSContainerAuth(),
    agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
).render()
```

---

## Manual integration

For fine-grained UI control, use `sis_init_session()` in place of `init_session()`. It automatically configures `SiSContainerAuth()` and `account_url_from_env()`:

```python
import streamlit as st
from streamlit_cortex_agents.chat import (
    sis_init_session,
    get_messages,
    append_message,
    reset_thread,
    render_stored_message,
    render_streaming_response,
    escape_dollars,
)
from streamlit_cortex_agents.client import StoredMessage

client, thread = sis_init_session(origin_application="my_sis_app")

if st.sidebar.button("New conversation", type="primary"):
    reset_thread(origin_application="my_sis_app")
    st.rerun()

for msg in get_messages():
    with st.chat_message(msg.role):
        if msg.role == "user":
            st.markdown(escape_dollars(msg.text))
        else:
            render_stored_message(msg, st, show_thinking=False)

if prompt := st.chat_input("Ask a question..."):
    with st.chat_message("user"):
        st.markdown(escape_dollars(prompt))
    append_message(StoredMessage(role="user", text=prompt))

    with st.chat_message("assistant"):
        stored = render_streaming_response(
            thread.chat("MY_DB.MY_SCHEMA.MY_AGENT", prompt),
            container=st,
        )
    append_message(stored)
```

> **Note on `reset_thread`:** `origin_application` defaults to `None` in `reset_thread()`. Pass `origin_application="my_sis_app"` to retain thread monitoring tags across conversation resets.

---

## Deploying the app

### Workspaces (recommended)

Workspaces is a file-based IDE in Snowsight where you edit files directly and deploy with a click, without writing manual DDL.

1. In Snowsight, navigate to **Workspaces → + Add new → Streamlit app**. Snowflake creates a project folder with starter files.
2. Copy the `src/streamlit_cortex_agents/` directory into your workspace root alongside your app file:

   ```
   your_workspace/
   ├── streamlit-app.py
   ├── pyproject.toml
   └── streamlit_cortex_agents/
       ├── __init__.py
       ├── py.typed
       ├── chat/
       │   ├── __init__.py
       │   ├── chatbot.py
       │   ├── render.py
       │   └── session.py
       └── client/
           ├── __init__.py
           ├── core.py
           ├── auth.py
           ├── exceptions.py
           ├── http.py
           ├── sse.py
           ├── _variables.py
           ├── models/
           │   ├── __init__.py
           │   ├── agent.py
           │   ├── events.py
           │   └── thread.py
           └── resources/
               ├── __init__.py
               ├── agents.py
               ├── runs.py
               └── threads.py
   ```

   Because the workspace root is placed on `sys.path`, `import streamlit_cortex_agents` resolves without a separate package installation step.

3. Edit `pyproject.toml` to declare dependencies:

   ```toml
   [project]
   name = "my-sis-app"
   requires-python = "~=3.11.0"
   version = "0.1.0"
   dependencies = [
       "streamlit[snowflake]>=1.64",
       "pandas",
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

   Streamlit is pre-installed in the SiS container image; declare `streamlit[snowflake]>=1.64` to pin the required version.

4. Click **Deploy**. In the deploy modal, open the **Network** tab and attach both `cortex_agents_api_eai` and `pypi_eai`.

### SQL / Snowflake CLI

Upload your app files to a Snowflake internal stage, then create the Streamlit object with SQL. Use the `FROM` parameter (`ROOT_LOCATION` is deprecated and applies only to warehouse runtime):

```sql
CREATE OR REPLACE STREAMLIT my_db.my_schema.my_app
  FROM '@my_db.my_schema.my_stage/app'
  MAIN_FILE                    = 'streamlit-app.py'
  RUNTIME_NAME                 = 'SYSTEM$ST_CONTAINER_RUNTIME_PY3_11'
  COMPUTE_POOL                 = my_compute_pool
  QUERY_WAREHOUSE              = 'MY_WH'
  EXTERNAL_ACCESS_INTEGRATIONS = (cortex_agents_api_eai, pypi_eai);
```

To update EAIs on an existing Streamlit object:

```sql
ALTER STREAMLIT my_db.my_schema.my_app
  SET EXTERNAL_ACCESS_INTEGRATIONS = (cortex_agents_api_eai, pypi_eai);
```

---

## RBAC and role considerations

### How RBAC is enforced

By default, SiS container runtime apps execute with **owner's rights**, identical to stored procedures. The OAuth token at `/snowflake/session/token` (read by `SiSContainerAuth()`) is scoped to the **app owner's role**, not the role of the user viewing the app. Snowflake enforces all access control server-side.

This means:
- `CURRENT_USER()` and `CURRENT_ROLE()` inside Cortex Agents API calls return the **app owner's** identity and role.
- Every viewer of the app shares the same token and effective privileges.
- All viewers share the same thread namespace on the server if threads are listed by the owner identity.

**Agent access requires (granted to the app owner's role):**
- `USAGE ON AGENT` granted to the app owner's role.
- `SNOWFLAKE.CORTEX_AGENT_USER` (or `SNOWFLAKE.CORTEX_USER`) database role granted to the app owner's role.
- Tool-level privileges: `SELECT` on tables for Cortex Analyst, `USAGE` on search services for Cortex Search.

### Restricted Caller's Rights

As of June 1, 2026 (GA), container runtime apps support **Restricted Caller's Rights**, which runs Snowflake connections with the viewer's privileges rather than the owner's (requires Streamlit ≥ 1.53.1). In this mode, `st.connection("snowflake-callers-rights")` provides a SQL connection scoped to the viewer's role for queries respecting per-user row access policies.

**However, Restricted Caller's Rights does not extend to the Cortex Agents REST API.** The caller's rights token (`Sf-Context-Current-User-Token` request header):
- Is designed for Snowflake SQL connections via the Python connector, not for raw REST API Bearer tokens.
- Is only valid for **2 minutes** (created at session start and not refreshed).
- Cannot be extracted or used as a Bearer token in external REST API calls.

`SiSContainerAuth()` reads `/snowflake/session/token`, which is always the **owner's** token. There is no supported way to pass the viewer's caller's rights token into Cortex Agents REST API calls.

### Role switching

Roles cannot be switched through the Cortex Agents REST API. The token is fixed at session launch — there is no `USE ROLE` equivalent for REST API requests.

### Options for per-viewer data isolation

Because the REST API always runs as the app owner, per-viewer data isolation can be achieved through:

1. **Row access policies on agent tools:** Configure row access policies on tables queried by Cortex Analyst. Note that `CURRENT_USER()` in owner's rights mode returns the app owner. To filter per viewer, pass the viewer's identity via `variables` (session attributes) or the prompt, and filter based on those attributes.
2. **Separate app deployments:** Deploy separate Streamlit apps owned by roles with different data access privileges, directing users to the appropriate app.
3. **Snowpark session for non-agent SQL:** Use `st.connection("snowflake-callers-rights")` for supplementary dashboard queries that must execute with viewer privileges.

The recommended governance pattern is to grant the app owner's role only the minimum privileges required on behalf of all viewers, and configure the agent's semantic models and search services to govern data access.

### Thread isolation between viewers

Because all API calls run as the app owner, threads are owned by the app owner's identity. `GET /api/v2/cortex/threads` returns all threads created by the owner.

- **Ephemeral (single session) — isolated by default:** `sis_init_session()` stores the thread in `st.session_state`, which Streamlit scopes to each browser session. Each viewer gets an isolated in-memory thread. When the browser tab closes, the session state is discarded.
- **Persistent (resuming across sessions) — requires application keying:** The viewer's identity is available via `st.context.user.login_name` (provided from HTTP session headers, independent of the Snowflake token). You can store the `thread_id` keyed by viewer in a Snowflake metadata table, and look it up on subsequent sessions.
- **`origin_application` tag:** Use `origin_application` as a soft namespace (e.g. `f"app_{viewer_login}"` up to 16 bytes) to filter thread listings by application or user group.

A first-class `sis_init_session_per_viewer()` helper is [on the roadmap](dev/roadmap.md).
