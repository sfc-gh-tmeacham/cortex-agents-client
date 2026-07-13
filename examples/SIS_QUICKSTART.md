# Streamlit-in-Snowflake Quickstart

This guide shows how to embed a Cortex Agents chatbot in a Streamlit-in-Snowflake
(SiS) container runtime app. It covers three layout modes — full-page, embedded,
and dialog — and applies to both new apps and existing ones.

> **Container runtime is required.** Warehouse runtime does not support the Cortex
> Agents API.

---

## Prerequisites

1. **EAI** — A container runtime app cannot call the Agents API without an External
   Access Integration. See the [README](../README.md#streamlit-in-snowflake-container-runtime)
   for the `CREATE NETWORK RULE` / `CREATE EXTERNAL ACCESS INTEGRATION` SQL.

2. **Library** — Copy `cortex_agents_client/` into your workspace root (the directory
   Snowflake puts on `sys.path`), or declare it as a dependency in `pyproject.toml`
   (replace the path with wherever you have the library on disk):

   ```toml
   dependencies = [
       "cortex-agents-client[streamlit] @ file:///path/to/cortex-agents-client",
   ]
   ```

3. **A Cortex Agent** — you need an agent path in `DB.SCHEMA.AGENT` format with
   the appropriate privileges granted to your role.

---

## Authentication in SiS

Snowflake automatically injects two things into every container runtime app:

| What | How to use it |
|---|---|
| `SNOWFLAKE_HOST` env var | `account_url_from_env()` wraps it with `https://` |
| `/snowflake/session/token` file | `SiSContainerAuth()` re-reads it on every request |

No `.streamlit/secrets.toml` is needed.

```python
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

account_url = account_url_from_env()   # https://<your-account>.snowflakecomputing.com
auth        = SiSContainerAuth()       # reads /snowflake/session/token on every request
```

---

## Mode 1 — Full-page

The entire Streamlit page is the chatbot. Best for a dedicated chat experience where
users come specifically to talk to the agent.

```python
# sis_fullpage.py
import os
import streamlit as st
from cortex_agents_client.st import StreamlitChatbot
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = os.environ.get("AGENT_PATH", "MY_DB.MY_SCHEMA.MY_AGENT")

st.set_page_config(
    page_title="My Agent",
    page_icon=":material/smart_toy:",
    layout="wide",
)
st.title("My Agent")

StreamlitChatbot(
    account_url=account_url_from_env(),
    auth=SiSContainerAuth(),
    agent_path=AGENT_PATH,
    show_thinking=st.sidebar.toggle("Show reasoning", value=True),
    origin_application="sis_fullpage",
).render()
```

> See [`sis_app.py`](sis_app.py) for the complete reference app.

---

## Mode 2 — Embedded

The chatbot lives in a column alongside charts, tables, or other content. Best for
dashboards where you want analysis and conversation in the same view.

Key points:
- `mode="embedded"` uses a fixed-height scrollable container (`st.container(height=..., autoscroll=True)`)
- Requires Streamlit ≥ 1.59
- Set `session_key_prefix` to a unique string if you place multiple chatbots on the same page

```python
# sis_embedded.py
import os
import streamlit as st
from cortex_agents_client.st import StreamlitChatbot
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = os.environ.get("AGENT_PATH", "MY_DB.MY_SCHEMA.MY_AGENT")

st.set_page_config(page_title="Sales Dashboard", layout="wide")
st.title("Sales Dashboard")

col_metrics_a, col_metrics_b, col_metrics_c = st.columns(3)
col_metrics_a.metric("Revenue",        "$1.2M",  "+8%")
col_metrics_b.metric("Orders",         "4,320",  "+12%")
col_metrics_c.metric("Avg order value","$278",   "-2%")

st.divider()

dash_col, chat_col = st.columns([3, 2], gap="large")

with dash_col:
    st.subheader("Monthly revenue")
    st.bar_chart({"Q1": 100, "Q2": 120, "Q3": 115, "Q4": 140})

with chat_col:
    st.subheader(":material/smart_toy: Ask the agent")
    StreamlitChatbot(
        account_url=account_url_from_env(),
        auth=SiSContainerAuth(),
        agent_path=AGENT_PATH,
        mode="embedded",
        height=500,
        session_key_prefix="_ca_dash",
        origin_application="sis_embedded",
    ).render()
```

---

## Mode 3 — Dialog

The chatbot opens as a modal overlay when the user clicks a button. Best when chat
is secondary to the main content and you want to minimise the UI footprint.

Key points:
- This is still `mode="embedded"` — the dialog is a layout pattern, not a separate mode value
- Wrap `bot.render()` inside `@st.dialog(..., width="large")` and call the function when the button is pressed
- `width="large"` gives the chat input enough room to be comfortable

```python
# sis_dialog.py
import os
import streamlit as st
from cortex_agents_client.st import StreamlitChatbot
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = os.environ.get("AGENT_PATH", "MY_DB.MY_SCHEMA.MY_AGENT")

st.set_page_config(page_title="Sales Dashboard", layout="wide")
st.title("Sales Dashboard")

# Your main dashboard content
st.bar_chart({"Q1": 100, "Q2": 120, "Q3": 115, "Q4": 140})
st.dataframe(
    {"Product": ["Widget A", "Widget B", "Widget C"], "Revenue": ["$248k", "$196k", "$130k"]},
    hide_index=True,
    use_container_width=True,
)

# Dialog trigger
if st.button("Ask the agent", icon=":material/chat:", type="primary"):
    @st.dialog("Cortex Agent", width="large")
    def _chat() -> None:
        StreamlitChatbot(
            account_url=account_url_from_env(),
            auth=SiSContainerAuth(),
            agent_path=AGENT_PATH,
            mode="embedded",
            height=450,
            session_key_prefix="_ca_dlg",
            origin_application="sis_dialog",
        ).render()

    _chat()
```

---

## Adding to an existing SiS app

If you already have a deployed SiS container runtime app, the only changes are:

1. Copy `cortex_agents_client/` into the workspace root (or add to `pyproject.toml`).
2. Ensure the EAI is attached to the Streamlit object.
3. Add the import and a single `.render()` call where you want the chat to appear:

```python
from cortex_agents_client.st import StreamlitChatbot
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

# Drop into any existing page — fullpage, a column, a tab, or inside @st.dialog
StreamlitChatbot(
    account_url=account_url_from_env(),
    auth=SiSContainerAuth(),
    agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
    mode="embedded",   # or "fullpage"
    height=500,
).render()
```

To attach the EAI to an already-deployed app without redeploying:

```sql
ALTER STREAMLIT my_db.my_schema.my_app
  SET EXTERNAL_ACCESS_INTEGRATIONS = (cortex_agents_api_eai);
```

---

## Choosing a mode

| Mode | Use when | `mode=` | Requires |
|---|---|---|---|
| Full-page | The whole app is the chatbot | `"fullpage"` (default) | — |
| Embedded | Chat lives alongside charts or tables | `"embedded"` | Streamlit ≥ 1.59 |
| Dialog | Chat is secondary; opened on demand | `"embedded"` inside `@st.dialog` | Streamlit ≥ 1.59 |
