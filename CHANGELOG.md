# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Documentation

- Corrected the Cortex Analyst live-test documentation in `docs/test_plan.md` and
  `tests/live/README.md`. It cited a `test_analyst_delta_event_contains_sql` test and three
  `test_table_event_*` tests that do not exist, and named the runtime tool type as
  `cortex_analyst_text_to_sql` rather than `system_execute_sql` /
  `system_agentic_semantic_context`. Added a note distinguishing the runtime event type from
  the agent-definition tool type, which legitimately still uses the older string.
- Documented the previously missing test surface in `docs/test_plan.md`: `tests/unit/test_http.py`
  (including the 409 mapping matrix), `tests/unit/test_exceptions.py`, the `[DONE]` sentinel
  tests, the integration `TestStreamRun` / `TestCancelRun` classes, and the three live files
  `test_runs_async.py`, `test_agents.py`, `test_streamlit_live.py`. Added the four undocumented
  live environment variables plus `LIVE_DUMP_EVENTS`.
- Corrected stale test totals (239 → 339) in `docs/test_plan.md` and `COCO.md`, and removed the
  unqualified accuracy claim in the `docs/test_plan.md` header.
- Fixed `COCO.md`, which described the pre-0.2.0 `select_dtypes(include="object")` column
  selection as current behaviour, and added `ConflictError`, `RunNotActiveError` and
  `CortexConnectionError` to its `exceptions.py` inventory. Added `stream_run` / `cancel_run`
  to the `RunsResource` descriptions in `COCO.md` and `README.md`.

## [0.2.0] — 2026-08-27

### Added

- Background runs: `background=True` on `runs.run()`, `runs.stream()`, and `Thread.chat()`
  raises the run timeout from 15 minutes to 6 hours. Requires a thread.
- `runs.stream_run(run_id, starting_after=...)` and `client.stream_run(...)` — reconnect to an
  active or recently finished run (`GET /api/v2/cortex/agent/runs/{run_id}`).
- `runs.cancel_run(run_id)` and `client.cancel_run(...)` — cancel an active run
  (`POST /api/v2/cortex/agent/runs/{run_id}/cancel`).
- `RunMetadata` model carrying `run_id`, `thread_id`, `user_message_id`,
  `assistant_message_id`, and token `usage`. Exposed as `RunResult.metadata`, with
  `RunResult.run_id` as a shortcut. Previously the non-streaming response `metadata` block
  was discarded.
- `orchestration=` argument on lite runs, for budget constraints
  (`{"budget": {"seconds": 30, "tokens": 16000}}`).
- `SSEEvent.sequence_number`, populated on every event type. This is the cursor
  value consumed by `stream_run(starting_after=...)`; without it a caller had no
  way to resume from a known position. Found during live verification.
- `role=` argument on `CortexAgentsClient` and `HttpClient`, sent as `X-Snowflake-Role`.
  `HttpClient.request()` and `HttpClient.stream()` also accept a per-call `headers` dict.
- `ConflictError` and `RunNotActiveError` for HTTP 409. `RunNotActiveError` is raised when a
  run is streamed or cancelled outside its 5-minute post-completion window.

### Fixed

- Lite runs sent a bare top-level `"model"` string, which is the pre-September-2025 API schema.
  The body now sends `"models": {"orchestration": ...}`, matching `AgentsResource` and the
  current spec. `docs/api_spec.md` documented the legacy field and has been corrected.
- Every stream ended with a spurious `UnknownEvent(event_type="_parse_error")` and a
  `WARNING` log entry. The server terminates all streams — both `agent:run` and
  `agent/runs/{run_id}` — with `event: done` / `data: [DONE]`, which is not JSON.
  `parse_sse_stream` now treats that sentinel as end-of-stream. This affected every
  consumer of the library, including the Streamlit renderer, on every turn. The
  behaviour is not described in the public API docs; it was found by live testing.
- Table columns with an explicit pandas `StringDtype` were not configured as Markdown
  columns, so Markdown in those cells rendered as literal text. `_markdown_column_config`
  used `select_dtypes(include="object")`, which misses `StringDtype` and additionally
  emits a `Pandas4Warning` — under pandas 3 the `"object"` selector no longer implies
  `"str"`, which would have silently broken all text columns. Found by running the real
  render pipeline against a live Analyst answer.


### Deprecated

- The `model=` argument on `runs.run()` and `runs.stream()`. Pass
  `models={"orchestration": "claude-4-sonnet"}` instead. `model=` still works, maps into
  `models`, and emits a `DeprecationWarning`.

## [0.1.0] — 2025-06-01

### Added

- Initial release of `cortex-agents-client`.
- `CortexAgentsClient` with PAT, JWT, OAuth, and SiS container auth providers.
- Agent CRUD operations (`create`, `get`, `update`, `list`, `delete`, `feedback`).
- Thread lifecycle management (`create`, `get`, `update`, `list`, `delete`).
- Streaming and non-streaming agent run invocations.
- Full SSE event parsing with 17 typed event dataclasses.
- `Thread` class with automatic `parent_message_id` tracking.
- `RunResult` dataclass for non-streaming and `stream_and_collect` results.
- Streamlit integration layer (`StreamlitChatbot`, `render_streaming_response`).
- Embedded and fullpage chat layout modes.
- Client-side tool execution with `tool_executor` callback.
- Compaction-aware `latest_context` for long conversations.
- Typed exception hierarchy with HTTP status code mapping.
