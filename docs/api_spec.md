[← Back to README](../README.md) · See also: [Python API](python_api.md) · [Event Types](event_types.md) · [Reference](reference.md)

# Cortex Agents REST API Specification

Reference for all endpoints used by the `streamlit_cortex_agents` Python library.

Base URL: `https://{account}.snowflakecomputing.com`

API timeout: 15 minutes per request by default. Set `background: true` on a run to raise this to 6 hours (requires a thread).

---

## Authentication

All requests require `Authorization: Bearer <token>`.

| Method | Header value | Optional type header |
|---|---|---|
| PAT | `Bearer <pat_token>` | `X-Snowflake-Authorization-Token-Type: PROGRAMMATIC_ACCESS_TOKEN` |
| JWT (key-pair) | `Bearer <jwt>` | `X-Snowflake-Authorization-Token-Type: KEYPAIR_JWT` |
| OAuth | `Bearer <oauth_token>` | `X-Snowflake-Authorization-Token-Type: OAUTH` |
| WIF | `Bearer WIF.{AWS\|AZURE\|GCP\|OIDC}.{token}` | `X-Snowflake-Authorization-Token-Type: WORKLOAD_IDENTITY_FEDERATION` |

JWT claims: `iss = ACCOUNT.USER.SHA256:<fingerprint>`, `sub = ACCOUNT.USER`, `iat` and `exp` (max 1h TTL). Both account and user must be UPPERCASE.

### Running under a non-default role

A request can run under a role other than the user's default by sending `X-Snowflake-Role: <role>`. Cortex Agents derives tool permissions from the querying user's **default** role, not the role in this header or the session role.

Library support: `CortexAgentsClient(..., role="MY_ROLE")`, or per-call via `HttpClient.request(..., headers={...})`.

---

## Agent CRUD — `/api/v2/databases/{database}/schemas/{schema}/agents`

### Create Agent

```
POST /api/v2/databases/{database}/schemas/{schema}/agents
```

Query params: `createMode` — `errorIfExists` (default) | `orReplace` | `ifNotExists`

Request body:

```json
{
  "name": "MY_AGENT",
  "comment": "optional description",
  "profile": {"display_name": "My Agent"},
  "models": {"orchestration": "claude-4-sonnet"},
  "instructions": {
    "response": "Be concise and friendly.",
    "orchestration": "Use Analyst for revenue questions; Search for policy."
  },
  "orchestration": {
    "budget": {"seconds": 30, "tokens": 16000}
  },
  "tools": [
    {
      "tool_spec": {
        "type": "cortex_analyst_text_to_sql",  // agent definition type; runtime events emit system_execute_sql
        "name": "Analyst1",
        "description": "Revenue analytics"
      }
    },
    {
      "tool_spec": {
        "type": "cortex_search",
        "name": "Search1",
        "description": "Policy documents"
      }
    },
    {
      "tool_spec": {
        "type": "generic",
        "name": "get_weather",
        "description": "Get current weather.",
        "input_schema": {
          "type": "object",
          "properties": {
            "location": {"type": "string", "description": "City and state"}
          },
          "required": ["location"]
        }
      }
    }
  ],
  "tool_resources": {
    "Analyst1": {
      "semantic_view": "db.schema.revenue_semantic_view",
      "execution_environment": {"type": "warehouse", "warehouse": "MY_WH", "query_timeout": 60}
    },
    "Search1": {
      "search_service": "db.schema.policy_search",
      "title_column": "doc_title",
      "id_column": "doc_id",
      "max_results": 5,
      "filter": {"@eq": {"region": "North America"}},
      "columns_and_descriptions": {
        "TEXT": {
          "description": "Main document content.",
          "type": "string",
          "searchable": true,
          "filterable": false
        },
        "CATEGORY": {
          "description": "Document category: policy, guide, reference.",
          "type": "string",
          "searchable": false,
          "filterable": true
        }
      }
    },
    "get_weather": {
      "type": "function",
      "execution_environment": {"type": "warehouse", "warehouse": "MY_WH"},
      "identifier": "DB.SCHEMA.GET_WEATHER_UDF"
    }
  }
}
```

Response: `{"status": "Agent MY_AGENT successfully created."}`

### Describe Agent

```
GET /api/v2/databases/{database}/schemas/{schema}/agents/{name}
```

Response:
```json
{
  "name": "MY_AGENT",
  "database_name": "MY_DB",
  "schema_name": "MY_SCHEMA",
  "owner": "ACCOUNTADMIN",
  "comment": "",
  "created_on": "2024-06-01T12:00:00Z",
  "profile": {"display_name": "My Agent"},
  "agent_spec": "{...escaped JSON...}"
}
```

### Update Agent

```
PUT /api/v2/databases/{database}/schemas/{schema}/agents/{name}
```

Body: same shape as Create minus `name`. All fields optional.

Response: `{"status": "Agent MY_AGENT successfully updated."}`

### List Agents

```
GET /api/v2/databases/{database}/schemas/{schema}/agents
```

Query params: `like` (pattern), `fromName` (cursor), `showLimit` (1–10000)

Response: JSON array of agent objects.

### Delete Agent

```
DELETE /api/v2/databases/{database}/schemas/{schema}/agents/{name}
```

Query params: `ifExists` (boolean)

Response: `{"status": "Request successfully completed"}`

### Submit Feedback

```
POST /api/v2/databases/{database}/schemas/{schema}/agents/{name}:feedback
```

```json
{
  "orig_request_id": "61987ff6-6d56-4695-83c0-1e7cfed818c7",
  "positive": true,
  "feedback_message": "Great answer!",
  "categories": ["accurate", "helpful"],
  "thread_id": 1234567890
}
```

Response: `200 OK`

---

## Run API

### Run with agent object

```
POST /api/v2/databases/{database}/schemas/{schema}/agents/{name}:run
```

### Run without agent object (lite / inline config)

```
POST /api/v2/cortex/agent:run
```

### SSE stream framing (verified live, not in the public docs)

Every stream from both run endpoints and from Stream Agent Run ends with a terminal
marker that is **not JSON**:

```
event: done
data: [DONE]
```

A parser that assumes every `data:` line is JSON reports this as a malformed event. The
library treats it as end-of-stream. Each real event also carries a `sequence_number`, which
is the cursor value for `starting_after`.

### Request body

```json
{
  "thread_id": 1234567890,
  "parent_message_id": 0,
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "What is total revenue for 2025?"}
      ]
    }
  ],
  "stream": true,
  "background": false,
  "tool_choice": {
    "type": "required",
    "name": ["Analyst1", "Search1"]
  }
}
```

`tool_choice.type` values: `"auto"` (default) | `"required"` | `"none"`

`variables` (optional): immutable session attributes for multi-tenancy. Snowflake sets each one on the session before it runs any SQL that the agent generates. A row access policy can then read each attribute with `SYS_CONTEXT('SNOWFLAKE$SESSION_ATTRIBUTES', '<name>')`:

```json
{
  "variables": {
    "region": {
      "value": "North",
      "type": "string",
      "is_immutable_session_attribute": true
    }
  }
}
```

Verified live (2026-09-25), beyond what the [public doc](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-multi-tenancy) states:

- **Works on agent-object runs**, not only the lite endpoint. The public doc shows the plain `/api/v2/cortex/agent:run` path, but the same block is accepted on `.../agents/{name}:run`. Unlike `models` / `instructions` / `orchestration`, `variables` is not rejected on an agent-object run.
- **Attributes persist for the whole interaction.** A background run started with `variables` and resumed later via [Stream Agent Run](#stream-agent-run) was still scoped. Resume and cancel therefore need no `variables` of their own (they send no body).
- **`type` is not limited to `"string"`.** A `"number"` attribute was accepted alongside a string one and scoping still applied. The public doc only shows `"string"`.
- **A missing attribute fails closed**, given a policy of the usual shape: `SYS_CONTEXT` returns NULL, `col = NULL` is never true, and no rows come back. Keep this in mind when you write the policy. The policy decides this, not the API.

`background` (optional, default `false`): run asynchronously with a 6-hour timeout instead of 15 minutes. The run survives a client disconnect. **Only available when using threads.** With `stream: false`, the call returns immediately with `status: "in_progress"` and a `metadata.run_id`. Collect the output later via [Stream Agent Run](#stream-agent-run).

For permission decisions (response to `tool_use` with non-empty `permission.options`):
```json
{
  "thread_id": 1234567890,
  "parent_message_id": 456,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "permission_decision",
          "permission_decision": {
            "tool_use_id": "toolu_abc123",
            "decision": "Allow Once",
            "reason": "I approve this query"
          }
        }
      ]
    }
  ]
}
```

Inline (lite agent) request adds config fields:
```json
{
  "tools": [...],
  "tool_resources": {...},
  "instructions": {"response": "...", "orchestration": "..."},
  "orchestration": {"budget": {"seconds": 30, "tokens": 16000}},
  "models": {"orchestration": "claude-4-sonnet"}
}
```

`models` is a `ModelConfig` **object**, not a string. A bare top-level `"model": "claude-4-sonnet"` is the pre-September-2025 legacy schema. It should not be used for new work. The library still accepts a `model=` argument, but it maps the argument into `models` and emits a `DeprecationWarning`.

These config fields apply to the lite endpoint only. `models`, `instructions`, and `orchestration` cannot be set or overwritten through an agent-object run. Use [Update Agent](#update-agent) instead.

### Non-streaming response (`stream: false`)

```json
{
  "role": "assistant",
  "content": [
    {"type": "text", "text": "The total revenue for 2025 was $4.2B."},
    {
      "type": "table",
      "table": {
        "tool_use_id": "toolu_123",
        "query_id": "abc-123",
        "result_set": {
          "statementHandle": "abc-123",
          "resultSetMetaData": {
            "partition": 0,
            "numRows": 3,
            "format": "jsonv2",
            "rowType": [
              {"name": "YEAR", "type": "INTEGER", "length": 0, "precision": 10, "scale": 0, "nullable": false},
              {"name": "REVENUE", "type": "FLOAT", "length": 0, "precision": 15, "scale": 2, "nullable": true}
            ]
          },
          "data": [["2023", "3800000000"], ["2024", "4000000000"], ["2025", "4200000000"]]
        },
        "title": "Revenue by Year"
      }
    }
  ],
  "status": "completed",
  "error": null
}
```

The Python client captures `status` as `RunResult.status`. The values are `"completed"` for a normal run,
`"cancelled"` if stopped early via CancelAgentRun, `"timed_out"` if the run exceeded its maximum
length, and `"in_progress"` for a background run that has not finished.

The library parses the response `metadata` block into `RunResult.metadata` (a `RunMetadata`). It carries
`run_id`, `thread_id`, `user_message_id`, `assistant_message_id`, and token `usage`.
`RunResult.run_id` is a shortcut to `metadata.run_id`.

---

## Stream Agent Run

```
GET /api/v2/cortex/agent/runs/{run_id}
```

Reconnects to an agent run and streams its output. The events are byte-for-byte the same as the events
that streaming `agent:run` returns.

| Parameter | Location | Description |
|---|---|---|
| `run_id` | path | Run identifier, in `{thread_id}-{user_message_id}` form |
| `starting_after` | query | (Optional) Sequence number to resume from, **exclusive**. Omit to replay the entire output. |

The cursor value is the `sequence_number` field carried on each streamed event. The library
exposes it as `SSEEvent.sequence_number` on every event type.

A run's events are accessible while it is active and for up to **5 minutes** after it completes.
A connection after that returns `409 Conflict`. Retrieve the full response from the thread instead.

> Observed on a test account in August 2026: a completed run was still streamable 5.5 minutes after
> finishing, so this window was not enforced. Treat the 5 minutes as a lower bound on
> availability, not as a guarantee that the run has expired. Do not rely on a 409 to detect
> that a run is finished. Check the run's terminal `response` event or read the thread.

Library: `client.stream_run(run_id, starting_after=None)` or `client.runs.stream_run(...)`.
A 409 raises `RunNotActiveError`.

---

## Cancel Agent Run

```
POST /api/v2/cortex/agent/runs/{run_id}/cancel
```

Cancels an actively running run. Partial output is saved to the thread and billed accordingly.

Response:

```json
{
  "metadata": {
    "run_id": "4264-83472",
    "thread_id": 4264,
    "user_message_id": 83472,
    "assistant_message_id": 83473,
    "usage": {"tokens_consumed": [...]}
  }
}
```

`metadata.assistant_message_id` is present only when partial output was saved. Use it as the
`parent_message_id` for the next turn. A run that has already completed or been cancelled returns
`409 Conflict`.

Library: `client.cancel_run(run_id)` returns a `RunMetadata`. A 409 raises `RunNotActiveError`.

---

## Thread API — `/api/v2/cortex/threads`

### Create Thread

```
POST /api/v2/cortex/threads
```

```json
{"origin_application": "my_streamlit_app"}
```

Response:
```json
{
  "thread_id": 1234567890,
  "thread_name": "",
  "origin_application": "my_streamlit_app",
  "created_on": 1717000000000,
  "updated_on": 1717000000000
}
```

### Describe Thread (with messages)

```
GET /api/v2/cortex/threads/{id}
```

Query params: `page_size` (default 20, max 100), `last_message_id` (cursor), `message_type` (`conversation` | `compaction`)

Response:
```json
{
  "metadata": {
    "thread_id": 1234567890,
    "thread_name": "Revenue Chat",
    "origin_application": "my_app",
    "created_on": 1717000000000,
    "updated_on": 1717000100000
  },
  "messages": [
    {
      "message_id": 2,
      "parent_id": 1,
      "created_on": 1717000001000,
      "role": "assistant",
      "message_payload": "The revenue was...",
      "request_id": "req_002",
      "message_type": "conversation"
    },
    {
      "message_id": 1,
      "parent_id": null,
      "created_on": 1717000000000,
      "role": "user",
      "message_payload": "What is revenue?",
      "request_id": "req_001",
      "message_type": "conversation"
    }
  ]
}
```

The API returns messages in **descending** order (newest first). To paginate, pass the smallest `message_id` from the page as `last_message_id`.

### Update Thread

```
POST /api/v2/cortex/threads/{id}
```

```json
{"thread_name": "Revenue Analysis 2025"}
```

Response: `{"status": "Thread 1234567890 successfully updated."}`

### List Threads

```
GET /api/v2/cortex/threads
```

Query params: `origin_application` (optional filter)

### Delete Thread

```
DELETE /api/v2/cortex/threads/{id}
```

Response: `{"success": true}`

---

## Tool spec types

| `type` | Description |
|---|---|
| `cortex_analyst_text_to_sql` | Text-to-SQL via semantic view (agent definition type) |
| `system_execute_sql` | Text-to-SQL execution (emitted in events since Apr 2026, replaces `cortex_analyst_text_to_sql` at runtime) |
| `cortex_search` | Document retrieval |
| `web_search` | Real-time web search |
| `generic` | Custom UDF or stored procedure |
| `code_execution` | Python sandbox |
| `data_to_chart` | Data visualization |
| `agent_skill` | Packaged skill |
| `system_agentic_semantic_context` | Cortex Analyst semantic-context tool (emitted alongside `system_execute_sql`) |
| `mcp_connector` | Remote MCP server tool |

## ToolResource variants by type

**`cortex_analyst_text_to_sql`**: `semantic_model_file` XOR `semantic_view`, plus optional `execution_environment: {type, warehouse, query_timeout?}`.

**`cortex_search`**: `search_service` (fully-qualified name), `title_column`, `id_column`, optional `filter`, optional `max_results` (integer), optional `columns_and_descriptions` (map of column name → `{description, type, searchable, filterable}`, recommended for filterable/searchable columns to improve result quality).

**`generic`**: `type` (`function` | `procedure`), `execution_environment`, `identifier`.

**`web_search`**: `max_results` (integer).

**`code_execution`**, **`data_to_chart`**: No `tool_resources` entry required.

**`agent_skill`**, **`mcp_connector`**: Resource schemas are not yet publicly documented. Pass tool-specific resource objects as needed.
