# Roadmap

Planned features and known limitations for `cortex_agents_client`.

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

A new `sis_init_session_per_viewer()` session helper in `cortex_agents_client/st/session.py`
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
CREATE TABLE IF NOT EXISTS my_db.my_schema.agent_threads (
    viewer_login    VARCHAR       NOT NULL,
    app_name        VARCHAR       NOT NULL,
    thread_id       VARCHAR       NOT NULL,
    created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (viewer_login, app_name)
);
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

- `cortex_agents_client/st/session.py` — add `sis_init_session_per_viewer()`
- `cortex_agents_client/st/__init__.py` — export new function
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

#### Current state

Once a user submits a prompt, the streaming response runs to completion with no way to
interrupt it. `render_streaming_response` loops synchronously on the main Streamlit
thread. There is no stop button, no cancellation token, and no running-state flag in
session state.

#### Why it's non-trivial

Streamlit is not thread-safe — all `st.*` / `container.*` calls must remain on the
main thread. The `render_streaming_response` loop makes UI calls on every event, so
it cannot simply be moved to a background thread.

#### Proposed approach

Split streaming into two responsibilities separated by a `queue.Queue`:

1. **Background thread** — drains the raw SSE iterator (`thread.chat(...)`) and puts
   events onto the queue. Checks a `threading.Event` stop flag on each iteration;
   calls `events_iter.close()` when set to synchronously abort the underlying `httpx`
   TCP connection (leaving this to GC is not guaranteed to be immediate).

2. **Main Streamlit thread** — reads from the queue and performs all `st.*` UI calls.
   Renders a "Stop" button that sets the stop flag.

To make the Stop button interactive *during* streaming (Streamlit only processes clicks
on a full rerun), wrap the streaming UI in `@st.fragment` so the fragment can rerun
independently while the background thread drains the HTTP connection.

#### Key constraints

- All `st.*` / `container.*` calls must stay on the main thread.
- `events_iter.close()` must be called explicitly — not left to GC.
- `render_streaming_response` would need to be refactored into a pure-IO drainer and a
  pure-UI renderer with a queue between them.
- `st.fragment` is needed to make the Stop button interactive during streaming.

#### Files to modify

`cortex_agents_client/st/render.py`, `cortex_agents_client/st/chatbot.py`

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
