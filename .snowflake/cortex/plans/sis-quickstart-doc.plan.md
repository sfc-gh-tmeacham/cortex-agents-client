# Plan: SiS Quickstart Document

## Context

- `examples/sis_app.py` — fullpage SiS chatbot, uses `SiSContainerAuth` + `account_url_from_env()`, good reference
- `examples/embedded_chat.py` — embedded + dialog patterns, but uses `st.secrets` (external app, not SiS)
- Dialog is not a separate `mode=` value — it is `mode="embedded"` placed inside `@st.dialog(...)`
- EAI setup is already covered in depth in README.md, so the quickstart links there rather than repeating it

## File

`examples/SIS_QUICKSTART.md`

## Document structure

### 1. Header + intro (2–3 sentences)
What this guide covers: deploying a Streamlit-in-Snowflake container runtime app that uses `cortex-agents-client` in three layout modes.

### 2. Prerequisites
- Snowflake account with container runtime enabled
- EAI granting the container outbound access to the Agents API — link to README for full SQL
- `cortex_agents_client/` directory copied into the workspace root (or installed via `uv add`)
- A Cortex Agent already created (`DB.SCHEMA.AGENT`)

### 3. Auth in SiS (one short paragraph)
Snowflake injects `SNOWFLAKE_HOST` env var and `/snowflake/session/token` automatically. Use `SiSContainerAuth()` + `account_url_from_env()` — no `secrets.toml` needed.

```python
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env
```

### 4. Mode 1 — Full-page (dedicated chat app)
Best for: a standalone chat page where the entire app IS the chatbot.

Complete runnable app, referencing and expanding `examples/sis_app.py`:

```python
import os
import streamlit as st
from cortex_agents_client.st import StreamlitChatbot
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = os.environ.get("AGENT_PATH", "MY_DB.MY_SCHEMA.MY_AGENT")

st.set_page_config(page_title="My Agent", page_icon=":material/smart_toy:", layout="wide")
st.title("My Agent")

StreamlitChatbot(
    account_url=account_url_from_env(),
    auth=SiSContainerAuth(),
    agent_path=AGENT_PATH,
    show_thinking=st.sidebar.toggle("Show reasoning", value=False),
).render()
```

→ Full example: `sis_app.py`

### 5. Mode 2 — Embedded (chat alongside dashboard content)
Best for: dashboards where the chat sits in a column next to charts or tables.

Key points:
- Use `mode="embedded"` with a `height` (pixels)
- Set `session_key_prefix` to a unique value when multiple chatbots appear on one page
- Uses `st.container(height=..., autoscroll=True)` internally — requires Streamlit ≥ 1.59

```python
import os
import streamlit as st
from cortex_agents_client.st import StreamlitChatbot
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = os.environ.get("AGENT_PATH", "MY_DB.MY_SCHEMA.MY_AGENT")

st.set_page_config(layout="wide")
st.title("Sales Dashboard")

dash_col, chat_col = st.columns([3, 2], gap="large")

with dash_col:
    # ... your dashboard charts and tables ...
    st.subheader("Revenue")
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
    ).render()
```

### 6. Mode 3 — Dialog (modal overlay)
Best for: minimising UI footprint — chat is hidden until the user clicks a button.

Key points:
- Still uses `mode="embedded"` — dialog is a layout pattern, not a separate mode
- Wrap `bot.render()` inside `@st.dialog(..., width="large")`
- The dialog function must be defined and called on each rerun (Streamlit's decorator pattern)

```python
import os
import streamlit as st
from cortex_agents_client.st import StreamlitChatbot
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

AGENT_PATH = os.environ.get("AGENT_PATH", "MY_DB.MY_SCHEMA.MY_AGENT")

st.set_page_config(layout="wide")
st.title("Sales Dashboard")

# ... your dashboard content ...
st.bar_chart({"Q1": 100, "Q2": 120, "Q3": 115, "Q4": 140})

if st.button("Ask the agent", icon=":material/chat:", type="primary"):
    @st.dialog("Cortex Agent", width="large")
    def _chat():
        StreamlitChatbot(
            account_url=account_url_from_env(),
            auth=SiSContainerAuth(),
            agent_path=AGENT_PATH,
            mode="embedded",
            height=450,
            session_key_prefix="_ca_dlg",
        ).render()
    _chat()
```

### 7. Adding to an existing SiS app
One-paragraph note: if you already have a SiS app, the only change is to import `StreamlitChatbot`, `SiSContainerAuth`, and `account_url_from_env`, then call `bot.render()` wherever you want the chat to appear. No secrets, no new integrations needed beyond the EAI.

### 8. Choosing a mode (quick-reference table)

| Mode | Use when | `mode=` value |
|---|---|---|
| Full-page | The entire app is the chatbot | `"fullpage"` (default) |
| Embedded | Chat lives alongside charts/tables | `"embedded"` |
| Dialog | Chat is secondary; user opens it on demand | `"embedded"` inside `@st.dialog` |

## Critical files

- `examples/SIS_QUICKSTART.md` — file to create
- `examples/sis_app.py` — referenced for fullpage mode
- `examples/embedded_chat.py` — referenced/adapted for embedded + dialog (SiS variant)
- `cortex_agents_client/st/chatbot.py` — source of truth for all mode behaviour
