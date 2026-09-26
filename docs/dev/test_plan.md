# Test Plan

Living document describing the test suite for `streamlit_cortex_agents`.
Test names and file paths are kept in sync with the code on disk; if you find a
discrepancy, the code is authoritative.

**Current totals:** 422 passing, 1 skipped (JWT-missing-cryptography path skipped when `cryptography` is installed), excluding the `live` suite, which requires credentials.

---

## Test structure

```
tests/
├── conftest.py                  # shared fixtures: pat_token, account_url
├── fixtures/
│   ├── api_responses.py         # THREAD_CREATE_RESPONSE, THREAD_DESCRIBE_RESPONSE, NON_STREAMING_RUN_RESPONSE, ...
│   └── sse_streams.py           # per-event-type payloads + ALL_EVENT_TYPES + stream_of()
├── unit/
│   ├── test_auth.py             # PATAuth, OAuthAuth, SiSContainerAuth, account_url_from_env, JWTAuth
│   ├── test_event_factory.py    # 40 tests across 17 SSE event types + sequence_number capture
│   ├── test_exceptions.py       # exception hierarchy, incl. ConflictError / RunNotActiveError (409)
│   ├── test_http.py             # status-code → exception mapping (incl. 409), headers, X-Snowflake-Role
│   ├── test_models.py           # Agent, ThreadMetadata, ThreadMessage, StoredMessage
│   ├── test_run_body.py         # agent:run body: models vs deprecated model, orchestration, background
│   ├── test_sse_parser.py       # SSE wire-level parsing + terminal [DONE] sentinel
│   ├── test_utils.py            # agent path resolution, result_set_to_dataframe, Thread.chat tool_executor
│   └── test_variables.py        # multi-tenancy variables: normalisation, body emission, forwarding
├── integration/
│   ├── conftest.py              # ca_client, pat_auth, http_client, make_sse_response, make_sse_httpx_response
│   ├── test_agents.py           # AgentsResource CRUD + feedback
│   ├── test_runs.py             # RunsResource streaming + Thread class multi-turn
│   └── test_threads.py          # ThreadsResource CRUD + pagination helpers
├── streamlit/
│   ├── test_chatbot.py          # CortexAgentChat constructor + render dispatch
│   ├── test_column_config.py    # _markdown_column_config dtype selection (object + StringDtype)
│   ├── test_render.py           # render_streaming_response + render_stored_message
│   └── test_session.py          # init_session, reset_thread, get_messages, append_message
└── live/
    ├── conftest.py              # fixtures: live_client, agent_path_minimal, agent_path_full, agent_path_analyst, agent_path_web, live_thread
    ├── test_auth.py             # PAT auth smoke; bad token → AuthError; missing agent → AgentNotFoundError
    ├── test_threads.py          # create, get, list, delete, fork, latest_context
    ├── test_runs.py             # streaming events, ResponseEvent, multi-turn, non-streaming run (minimal agent)
    ├── test_runs_full.py        # ToolUseEvent, ToolResultEvent, TextAnnotationEvent (Cortex Search agent)
    ├── test_runs_analyst.py     # ToolUseEvent (system_execute_sql), SQL via ToolUseEvent.input, verified query
    ├── test_runs_web.py         # ToolUseEvent (web_search), ToolResultEvent, non-empty text (web agent)
    ├── test_runs_multitenancy.py # multi-tenancy variables end-to-end: row access policy scoping
    ├── test_runs_async.py       # background runs, stream_run reconnect, starting_after, cancel_run + 409, Thread.chat(background), lite models/orchestration, X-Snowflake-Role
    ├── test_agents.py           # agent CRUD lifecycle, createMode, ifExists, agent- and request-level feedback
    ├── test_streamlit_live.py   # AppTest against a live agent: render pipeline, history replay, Analyst dataframe
    ├── apps/
    │   └── live_chat_app.py     # app script driven by AppTest
    ├── captures/                # recorded live SSE payloads, for offline inspection
    ├── README.md                # setup instructions, env vars, how to run
    └── seed/
        ├── 01_minimal_agent.sql       # LLM-only agent DDL
        ├── 02_search_service.sql      # fixed corpus table + Cortex Search service
        ├── 03_full_agent.sql          # Cortex Search agent DDL
        ├── 04_semantic_view.sql       # sales table + semantic view DDL
        ├── 05_analyst_agent.sql       # Cortex Analyst agent DDL
        ├── 06_web_search_agent.sql    # web search agent DDL
        ├── 07_multitenancy.sql        # scoped table + row access policy + agent, for variables tests
        ├── teardown.sql               # DROP all test objects
        ├── teardown.py                # run teardown.sql via snowflake-connector
        ├── cleanup_leaked_threads.py  # sweep origin_application='cac_live' threads
        └── cleanup_leaked_agents.py   # sweep cac_live_crud_* agents left by a hard kill
```

---

## Unit tests

### `tests/unit/test_auth.py`

| Test | What it verifies |
|---|---|
| `test_pat_auth_authorization_header` | `PATAuth.headers()` returns `Authorization: Bearer <token>` |
| `test_pat_auth_token_type_header` | `PATAuth.headers()` includes `PROGRAMMATIC_ACCESS_TOKEN` type header |
| `test_string_coercion_wraps_as_pat` | `_coerce_auth(str)` wraps the string as `PATAuth` |
| `test_auth_provider_passthrough` | `_coerce_auth(AuthProvider)` returns the instance unchanged |
| `test_oauth_auth_authorization_header` | `OAuthAuth.headers()` returns correct bearer token |
| `test_oauth_auth_includes_type_header` | `OAuthAuth` includes `X-Snowflake-Authorization-Token-Type: OAUTH` |
| `test_jwt_auth_raises_without_cryptography` | `JWTAuth` raises `ImportError` when `cryptography` is missing (skipped when installed) |
| **`TestSiSContainerAuth`** | |
| `test_reads_token_from_file` | `headers()` reads bearer token from token file |
| `test_strips_whitespace_from_token` | Trailing newline is stripped |
| `test_re_reads_token_on_each_call` | Each `headers()` call re-reads the file (token rotation) |
| `test_raises_if_token_file_missing` | `FileNotFoundError` if token file is absent |
| `test_includes_oauth_type_header` | `SiSContainerAuth` includes `X-Snowflake-Authorization-Token-Type: OAUTH` |
| **`TestAccountUrlFromEnv`** | |
| `test_returns_https_url` | Constructs `https://` URL from `SNOWFLAKE_HOST` env var |
| `test_raises_if_env_var_missing` | `EnvironmentError` if `SNOWFLAKE_HOST` not set |
| `test_custom_env_var_name` | Custom `host_env` parameter is respected |
| **`TestJWTAuth`** (requires `cryptography` + `PyJWT`) | |
| `test_headers_include_authorization_and_keypair_jwt_type` | `headers()` returns `Authorization` + `KEYPAIR_JWT` type header |
| `test_jwt_claims_iss_format` | `iss` claim is `ACCOUNT.USER.SHA256:<fingerprint>` |
| `test_jwt_claims_sub_format` | `sub` claim is `ACCOUNT.USER` |
| `test_jwt_exp_within_one_hour` | `exp - iat <= 3600` |
| `test_account_and_user_uppercased_in_claims` | Lowercase account/user are uppercased in claims |

---

### `tests/unit/test_event_factory.py`

One test per SSE event type, verifying that `event_from_sse(event_type, payload)` returns the correct dataclass with all fields populated.

| Test | Event type → Dataclass |
|---|---|
| `test_text_delta_event` | `response.text.delta` → `TextDeltaEvent` (text, delta alias, content_index, is_elicitation) |
| `test_text_delta_event_is_elicitation` | `is_elicitation=True` captured |
| `test_text_event` | `response.text` → `TextEvent` |
| `test_text_event_is_elicitation` | `is_elicitation=True` in final text event |
| `test_text_event_inline_annotations` | Inline `annotations` array parsed |
| `test_text_annotation_event` | `response.text.annotation` → `TextAnnotationEvent` (all citation fields) |
| `test_thinking_delta_event` | `response.thinking.delta` → `ThinkingDeltaEvent` |
| `test_thinking_event` | `response.thinking` → `ThinkingEvent` |
| `test_tool_use_event_no_permission` | `response.tool_use` (no permission) → `permission_options=[]`, `client_side_execute=False` |
| `test_tool_use_event_with_permission` | `response.tool_use` with options → `permission_options` populated |
| `test_tool_use_client_side_execute_string_true` | `client_side_execute: "true"` (string) parses to `True` |
| `test_tool_use_client_side_execute_string_false` | `client_side_execute: "false"` (string) parses to `False` (not `True`) |
| `test_tool_use_client_side_execute_bool_true` | `client_side_execute: true` (boolean) parses to `True` |
| `test_tool_result_success` | `response.tool_result` status=success → `ToolResultEvent` |
| `test_tool_result_error` | `response.tool_result` status=error |
| `test_tool_result_status_event` | `response.tool_result.status` → `ToolResultStatusEvent` |
| `test_analyst_delta_all_fields` | `response.tool_result.analyst.delta` → `AnalystDeltaEvent` (all fields) |
| `test_analyst_delta_sql_only` | Delta with only `sql` field; text/result_set are `None` |
| `test_analyst_delta_with_suggestions` | Delta with `suggestions` field |
| `test_table_event` | `response.table` → `TableEvent` (result_set + title) |
| `test_table_event_no_title` | `title=None` handled |
| `test_chart_event` | `response.chart` → `ChartEvent` (chart_spec string) |
| `test_status_event` | `response.status` → `StatusEvent` |
| `test_warning_event_with_code` | `response.warning` → `WarningEvent` with code |
| `test_warning_event_without_code` | `code=None` when absent |
| `test_error_event` | `error` → `ErrorEvent` (code, message, request_id) |
| `test_error_event_uses_error_code_alias` | Falls back to `error_code` field when `code` missing |
| `test_metadata_user_event` | `metadata` role=user → `MetadataEvent` |
| `test_metadata_assistant_event` | `metadata` role=assistant |
| `test_response_event` | `response` → `ResponseEvent` (usage, token counts, IDs) |
| `test_response_event_cancelled` | `status="cancelled"` captured |
| `test_response_event_missing_metadata` | Missing metadata fields default to `None`/`[]` |
| `test_unknown_event_type_returns_unknown_event` | Unknown type → `UnknownEvent` (event_type + raw_payload) |
| `test_unknown_event_does_not_raise` | Never raises, even for unusual type strings |

---

### `tests/unit/test_models.py`

| Class | Tests |
|---|---|
| `TestAgentProfile` | `test_from_dict_with_display_name`, `test_from_dict_empty`, `test_to_dict` |
| `TestAgentInstructions` | `test_from_dict_all_fields`, `test_to_dict_omits_empty_fields` |
| `TestBudgetConfig` | `test_from_dict`, `test_to_dict_omits_none_fields` |
| `TestAgent` | `test_from_dict_list_response`, `test_from_dict_describe_response_with_agent_spec`, `test_path_property` |
| `TestThreadMetadata` | `test_from_dict` |
| `TestThreadMessage` | `test_from_dict_with_parent`, `test_from_dict_without_parent` |
| `TestStoredMessage` | `test_default_fields_are_empty` |
| `TestRepr` | `test_cortex_agents_client_repr`, `test_thread_repr` |

---

### `tests/unit/test_exceptions.py`

| Class | Tests |
|---|---|
| `TestExceptionHierarchy` | `test_agent_not_found_is_not_found_error`, `test_thread_not_found_is_not_found_error`, `test_run_not_active_is_conflict_error`, `test_conflict_error_is_not_a_not_found_error`, `test_cortex_permission_error_is_cortex_agent_error`, `test_cortex_timeout_error_is_cortex_agent_error`, `test_auth_error_is_cortex_agent_error`, `test_rate_limit_error_is_cortex_agent_error`, `test_server_error_is_cortex_agent_error`, `test_run_error_is_cortex_agent_error`, `test_not_found_catchall_catches_agent_variant`, `test_not_found_catchall_catches_thread_variant` |
| `TestDeprecatedAliases` | `test_permission_error_alias_emits_deprecation_warning`, `test_timeout_error_alias_emits_deprecation_warning` |

---

### `tests/unit/test_http.py`

Tests for the transport layer (`HttpClient`):

| Class | What it verifies |
|---|---|
| `TestHeaderAssembly` | Auth and `Content-Type` headers on `request`; `Accept: text/event-stream` on `stream`; `X-Snowflake-Role` absent by default, sent when `role` is configured, sent on streams too; per-call headers override the role and merge with auth; per-call `Accept` override |
| `TestErrorMapping` | `test_status_code_raises_correct_exception` is parametrized over the full status/resource matrix, including **409 → `RunNotActiveError`** for `resource='run'` and **409 → `ConflictError`** otherwise; `test_error_preserves_status_code` |
| `TestJsonParseFallback` | Non-JSON error body falls back to raw text; empty body reports the status code |
| `TestConnectionErrors` | Timeout → `CortexTimeoutError`; connect failure → `CortexConnectionError`; generic transport error → `CortexAgentError` |
| `TestSuccessResponses` | JSON parsed; `204` → `None`; empty body → `None` |
| `TestClose` | `close()` does not raise and is idempotent |
| `TestUrlConstruction` | URL joined from base and path; trailing slash stripped from base |
| `TestConnectionPooling` | No keep-alive connections (streaming correctness) |
| `TestTimeoutConfiguration` | Default and custom read timeouts; read timeout mid-stream → `CortexTimeoutError` |

This file holds the only unit-level proof of the 409 mapping.

---

### `tests/unit/test_sse_parser.py`

Tests for the wire-level SSE parser (`parse_sse_stream`):

| Test | What it verifies |
|---|---|
| `test_empty_stream_yields_nothing` | Empty iterator → no events |
| `test_single_text_delta_event` | Single event parsed and dispatched |
| `test_multiple_events_all_yielded` | Multiple events all yielded in order |
| `test_comment_lines_ignored` | `:` comment lines are skipped |
| `test_retry_lines_ignored` | `retry:` lines are ignored |
| `test_blank_line_dispatches_accumulated_event` | Blank line flushes accumulated event |
| `test_all_17_event_types_parsed` | All 17 API-emitted event types round-trip through the parser |
| `test_truncated_stream_discards_partial_event` | Incomplete event at end of stream is discarded |
| `test_invalid_json_in_data_yields_parse_error` | Bad JSON yields `("_parse_error", {"raw": "..."})` |
| `test_missing_event_line_uses_message_default` | No `event:` line → type defaults to `"message"` |
| `test_event_without_data_not_dispatched` | Event line with no `data:` is not dispatched |
| `test_data_field_whitespace_stripped` | Leading space in `data: value` is stripped |
| `test_done_sentinel_does_not_yield_an_event` | `data: [DONE]` is swallowed rather than surfaced as `_parse_error` |
| `test_done_sentinel_ends_iteration` | Nothing after the `[DONE]` frame is yielded |
| `test_done_sentinel_without_event_name` | `[DONE]` is recognised even with no preceding `event:` line |
| `test_malformed_json_still_yields_parse_error` | The `[DONE]` special case does not mask genuine JSON errors |

---

### `tests/unit/test_utils.py`

#### `TestAgentPathResolution`

Tests `RunsResource._resolve_path()`:

| Test | What it verifies |
|---|---|
| `test_three_part_path` | `"DB.SC.AGENT"` resolves fully, overrides defaults |
| `test_two_part_path_uses_default_database` | `"SC.AGENT"` + `default_database` |
| `test_one_part_path_uses_both_defaults` | `"AGENT"` + both defaults |
| `test_three_part_path_overrides_defaults` | Explicit path always wins |
| `test_two_part_path_missing_default_database_raises` | `ValueError` when `default_database` absent |
| `test_one_part_path_missing_defaults_raises` | `ValueError` when both defaults absent |
| `test_none_agent_path_returns_none` | `agent_path=None` → `None` (lite/objectless run) |
| `test_agent_name_with_database_schema` | `agent=` / `database=` / `schema=` kwargs |

#### `TestResultSetToDataframe`

Tests `result_set_to_dataframe(table_event)` from `streamlit_cortex_agents.chat.render`:

| Test | What it verifies |
|---|---|
| `test_column_names_match_row_types` | Column names match `rowType[n].name` |
| `test_integer_type_casting` | `INTEGER` column → pandas `Int64` (nullable) |
| `test_float_type_casting` | `FLOAT` column → `float64` |
| `test_varchar_type_stays_as_string` | `VARCHAR` → `object` |
| `test_empty_result_set_returns_empty_dataframe` | Empty `data` → 0-row DataFrame with correct columns |
| `test_empty_row_types_returns_empty_dataframe` | Empty `rowType` → empty DataFrame |

#### `TestToolExecutor`

Tests `Thread.chat()` with client-side `tool_executor` callback:

| Test | What it verifies |
|---|---|
| `test_tool_executor_called_for_client_side_tool` | `tool_executor` is called; synthetic `ToolResultEvent` yielded; follow-up run fires (2 total stream calls) |
| `test_tool_executor_exception_yields_error_result` | Executor raising `RuntimeError` yields `status="error"` result; follow-up still fires |
| `test_no_tool_executor_client_side_event_yields_normally` | `client_side_execute=True` without executor → event passes through; only 1 stream call |

---

### `tests/unit/test_variables.py`

Covers the optional `variables` argument (multi-tenancy session attributes).

#### `TestNormalize`

Tests `normalize_variables()` from `streamlit_cortex_agents.client._variables`:

| Test | What it verifies |
|---|---|
| `test_none_and_empty_return_none` | `None` and `{}` both produce `None`, so no key is sent |
| `test_shorthand_string` | A bare value expands to `{value, type, is_immutable_session_attribute}` |
| `test_shorthand_type_inference` | Parametrized: `str` → `string`, `int`/`float` → `number`, `bool` → `boolean` |
| `test_full_form_passthrough` | A full dict is preserved as given |
| `test_full_form_defaults_type_and_immutable` | Missing `type` is inferred; `is_immutable_session_attribute` defaults to `True` |
| `test_full_form_explicit_false_respected` | An explicit `is_immutable_session_attribute=False` is not overwritten |
| `test_full_form_explicit_type_kept` | An explicit `type` is never replaced by inference |
| `test_input_not_mutated` | The caller's mapping is copied, not modified in place |
| `test_invalid_raises_value_error` | Parametrized: `None` value, missing `value` key, unsupported type, NaN, infinity, empty name |
| `test_non_mapping_raises_value_error` | A non-mapping `variables` argument raises `ValueError` |

#### `TestBuildBody`

Tests `RunsResource._build_body()`:

| Test | What it verifies |
|---|---|
| `test_omitted_has_no_variables_key` | No `variables` key when the argument is absent |
| `test_omitted_body_unchanged` | The body is byte-identical to the pre-feature body |
| `test_shorthand_normalised_into_body` | Shorthand values are expanded in the emitted body |
| `test_invalid_raises_before_http` | Validation fails before any HTTP request is made |

#### `TestRunsForwarding`, `TestClientForwarding`, `TestThreadChat`

| Test | What it verifies |
|---|---|
| `test_stream_sends_variables` | `runs.stream()` forwards `variables` |
| `test_run_sends_variables` | `runs.run()` forwards `variables` |
| `test_stream_and_collect_forwards_variables` | `stream_and_collect()` forwards `variables` |
| `test_stream_without_thread` | `client.stream()` forwards on the threadless branch |
| `test_stream_with_thread_forwards_to_chat` | `client.stream(thread=...)` forwards through `Thread.chat` |
| `test_run_forwards` / `test_run_with_thread_forwards` | `client.run()` forwards on both branches |
| `test_chat_forwards_variables` | `Thread.chat()` forwards `variables` |
| `test_chat_default_sends_none` | Default omits the key |
| `test_tool_loop_follow_up_carries_variables` | Tool-result follow-up requests carry the same `variables` |

---

## Integration tests

Fixtures (defined in `tests/integration/conftest.py`):
- `ca_client` — `CortexAgentsClient` with `pytest-httpx`-intercepted transport
- `make_sse_response(events)` — builds SSE body string
- `make_json_response(data, status_code)` — builds `httpx.Response` with JSON content
- `make_sse_httpx_response(events)` — builds `httpx.Response` with SSE content

### `tests/integration/test_agents.py`

| Class | Tests |
|---|---|
| `TestCreateAgent` | `test_create_returns_agent`, `test_create_with_or_replace_sends_query_param`, `test_create_with_if_not_exists` |
| `TestGetAgent` | `test_get_happy_path`, `test_get_404_raises_agent_not_found`, `test_get_403_raises_permission_error`, `test_get_401_raises_auth_error` |
| `TestUpdateAgent` | `test_update_happy_path`, `test_update_only_sends_provided_fields` |
| `TestListAgents` | `test_list_returns_all_agents`, `test_list_empty_returns_empty_list`, `test_list_with_like_filter_sends_query_param` |
| `TestDeleteAgent` | `test_delete_happy_path`, `test_delete_if_exists_sends_query_param`, `test_delete_missing_without_if_exists_raises` |
| `TestFeedback` | `test_feedback_request_level`, `test_feedback_agent_level_no_request_id`, `test_feedback_url_no_trailing_colon` |

---

### `tests/integration/test_runs.py`

| Class | Tests |
|---|---|
| `TestStreamAllEventTypes` | `test_stream_yields_all_17_event_types`, `test_stream_text_delta_type` (includes `.delta` backward-compat alias) |
| `TestStreamMetadataTracking` | `test_metadata_events_both_yielded` — both user + assistant metadata events yielded in order |
| `TestWarningEvent` | `test_warning_followed_by_text_both_yielded` — warning + text both yield |
| `TestErrorEvent` | `test_stream_and_collect_raises_run_error`, `test_stream_yields_error_event_before_raising` |
| `TestUnknownEventType` | `test_unknown_type_yields_unknown_event` |
| `TestNonStreamingRun` | `test_run_returns_run_result`, `test_run_non_streaming_error_raises` |
| `TestRunURLs` | `test_agent_object_run_uses_agent_url`, `test_lite_run_uses_cortex_agent_run_url` |
| `TestHttpErrors` | `test_http_401_raises_auth_error`, `test_http_403_raises_permission_error`, `test_http_429_raises_rate_limit_error`, `test_http_500_raises_server_error` |
| `TestThreadClass` | `test_first_turn_uses_parent_message_id_zero`, `test_second_turn_uses_assistant_message_id`, `test_fork_creates_new_thread_at_message_id`, `test_missing_assistant_metadata_preserves_id` |
| `TestNotFoundErrorHierarchy` | `test_agent_not_found_catchable_as_not_found_error`, `test_thread_not_found_catchable_as_not_found_error` |
| `TestCortexTimeoutError` | `test_request_timeout_raises_cortex_timeout_error` |
| `TestStreamAndCollectFallback` | `test_text_delta_fallback_when_no_text_event`, `test_thinking_delta_fallback_when_no_thinking_event`, `test_summary_event_takes_precedence_over_deltas` |
| `TestNonStreamingThinking` | `test_run_with_thinking_content_in_response` |
| `TestNonStreamingToolParsing` | `test_run_parses_tool_use_and_tool_result`, `test_run_parses_top_level_warnings` |
| `TestStreamRun` | `test_stream_run_uses_get_on_run_path`, `test_stream_run_omits_starting_after_by_default`, `test_stream_run_sends_starting_after`, `test_stream_run_yields_typed_events`, `test_stream_run_409_raises_run_not_active`, `test_stream_run_via_client_facade` |
| `TestCancelRun` | `test_cancel_run_posts_to_cancel_path`, `test_cancel_run_returns_metadata`, `test_cancel_run_without_partial_output`, `test_cancel_run_409_raises_run_not_active`, `test_cancel_run_via_client_facade` |

---

### `tests/integration/test_threads.py`

| Class | Tests |
|---|---|
| `TestCreateThread` | `test_create_returns_metadata`, `test_create_with_origin_application_in_body`, `test_create_without_origin_application` |
| `TestGetThread` | `test_get_returns_thread_detail`, `test_get_404_raises_thread_not_found`, `test_get_with_message_type_filter` |
| `TestListMessages` | `test_list_messages_paginates` — auto-pagination returns all pages oldest-first |
| `TestLatestContext` | `test_latest_context_no_compaction`, `test_latest_context_with_compaction` |
| `TestDeleteThread` | `test_delete_happy_path`, `test_delete_404_raises_thread_not_found` |
| `TestUpdateThread` | `test_update_happy_path`, `test_update_sends_correct_body` |
| `TestListThreads` | `test_list_returns_metadata_list`, `test_list_with_origin_filter_sends_query_param` |
| `TestClientGetThread` | `test_get_thread_returns_thread_with_correct_thread_id`, `test_get_thread_with_explicit_parent_message_id` |
| `TestThreadWrapperMethods` | `test_list_messages_delegates_to_resource`, `test_latest_context_delegates_to_resource`, `test_get_history_emits_deprecation_warning` |

---

## Streamlit tests

Both files use `unittest.mock.MagicMock` and `patch.dict("sys.modules", ...)` to stub Streamlit — no real browser or `AppTest` runner required.

### `tests/streamlit/test_chatbot.py`

| Class | Tests |
|---|---|
| `TestCortexAgentChatInit` | `test_defaults`, `test_embedded_mode_params_stored`, `test_session_key_prefix_propagates`, `test_accept_file_params_stored` |
| `TestRenderDispatch` | `test_fullpage_dispatches_to_render_fullpage`, `test_embedded_dispatches_to_render_embedded`, `test_invalid_mode_raises_value_error` |
| `TestRenderFullpage` | `test_calls_chat_input`, `test_no_sidebar_button_when_disabled`, `test_accept_file_passed_to_chat_input` |
| `TestRenderEmbedded` | `test_uses_chat_input_not_form`, `test_scrollable_container_with_correct_height`, `test_process_prompt_called_when_chat_input_returns_text`, `test_process_prompt_not_called_when_chat_input_returns_none`, `test_chat_input_uses_input_key`, `test_no_new_conversation_button_when_disabled`, `test_sidebar_not_used_in_embedded_mode` |

### `tests/streamlit/test_render.py`

#### `TestRenderStreamingResponse`

| Test | What it verifies |
|---|---|
| `test_text_only_stream_sets_stored_text` | Text delta + text events populate `StoredMessage.text` |
| `test_table_event_stored_and_rendered` | `TableEvent` stored in `tables` and rendered |
| `test_chart_event_stored_and_rendered` | `ChartEvent` stored in `charts` and rendered |
| `test_thinking_event_stored_regardless_of_show_flag` | Thinking always stored; only rendered when `show_thinking=True` |
| `test_thinking_event_rendered_when_show_thinking_true` | Expander created when `show_thinking=True` |
| `test_streaming_default_show_thinking_false_suppresses_expander` | Default `show_thinking=False` suppresses expander |
| `test_warning_event_stored_and_rendered` | `WarningEvent` stored + `container.warning()` called |
| `test_error_event_stored_and_rendered` | `ErrorEvent` stored + `container.error()` called |
| `test_annotation_event_stored` | `TextAnnotationEvent` stored in `annotations` |
| `test_annotations_render_sources_expander` | Annotations list triggers a "Sources" expander |
| `test_tool_execution_stored_as_pair` | `(ToolUseEvent, ToolResultEvent)` stored as pair in `tool_executions` |
| `test_tool_result_text_content_stored_and_rendered` | Text-type tool result content stored in `tool_result_text` and rendered |
| `test_tool_result_json_content_not_rendered_as_markdown` | JSON tool result content not rendered as raw markdown |
| `test_permission_required_stops_stream_and_sets_pending` | `ToolUseEvent` with permission options halts stream; sets `pending_permission` |
| `test_permission_required_no_spinner_created` | No `st.status()` spinner for permission-gated tool |
| `test_tool_use_without_permission_still_creates_spinner` | Normal tool use creates spinner |
| `test_analyst_delta_sql_captured` | SQL from `AnalystDeltaEvent` stored in `analyst_sql` |
| `test_metadata_event_captured_as_message_id` | `MetadataEvent` role=assistant sets `message_id` |
| `test_text_deltas_without_final_text_event` | Accumulated deltas used when no final `TextEvent` arrives |
| `test_verified_query_used_sets_flag` | `verified_query_used=True` sets flag in `verified_tool_uses` |
| `test_verified_query_status_label_uses_verified_icon` | Verified query → verified icon in status label |
| `test_non_verified_query_status_label_uses_check_circle_icon` | Non-verified → check_circle icon |

#### `TestRenderStoredMessage`

| Test | What it verifies |
|---|---|
| `test_renders_text` | `StoredMessage.text` rendered via `st.markdown` |
| `test_renders_table` | `StoredMessage.tables` rendered via `st.dataframe` |
| `test_renders_chart` | `StoredMessage.charts` rendered via `st.vega_lite_chart` |
| `test_renders_thinking_expander` | Thinking text in expander (show_thinking=True) |
| `test_does_not_render_thinking_when_show_thinking_false` | Expander not created when show_thinking=False |
| `test_default_show_thinking_is_false` | Default show_thinking=False matches render_streaming_response |
| `test_elicitation_renders_info_not_markdown` | is_elicitation=True uses st.info() not st.markdown() |
| `test_renders_warning` | `WarningEvent` rendered as `st.warning` |
| `test_renders_error` | `ErrorEvent` rendered as `st.error` |
| `test_empty_message_no_calls` | Empty `StoredMessage` makes no render calls |
| `test_tool_result_text_replayed` | `tool_result_text` re-rendered on replay |
| `test_pending_permission_renders_warning` | Pending permission shown as `st.warning` |
| `test_annotations_render_sources_expander_in_stored_message` | Sources expander in stored message |
| `test_url_doc_id_rendered_with_unsafe_html` | URL `doc_id` renders as HTML anchor |
| `test_non_url_doc_id_no_html` | Non-URL `doc_id` rendered as plain text |

---

## Future coverage

Items not yet implemented — candidates for future test sprints:

| Area | Description |
|---|---|
| `Thread.chat()` tool_choice body | Verify `tool_choice` dict is sent correctly in the run request body. |
| `Thread.chat()` permission_decisions body | Verify `permission_decisions` content items are sent in the user message. |
| Thread `update` 404 | `threads.update()` on a non-existent thread raises `ThreadNotFoundError`. |
| Mock-based AppTest for CI | `tests/live/test_streamlit_live.py` covers the render pipeline but needs live credentials. A mock-driven AppTest over `examples/demo/mock_thread.py` would give the same structural coverage in CI. |

> `CortexAgentChat` AppTest integration was previously listed here. It is now implemented in
> `tests/live/test_streamlit_live.py`. It was worth the complexity: the first run surfaced a
> real defect in `_markdown_column_config` that no mock-based test could reach.

---

## Live tests (`tests/live/`)

Marked `@pytest.mark.live`. Deselected by default via `addopts = "--tb=short -m 'not live'"`
in `pyproject.toml`, regardless of whether the env vars are set, so a bare `pytest` never
reaches the network. Run them with `-m live`, which overrides the default; individual tests
still skip if their required env vars are absent.
See [`tests/live/README.md`](../../tests/live/README.md) for setup instructions.

### Environment variables

| Variable | Required for | Description |
|---|---|---|
| `SNOWFLAKE_ACCOUNT_URL` | All | `https://myorg-myaccount.snowflakecomputing.com` |
| `SNOWFLAKE_PAT` | All | PAT token |
| `LIVE_AGENT_MINIMAL` | All | Fully-qualified path to the minimal agent |
| `LIVE_AGENT_FULL` | `test_runs_full.py` | Fully-qualified path to the Cortex Search agent |
| `LIVE_AGENT_ANALYST` | `test_runs_analyst.py` | Fully-qualified path to the Cortex Analyst agent |
| `LIVE_AGENT_WEB` | `test_runs_web.py` | Fully-qualified path to the web search agent (requires account-level web search enabled) |
| `LIVE_AGENT_MULTITENANCY` | `test_runs_multitenancy.py` | Fully-qualified path to the multi-tenancy agent created by `seed/07_multitenancy.sql` |
| `LIVE_APPTEST_AGENT` | `test_streamlit_live.py` | Set automatically by `test_streamlit_live.py` to point the AppTest app at a non-default agent; falls back to `LIVE_AGENT_MINIMAL`. Not intended to be set by hand |
| `LIVE_SKIP_TEARDOWN` | Optional | Set to `1` to skip teardown. **Teardown drops `CAC_LIVE_DB`**, so set this unless you intend that |
| `LIVE_TIMEOUT` | Optional | Client read timeout in seconds (default 120; `test_streamlit_live.py` defaults to 180) |
| `LIVE_SLOW` | Optional | Set to `1` to run the ~6-minute run-expiry test in `test_runs_async.py`, which is otherwise skipped |
| `LIVE_DUMP_EVENTS` | Optional | Set to `1` to always write captured SSE events to `captures/<test_name>.json`, not just on failure |

### `tests/live/test_auth.py`

| Test | Description |
|---|---|
| `test_valid_pat_allows_agent_list` | Valid PAT — `agents.list()` succeeds |
| `test_invalid_token_raises_auth_error` | Bad token → `AuthError` |
| `test_nonexistent_agent_raises_agent_not_found` | Missing agent path → `AgentNotFoundError` |

### `tests/live/test_threads.py`

| Test | Description |
|---|---|
| `test_create_returns_metadata_with_thread_id` | `threads.create()` returns `ThreadMetadata` with `thread_id > 0` |
| `test_get_thread_returns_correct_id` | `threads.get(id)` returns the same `thread_id` |
| `test_get_nonexistent_thread_raises_not_found` | Non-existent id → `ThreadNotFoundError` |
| `test_list_with_origin_filter_returns_own_threads` | `threads.list(origin_application=...)` includes test thread |
| `test_delete_removes_thread` | After delete, `get()` raises `ThreadNotFoundError` |
| `test_fork_creates_new_thread` | `thread.fork(at_message_id=N)` returns a Thread with same `thread_id` but `parent_message_id == N` |
| `test_latest_context_returns_list` | `latest_context()` returns a list on a fresh thread |
| `test_latest_context_after_chat_contains_messages` | After one chat turn, at least 2 messages in context |

### `tests/live/test_runs.py` (minimal agent)

| Test | Description |
|---|---|
| `test_streaming_yields_text_delta_events` | At least one `TextDeltaEvent` per turn |
| `test_streaming_last_event_is_response_event_completed` | Final event is `ResponseEvent(status='completed')` |
| `test_streaming_yields_text_event` | Non-empty `TextEvent` is emitted |
| `test_streaming_emits_metadata_events_for_user_and_assistant` | Both user and assistant `MetadataEvent`s present |
| `test_streaming_response_contains_token_usage` | `ResponseEvent.usage` has non-zero total tokens |
| `test_run_returns_result_with_text` | `client.run()` returns `RunResult` with non-empty text |
| `test_run_result_status_completed` | `RunResult.status == 'completed'` |
| `test_second_turn_succeeds` | Second `thread.chat()` produces `TextDeltaEvent`s |
| `test_parent_message_id_advances` | `parent_message_id` increments after each turn |

### `tests/live/test_runs_full.py` (Cortex Search agent)

| Test | Description |
|---|---|
| `test_tool_use_event_is_emitted` | `ToolUseEvent` with `type='cortex_search'` is yielded |
| `test_tool_result_event_follows_tool_use` | Every `tool_use_id` has a matching `ToolResultEvent` |
| `test_tool_result_status_is_success` | All `ToolResultEvent.status == 'success'` |
| `test_text_annotation_events_are_emitted` | At least one `TextAnnotationEvent` per search query |
| `test_annotation_has_doc_id_and_title` | Each annotation has non-empty `doc_id` and `doc_title` |
| `test_response_event_completed` | Final `ResponseEvent(status='completed')` |
| `test_text_is_non_empty` | Assembled text from deltas is non-empty |

---

### `tests/live/test_runs_async.py` (async run lifecycle)

Covers the v0.2.0 async surface. Requires `LIVE_AGENT_MINIMAL`.

| Class | Tests | What it verifies |
|---|---|---|
| `TestBackgroundRun` | `test_background_run_returns_usable_run_id`, `test_background_run_status_is_recognised` | `background=True` returns a `run_id` of the form `{thread_id}-{user_message_id}` |
| `TestThreadChatBackground` | `test_background_chat_yields_text_and_advances_parent`, `test_background_chat_supports_a_second_turn` | `Thread.chat(background=True)` still yields text and advances the parent message id across turns |
| `TestStreamRun` | `test_stream_run_yields_the_answer`, `test_starting_after_truncates_the_replay`, `test_events_expose_sequence_number_for_the_cursor`, `test_events_are_typed_not_unknown` | Reconnecting with `stream_run` replays the run; `starting_after` truncates the replay; every event carries `sequence_number`; no event degrades to `UnknownEvent` (the `[DONE]` regression guard) |
| `TestCancelRun` | `test_cancel_active_run_returns_metadata`, `test_cancel_finished_run_raises_run_not_active` | `cancel_run` returns `RunMetadata`; cancelling a finished run raises `RunNotActiveError` (409) |
| `TestLiteRunModelConfig` | `test_lite_run_with_models_object`, `test_models_orchestration_is_read_by_the_server`, `test_lite_run_with_orchestration_budget`, `test_deprecated_model_alias_still_reaches_server` | The server parses `models.orchestration` — proved by an invalid model name being echoed back in the error |
| `TestRoleHeader` | `test_valid_role_succeeds`, `test_nonexistent_role_is_rejected` | `X-Snowflake-Role` is honoured end to end |
| `TestRunExpiryWindow` | `test_stream_run_after_window` | **`xfail`** — gated behind `LIVE_SLOW=1`. The documented 5-minute expiry window was **not** enforced on the test account: the run remained streamable at 5.5 minutes. Do not rely on a 409 here. See `docs/api_spec.md`. |

---

### `tests/live/test_agents.py` (agent object CRUD)

| Class | Tests | What it verifies |
|---|---|---|
| `TestAgentLifecycle` | `test_create_then_get`, `test_update_changes_the_spec`, `test_list_finds_the_agent_with_like_filter`, `test_delete_removes_the_agent` | Full create/get/update/list/delete round trip |
| `TestCreateMode` | `test_create_twice_raises_by_default`, `test_or_replace_succeeds_on_existing` | `createMode` semantics |
| `TestDeleteIfExists` | `test_delete_missing_with_if_exists_succeeds`, `test_delete_missing_without_if_exists_raises` | `ifExists` on delete |
| `TestFeedback` | `test_agent_level_feedback_accepted`, `test_request_level_feedback_accepted` | Both `:feedback` forms are accepted |

Agents created here are named with a `cac_live` prefix; `seed/cleanup_leaked_agents.py` sweeps any left behind by an interrupted run.

---

### `tests/live/test_streamlit_live.py` (AppTest against a live agent)

Drives `apps/live_chat_app.py` through `streamlit.testing.v1.AppTest`. Honours `LIVE_APPTEST_AGENT`; `LIVE_TIMEOUT` defaults to 180 here.

| Class | Tests | What it verifies |
|---|---|---|
| `TestAppLoads` | `test_initial_render_succeeds`, `test_chat_input_is_present` | App renders without exception and exposes a chat input |
| `TestLiveTurn` | `test_turn_renders_assistant_text`, `test_turn_renders_no_parse_error_text`, `test_second_turn_replays_history` | A real turn renders assistant text; **no `_parse_error` leaks into the UI** (the `[DONE]` regression guard at the render layer); history replays on the second turn |
| `TestAnalystTableRendering` | `test_analyst_turn_renders_dataframe` | An Analyst turn renders a non-empty dataframe — this is the test that surfaced the pandas `StringDtype` column-config defect |

### `tests/live/test_runs_analyst.py` (Cortex Analyst agent)

| Test | Description |
|---|---|
| `test_tool_use_event_is_emitted` | At least one `ToolUseEvent` whose `type` is in `{'system_execute_sql', 'system_agentic_semantic_context'}` |
| `test_tool_result_event_follows_tool_use` | Every `tool_use_id` has a matching `ToolResultEvent` |
| `test_system_execute_sql_contains_sql` | A `system_execute_sql` `ToolUseEvent` carries non-empty `input['sql']` referencing `REVENUE` or `SALES` |
| `test_verified_query_used` | At least one `system_execute_sql` event sets `input['verified_query_used']` |
| `test_response_event_completed` | Final `ResponseEvent(status='completed')` |
| `test_text_is_non_empty` | Assembled text from deltas is non-empty |

> **Note on tool types.** Agentic Cortex Analyst (Apr 2026+) emits
> `system_execute_sql` / `system_agentic_semantic_context` as the *runtime event*
> type, and the generated SQL arrives on `ToolUseEvent.input['sql']` — there is no
> `AnalystDeltaEvent` in this flow. The `cortex_analyst_text_to_sql` string that
> still appears in `seed/05_analyst_agent.sql` is the *agent-definition* tool type,
> which is a separate namespace. See `docs/api_spec.md`.

### `tests/live/test_runs_web.py` (web search agent)

| Test | Description |
|---|---|
| `test_tool_use_event_is_emitted` | `ToolUseEvent` with `type='web_search'` is yielded |
| `test_tool_result_event_follows_tool_use` | Every `tool_use_id` has a matching `ToolResultEvent` |
| `test_tool_result_status_is_success` | All `ToolResultEvent.status == 'success'` |
| `test_response_event_completed` | Final `ResponseEvent(status='completed')` |
| `test_text_is_non_empty` | Assembled text from deltas is non-empty |

---

### `tests/live/test_runs_multitenancy.py` (multi-tenancy session attributes)

Requires `LIVE_AGENT_MULTITENANCY`. Seeded by `seed/07_multitenancy.sql`, which creates a
dedicated table, attaches a row access policy reading
`SYS_CONTEXT('SNOWFLAKE$SESSION_ATTRIBUTES', 'tenant_region')`, and builds an agent over it.
The policy is attached only to the seeded table, never to a pre-existing one.

#### `TestTenantIsolation`

| Test | Description |
|---|---|
| `test_no_variables_returns_no_rows` | Fail-closed: with no `variables`, the attribute is NULL and the policy returns zero rows |
| `test_tenant_sees_only_own_region` | Shorthand `variables={"tenant_region": "North"}` returns only that region's rows |
| `test_full_rest_form_scopes_run` | The full `{value, type, is_immutable_session_attribute}` form scopes the run identically |
| `test_numeric_attribute_accepted` | `type: "number"` is accepted by the API and scopes the run |

#### `TestScopePersistsAcrossRequests`

| Test | Description |
|---|---|
| `test_second_turn_on_same_thread_still_scoped` | A second turn on the same thread stays scoped to the same tenant |
| `test_background_run_resumed_keeps_scope` | Attributes survive a `stream_run` reconnect to a background run |
