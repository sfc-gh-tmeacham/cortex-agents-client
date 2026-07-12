# Test Plan

Comprehensive test strategy for the `cortex_agents_client` library.

---

## Philosophy

- **No real network calls in CI.** Every test that touches HTTP uses `pytest-httpx` to intercept at the transport layer.
- **Live tests are opt-in.** Marked `@pytest.mark.live`, gated by `SNOWFLAKE_ACCOUNT_URL` and `SNOWFLAKE_PAT` environment variables. Run with `pytest -m live`.
- **SSE fixtures are synthetic byte sequences.** They cover every event type, edge case, and error scenario without depending on a running agent.
- **Streamlit tests use `AppTest`.** Headless execution via `streamlit.testing.v1.AppTest` — no browser required.
- **Tests are the spec.** If a test name is specific enough to double as documentation, that's a sign it's well-written.

---

## Test structure

```
tests/
├── conftest.py                  # Shared fixtures (auth, base URL)
├── fixtures/
│   ├── sse_streams.py           # Synthetic SSE byte sequences
│   └── api_responses.py         # Mock HTTP JSON responses
├── unit/
│   ├── test_sse_parser.py
│   ├── test_auth.py
│   ├── test_event_factory.py
│   ├── test_models.py
│   └── test_utils.py
├── integration/
│   ├── conftest.py              # httpx MockTransport setup
│   ├── test_agents.py
│   ├── test_threads.py
│   ├── test_runs.py
│   └── test_thread_class.py
├── streamlit/
│   ├── test_session.py
│   ├── test_render.py
│   └── test_chatbot.py
└── live/
    └── test_live.py             # @pytest.mark.live
```

---

## Unit tests

### `test_sse_parser.py`

Tests `cortex_agents_client.sse.parse_sse_stream()` in isolation.

| Test | Description |
|---|---|
| `test_empty_stream` | Empty iterator → no events yielded |
| `test_single_text_delta` | One complete event block → `("response.text.delta", {...})` |
| `test_multi_line_data` | `data:` field split across multiple lines → concatenated correctly |
| `test_comment_lines_ignored` | Lines starting with `:` are skipped |
| `test_retry_field_ignored` | `retry:` lines are skipped |
| `test_blank_line_dispatches` | Event dispatched on blank line separator |
| `test_multiple_events_sequential` | Two consecutive events both yielded |
| `test_all_15_event_types` | One fixture event of each type → 15 tuples |
| `test_truncated_stream` | Stream ends mid-event → partial event discarded |
| `test_invalid_json_in_data` | Malformed JSON in `data:` → yielded as `("error", None)` or raw |
| `test_missing_event_line` | `data:` without preceding `event:` → event_type defaults to `"message"` |
| `test_event_without_data` | `event:` without following `data:` → no dispatch |

### `test_event_factory.py`

Tests `cortex_agents_client.sse.event_from_sse()`.

| Test | Description |
|---|---|
| `test_text_event` | `response.text` → `TextEvent(content_index=0, text="...")` |
| `test_text_delta_event` | `response.text.delta` → `TextDeltaEvent` |
| `test_text_annotation_event` | `response.text.annotation` → `TextAnnotationEvent` with all citation fields |
| `test_thinking_event` | `response.thinking` → `ThinkingEvent` with `signature` |
| `test_thinking_delta_event` | `response.thinking.delta` → `ThinkingDeltaEvent` |
| `test_tool_use_event_no_permission` | `response.tool_use` with empty `permission.options` → `permission_options=[]` |
| `test_tool_use_event_with_permission` | `permission.options=["Allow Once","Deny"]` → stored on event |
| `test_tool_use_client_side_execute` | `client_side_execute=true` → `True` |
| `test_tool_result_success` | `response.tool_result` status=success |
| `test_tool_result_error` | `response.tool_result` status=error |
| `test_tool_result_status_event` | `response.tool_result.status` → `ToolResultStatusEvent` |
| `test_analyst_delta_all_fields` | `response.tool_result.analyst.delta` with full delta |
| `test_analyst_delta_sql_only` | delta with only `sql` field set |
| `test_analyst_delta_with_result_set` | delta with `result_set` field |
| `test_analyst_delta_with_suggestions` | delta with `suggestions` field |
| `test_table_event` | `response.table` → `TableEvent` with `result_set` and `title` |
| `test_table_event_no_title` | `title=null` → `title=None` |
| `test_chart_event` | `response.chart` → `ChartEvent` with raw string `chart_spec` |
| `test_status_event` | `response.status` → `StatusEvent` |
| `test_warning_event` | `response.warning` with and without `code` |
| `test_error_event` | `error` → `ErrorEvent` with `code`, `message`, `request_id` |
| `test_metadata_user_event` | `metadata` role=user → `MetadataEvent` |
| `test_metadata_assistant_event` | `metadata` role=assistant → `MetadataEvent` |
| `test_unknown_event_type` | `"response.new_future_type"` → `UnknownEvent(event_type=..., raw_payload={...})` |
| `test_unknown_event_does_not_raise` | Unknown type never raises `KeyError` or `Exception` |

### `test_auth.py`

| Test | Description |
|---|---|
| `test_pat_auth_headers` | Returns `Authorization: Bearer <token>` + token type header |
| `test_pat_auth_string_coercion` | Passing str to `CortexAgentsClient` wraps as `PATAuth` |
| `test_jwt_auth_headers_structure` | Returns `Authorization: Bearer <jwt>` + type header |
| `test_jwt_claims_iss` | JWT `iss` = `ACCOUNT.USER.SHA256:<fingerprint>` |
| `test_jwt_claims_sub` | JWT `sub` = `ACCOUNT.USER` |
| `test_jwt_exp_within_one_hour` | `exp - iat <= 3600` |
| `test_jwt_account_user_uppercase` | Account and user in iss/sub are uppercased |
| `test_oauth_auth_no_type_header` | OAuth does not send `X-Snowflake-Authorization-Token-Type` |

### `test_models.py`

| Test | Description |
|---|---|
| `test_result_set_from_dict` | Dict → `ResultSet` dataclass with correct `row_types` |
| `test_result_set_num_rows` | `num_rows` matches `len(data)` |
| `test_stored_message_defaults` | All list fields default to empty list |
| `test_agent_from_dict` | Dict → `Agent` with nested `profile`, `instructions`, `tools` |
| `test_thread_metadata_from_dict` | Dict → `ThreadMetadata` |
| `test_thread_message_from_dict` | Dict → `ThreadMessage` |

### `test_utils.py`

| Test | Description |
|---|---|
| `test_parse_three_part_path` | `"DB.SCHEMA.AGENT"` → `("DB", "SCHEMA", "AGENT")` |
| `test_parse_two_part_path_with_default_db` | `"SCHEMA.AGENT"` + `default_database="DB"` → `("DB", "SCHEMA", "AGENT")` |
| `test_parse_one_part_path_with_defaults` | `"AGENT"` + both defaults → `("DB", "SCHEMA", "AGENT")` |
| `test_parse_full_path_overrides_defaults` | Full 3-part path ignores defaults |
| `test_parse_missing_database_raises` | 2-part path with no default_database → `ValueError` |
| `test_parse_missing_schema_raises` | 1-part path with no default_schema → `ValueError` |
| `test_result_set_to_dataframe_column_names` | Column names match `rowType[].name` |
| `test_result_set_to_dataframe_integer_type` | `INTEGER` rowType → int64 dtype |
| `test_result_set_to_dataframe_float_type` | `FLOAT` → float64 dtype |
| `test_result_set_to_dataframe_boolean_type` | `BOOLEAN` → bool dtype |
| `test_result_set_to_dataframe_varchar_type` | `VARCHAR` → object dtype |
| `test_result_set_to_dataframe_nullable_int` | nullable `INTEGER` → `Int64` (nullable) dtype |
| `test_result_set_to_dataframe_empty_result` | 0-row result set → empty DataFrame with correct columns |

---

## Integration tests

All use `pytest-httpx` to mock the `httpx.Client` transport. No real network calls.

### `conftest.py` (integration)

Provides:
- `mock_client` fixture — `CortexAgentsClient` with mocked transport
- `mock_transport` fixture — raw `httpx.MockTransport` for custom routing
- `pat_client` fixture — pre-configured client with fake PAT token
- `sse_response(events)` helper — builds an `httpx.Response` from a list of SSE event dicts

### `test_agents.py`

| Test | Description |
|---|---|
| `test_create_agent_happy_path` | POST returns 200 → `Agent` object returned |
| `test_create_agent_or_replace` | `create_mode="orReplace"` → `?createMode=orReplace` in URL |
| `test_create_agent_if_not_exists` | `create_mode="ifNotExists"` in URL |
| `test_describe_agent_happy_path` | GET → `Agent` with all fields |
| `test_describe_agent_404` | HTTP 404 → `AgentNotFoundError` |
| `test_describe_agent_403` | HTTP 403 → `PermissionError` |
| `test_update_agent_happy_path` | PUT 200 → no error |
| `test_update_agent_partial_fields` | Only provided fields in request body |
| `test_list_agents_empty` | Empty array → `[]` |
| `test_list_agents_multiple` | Array of 3 → list of 3 `Agent` objects |
| `test_list_agents_with_like_filter` | `like="MY*"` → `?like=MY*` in URL |
| `test_delete_agent_happy_path` | DELETE 200 → no error |
| `test_delete_agent_if_exists_true` | `if_exists=True` → `?ifExists=true` in URL |
| `test_delete_missing_agent_without_if_exists` | 404 → `AgentNotFoundError` |
| `test_feedback_happy_path` | POST feedback with all fields |
| `test_feedback_minimal_fields` | Only `request_id` and `positive` |

### `test_threads.py`

| Test | Description |
|---|---|
| `test_create_thread_returns_metadata` | POST → `ThreadMetadata` with `thread_id` |
| `test_create_thread_with_origin_app` | `origin_application` in request body |
| `test_create_thread_no_origin_app` | Empty body when no `origin_application` |
| `test_get_thread_returns_messages_descending` | Messages in descending `message_id` order |
| `test_get_thread_with_message_type_filter` | `message_type="conversation"` → `?message_type=conversation` |
| `test_list_messages_paginates` | Two pages of 2 messages each → 4 total messages |
| `test_list_messages_uses_last_message_id_cursor` | Second page request includes `?last_message_id=N` |
| `test_latest_context_no_compaction` | No compaction → all conversation messages returned |
| `test_latest_context_with_compaction` | Compaction at ID 42 → summary + messages after 42 |
| `test_latest_context_compaction_boundary` | Messages exactly at anchor ID excluded |
| `test_update_thread_happy_path` | POST 200 → no error |
| `test_list_threads_returns_all` | GET → list of `ThreadMetadata` |
| `test_list_threads_origin_filter` | `origin_application` → query param |
| `test_delete_thread_happy_path` | DELETE → no error |
| `test_delete_thread_404` | HTTP 404 → `ThreadNotFoundError` |

### `test_runs.py`

| Test | Description |
|---|---|
| `test_stream_all_15_event_types` | One of each event type → correct dataclass for each |
| `test_stream_text_accumulation` | 3 `text.delta` + 1 `text` → final `TextEvent.text` matches deltas |
| `test_stream_thinking_events` | Thinking delta + thinking complete → both yielded |
| `test_stream_tool_use_and_result` | `tool_use` → `tool_result.status` → `tool_result` sequence |
| `test_stream_analyst_delta_sequence` | Multiple analyst deltas → accumulated |
| `test_stream_table_event` | `response.table` with result set → `TableEvent` |
| `test_stream_chart_event` | `response.chart` with Vega-Lite spec → `ChartEvent` |
| `test_stream_warning_does_not_stop_stream` | `response.warning` + subsequent events all yielded |
| `test_stream_error_event` | `error` event → `RunError` raised by `run()` |
| `test_stream_error_event_yielded_raw` | `stream()` yields `ErrorEvent` before caller sees it |
| `test_stream_metadata_user_then_assistant` | Two metadata events in order |
| `test_stream_unknown_event_type` | Unknown type → `UnknownEvent` yielded, no exception |
| `test_run_non_streaming` | `stream=False` → single JSON response → `RunResult` |
| `test_run_non_streaming_with_table` | Non-streaming response with table content |
| `test_run_non_streaming_error` | Non-streaming error response → `RunError` |
| `test_agent_object_url` | Run with agent → correct URL pattern |
| `test_lite_agent_url` | Run without agent → `/api/v2/cortex/agent:run` |
| `test_tool_choice_in_request_body` | `tool_choice` passed through |
| `test_permission_decision_in_message` | `permission_decision` content type sent correctly |
| `test_http_401_raises_auth_error` | HTTP 401 → `AuthError` |
| `test_http_403_raises_permission_error` | HTTP 403 → `PermissionError` |
| `test_http_429_raises_rate_limit_error` | HTTP 429 → `RateLimitError` |
| `test_http_500_raises_server_error` | HTTP 500 → `ServerError` |
| `test_connection_error_raises_cortex_agent_error` | `httpx.ConnectError` → `CortexAgentError` |
| `test_timeout_raises_timeout_error` | `httpx.TimeoutException` → `TimeoutError` |

### `test_thread_class.py`

| Test | Description |
|---|---|
| `test_chat_initial_parent_message_id_is_zero` | First turn uses `parent_message_id=0` |
| `test_chat_advances_parent_message_id` | After first turn, `parent_message_id=456` (from metadata) |
| `test_chat_second_turn_uses_assistant_id` | Second turn request body has `parent_message_id=456` |
| `test_chat_missing_assistant_metadata_preserves_id` | If assistant metadata missing, ID unchanged |
| `test_chat_yields_all_event_types` | All events from underlying `stream()` are yielded |
| `test_fork_creates_new_thread_with_correct_parent` | `fork(at_message_id=42)` → new Thread with `parent_message_id=42` |
| `test_fork_does_not_affect_original` | Original thread's `parent_message_id` unchanged after fork |
| `test_delete_calls_threads_resource` | `thread.delete()` calls `threads_resource.delete(thread_id)` |
| `test_get_history_calls_threads_resource` | `thread.get_history()` calls `list_messages(thread_id)` |

---

## Streamlit tests

Uses `streamlit.testing.v1.AppTest` for headless execution.

### `test_session.py`

| Test | Description |
|---|---|
| `test_init_session_creates_client` | Client is created and stored in session state on first call |
| `test_init_session_creates_thread` | Thread is created with correct `origin_application` |
| `test_init_session_idempotent` | Second call returns same client and thread objects |
| `test_init_session_empty_messages` | `get_messages()` returns `[]` after init |
| `test_reset_thread_clears_messages` | Messages list emptied after reset |
| `test_reset_thread_creates_new_thread` | Thread ID changes after reset |
| `test_reset_thread_preserves_client` | Same client reused after reset |
| `test_custom_keys_dont_collide` | Custom `client_key` and `thread_key` work independently |

### `test_render.py`

| Test | Description |
|---|---|
| `test_render_streaming_text_only` | Text deltas accumulated → `StoredMessage.text` correct |
| `test_render_streaming_table` | `TableEvent` → `StoredMessage.tables` has 1 entry |
| `test_render_streaming_chart` | `ChartEvent` → `StoredMessage.charts` has 1 entry |
| `test_render_streaming_thinking_shown` | Thinking event with `show_thinking=True` → stored |
| `test_render_streaming_thinking_hidden` | `show_thinking=False` → thinking captured but not rendered |
| `test_render_streaming_warning` | Warning → `StoredMessage.warnings` |
| `test_render_streaming_error` | Error event → `StoredMessage.error` set |
| `test_render_streaming_annotations` | Annotation events → `StoredMessage.annotations` |
| `test_render_streaming_tool_execution` | `tool_use` + `tool_result` → `StoredMessage.tool_executions` |
| `test_render_stored_matches_streaming` | `render_stored_message` produces same markdown as streaming |
| `test_render_stored_table` | `StoredMessage` with table → `st.dataframe()` called |
| `test_render_stored_chart` | `StoredMessage` with chart → `st.vega_lite_chart()` called |
| `test_result_set_to_dataframe_integer_column` | INTEGER → int64 |
| `test_result_set_to_dataframe_float_column` | FLOAT → float64 |
| `test_result_set_to_dataframe_varchar_column` | VARCHAR → object |

### `test_chatbot.py`

| Test | Description |
|---|---|
| `test_chatbot_renders_empty_state` | No messages → only input widget visible |
| `test_chatbot_shows_user_message` | After input → user message appears |
| `test_chatbot_shows_assistant_response` | After input → assistant message appears |
| `test_chatbot_persists_on_rerun` | Both messages still present after simulated rerun |
| `test_chatbot_new_conversation_clears_history` | "New conversation" button clears messages |
| `test_chatbot_error_state_shown` | Error event → error displayed, app does not crash |
| `test_chatbot_multiple_turns` | Two inputs → four messages in history |

---

## Live tests

Run with: `pytest tests/live/ -m live`

Required env vars: `SNOWFLAKE_ACCOUNT_URL`, `SNOWFLAKE_PAT`, `SNOWFLAKE_AGENT_PATH`.

| Test | Description |
|---|---|
| `test_pat_auth_valid` | `CortexAgentsClient` connects successfully |
| `test_create_and_delete_thread` | Create thread → assert `thread_id` is integer → delete |
| `test_single_turn_run` | `Thread.chat()` → at least one `TextEvent` received |
| `test_multi_turn_conversation` | Two turns → `parent_message_id` advances correctly |
| `test_feedback_submission` | Submit positive feedback on a run → no error |

---

## Coverage targets

| Module | Target |
|---|---|
| `sse.py` | 100% |
| `auth.py` | 100% |
| `models/events.py` | 100% |
| `resources/agents.py` | ≥ 95% |
| `resources/threads.py` | ≥ 95% |
| `resources/runs.py` | ≥ 95% |
| `client.py` | ≥ 90% |
| `st/session.py` | ≥ 90% |
| `st/render.py` | ≥ 85% |
| `st/chatbot.py` | ≥ 80% |

---

## Running tests

```bash
# All unit + integration tests
pytest tests/unit/ tests/integration/ -v

# With coverage report
pytest tests/unit/ tests/integration/ --cov=cortex_agents_client --cov-report=term-missing

# Streamlit tests only
pytest tests/streamlit/ -v

# Live tests (requires env vars)
pytest tests/live/ -m live -v

# All tests except live
pytest tests/ -m "not live" -v
```
