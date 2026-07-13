# Cortex Agents REST API Specification

Reference for all endpoints used by the `cortex_agents_client` Python library.

Base URL: `https://{account}.snowflakecomputing.com`

API timeout: 15 minutes per request.

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
        "type": "cortex_analyst_text_to_sql",
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
  "tool_choice": {
    "type": "required",
    "name": ["Analyst1", "Search1"]
  }
}
```

`tool_choice.type` values: `"auto"` (default) | `"required"` | `"none"`

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
  "model": "claude-4-sonnet"
}
```

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

The Python client captures `status` as `RunResult.status` — `"completed"` for a normal run,
`"cancelled"` if stopped early via CancelAgentRun.

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

Messages are returned in **descending** order (newest first). Paginate by passing the smallest `message_id` from the page as `last_message_id`.

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
| `mcp_connector` | Remote MCP server tool |

## ToolResource variants by type

**`cortex_analyst_text_to_sql`**: `semantic_model_file` XOR `semantic_view`, plus optional `execution_environment: {type, warehouse, query_timeout?}`.

**`cortex_search`**: `search_service` (fully-qualified name), `title_column`, `id_column`, optional `filter`, optional `max_results` (integer), optional `columns_and_descriptions` (map of column name → `{description, type, searchable, filterable}` — recommended for filterable/searchable columns to improve result quality).

**`generic`**: `type` (`function` | `procedure`), `execution_environment`, `identifier`.

**`web_search`**: `max_results` (integer).

**`code_execution`**, **`data_to_chart`**: No `tool_resources` entry required.

**`agent_skill`**, **`mcp_connector`**: Resource schemas not yet publicly documented; pass tool-specific resource objects as needed.
