[← Back to README](../README.md) · See also: [Event Types](event_types.md) · [REST API Spec](api_spec.md) · [Reference](reference.md)

# Core Python API

The chat component uses this REST client (`streamlit_cortex_agents.client`). You can also use the client directly. The sections below apply to all environments: scripts, notebooks, external Streamlit, and SiS.

## Authentication

> **Streamlit-in-Snowflake (container runtime)**: Snowflake injects credentials automatically. Use `SiSContainerAuth()`. You do not need to manage tokens. See [Streamlit-in-Snowflake → Authentication](sis.md#prerequisites--external-access-integrations).

### PAT (Programmatic Access Token) — recommended

```python
client = CortexAgentsClient(
    account_url="https://myorg-myaccount.snowflakecomputing.com",
    auth="v2:my_pat_token",   # plain string → auto-wrapped as PATAuth
)
```

### JWT (RSA key-pair)

JWT requires the `[jwt]` extra. See [Installation](../README.md#installation).

```python
from streamlit_cortex_agents.client.auth import JWTAuth

auth = JWTAuth(
    account="myorg-myaccount",
    user="MYUSER",
    private_key_path="/path/to/rsa_key.p8",
    passphrase=b"optional_passphrase",
)
client = CortexAgentsClient("https://myorg.snowflakecomputing.com", auth)
```

### OAuth

```python
from streamlit_cortex_agents.client.auth import OAuthAuth

auth = OAuthAuth("my_oauth_token")
client = CortexAgentsClient("https://myorg.snowflakecomputing.com", auth)
```

## Quick start

```python
from streamlit_cortex_agents import CortexAgentsClient
from streamlit_cortex_agents.client.models.events import TextDeltaEvent

client = CortexAgentsClient(
    account_url="https://myorg-myaccount.snowflakecomputing.com",
    auth="v2:my_pat_token",
    default_database="MY_DB",
    default_schema="MY_SCHEMA",
)

thread = client.create_thread()
for event in thread.chat("MY_AGENT", "What was total revenue in 2025?"):
    if isinstance(event, TextDeltaEvent):
        print(event.text, end="", flush=True)
```

## Multi-turn conversations

The `Thread` class tracks `parent_message_id` automatically, so you never have to manage it:

```python
thread = client.create_thread(origin_application="my_app")

# First turn
for event in thread.chat("MY_AGENT", "What was revenue in 2025?"):
    if isinstance(event, TextDeltaEvent):
        print(event.text, end="")

# Second turn — uses correct parent_message_id automatically
for event in thread.chat("MY_AGENT", "How does that compare to 2024?"):
    if isinstance(event, TextDeltaEvent):
        print(event.text, end="")
```

## Handling all event types

```python
from streamlit_cortex_agents.client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    MetadataEvent,
    ResponseEvent,
    StatusEvent,
    SuggestedQueriesEvent,
    TableEvent,
    TextAnnotationEvent,
    TextDeltaEvent,
    TextEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
    ToolResultEvent,
    ToolResultStatusEvent,
    ToolUseEvent,
    UnknownEvent,
    WarningEvent,
)

for event in thread.chat("MY_AGENT", "Show me the top 5 customers by revenue"):
    if isinstance(event, TextDeltaEvent):
        print(event.text, end="", flush=True)

    elif isinstance(event, TextEvent):
        # Full text after all deltas — use for non-streaming assembly
        pass  # already printed via TextDeltaEvent above

    elif isinstance(event, TableEvent):
        print(f"\nTable: {event.title}")
        print(f"  Rows: {event.result_set['resultSetMetaData']['numRows']}")

    elif isinstance(event, ChartEvent):
        import json
        spec = json.loads(event.chart_spec)  # Vega-Lite v5 dict
        print(f"\nChart type: {spec.get('mark')}")

    elif isinstance(event, ThinkingEvent):
        print(f"\n[Thinking: {event.text[:80]}...]")

    elif isinstance(event, ToolUseEvent):
        print(f"\n[Using tool: {event.name} (type: {event.type})]")
        if event.permission_options:
            print(f"  Permission required: {event.permission_options}")

    elif isinstance(event, ToolResultEvent):
        print(f"\n[Tool {event.tool_use_id} completed: {event.status}]")

    elif isinstance(event, AnalystDeltaEvent):
        # Deprecated (Apr 2026) — SQL now arrives in ToolUseEvent.input["sql"]
        # for events with type="system_execute_sql". Kept for backward compat.
        if event.sql:
            print(f"\n[SQL]: {event.sql[:120]}")

    elif isinstance(event, WarningEvent):
        print(f"\n[Warning {event.code}]: {event.message}")

    elif isinstance(event, ErrorEvent):
        print(f"\n[Error {event.code}]: {event.message}")

    elif isinstance(event, MetadataEvent):
        print(f"\n[{event.role} message saved: id={event.message_id}]")

    elif isinstance(event, TextAnnotationEvent):
        print(f"\n[Citation {event.index}: {event.doc_title} (doc_id={event.doc_id})]")

    elif isinstance(event, ThinkingDeltaEvent):
        print(event.text, end="", flush=True)

    elif isinstance(event, ToolResultStatusEvent):
        print(f"\n[Tool {event.tool_use_id} status: {event.status} — {event.message}]")

    elif isinstance(event, StatusEvent):
        print(f"\n[Status: {event.status} — {event.message}]")

    elif isinstance(event, ResponseEvent):
        for usage in event.usage:
            print(f"\n[Tokens — {usage.model_name}: {usage.input_tokens.total} in / {usage.output_tokens.total} out]")

    elif isinstance(event, SuggestedQueriesEvent):
        print(f"\n[Suggested follow-ups: {event.queries}]")

    elif isinstance(event, UnknownEvent):
        # Forward-compatible catch-all — never raises
        print(f"\n[Unknown event type: {event.event_type}]")
```

Every event also carries `event.sequence_number`. This value is the event's position in the run's output.
It is also the cursor value for `client.stream_run(run_id, starting_after=...)`. It is `None` if the server
omits it. The parser consumes the stream's terminal `[DONE]` marker, so the marker never reaches
your loop.

The 18 classes above are the complete set. For the wire format behind each class, see [event_types.md](event_types.md).
That page shows the raw `event:` / `data:` frames. It also lists the `event_type` strings that
`UnknownEvent.event_type` reports for tools this version does not yet model.

## Non-streaming run

```python
result = client.run("MY_DB.MY_SCHEMA.MY_AGENT", "What is total revenue?")
print(result.text)
print(result.status)  # "completed" | "cancelled" | "timed_out" | "in_progress"
for table in result.tables:
    print(f"Table: {table.title}")

# Run and message IDs plus token usage, when the response carries metadata
if result.metadata:
    print(result.run_id, result.metadata.assistant_message_id)
```

> **Note:** Only the streaming path (`stream_and_collect` / `SuggestedQueriesEvent`)
> fills `result.suggested_queries`. The non-streaming parser (`client.run()`)
> does not fill it. The list is always empty for non-streaming runs.

## Background (asynchronous) runs

By default a run times out after 15 minutes. Set `background=True` to raise that to 6 hours. The
run then survives a client disconnect. Background runs require a thread.

```python
thread = client.create_thread()

# Fire and forget — returns immediately with status "in_progress"
result = client.run(
    "MY_DB.MY_SCHEMA.MY_AGENT",
    "Summarise every support ticket from last quarter.",
    thread=thread,
    background=True,
)
run_id = result.run_id  # e.g. "4264-83472"

# Reconnect later and stream the output from the beginning
for event in client.stream_run(run_id):
    ...

# Or resume after a known sequence number, exclusive
for event in client.stream_run(run_id, starting_after=42):
    ...
```

A run's events stay available while it is active and for at least 5 minutes after it completes.
The 5-minute window is the documented contract. Live testing observed availability beyond it.
Treat the window as a lower bound on availability, not a guarantee that the run has expired.
After the window closes, `stream_run` raises `RunNotActiveError`. You must then read the response
from the thread.

`Thread.chat` accepts the same flag:

```python
for event in thread.chat("MY_DB.MY_SCHEMA.MY_AGENT", "Long question…", background=True):
    ...
```

## Cancelling a run

```python
from streamlit_cortex_agents import RunNotActiveError

try:
    metadata = client.cancel_run(run_id)
except RunNotActiveError:
    print("Run already finished.")
else:
    # Present only when partial output was saved to the thread
    if metadata.assistant_message_id:
        print(f"Continue from message {metadata.assistant_message_id}")
```

If you cancel a run, the partial output that it produced is saved to the thread and billed.

## Runs without an agent object (lite runs)

Omit `agent_path` to configure the agent inline instead of referencing an agent object:

```python
result = client.runs.run(
    messages=[{"role": "user", "content": [{"type": "text", "text": "Hi"}]}],
    models={"orchestration": "claude-4-sonnet"},
    instructions={"response": "Be concise."},
    orchestration={"budget": {"seconds": 30, "tokens": 16000}},
    tools=[...],
    tool_resources={...},
)
```

`models`, `instructions`, `orchestration`, `tools`, and `tool_resources` apply to lite runs only.
The API rejects attempts to set them on an agent-object run. Change the agent with
`client.agents.update()` instead.

> The older `model="claude-4-sonnet"` argument is deprecated. It still works and maps into
> `models`, but emits a `DeprecationWarning`.

## Agent management (CRUD)

```python
# Create an agent
agent = client.agents.create(
    "MY_AGENT",
    database="MY_DB",
    schema="MY_SCHEMA",
    instructions={
        "response": "Be concise and data-driven.",
        "orchestration": "Use Analyst for revenue questions; Search for policy.",
    },
    tools=[
        {"tool_spec": {"type": "cortex_analyst_text_to_sql", "name": "Analyst1"}},
        {"tool_spec": {"type": "cortex_search", "name": "Search1"}},
    ],
    tool_resources={
        "Analyst1": {
            "semantic_view": "MY_DB.MY_SCHEMA.REVENUE_VIEW",
            "execution_environment": {"type": "warehouse", "warehouse": "MY_WH"},
        },
        "Search1": {
            "search_service": "MY_DB.MY_SCHEMA.POLICY_SEARCH",
            "title_column": "title",
            "id_column": "doc_id",
        },
    },
)

# List agents — agent.path gives the fully-qualified name for use in thread.chat()
for agent in client.agents.list():
    print(f"{agent.path}: {agent.profile.display_name}")

# Update
client.agents.update("MY_AGENT", comment="Updated for Q3")

# Delete
client.agents.delete("MY_AGENT", if_exists=True)
```

## Thread management

```python
# Create and list threads
thread_meta = client.threads.create(origin_application="my_app")
threads = client.threads.list(origin_application="my_app")

# Resume a previously stored conversation
thread = client.get_thread(thread_meta.thread_id, parent_message_id=last_assistant_id)

# Get message history
messages = thread.list_messages()

# Compaction-aware context (for resuming long conversations)
context = thread.latest_context()

# Delete
client.threads.delete(thread_meta.thread_id)
```

## Forking conversations

```python
fork = thread.fork(at_message_id=456)
for event in fork.chat("MY_AGENT", "What about revenue by region instead?"):
    ...
```

## Multi-tenancy (session attributes)

One agent can serve several tenants while keeping their data apart. Pass `variables` to any run. Snowflake sets each variable as a session attribute before the agent runs its generated SQL. A row access policy then filters rows on the attribute. See [Multi-tenancy for Cortex Agents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-multi-tenancy).

```python
# Shorthand: each value becomes an immutable string/number/boolean attribute
for event in thread.chat("DB.SCHEMA.MY_AGENT", "Show my sales", variables={"region": "NORTH"}):
    ...

# Full REST shape is also accepted; is_immutable_session_attribute defaults to True
client.run(
    "DB.SCHEMA.MY_AGENT",
    "Show my sales",
    variables={"region": {"value": "NORTH", "type": "string"}},
)
```

`variables` is accepted by `thread.chat`, `client.stream`, `client.run`, `client.runs.stream`, `client.runs.run` and `client.runs.stream_and_collect`. `thread.chat` sends it on every request of the turn, including client-side tool follow-ups. If you omit it, requests are unchanged.

Pair it with a row access policy that reads the attribute:

```sql
CREATE OR REPLACE ROW ACCESS POLICY rap_region_filter
  AS (region_col STRING) RETURNS BOOLEAN ->
    region_col = SYS_CONTEXT('SNOWFLAKE$SESSION_ATTRIBUTES', 'region');

ALTER TABLE db1.schema1.sales ADD ROW ACCESS POLICY rap_region_filter ON (region);
```

> [!IMPORTANT]
> Tenant isolation is a shared responsibility. The library only sends the attributes. Your row access policies must enforce the boundary. Keep attributes immutable (the default) so generated SQL cannot change them, and test each policy on its own before relying on it.

## Exception handling

```python
from streamlit_cortex_agents import (
    AuthError,
    CortexConnectionError,
    CortexPermissionError,
    CortexTimeoutError,
    AgentNotFoundError,
    ThreadNotFoundError,
    NotFoundError,       # base class — catches both Agent and Thread variants
    ConflictError,       # base class for HTTP 409
    RunNotActiveError,   # 409 on a run that is finished or expired
    RateLimitError,
    ServerError,
)

try:
    for event in thread.chat("MY_AGENT", "Summarise Q3 revenue"):
        ...
except AgentNotFoundError:
    print("Agent not found — check DB.SCHEMA.AGENT_NAME")
except NotFoundError:
    print("Resource not found")
except CortexPermissionError:
    print("Insufficient privileges — check USAGE on the agent and its resources")
except AuthError:
    print("Token invalid or expired")
except CortexConnectionError:
    print("Network error — check connectivity and DNS")
except CortexTimeoutError:
    print("Request exceeded timeout")
except RateLimitError:
    print("Rate limit hit — back off and retry")
except ServerError as exc:
    print(f"Snowflake server error: {exc}")
```

`RunNotActiveError` applies only to `stream_run` and `cancel_run`. It means the run has
already finished or is outside its retention window. In that case, read the response from the thread
instead:

```python
from streamlit_cortex_agents import RunNotActiveError

try:
    for event in client.stream_run(run_id):
        ...
except RunNotActiveError:
    messages = client.threads.list_messages(thread.thread_id)
```
