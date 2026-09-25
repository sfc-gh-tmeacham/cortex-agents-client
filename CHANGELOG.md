# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (Streamlit UI)

- Tool calls render as a connected `type="step"` timeline, live and on history replay,
  instead of separate compact status boxes.
- The chat input's send button becomes a stop button while a response streams
  (`submit_mode="stop"`). A stopped turn keeps the user's message without an answer, and
  the thread stays on its last completed message. Stop ends the Streamlit script only: the
  agent run keeps executing in Snowflake and is billed until it finishes.
- Suggested questions render as native `st.pills` instead of tertiary buttons styled with
  injected CSS. Selecting one clears the pill, so the same suggestion can be picked again.

### Fixed

- `Thread.chat()` client-side tools now complete against the live API. Three changes were
  needed, verified end to end on a live account:
  - The follow-up sends only the `tool_result`, not the user's text and attachments again.
  - The `tool_result` carries `type` and `name`; without them the server rejects it.
  - The loop reads the stream to the end so it picks up the assistant `message_id` that
    follows the tool request. Previously the follow-up went out with the stale
    `parent_message_id`, and the agent re-requested the tool until the 20-iteration cap.
- An HTTP error whose JSON body is not an object (a bare string, list, number, or `null`)
  now raises the typed exception instead of `AttributeError`.
- Suggestion button widget keys derive from `suggestion_key`, so two chatbots on one page no
  longer raise `DuplicateWidgetID`.
- The verified-query badge now appears for `system_execute_sql` tool uses that report
  `verified_query_used`, which is how the current Cortex Analyst API signals it.
- `StoredMessage.text` holds every text segment of a response, not only the last one.
- `runs.stream_and_collect()` assembles text and thinking per `content_index`, so a block that
  receives only deltas is no longer dropped when another block has a summary event.
- `threads.list()` and `agents.list()` log a warning when the response is not a list.
- Docs: `JWTAuth` example uses `private_key_path`; `docs/test_plan.md` names `HttpClient`; the
  README no longer calls the event classes frozen. The demo's dialog snippet defines
  `@st.dialog` outside the button branch.

- `tests/live/seed/cleanup_leaked_threads.py` failed with `SyntaxError` on line 1 because its
  header used SQL `--` comments. It is now a Python docstring.

### Added

- `py.typed` marker, so type checkers see the package's annotations.
- `cortex_agents_client.__version__`, read from the installed package metadata.
- CI workflow running ruff, mypy, and the offline test suite on Python 3.11 and 3.12.
- ruff and mypy configuration, and both tools in the `dev` extra.
- Tests for SiS token-file errors after construction, stream connection errors, and
  `sis_init_session`.

### Changed

- `httpx` is bounded below 1.0.
- The `streamlit` extra requires Streamlit 1.64 or later. Charts and tables pass
  `width="stretch"` instead of the deprecated `use_container_width=True`.
- `PATAuth`, `OAuthAuth`, and a plain-string `auth` raise `ValueError` for an empty or
  whitespace-only token. Previously the client failed on the first request with
  `Illegal header value b'Bearer '`.
- Passing both `agent_path` and `agent` raises `ValueError`. Previously `agent` was ignored.
- `background=True` without a `thread_id` raises `ValueError` before the request is sent.
- The deprecated `PermissionError` and `TimeoutError` aliases are no longer in `__all__`, so
  `from cortex_agents_client import *` does not shadow the builtins. They remain importable
  by name.

## [0.2.1] — 2026-08-28

### Documentation

- `README.md` now points to `docs/event_types.md` from the end of the "Handling all event
  types" section, and states explicitly that the 18 classes listed there are the complete set.
  The README documents the Python classes but not the wire `event_type` strings, and it
  previously contained no link to the reference that does — so a reader matching a raw SSE
  frame to a class, or inspecting `UnknownEvent.event_type`, had no signpost. Verified that
  the README example imports and branches on all 17 registered event classes plus
  `UnknownEvent`, and that `docs/event_types.md` covers all 17 wire types.

## [0.2.0] — 2026-08-28

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

### Changed

- Live tests are now deselected by default: `addopts` in `pyproject.toml` is
  `"--tb=short -m 'not live'"`. Previously `testpaths = ["tests"]` collected the live suite,
  so a bare `pytest` run by a developer who happened to have the live env vars set would
  silently reach the network and spend credits. A bare run now behaves identically whether or
  not credentials are present. Select live tests explicitly with `-m live`, which overrides
  the default; individual tests still skip when their own env vars are absent.

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
- Fixed `COCO.md`, which described the pre-fix `select_dtypes(include="object")` column
  selection as current behaviour, and added `ConflictError`, `RunNotActiveError` and
  `CortexConnectionError` to its `exceptions.py` inventory. Added `stream_run` / `cancel_run`
  to the `RunsResource` descriptions in `COCO.md` and `README.md`.
- Expanded the "Cancel in-progress streaming request" roadmap item with the obstacles that
  caused the Streamlit stop-button work to be set aside, and recorded two alternatives: a
  custom route via `st.App` (`streamlit run` does support ASGI discovery, but the warehouse
  runtime is too old, container-runtime support is unverified, and SiS CSP blocks the inline
  `fetch()` it needs) and background runs as the transport.
- Added a "no stop button" limitation section to `docs/streamlit_guide.md`, noting that
  cancellation exists in the core client but is not wired into the `st` layer.
- Added the terminal `event: done` / `data: [DONE]` frame to the streaming example in
  `docs/event_types.md`, which previously ended at `event: response` despite the document
  stating elsewhere that every stream ends with that frame.
- Noted in the `RunNotActiveError` and `stream_run` docstrings that the documented 5-minute run
  expiry window was not enforced in live testing and should be treated as a lower bound.

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
