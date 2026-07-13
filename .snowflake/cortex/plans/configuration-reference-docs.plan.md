# Plan: Configuration reference documentation

## Context

README.md is 549 lines. The `## Authentication` section ends around line 94 and the `## Multi-turn conversations` section begins at line 96. The new section goes between them — readers are in setup mode at that point and will immediately want a reference for what to configure.

Key corrections from user feedback:
- `AGENT_PATH` is **not** a secret. It is a required constructor parameter to `StreamlitChatbot`; where it comes from (hardcoded, `st.secrets`, a selectbox, etc.) is the developer's choice.
- For PAT and OAuth, the token belongs in `st.secrets` when using Streamlit, or an env var when running scripts/CLI tools.

## Implementation steps

### Step 1 — `CortexAgentsClient` parameter table

Insert after line 94 (`## Multi-turn conversations` header), adding a new `## Configuration reference` section with this table:

```markdown
## Configuration reference

### `CortexAgentsClient`

| Parameter | Required | Default | Description |
|---|---|---|---|
| `account_url` | Yes | — | `https://myorg-myaccount.snowflakecomputing.com` |
| `auth` | Yes | — | `AuthProvider` instance or PAT string (auto-wrapped as `PATAuth`) |
| `timeout` | No | `900.0` | HTTP timeout in seconds (15 min = API max) |
| `default_database` | No | `None` | Default database — avoids repeating it in every `thread.chat()` call |
| `default_schema` | No | `None` | Default schema |
| `origin_application` | No | `None` | Label attached to threads for monitoring (max 16 bytes) |
```

### Step 2 — `StreamlitChatbot` parameter table

```markdown
### `StreamlitChatbot`

`account_url`, `auth`, and `agent_path` are always required. `agent_path` can come from
anywhere — hardcoded, `st.secrets`, a `st.selectbox`, etc.

| Parameter | Required | Default | Description |
|---|---|---|---|
| `account_url` | Yes | — | Snowflake account URL |
| `auth` | Yes | — | Auth provider or PAT string |
| `agent_path` | Yes | — | `DB.SCHEMA.AGENT` |
| `mode` | No | `"fullpage"` | `"fullpage"` or `"embedded"` |
| `height` | No | `450` | Message area height in px — `embedded` mode only |
| `show_thinking` | No | `False` | Show agent reasoning in an expander |
| `show_tool_status` | No | `True` | Show tool execution spinners |
| `new_conversation_button` | No | `True` | Show "New conversation" button |
| `origin_application` | No | `None` | Thread label for monitoring (max 16 bytes) |
| `input_placeholder` | No | `"Ask a question..."` | Chat input placeholder |
| `session_key_prefix` | No | `"_ca"` | `st.session_state` key prefix — change when running multiple bots on one page |
| `default_database` | No | `None` | Default database |
| `default_schema` | No | `None` | Default schema |
| `accept_file` | No | `False` | `True`, `"multiple"`, `"directory"`, or `False` |
| `accept_audio` | No | `False` | Enable microphone input |
| `file_type` | No | `None` | Allowed extensions, e.g. `["pdf","csv"]` — only applies when `accept_file` is set; `None` = all types |
| `tool_executor` | No | `None` | Callable for client-side tool execution |
```

### Step 3 — Secrets and environment variables by context

Organized by auth method. PAT and OAuth tokens go in `st.secrets` for Streamlit apps and env vars for scripts. JWT only needs the account URL stored externally — the key file path is passed in code. SiS has nothing user-supplied.

```markdown
### Secrets and environment variables

What you need to supply depends on both your auth method and where the app runs.

#### Streamlit app — `.streamlit/secrets.toml`

| Auth method | Key | Description |
|---|---|---|
| PAT *(recommended)* | `SNOWFLAKE_ACCOUNT_URL` | `https://myorg-myaccount.snowflakecomputing.com` |
| PAT | `SNOWFLAKE_PAT` | Programmatic Access Token (`v2:...`) |
| JWT | `SNOWFLAKE_ACCOUNT_URL` | Account URL — the key file path is passed in code |
| OAuth | `SNOWFLAKE_ACCOUNT_URL` | Account URL |
| OAuth | `SNOWFLAKE_OAUTH_TOKEN` | OAuth bearer token |

#### Streamlit-in-Snowflake (container runtime)

No `.streamlit/secrets.toml` needed. Snowflake injects credentials automatically:

| Variable / path | Injected by | Read by |
|---|---|---|
| `SNOWFLAKE_HOST` env var | Snowflake | `account_url_from_env()` |
| `/snowflake/session/token` file | Snowflake (auto-refreshed) | `SiSContainerAuth()` |

Do not set these manually — use `SiSContainerAuth()` and `account_url_from_env()`.

#### Plain Python scripts and live tests — environment variables

| Variable | Auth method | Description |
|---|---|---|
| `SNOWFLAKE_ACCOUNT_URL` | All | Account URL with `https://` scheme |
| `SNOWFLAKE_PAT` | PAT | Programmatic Access Token |
| `SNOWFLAKE_AGENT_PATH` | All | `DB.SCHEMA.AGENT` |
```

## Verification

After inserting: read the section back and confirm markdown tables render correctly (no misaligned columns, correct header separators). No code changes, no tests required.

## Critical files

- [README.md](README.md) — only file modified
