[← Back to README](../README.md)

# Streamlit Integration Guide

For Streamlit-in-Snowflake (container runtime) deployment, see [Streamlit-in-Snowflake](sis.md). For parameter reference, see [Reference](reference.md#cortexagentchat-parameters). For wire-level event definitions, see [Event Types](event_types.md). For the REST API specification, see [API Spec](api_spec.md).

---

## Using the chat component

The `streamlit_cortex_agents.chat` subpackage provides a high-level drop-in chatbot component (`CortexAgentChat`). It also provides session-state and rendering helpers for custom Streamlit integrations.

---

## Streamlit-in-Snowflake (container runtime)

For deploying inside Snowflake using Streamlit-in-Snowflake container runtime (including External Access Integrations, authentication, and layout modes), see [Streamlit-in-Snowflake (container runtime)](sis.md).

---

## External Streamlit

For Streamlit applications running locally or hosted outside Snowflake.

### Dependencies

Add core dependencies to `requirements.txt`:

```text
streamlit>=1.64
pandas>=2.0
httpx>=0.27,<1
```

Or install the package directly with `pip` or `uv`:

```bash
pip install /path/to/streamlit-cortex-agents
# or with uv
uv add /path/to/streamlit-cortex-agents
```

### Secrets configuration

Create `.streamlit/secrets.toml` in your project root:

```toml
SNOWFLAKE_ACCOUNT_URL = "https://myorg-myaccount.snowflakecomputing.com"
SNOWFLAKE_PAT         = "v2:..."
```

`SNOWFLAKE_PAT` is a Programmatic Access Token. Generate one in Snowsight under **Governance & security → Users & roles → your user → Programmatic access tokens**.

The agent path is not sensitive. You can set it directly in your application code.

### Quickstart

```python
# app.py
import streamlit as st
from streamlit_cortex_agents.chat import CortexAgentChat

st.title("Revenue Assistant")

CortexAgentChat(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
    show_thinking=True,
    origin_application="revenue_app",
).render()
```

Run with:

```bash
streamlit run app.py
```

### Manual integration

For fine-grained control over layout and rendering, use the session state and rendering helpers:

```python
import streamlit as st
from streamlit_cortex_agents.chat import (
    init_session,
    get_messages,
    append_message,
    reset_thread,
    render_stored_message,
    render_streaming_response,
    escape_dollars,
)
from streamlit_cortex_agents.client import StoredMessage

client, thread = init_session(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    origin_application="my_app",
)

st.title("Revenue Assistant")

if st.sidebar.button("New conversation", type="primary"):
    reset_thread(origin_application="my_app")
    st.rerun()

for msg in get_messages():
    with st.chat_message(msg.role):
        if msg.role == "user":
            st.markdown(escape_dollars(msg.text))
        else:
            render_stored_message(msg, st, show_thinking=False, show_tool_status=True)

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

Pass the same `show_thinking` and `show_tool_status` values to `render_stored_message` and `render_streaming_response`. The replayed reasoning timeline then matches what the user saw while the answer streamed.

> **Note on `reset_thread`:** In manual integrations, `origin_application` defaults to `None` in `reset_thread()`. Pass `origin_application="my_app"` matching `init_session` to preserve thread tagging across resets.

### Other auth options

Pass an `AuthProvider` from `streamlit_cortex_agents.client.auth` instead of a raw PAT string when using key-pair or OAuth authentication:

```python
from streamlit_cortex_agents.client.auth import PATAuth, JWTAuth, OAuthAuth

# PAT — equivalent to passing the token string directly
auth = PATAuth("v2:...")

# Key-pair / JWT
auth = JWTAuth(
    account="myorg-myaccount",
    user="MY_USER",
    private_key_path="/path/to/rsa_key.p8",
)

# OAuth (you supply the already-obtained bearer token)
auth = OAuthAuth(oauth_token)
```

### Choosing an identity

The credential in `auth` sets whose access the agent uses. If the app uses one PAT or one key pair for all viewers, the app acts with that one user's rights. Every viewer gets that user's agent access and shares its thread namespace. This is the same model as the owner's rights in [Streamlit-in-Snowflake](sis.md#rbac-and-role-considerations).

The Quickstart uses a PAT for your own user. Use that setup for local development only. Do not deploy a shared app with the credential of a human user.

**When to use which identity:**
- **Shared service user.** Use this when all viewers can see the same data, for example an internal app for one team.
- **Shared service user with `variables`.** Use this when viewers must see different data but you cannot use per-viewer OAuth. See [Isolate viewers with `variables`](#isolate-viewers-with-variables).
- **Per-viewer OAuth.** Use this when viewers must see different data, or when audit logs must show each viewer.

#### Use a dedicated service user

Create a user with `TYPE = SERVICE`. A service user cannot sign in with a password or through the web interface. Give the user a dedicated role that follows the principle of least privilege:

```sql
USE ROLE USERADMIN;
CREATE ROLE IF NOT EXISTS cortex_chat_app_role;
CREATE USER IF NOT EXISTS cortex_chat_app_svc
  TYPE = SERVICE
  DEFAULT_ROLE = cortex_chat_app_role;
GRANT ROLE cortex_chat_app_role TO USER cortex_chat_app_svc;
```

Grant that role only the privileges that the agent and its tools need:
- `USAGE` on the agent, and on its database and schema.
- The `SNOWFLAKE.CORTEX_AGENT_USER` (or `SNOWFLAKE.CORTEX_USER`) database role.
- Tool-level privileges: `SELECT` on tables for Cortex Analyst, `USAGE` on search services for Cortex Search, and a warehouse for SQL tools.

Do not grant `ACCOUNTADMIN`, `SYSADMIN`, or another broad role to the service user. Every viewer receives that user's agent access.

#### Isolate viewers with `variables`

A service user cannot tell viewers apart. `CURRENT_USER()` and `CURRENT_ROLE()` always return the service user and its role. To isolate data per viewer:
1. Sign the viewer in to your app, for example with `st.login()`.
2. Pass the viewer's identity to the agent in `variables` (session attributes).
3. Filter on that attribute in a row access policy on the tables that the agent's tools query.

The row access policy enforces the boundary, not the API. Your app sets the identity, so the isolation is only as trusted as your app's sign-in. Viewers must not be able to change the value that the app sends. See [Multi-tenancy](#multi-tenancy).

#### Choose a credential for the service user

- **Key-pair JWT (`JWTAuth`).** Recommended for long-running services. The key pair does not expire, and you can rotate it with no downtime because a user can have two public keys (`RSA_PUBLIC_KEY` and `RSA_PUBLIC_KEY_2`). See [Key-pair authentication](https://docs.snowflake.com/en/user-guide/key-pair-auth).
- **PAT (`PATAuth`).** Simpler to set up, but a PAT expires, 15 days by default and 365 days at most. For a service user, a PAT has two requirements:
  - The user must be subject to a network policy. By default, Snowflake does not let a service user generate or use a PAT without one. Allow only the addresses of your app host.
  - You must set `ROLE_RESTRICTION` when you generate the PAT. The session uses only that role.

```sql
ALTER USER cortex_chat_app_svc
  ADD PROGRAMMATIC ACCESS TOKEN cortex_chat_app_token
  ROLE_RESTRICTION = 'cortex_chat_app_role'
  DAYS_TO_EXPIRY = 90;
```

See [Programmatic access tokens](https://docs.snowflake.com/en/user-guide/programmatic-access-tokens).

#### Store and rotate the credential

- Keep the PAT or private key in a secrets manager, or in `.streamlit/secrets.toml` that is not in version control. Do not put the credential in code.
- Plan rotation before the credential expires. Rotate a PAT with `ALTER USER ... ROTATE PROGRAMMATIC ACCESS TOKEN`. Rotate a key pair by setting the new key in the second public-key slot, updating the app, and then removing the old key.
- If a credential leaks, revoke it at once. Snowflake automatically disables PATs that are pushed to public GitHub repositories.

#### Per-viewer identity with OAuth

A shared service user cannot tell viewers apart. `CURRENT_USER()` is always the service user. For per-viewer access, sign each viewer in with OAuth (Snowflake OAuth or External OAuth). Then pass that viewer's access token to `OAuthAuth`. The agent then runs with the viewer's own role, and row access policies apply to each viewer.

The library does not get or refresh OAuth tokens. Your app must do the OAuth flow, keep the token in `st.session_state`, and refresh it before it expires.

---

## CortexAgentChat options

These options apply to both external Streamlit and Streamlit-in-Snowflake deployments.

### Full-page mode (default)

`st.chat_input` is pinned to the bottom of the page. The "New conversation" button appears in the sidebar:

```python
bot = CortexAgentChat(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
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

Embedded mode fits inside any Streamlit container: a column, dialog, sidebar, or expander. It uses a scrollable message area and an inline `st.chat_input`.

The `height` parameter sets the height of the scrollable message area. Use pixels as an `int` (default `450`), or a CSS height string such as `"calc(100vh - 300px)"`. A string height lets the chat fill an `st.dialog`, which has no height option of its own.

```python
# Two-column layout
dash_col, chat_col = st.columns([2, 1])
with dash_col:
    st.write("Your dashboard content")
with chat_col:
    CortexAgentChat(
        account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
        auth=st.secrets["SNOWFLAKE_PAT"],
        agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
        mode="embedded",
        height=500,
    ).render()
```

Inside an `@st.dialog`, control display with a session state flag. Set `dismissible=False` so the dialog persists across reruns that the chatbot triggers internally:

```python
# Modal dialog
if "chat_dialog_open" not in st.session_state:
    st.session_state.chat_dialog_open = False

st.session_state.setdefault("_dlg_messages", [])

@st.dialog("Ask the agent", width="large", dismissible=False)
def open_chat():
    with st.container(horizontal_alignment="right"):
        if st.button("Close", icon=":material/close:", type="tertiary"):
            st.session_state.chat_dialog_open = False
            st.rerun()
    CortexAgentChat(
        account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
        auth=st.secrets["SNOWFLAKE_PAT"],
        agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
        mode="embedded",
        height="calc(100vh - 440px)",
        session_key_prefix="_dlg",
    ).render()

if st.button("Open chat", icon=":material/chat:"):
    st.session_state.chat_dialog_open = True

if st.session_state.chat_dialog_open:
    open_chat()
```

### File and audio attachments

The chat input can accept files and audio, but attachments are display only. The chatbot shows files and audio uploaded via `accept_file` or `accept_audio` in the user bubble. It saves them in `StoredMessage.attachments` for replay across reruns. It does **not forward them to the agent**.

**Why:** the [Cortex Agents Run API](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-run) accepts only text in user messages. Its message schema has no content type for files, images, or audio, so there is no field to send an attachment in. This is an API limit, not a missing feature in this library.

Use attachments to show users what they uploaded. To act on a file, process it in your own app code with a [manual integration](#manual-integration). Only the typed text of the prompt reaches the agent:

```python
bot = CortexAgentChat(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
    accept_file="multiple",           # True, "multiple", "directory", or False
    file_type=["pdf", "csv", "txt"],  # None accepts all types
    accept_audio=True,                # microphone button
)
```

### Multiple chatbots on one page

Pass unique `session_key_prefix` values to isolate session state and DOM element keys:

```python
bot1 = CortexAgentChat(..., agent_path="DB.SCHEMA.AGENT_A", session_key_prefix="_bot1")
bot2 = CortexAgentChat(..., agent_path="DB.SCHEMA.AGENT_B", session_key_prefix="_bot2")
```

### Client-side tool execution

Pass a `tool_executor` callable to handle tools marked with `client_side_execute=True`:

```python
from streamlit_cortex_agents.client.models.events import ToolUseEvent

def my_executor(event: ToolUseEvent) -> list[dict]:
    if event.name == "get_current_user":
        return [{"type": "json", "json": {"user": st.context.user.email}}]
    return [{"type": "text", "text": "unknown tool"}]

bot = CortexAgentChat(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
    tool_executor=my_executor,
)
```

For tools that require user consent (`ToolUseEvent.permission_options` is non-empty), the chatbot automatically displays a permission approval UI before the tool runs.

### Working with table results

`result_set_to_dataframe` converts a `TableEvent` result set to a typed pandas DataFrame:

```python
import streamlit as st
from streamlit_cortex_agents.chat.render import result_set_to_dataframe
from streamlit_cortex_agents.client.models.events import TableEvent

for event in thread.chat("MY_DB.MY_SCHEMA.MY_AGENT", prompt):
    if isinstance(event, TableEvent):
        df = result_set_to_dataframe(event)
        st.dataframe(df.style.highlight_max(axis=0), width="stretch")
```

### Multi-tenancy

Pass `variables` to scope runs to a tenant. Supply a mapping for a fixed tenant, or a zero-argument callable to resolve the tenant per viewer at runtime:

```python
TENANT_BY_EMAIL = {"ana@example.com": "NORTH", "raj@example.com": "SOUTH"}

CortexAgentChat(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    agent_path="MY_DB.MY_SCHEMA.MY_AGENT",
    variables=lambda: {"region": TENANT_BY_EMAIL[st.context.user.email]},
).render()
```

See [Python API: Multi-tenancy (session attributes)](python_api.md#multi-tenancy-session-attributes) for the row access policy side.

### Elicitation

When the agent needs clarification before it continues, it emits a `TextEvent` with `is_elicitation=True`. Both `render_streaming_response` and `render_stored_message` render this turn in an info callout (`st.info(..., icon=":material/contact_support:", title="Clarification needed")`) instead of plain markdown. In custom renderers, check `msg.is_elicitation` on `StoredMessage`.

### Suggested follow-up queries

When the agent returns `response.suggested_queries` events, the chatbot renders them as `st.pills` below the last assistant message. Clicking a pill submits it as the next prompt.

- Suggestions appear only for the **most recent** assistant message (stale suggestions are hidden).
- When a thread has no messages, the chatbot fetches the agent specification and displays up to five starter questions (`agent_spec.instructions.sample_questions[:5]`). The chatbot caches the spec in `st.session_state["_ca_agent_spec"]`. If the spec fetch fails, the error is swallowed and no starter questions appear.
- Clicking a pill stores the text in `st.session_state["_ca_pending_suggestion"]` and clears the widget value before triggering a rerun.

### CSS targeting via widget keys

All rendered widgets receive stable `key` values. These keys produce `.st-key-*` CSS classes in the DOM:

Key pattern: `{css_prefix}-{msg_index}-{widget_type}` where `css_prefix` comes from `session_key_prefix` with the leading underscore removed.

| Widget | Key format | CSS class |
|---|---|---|
| Reasoning timeline (thinking and tool steps) | `{css_prefix}-{i}-thinking` | `.st-key-ca-{i}-thinking` |
| Verified-query step | `{css_prefix}-{i}-verified-step-{tool_use_id}` | `.st-key-ca-{i}-verified-step-toolu_01` |
| Table dataframe | `{css_prefix}-{i}-table-{n}` | `.st-key-ca-{i}-table-0` |
| Chart container | `{css_prefix}-{i}-chart-{n}` | `.st-key-ca-{i}-chart-0` |
| Sources expander | `{css_prefix}-{i}-sources` | `.st-key-ca-{i}-sources` |

Default `session_key_prefix` is `"_ca"` → `css_prefix` = `"ca"`.

Manual integration users can pass `key_prefix` directly to `render_streaming_response` and `render_stored_message` for custom CSS targeting.

---

## Session state helpers

| Function | Description |
|---|---|
| `init_session(account_url, auth, ...)` | Creates client and thread on first call. Returns cached objects on later reruns |
| `sis_init_session(*, origin_application=None, ...)` | Keyword-only helper for SiS container runtime that reads credentials from the container environment |
| `get_messages(key="_ca_messages")` | Returns the current `list[StoredMessage]` |
| `append_message(msg, key="_ca_messages")` | Appends a `StoredMessage` to session state history |
| `reset_thread(*, client_key=..., thread_key=..., messages_key=..., origin_application=None)` | Clears message history and creates a new thread while keeping the cached client |

---

## Thread lifecycle

| Scenario | Approach |
|---|---|
| Single conversation per session | `init_session()` / `sis_init_session()` once. The thread persists for the browser session |
| Start over | `reset_thread(origin_application=...)`. It clears history and creates a new thread |
| Resume a previous conversation | Store `thread.thread_id`. Call `client.get_thread(thread_id, parent_message_id=last_id)` |
| Branch a conversation | `thread.fork(at_message_id=N)` |

---

## `escape_dollars(text)`

Wrap user-supplied text before you pass it to `st.markdown()`. This stops Streamlit from reading `$N` patterns as LaTeX math:

```python
st.markdown(escape_dollars(user_text))
```

Both `render_streaming_response` and `render_stored_message` invoke `escape_dollars` internally. You only need to call it when rendering user text manually.

---

## macOS note (ARM64)

If Streamlit crashes with a segmentation fault when it renders DataFrames on Apple Silicon, pass these environment variables inline in the shell command that starts Streamlit:

```bash
ARROW_DEFAULT_MEMORY_POOL=system MALLOC_NANO_ZONE=0 streamlit run app.py
# or with uv:
ARROW_DEFAULT_MEMORY_POOL=system MALLOC_NANO_ZONE=0 uv run streamlit run app.py
```

> **Note:** Setting these environment variables in Python code is too late because PyArrow is imported during startup. Pass them in the terminal invocation.

This is a known PyArrow mimalloc allocator issue on macOS ARM64. It does not affect Linux deployments. See upstream issues: [microsoft/mimalloc#343](https://github.com/microsoft/mimalloc/issues/343) and [apache/arrow#41696](https://github.com/apache/arrow/issues/41696).

---

## Design reference

For internal implementation details, session state architecture, and the streaming/replay pipelines, see the [Streamlit Integration Design Reference](dev/streamlit_design.md).
