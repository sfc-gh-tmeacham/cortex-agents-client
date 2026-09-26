[← Back to README](../README.md) · See also: [Python API](python_api.md) · [REST API Spec](api_spec.md) · [Reference](reference.md)

# Cortex Agents SSE Event Types

This page lists all 17 server-sent event types that the `agent:run` endpoint emits.

The streaming protocol is standard SSE (`text/event-stream`):

```
event: <event_type>
data: <json_payload>

```

The library passes unknown event types through as `UnknownEvent` and never raises an error. This keeps the library forward-compatible when Snowflake adds new tools and event types.

## Fields present on every event

### `sequence_number`

Each event carries a `sequence_number` giving its position in the run's output. It is the
cursor value consumed by the Stream Agent Run endpoint:

```python
for event in client.stream_run(run_id, starting_after=42):
    ...
```

The library exposes it as `SSEEvent.sequence_number` on every event type, or `None` when the
server omits it. Without it, `starting_after` cannot be used with a known position.

## Terminal marker (`event: done`)

Every stream from `agent:run` and from `GET agent/runs/{run_id}` ends with a marker whose
data is **not JSON**:

```
event: done
data: [DONE]

```

The public API reference does not document this marker. Live testing found it. A parser
that assumes every `data:` line is JSON reports it as a malformed event. `parse_sse_stream`
treats it as end-of-stream, so it never reaches the caller. It is not one of the 17
event types below.

---

## 1. `response.text`

Complete text block after all deltas have been sent. Always follows a series of `response.text.delta` events for the same `content_index`.

```json
{
  "content_index": 0,
  "text": "The total revenue for 2025 was $4.2 billion, up 5% from 2024 [^1].",
  "annotations": [
    {
      "type": "cortex_search_citation",
      "index": 1,
      "search_result_id": "cs_61987ff6-6d56-4695-83c0-1e7cfed818c7",
      "doc_id": "4ac085cb-82d0-4eb4-94f3-2672aa0599a2",
      "doc_title": "Earnings Report Q4 2025",
      "text": "Revenue for 2025 was $4.2B based on consolidated financials."
    }
  ],
  "is_elicitation": false
}
```

> **`annotations`**: present when the text carries `[^N]` citation markers, and parsed into
> `TextEvent.annotations` (defaults to `[]` when absent). The same citations also arrive as
> separate `response.text.annotation` events (see below). A renderer should pick one
> source and not show both.

> **`is_elicitation`**: `true` when the agent asks the user a clarifying question instead of giving an answer. Render with `st.info()` instead of `st.markdown()` to show the question differently.

**Streamlit rendering:** `st.markdown(text)`. It supports inline citation markers like `[^1]`.

---

## 2. `response.text.delta`

Token-by-token text streaming. Accumulate deltas in order of `content_index` to reconstruct the full `response.text`.

```json
{
  "content_index": 0,
  "text": "The total",
  "is_elicitation": false
}
```

**Streamlit rendering:** `placeholder.markdown(accumulated + "▌")` during streaming; replace with `response.text` when complete.

---

## 3. `response.text.annotation`

A citation annotation inside a text block. The server sends it with the `response.text` events for the same `content_index`.

```json
{
  "content_index": 0,
  "annotation_index": 0,
  "annotation": {
    "type": "cortex_search_citation",
    "index": 1,
    "search_result_id": "cs_61987ff6-6d56-4695-83c0-1e7cfed818c7",
    "doc_id": "4ac085cb-82d0-4eb4-94f3-2672aa0599a2",
    "doc_title": "Earnings Report Q4 2025",
    "text": "Revenue for 2025 was $4.2B based on consolidated financials."
  }
}
```

`annotation_index` is the ordinal position of this annotation within its text block (defaults to `0`).

Currently, the annotation type is always `cortex_search_citation`. The `index` corresponds to citation markers like `[^1]` in the text.

**Streamlit rendering:** Collect the annotations into a list. Render them as an expandable citations section below the text.

---

## 4. `response.thinking`

Complete agent reasoning/thinking block. Sent after all `response.thinking.delta` events for the same `content_index`. Only emitted when the model supports extended thinking (Claude 3.5+).

```json
{
  "content_index": 1,
  "text": "The user is asking about 2025 revenue. I should use Analyst to query the revenue table and compare with 2024.",
  "signature": "EqoBCkgIARgCIkDIGe3Bm..."
}
```

**Streamlit rendering:** a `Thinking` step (`st.status(type="step")`) in the reasoning timeline, only when `show_thinking=True`. Thinking before and after a tool call renders as separate steps.

---

## 5. `response.thinking.delta`

Streaming thinking token. Accumulate for the same `content_index` to build `response.thinking.text`.

```json
{
  "content_index": 1,
  "text": "The user is asking",
  "signature": ""
}
```

---

## 6. `response.tool_use`

The agent decided to use a tool. If `permission.options` is non-empty, the client must send a `permission_decision` message before the tool executes.

```json
{
  "content_index": 2,
  "tool_use_id": "toolu_01XyZ",
  "type": "system_execute_sql",
  "name": "Analyst1",
  "input": {
    "query": "Total revenue for 2025",
    "sql": "SELECT SUM(revenue) AS total FROM sales WHERE year = 2025"
  },
  "client_side_execute": false,
  "permission": {
    "options": []
  }
}
```

> **Note:** The API may send `client_side_execute` as the JSON string `"true"` (not a boolean) when the flag is set. The library handles both forms. When `false`, the field is sent as a JSON boolean.

When permission is required:
```json
{
  "permission": {
    "options": ["Allow Once", "Deny"]
  }
}
```

`client_side_execute: true` means the client must execute the tool and send the results in the next request.

**Tool types:** `system_execute_sql`, `system_agentic_semantic_context`, `cortex_search`, `web_search`, `generic`, `code_execution`, `data_to_chart`, `agent_skill`, `mcp_connector`.

> **Note:** Prior to Apr 2026, Cortex Analyst emitted `cortex_analyst_text_to_sql`. `system_execute_sql` replaced it. The generated SQL is now in `input["sql"]`.

**Streamlit rendering:** a running `Using {name}...` step (`st.status(type="step")`) in the reasoning timeline, labelled with an icon for the tool type, only when `show_tool_status=True`.

---

## 7. `response.tool_result`

Tool execution is complete. Sent after all `response.tool_result.status` and `response.tool_result.analyst.delta` events for the same `tool_use_id`.

```json
{
  "content_index": 2,
  "tool_use_id": "toolu_01XyZ",
  "type": "system_execute_sql",
  "name": "Analyst1",
  "content": [
    {
      "type": "json",
      "json": {
        "answer": "Revenue was $4.2B"
      }
    }
  ],
  "status": "success"
}
```

`status` values: `"success"` | `"error"`

`content[].type` values: `"json"` | `"text"`

**Streamlit rendering:** the tool step moves to the complete or error state. For a verified-query success, a step with a green shield marker replaces the tool step.

---

## 8. `response.tool_result.status`

In-progress status update for a running tool. It is useful for showing progress spinners.

```json
{
  "tool_use_id": "toolu_01XyZ",
  "tool_type": "system_execute_sql",
  "status": "Executing SQL",
  "message": "Executing query 'SELECT SUM(revenue) FROM sales WHERE year = 2025'",
  "details": {}
}
```

**Streamlit rendering:** Update the running tool step's label.

---

## 9. `response.tool_result.analyst.delta`

> **Deprecated (Apr 2026):** Cortex Analyst no longer emits this event type. SQL is now delivered in `ToolUseEvent.input["sql"]` for events with `type="system_execute_sql"`. This event type is still parsed for backward compatibility with older API versions.

Streaming delta from the Cortex Analyst tool. It contains progressive SQL generation, execution, and result output.

```json
{
  "content_index": 2,
  "tool_use_id": "toolu_01XyZ",
  "tool_type": "system_execute_sql",
  "tool_name": "Analyst1",
  "delta": {
    "text": "Based on the data,",
    "think": "I need to group by year...",
    "sql": "SELECT year, SUM(revenue) AS total FROM sales GROUP BY year ORDER BY year DESC",
    "sql_explanation": "This query sums revenue by year.",
    "query_id": "707787a0-a684-4ead-adb0-3c3b62b043d9",
    "verified_query_used": false,
    "result_set": {
      "statementHandle": "707787a0-a684-4ead-adb0-3c3b62b043d9",
      "resultSetMetaData": {
        "partition": 0,
        "numRows": 3,
        "format": "jsonv2",
        "rowType": [
          {"name": "YEAR", "type": "INTEGER", "length": 0, "precision": 10, "scale": 0, "nullable": false},
          {"name": "TOTAL", "type": "FLOAT", "length": 0, "precision": 15, "scale": 2, "nullable": true}
        ]
      },
      "data": [["2025", "4200000000"], ["2024", "4000000000"], ["2023", "3800000000"]]
    },
    "suggestions": null
  }
}
```

All `delta` fields are optional. When Analyst cannot answer: `result_set` is null and `suggestions` contains alternative questions.

`suggestions` is a nested object inside `delta`:
```json
{
  "delta": {
    "suggestions": {
      "index": 0,
      "delta": "What was the total revenue by region?"
    }
  }
}
```

---

## 10. `response.table`

A SQL result set rendered as a table. Typically emitted after Cortex Analyst or a custom tool returns tabular data.

```json
{
  "content_index": 3,
  "tool_use_id": "toolu_01XyZ",
  "query_id": "707787a0-a684-4ead-adb0-3c3b62b043d9",
  "result_set": {
    "statementHandle": "707787a0-a684-4ead-adb0-3c3b62b043d9",
    "resultSetMetaData": {
      "partition": 0,
      "numRows": 3,
      "format": "jsonv2",
      "rowType": [
        {"name": "YEAR", "type": "INTEGER", "length": 0, "precision": 10, "scale": 0, "nullable": false},
        {"name": "REVENUE", "type": "FLOAT", "length": 0, "precision": 15, "scale": 2, "nullable": true}
      ]
    },
    "data": [
      ["2025", "4200000000.00"],
      ["2024", "4000000000.00"],
      ["2023", "3800000000.00"]
    ]
  },
  "title": "Annual Revenue"
}
```

All `data` values are strings in `jsonv2` format. Use `rowType` to cast types.

**Streamlit rendering:**
```python
if table.title:
    container.caption(table.title)
container.dataframe(result_set_to_dataframe(table))
```

---

## 11. `response.chart`

A Vega-Lite chart specification. Emitted by the "Data to Chart" tool after Analyst or a custom tool produces tabular data.

```json
{
  "content_index": 4,
  "tool_use_id": "toolu_chart_01",
  "chart_spec": "{\"$schema\":\"https://vega.github.io/schema/vega-lite/v5.json\",\"data\":{\"values\":[{\"year\":2025,\"revenue\":4200000000},{\"year\":2024,\"revenue\":4000000000}]},\"mark\":\"bar\",\"encoding\":{\"x\":{\"field\":\"year\",\"type\":\"ordinal\"},\"y\":{\"field\":\"revenue\",\"type\":\"quantitative\"}}}"
}
```

`chart_spec` is a JSON string (not a dict). Parse it with `json.loads()`.

**Streamlit rendering:** `container.vega_lite_chart(json.loads(chart_spec), width="stretch")`

---

## 12. `response.status`

High-level execution status update. Not tied to a specific tool.

```json
{
  "status": "executing_tool",
  "message": "Executing tool `Analyst1`"
}
```

Common status values: `"executing_tool"`, `"generating_response"`, `"complete"`.

**Streamlit rendering:** Transient update only. It is not stored in `StoredMessage`.

---

## 13. `response.warning`

A non-fatal warning. The stream continues after this event.

```json
{
  "message": "Unable to fetch tools from MCP server 'jira_connector'. Response quality may be degraded.",
  "code": "003001"
}
```

`code` is an optional structured code for client-side handling.

**Streamlit rendering:** `container.warning(message)`. The warning persists in `StoredMessage.warnings`.

---

## 14. `error`

A fatal error. The stream ends after this event. The library raises `RunError`.

```json
{
  "code": "399504",
  "error_code": "399504",
  "message": "Error during agent execution: warehouse MY_WH is suspended.",
  "request_id": "61987ff6-6d56-4695-83c0-1e7cfed818c7"
}
```

`error_code` is a deprecated alias for `code` kept for backward compatibility.

**Streamlit rendering:** `container.error(f"Error {code}: {message}")`. The error persists in `StoredMessage.error`.

---

## 15. `metadata`

Thread persistence confirmation. The server sends it **twice** per run: once when it saves the user message, and once when it saves the assistant message. It contains the `message_id` values that multi-turn conversation needs.

```json
{"metadata": {"role": "user", "message_id": 123, "run_id": "4264-83472"}}
```

```json
{"metadata": {"role": "assistant", "message_id": 456, "run_id": "4264-83472"}}
```

**Usage:** The assistant `message_id` (456 in this example) becomes the `parent_message_id` for the next request.

`Thread.chat()` captures these events automatically and advances `parent_message_id`. Users never interact with this event directly.

---

## 16. `response`

Final aggregated response. **Always the last event in the stream.** Emitted once, after all other events. For streaming clients, most content already arrived in individual events. But this event is the only source of per-model token counts and the cancellation status.

```json
{
  "role": "assistant",
  "content": [...],
  "warnings": [],
  "status": "completed",
  "metadata": {
    "usage": {
      "tokens_consumed": [
        {
          "model_name": "llama3.1-70b",
          "input_tokens": {"total": 812, "cache_read": 0, "cache_write": 0, "uncached": 812},
          "output_tokens": {"total": 104},
          "context_window": 128000
        }
      ]
    },
    "run_id": "4264-83472",
    "thread_id": 7,
    "user_message_id": 123,
    "assistant_message_id": 456
  }
}
```

**Dataclass:** `ResponseEvent` — fields: `role`, `content`, `warnings`, `status` (`"cancelled"` if aborted via CancelAgentRun, `"completed"` for normal completion), `usage` (list of `TokensConsumed`), `run_id`, `thread_id`, `user_message_id`, `assistant_message_id`.

**Usage:** inspect `usage` for token counts; check `status == "cancelled"` to detect server-side abort.

---

## 17. `response.suggested_queries`

Suggested follow-up questions the agent recommends based on the conversation context. The server does not always emit it. This depends on the agent configuration and on whether the model generates suggestions.

```json
{
  "content_index": 0,
  "suggested_queries": [
    {"query": "What regions have the highest revenue?"},
    {"query": "Show me a chart of monthly trends"},
    {"query": "How does Q1 compare to last year?"}
  ]
}
```

**Dataclass:** `SuggestedQueriesEvent` — fields: `content_index`, `queries` (list of query strings extracted from the payload).

**Streamlit rendering:** Rendered as `st.pills` below the last assistant message under a "Suggested questions" label. Selecting a pill submits that query as the next user message.

---

## Typical streaming event sequence

```
event: response.status
data: {"status": "executing_tool", "message": "Executing tool `Analyst1`"}

event: response.tool_use
data: {"content_index": 0, "tool_use_id": "toolu_01", "type": "system_execute_sql", "name": "Analyst1", "input": {...}, ...}

event: response.tool_result.status
data: {"tool_use_id": "toolu_01", "tool_type": "system_execute_sql", "status": "Generating SQL", "message": "..."}

event: response.tool_result.analyst.delta
data: {"content_index": 0, "tool_use_id": "toolu_01", ..., "delta": {"sql": "SELECT ...", "result_set": {...}}}

event: response.tool_result
data: {"content_index": 0, "tool_use_id": "toolu_01", ..., "status": "success"}

event: response.table
data: {"content_index": 1, "tool_use_id": "toolu_01", "result_set": {...}, "title": "Revenue"}

event: response.text.delta
data: {"content_index": 2, "text": "Based on the "}

event: response.text.delta
data: {"content_index": 2, "text": "data, revenue was $4.2B."}

event: response.text
data: {"content_index": 2, "text": "Based on the data, revenue was $4.2B."}

event: metadata
data: {"metadata": {"role": "user", "message_id": 123, "run_id": "run_001"}}

event: metadata
data: {"metadata": {"role": "assistant", "message_id": 456, "run_id": "run_001"}}

event: response
data: {"role": "assistant", "content": [...], "status": "completed", "metadata": {"usage": [...], "run_id": "run_001"}}

event: done
data: [DONE]
```

The trailing `done` / `[DONE]` frame ends every stream. `parse_sse_stream` consumes it,
and it never reaches the caller, so `ResponseEvent` is the last event a
consumer observes.
