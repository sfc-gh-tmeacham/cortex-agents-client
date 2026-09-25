# Roadmap

Planned features and known limitations for `streamlit_cortex_agents`.

---

## Planned

Items with a detailed implementation plan, ready to build.

---

### Per-viewer thread isolation in SiS (container runtime)

#### Current state

In a SiS container runtime app using owner's rights (the default), all Cortex Agents API
calls run as the **app owner**. Threads are owned by the app owner's identity, so
`GET /api/v2/cortex/agents/threads` returns every thread created by every viewer of the
app in the same flat namespace.

For ephemeral (single-session) use, this is already fine — `sis_init_session()` stores
the thread in `st.session_state`, which Streamlit isolates per browser session. The
problem arises when threads need to persist across sessions: there is no built-in way to
associate a stored `thread_id` with the viewer who created it.

#### Viewer identity

`st.context.user.login_name` provides the viewer's Snowflake login name at the HTTP
session level, even in owner's rights mode (it reads from the request, not the Snowflake
token). This can be used as a stable key to store and look up per-viewer thread IDs.

#### Proposed implementation: `sis_init_session_per_viewer()`

A new `sis_init_session_per_viewer()` session helper in `streamlit_cortex_agents/st/session.py`
that wraps `sis_init_session()` and adds automatic per-viewer thread persistence:

1. On first call for a given viewer + `session_key_prefix`:
   - Query a metadata table (`thread_store_table`) for an existing `thread_id` belonging to this viewer.
   - If found, call `client.get_thread(thread_id)` to resume.
   - If not found, call `client.create_thread()` and insert the new `thread_id` into the metadata table.
2. On subsequent Streamlit reruns (same browser session): return the cached objects from `st.session_state` as normal.

**Signature (proposed):**

```python
def sis_init_session_per_viewer(
    agent_path: str,
    *,
    thread_store_table: str,        # fully-qualified: "DB.SCHEMA.TABLE"
    viewer_key: str | None = None,  # defaults to st.context.user.login_name
    origin_application: str | None = None,
    session_key_prefix: str = "_ca",
    **kwargs,
) -> tuple[CortexAgentsClient, Thread]:
    ...
```

**Metadata table DDL:**

```sql
CREATE HYBRID TABLE IF NOT EXISTS my_db.my_schema.agent_threads (
    viewer_login    VARCHAR       NOT NULL COMMENT 'Snowflake login name of the app viewer (st.context.user.login_name)',
    app_name        VARCHAR       NOT NULL COMMENT 'Application identifier — use the origin_application value or a hardcoded app name',
    thread_id       VARCHAR       NOT NULL COMMENT 'Cortex Agents thread ID returned by client.create_thread()',
    created_at      TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP() COMMENT 'UTC timestamp when the thread was first created for this viewer',
    PRIMARY KEY (viewer_login, app_name)
)
COMMENT = 'Per-viewer Cortex Agents thread registry. Maps each (viewer, app) pair to a persistent thread ID so conversations can be resumed across browser sessions.';
```

The table is queried and written using the owner's rights SQL connection
(`st.connection("snowflake")`), which already has the necessary privileges.

#### `origin_application` as a soft namespace (interim)

Until this helper is implemented, use `origin_application=f"app_{st.context.user.login_name}"`
(truncated to 16 bytes) when calling `sis_init_session()`. This tags each thread with the
viewer's identity and allows filtering by that tag when listing threads. It does not provide
hard isolation — the owner can still list all threads — but it gives functional separation
for most use cases.

#### Files to create / modify

- `streamlit_cortex_agents/st/session.py` — add `sis_init_session_per_viewer()`
- `streamlit_cortex_agents/st/__init__.py` — export new function
- `tests/streamlit/test_session.py` — add tests covering first-visit, resume, and rerun paths

---

### File and audio attachment support

#### Current state

`StreamlitChatbot` accepts `accept_file`, `accept_audio`, and `file_type` parameters
that enable the corresponding controls on `st.chat_input` (Streamlit ≥ 1.59). When a
user uploads a file or records audio, those attachments are:

- Displayed in the user's chat bubble (`st.image`, `st.audio`, `st.write`)
- Stored in `StoredMessage.attachments` so they survive Streamlit reruns

**The file and audio content is not forwarded to the agent.** Only the typed text
portion of the prompt reaches `thread.chat()`. See the inline comment in
`chatbot.py::_process_prompt` for the code-level note.

#### Why

The Cortex Agents Run API's `MessageContentItem` schema currently only defines `text`
as a valid user-input content type. There is no `image`, `document`, or `audio` content
type for user messages in the public REST API.

#### How Snowflake CoWork does it

Snowflake CoWork supports pasting and uploading files (CSV, JSON, PDF, PPTX, TXT, XLSX,
images) despite using the same Cortex Agents backend. It does this by adding a
**two-step preprocessing flow** that the public REST API doesn't expose inline:

1. The file is automatically uploaded to the user's personal Snowflake internal stage.
2. The agent message then references the staged file — either via a `document` content
   type (not yet in the public schema) or by pre-processing the document into text
   context before the API call.

This is consistent with how all Snowflake Cortex AI multimodal functions work: files
must live on a Snowflake stage and are referenced via `TO_FILE('@stage', 'file.pdf')`.
Raw binary is never sent inline in the chat API.

Reference: [Snowflake CoWork — Zero-setup file upload](https://docs.snowflake.com/en/user-guide/snowflake-cortex/snowflake-cowork)

#### What needs to be built

To reach feature-parity with CoWork, two things are required:

1. **Stage upload helper** — PUT the uploaded file to a Snowflake user stage via the
   Snowflake Files REST API (`/api/v2/databases/.../stages/.../files` or equivalent).
   CoWork targets the user's personal stage (`~/uploads/...`). The library would need
   an auth-aware upload utility that works with `PATAuth`, `OAuthAuth`, and
   `SiSContainerAuth`.

2. **File content item wiring** — Once the file is staged, pass its stage path to the
   agent via `Thread.chat(extra_content=[...])`. The exact content item schema (e.g.
   `{"type": "document", "stage_path": "@~/uploads/file.pdf"}`) is not yet documented
   in the public API; it will need to be confirmed once Snowflake publishes the schema
   or the feature becomes generally available.

The UI plumbing is already in place: `accept_file`/`accept_audio` capture the
`UploadedFile` objects, `StoredMessage.attachments` persists them across reruns, and
`Thread.chat` has the `extra_content` parameter ready to receive additional content
items. Only the upload + wiring step is missing.

#### Supported file types (CoWork reference)

| Type      | Formats                            | Max size                     |
|-----------|------------------------------------|------------------------------|
| Documents | CSV, JSON, PDF, PPTX, TXT, XLSX    | 50 MB each, up to 5 files    |
| Images    | JPEG, PNG, WEBP, GIF               | Model-dependent (3.75–10 MB) |
| Audio     | WAV, MP3, FLAC, AAC, OGG, M4A      | Model-dependent              |

---

### Cancel in-progress streaming request

**Status: implemented in 0.3.0** without the concurrency designs below. `StreamlitChatbot`
uses `st.chat_input(submit_mode="stop")`; pressing stop raises `StopException` at the next
streamed event, and `_stream_with_retry` catches it, calls `cancel_run(run_id)`, and
re-raises. See "Stopping a response" in `docs/streamlit_guide.md`. The rest of this section
is the design history from before that approach was found. Still open: a live check that
cancelling a non-background streaming run works, and stop for pill-selected runs.

#### Current state

Server-side cancellation now exists in the library: `client.cancel_run(run_id)` calls
`POST /api/v2/cortex/agent/runs/{run_id}/cancel`, which stops the run and saves any partial
output to the thread. That is verified live.

What is still missing is the **Streamlit UX**. Once a user submits a prompt,
`render_streaming_response` loops synchronously on the main Streamlit thread. There is no
stop button and no running-state flag in session state, so the user has no way to trigger the
cancel that the API now supports.

The `run_id` needed for the call is available during streaming from any
`MetadataEvent.run_id`, so no additional plumbing is required to obtain it.

#### Why it's non-trivial

Streamlit is not thread-safe — all `st.*` / `container.*` calls must remain on the
main thread. The `render_streaming_response` loop makes UI calls on every event, so
it cannot simply be moved to a background thread.

The deeper problem is that Streamlit's execution model gives a synchronous script no
way to observe a click. Widget interactions are only processed on a rerun, but the
script is blocked inside the streaming loop for the whole duration of the response —
precisely the window in which the user wants to press Stop. So a Stop button is not an
additive change to the render loop; it requires inverting that loop's control flow.
Every viable design therefore has to introduce concurrency (a queue plus a background
drainer) or move the cancel trigger outside the script run entirely.

Consequences that make this more than a refactor:

- `render_streaming_response` is public API. Splitting it into an IO drainer and a UI
  renderer changes its internal contract, and it is exercised by both `StreamlitChatbot`
  render paths plus the AppTest suite.
- The drainer thread has no `ScriptRunContext`, so any accidental `st.*` call inside it
  fails at runtime rather than at import time — an easy defect to introduce and a hard
  one to catch without live AppTest coverage.
- `@st.fragment` reruns interact with session-state mutation ordering; partial output must
  be committed to `StoredMessage` history in a way that survives a mid-stream rerun.
- Cancellation is two operations that can each fail independently (close the connection,
  then `cancel_run`). A partial failure silently leaves a billed run executing server-side.

#### Alternatives considered

**Custom HTTP route via `st.App` (Streamlit ≥1.57).** `st.App` exposes a Starlette ASGI
app, so a `/cancel` route could call `cancel_run` outside the script run, sidestepping the
rerun problem entirely. Verified in the installed Streamlit source: `streamlit run`
*does* support this — `_main_run` calls `discover_asgi_app()` and, on finding a
module-level `st.App`/`FastAPI`/`Starlette` assignment via AST analysis, serves it under
uvicorn instead of `bootstrap.run()`. Also verified that `ScriptRunner.start` runs scripts
on a separate thread, so the ASGI event loop stays responsive during a script run.

Why it is not currently a path forward:

- **Warehouse runtime: ruled out.** It pins Streamlit ≤1.52.2; `st.App` landed in 1.57.
- **Container runtime: unverified.** It permits any Streamlit ≥1.50, so the version is
  attainable, but whether Snowflake's launcher performs ASGI discovery is undocumented
  and has not been tested. Do not assume either way without deploying a probe.
- **CSP.** Even where the route is served, driving it from the browser needs an inline
  `fetch()`, which the documented SiS Content-Security-Policy blocks. This constraint is
  independent of the two above and applies to every runtime.

**Background runs (`background=True`) as the transport.** Submitting the run detached and
reattaching with `stream_run(starting_after=N)` makes the run survive a rerun, which is
appealing: Stop could then be an ordinary button on a normal rerun. Not pursued yet, but
this is the most promising direction, since it needs no threads and no ASGI route. The open
question is reattach latency per rerun and how to render smoothly across the cursor.

#### Proposed approach

Split streaming into two responsibilities separated by a `queue.Queue`:

1. **Background thread** — drains the raw SSE iterator (`thread.chat(...)`) and puts
   events onto the queue. Checks a `threading.Event` stop flag on each iteration;
   calls `events_iter.close()` when set to synchronously abort the underlying `httpx`
   TCP connection (leaving this to GC is not guaranteed to be immediate).

2. **Main Streamlit thread** — reads from the queue and performs all `st.*` UI calls.
   Renders a "Stop" button that sets the stop flag.

The stop handler should also call `client.cancel_run(run_id)`. Closing the HTTP connection
only stops the client reading; without the cancel the run keeps executing server-side and is
still billed.

To make the Stop button interactive *during* streaming (Streamlit only processes clicks
on a full rerun), wrap the streaming UI in `@st.fragment` so the fragment can rerun
independently while the background thread drains the HTTP connection.

#### Key constraints

- All `st.*` / `container.*` calls must stay on the main thread.
- `events_iter.close()` must be called explicitly — not left to GC.
- Closing the connection is not cancellation; call `cancel_run` as well or the run continues
  to completion and is billed.
- `render_streaming_response` would need to be refactored into a pure-IO drainer and a
  pure-UI renderer with a queue between them.
- `st.fragment` is needed to make the Stop button interactive during streaming.
- The drainer thread has no `ScriptRunContext`; it must contain no `st.*` calls.
- SiS CSP blocks inline `fetch()`, so no browser-driven custom-route design will work there.

#### Files to modify

`streamlit_cortex_agents/st/render.py`, `streamlit_cortex_agents/st/chatbot.py`

---

## Backlog

Items identified but not yet specced out.

- **Image pasting** — CoWork supports pasting images directly from the clipboard; this
  would follow the same stage-upload pattern as file attachments.
- **Voice-to-text preview** — Show a transcript of recorded audio in the user bubble
  before sending (requires client-side transcription or a round-trip to `AI_TRANSCRIBE`).
- **Attachment size validation** — Surface a clear error when an uploaded file exceeds
  the per-model size limit before the API call is made.

---

## Completed

### Multi-tenancy session attributes

**Status: implemented, unreleased** (on `main` after 0.3.0; see the CHANGELOG's Unreleased
section). Optional `variables` on every run entry
point, sent as the `agent:run` `variables` block, so one agent can serve several tenants
with row access policies enforcing the boundary. Accepts shorthand scalars or the REST
shape; both default to immutable. `Thread.chat` sends them on client-side tool-loop
follow-ups, and `StreamlitChatbot` takes a mapping or a per-prompt callable.

Verified live against a row access policy: two tenants saw disjoint rows, a second turn on
one thread stayed scoped, a resumed background run stayed scoped, and a request with no
attribute returned nothing rather than everything. See
[api_spec.md](api_spec.md#request-body) for the findings that are not in the public doc.

### API-consistency improvements

All four items below were implemented and are no longer deferred.

- **`PermissionError` / `TimeoutError` → `CortexPermissionError` / `CortexTimeoutError`** —
  Renamed to avoid shadowing Python builtins. Deprecated aliases kept for a transition window.
- **`NotFoundError` base class** — Added as intermediate base for `AgentNotFoundError` and
  `ThreadNotFoundError`. Callers can now write `except NotFoundError`.
- **`Thread.get_history` → `Thread.list_messages`** — Renamed for parity with
  `ThreadsResource.list_messages()`. `Thread.latest_context()` also added.
  `get_history()` kept as a deprecated alias emitting `DeprecationWarning`.
- **`RunResult.thinking: str | None = None`** — Standardised on `None` to match
  `StoredMessage.thinking`. Accumulation logic updated in `_parse_non_streaming_response`
  and `stream_and_collect`.
