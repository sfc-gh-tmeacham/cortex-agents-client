# Roadmap

Planned features and known limitations for `cortex_agents_client`.

---

## File and audio attachment support

### Current state

`StreamlitChatbot` accepts `accept_file`, `accept_audio`, and `file_type` parameters
that enable the corresponding controls on `st.chat_input` (Streamlit ≥ 1.59). When a
user uploads a file or records audio, those attachments are:

- Displayed in the user's chat bubble (`st.image`, `st.audio`, `st.write`)
- Stored in `StoredMessage.attachments` so they survive Streamlit reruns

**The file and audio content is not forwarded to the agent.** Only the typed text
portion of the prompt reaches `thread.chat()`. See the inline comment in
`chatbot.py::_process_prompt` for the code-level note.

### Why

The Cortex Agents Run API's `MessageContentItem` schema currently only defines `text`
as a valid user-input content type. There is no `image`, `document`, or `audio` content
type for user messages in the public REST API.

### How Snowflake CoWork does it

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

### What needs to be built

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

### Supported file types (CoWork reference)

| Type   | Formats                          | Max size |
|--------|----------------------------------|----------|
| Documents | CSV, JSON, PDF, PPTX, TXT, XLSX | 50 MB each, up to 5 files |
| Images | JPEG, PNG, WEBP, GIF             | Model-dependent (3.75–10 MB) |
| Audio  | WAV, MP3, FLAC, AAC, OGG, M4A   | Model-dependent |

---

## Potential future items

- **Image pasting** — CoWork supports pasting images directly from the clipboard; this
  would follow the same stage-upload pattern as file attachments.
- **Voice-to-text preview** — Show a transcript of recorded audio in the user bubble
  before sending (requires client-side transcription or a round-trip to `AI_TRANSCRIBE`).
- **Attachment size validation** — Surface a clear error when an uploaded file exceeds
  the per-model size limit before the API call is made.
