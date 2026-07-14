# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2025-06-01

### Added

- Initial release of `cortex-agents-client`.
- `CortexAgentsClient` with PAT, JWT, OAuth, and SiS container auth providers.
- Agent CRUD operations (`create`, `get`, `update`, `list`, `delete`, `feedback`).
- Thread lifecycle management (`create`, `get`, `update`, `list`, `delete`).
- Streaming and non-streaming agent run invocations.
- Full SSE event parsing with 16 typed event dataclasses.
- `Thread` class with automatic `parent_message_id` tracking.
- `RunResult` dataclass for non-streaming and `stream_and_collect` results.
- Streamlit integration layer (`StreamlitChatbot`, `render_streaming_response`).
- Embedded and fullpage chat layout modes.
- Client-side tool execution with `tool_executor` callback.
- Compaction-aware `latest_context` for long conversations.
- Typed exception hierarchy with HTTP status code mapping.
