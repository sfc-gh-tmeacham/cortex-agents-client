# Streamlit Integration Design Reference

This document details the internal architecture, state management, and rendering pipeline of `streamlit_cortex_agents.chat`.

For user-facing integration and usage instructions, see the [Streamlit Integration Guide](../streamlit_guide.md). For Streamlit-in-Snowflake container runtime deployment, see [Streamlit-in-Snowflake](../sis.md).

---

## The Streamlit rerun problem

Streamlit reruns the entire Python script on every user interaction. This means:

1. Objects created at the top of the script (client, thread) are re-instantiated on every rerun unless stored in `st.session_state`.
2. Streaming responses cannot be re-streamed — what was streamed on a previous run must be replayed from stored data.
3. Rich content types (tables, charts, thinking) must be rendered identically from session state on every rerun.

The `streamlit_cortex_agents.chat` subpackage solves all three problems.

---

## Session state layout

All keys are scoped under `session_key_prefix` (default `"_ca"`):

```
st.session_state:
  _ca_client              → CortexAgentsClient    (created once, reused across reruns)
  _ca_thread              → Thread                (created once, reused across reruns)
  _ca_messages            → list[StoredMessage]   (grows with each conversation turn)
  _ca_input               → str                   (chat input widget state)
  _ca_pending_perm        → ToolUseEvent | None   (tool awaiting user permission decision)
  _ca_agent_spec          → Agent | None          (cached agent specification for starter questions)
  _ca_pending_suggestion  → str                   (clicked suggestion query to auto-submit)
```

In addition, interactive child widgets instantiate dynamic session keys:
- `{suggestion_key}_pills` — selection state for suggestion `st.pills`.
- `{pending_permission_key}_radio` — selection state for permission approval options.
- `{pending_permission_key}_confirm` — button state for permission submission.

Custom prefixes can be passed to `CortexAgentChat(session_key_prefix=...)` or `init_session(client_key=..., thread_key=..., messages_key=...)` to prevent key collisions when multiple chatbots exist on a page.

---

## StoredMessage schema

Every conversation turn is stored as a `StoredMessage` dataclass. This is the canonical unit of history:

```python
@dataclass
class StoredMessage:
    role: str
    text: str = ""
    thinking: str | None = None
    is_elicitation: bool = False
    tables: list[TableEvent] = field(default_factory=list)
    charts: list[ChartEvent] = field(default_factory=list)
    annotations: list[TextAnnotationEvent] = field(default_factory=list)
    tool_executions: list[tuple[ToolUseEvent, ToolResultEvent | None]] = field(default_factory=list)
    warnings: list[WarningEvent] = field(default_factory=list)
    error: ErrorEvent | None = None
    analyst_sql: dict[str, str] = field(default_factory=dict)
    verified_tool_uses: set[str] = field(default_factory=set)
    message_id: int | None = None
    attachments: list[Any] = field(default_factory=list)
    tool_result_text: dict[str, str] = field(default_factory=dict)
    text_segments: list[str] = field(default_factory=list)
    content_blocks: list[tuple[str, int]] = field(default_factory=list)
    suggested_queries: list[str] = field(default_factory=list)
    pending_permission: ToolUseEvent | None = None
    thinking_segments: list[str] = field(default_factory=list)
    timeline: list[tuple[str, int | str]] = field(default_factory=list)
```

Field semantics:
- `analyst_sql`: Maps `tool_use_id` to generated SQL queries, rendered inside the tool step.
- `attachments`: File and audio objects displayed in the user bubble and preserved across reruns (not forwarded to the agent).
- `content_blocks`: Preserves the interleaved arrival order of text segments, tables, and charts (`("text", idx)`, `("table", idx)`, `("chart", idx)`).
- `tool_result_text`: Maps `tool_use_id` to text returned by tools (e.g. web search summaries or generic tool output).
- `thinking_segments`: Reasoning text split at each tool call. `thinking` holds the segments joined.
- `timeline`: Order of reasoning and tool steps (`("thinking", idx)`, `("tool", tool_use_id)`) for replaying the reasoning timeline.

`StoredMessage` captures everything needed to re-render the message identically on any subsequent rerun. The `content_blocks` field ensures replay produces the same visual layout as the original streaming render.

---

## Rendering strategy

There are two code paths that produce identical output:

### Path 1: Streaming (new message)

Called during the active generation of a new assistant turn:

```python
with st.chat_message("assistant"):
    stored = render_streaming_response(thread.chat(agent_path, message), st)
append_message(stored)
```

Internal implementation:
1. If `loading_placeholder` is provided, display `:shimmer[▌]` waiting cursor; clear it on the first received event.
2. Create `text_placeholder = container.empty()`.
3. On `TextDeltaEvent`: accumulate text into segment buffer. If `event.is_elicitation` is True, render in `text_placeholder.info(..., icon=":material/contact_support:", title="Clarification needed")`; otherwise update `text_placeholder.markdown(accumulated_text + " :shimmer[▌]")`.
4. On `TextEvent`: replace placeholder with final text. If `event.is_elicitation` is True, render as info box; otherwise as standard markdown.
5. On `TextAnnotationEvent`: append citation annotation to `stored.annotations`.
6. On `ThinkingDeltaEvent`: open a thinking segment if none is open (appended to `stored.thinking_segments` and `stored.timeline`) and accumulate text into it. If `show_thinking=True`, stream it into a `:material/psychology: Thinking` step in the reasoning timeline.
7. On `ThinkingEvent`: set the open segment's final text, opening one if no deltas arrived, then close the segment.
8. On `ToolUseEvent`:
   - If `event.permission_options` is non-empty: tool requires user approval. Render `container.warning(f"**{event.name}** is requesting permission before executing.", icon=":material/security:")`, set `stored.pending_permission = event`, and `break` immediately out of the event stream.
   - Otherwise close the open thinking segment and append `("tool", tool_use_id)` to `stored.timeline`. If `show_tool_status=True`, add a running step `st.status(f"{icon} Using {event.name}...", type="step")` to the reasoning timeline, where `icon` names the tool type (search, database, web search, or wrench). If SQL is present in `stored.analyst_sql`, display it as a code block.
9. On `ToolResultStatusEvent`: update the tool step's label, keeping the tool type icon.
10. On `ToolResultEvent`: move the step to the complete state (label `{icon} {name}`) or the error state (label `{icon} {name} failed`). A verified-query success replaces the step with `st.expander(type="step", icon=":material/verified_user:")`, colored green by CSS, so the shield is its only marker. Render any text items from `event.content` via markdown and record in `stored.tool_result_text`.
11. On `AnalystDeltaEvent` (legacy path): extract generated SQL and verified query status.
12. On `TableEvent`: seal current text segment into `stored.text_segments`, record block sequence in `stored.content_blocks`, and render DataFrame with `hide_index=True`, `width="stretch"`, `column_config=_markdown_column_config(df)`, and an optional title caption.
13. On `ChartEvent`: seal current text segment, record block sequence in `stored.content_blocks`, and render Vega-Lite spec with `width="stretch"`.
14. On `StatusEvent`: log debug info; transient.
15. On `WarningEvent`: record on `stored.warnings` and render `container.warning(...)`.
16. On `ErrorEvent`: record on `stored.error`, render `container.error(...)`, and `break` stream consumption.
17. On `SuggestedQueriesEvent`: record queries on `stored.suggested_queries`.
18. On `MetadataEvent`: record `message_id` on `stored.message_id` for assistant responses; track active `run_id` for stop/cancel handling.
19. Post-stream finalization:
    - If the stream ended before a tool result arrived, record the tool in `stored.tool_executions` with a `None` result and update its step to `{icon} {name} interrupted` (`state="error"`).
    - Complete the reasoning timeline. It starts expanded, collapses when the first text, table, or chart arrives, reopens if a later step arrives, and stays open in the error state if any step failed.
    - If annotations exist, render the collapsible Sources expander (deduplicated by `doc_id` + `text`).
    - If no visible content was produced (no text, tables, charts, errors, warnings, pending permissions, or tool result text), display the empty-response fallback warning.
20. Return assembled `StoredMessage`.

### Path 2: History replay (rerun)

Called for every existing message on every Streamlit rerun:

```python
for msg in get_messages():
    with st.chat_message(msg.role):
        render_stored_message(msg, st)
```

`render_stored_message()` renders elements in the following order:
1. Reasoning timeline, collapsed: thinking steps (if `show_thinking=True`) and tool steps (if `show_tool_status=True`) in `msg.timeline` order, with the same labels, states, SQL, and verified shield as the live stream. Legacy messages without `timeline` replay one thinking step, then the tool steps.
2. Tool result text (if present) for each tool execution.
3. **Interleaved content**: render text segments, tables, and charts in arrival order using `content_blocks` (with `width="stretch"` for tables and charts). If `msg.is_elicitation` is True, text segments render as `container.info(..., icon=":material/contact_support:", title="Clarification needed")`; otherwise as standard markdown. (Legacy messages without `content_blocks` fall back to sequential text → tables → charts.)
4. Citations / Sources expander (if annotations are present, deduplicated by `doc_id` + `text`).
5. Warnings via `st.warning()`.
6. Error via `st.error()`.
7. Pending permission notice via `st.warning()` (if awaiting user approval).

---

## Suggested follow-up queries

Suggestion pills are rendered **only for the last assistant message** and **outside** `st.chat_message()`. This is handled by `_render_last_suggestions()` in `chatbot.py`, not by the per-message rendering functions.

- During streaming: `SuggestedQueriesEvent` is captured on `StoredMessage.suggested_queries`.
- After streaming: `st.rerun()` triggers a fresh render cycle.
- On rerun: `_render_last_suggestions()` checks the last message for suggestions and renders them with `st.pills` under a "Suggested questions" label.
- On select: an `on_change` callback stores the query in `st.session_state["_ca_pending_suggestion"]` and clears the pill, so the query is submitted as the next user message on the subsequent rerun.
- Stale suggestions from older messages are not shown.

### Agent starter questions

When a thread contains no messages, `_render_last_suggestions()` checks `st.session_state["_ca_agent_spec"]`. If the agent specification contains sample questions (`agent_spec.instructions.sample_questions`), up to the first 5 questions are rendered as starter pills.

To support this, `CortexAgentChat` fetches the agent spec once on initial render and caches it in `_ca_agent_spec`. If fetching the agent spec fails (for example, if the user lacks `DESCRIBE` privileges on the agent), the error is caught and logged at debug level, and starter questions are silently skipped.

---

## Empty response fallback

When a stream completes with no visible content (no text, tables, charts, errors, warnings, pending permissions, or tool result text), the renderer displays a fallback notice:

```
The agent returned an empty response. Try rephrasing your question.
```

This prevents an empty assistant message bubble from confusing users.

---

## CSS targeting via widget keys

Both `render_streaming_response` and `render_stored_message` accept optional `key_prefix` and `loading_placeholder` parameters:
- `key_prefix`: Assigns deterministic keys to child widgets, creating stable `.st-key-*` CSS classes in the DOM (`.st-key-{prefix}-thinking` on the container wrapping the reasoning timeline, `.st-key-{prefix}-verified-step-{tool_use_id}`, `.st-key-{prefix}-sources`, `.st-key-{prefix}-table-{i}`, `.st-key-{prefix}-chart-{i}`).
- `loading_placeholder`: Accepts an `st.empty()` container displaying a waiting shimmer indicator, which is cleared as soon as the first event arrives.

`CortexAgentChat` automatically constructs `key_prefix` as `{css_prefix}-{msg_index}`, where `css_prefix` is derived from `session_key_prefix` with leading underscores stripped.

---

## Stopping a response

`CortexAgentChat` passes `submit_mode="stop"` to `st.chat_input`, so the send button transforms into a stop button while a response streams.

Pressing stop causes Streamlit to raise `StopException` at the script's next yield point (the next streamed event). The chatbot catches the exception, calls `client.cancel_run(run_id)` with the `run_id` from the **most recent** `metadata` event, and re-raises so Streamlit terminates the script run. Each client-side tool follow-up initiates a new run, so tracking the latest `run_id` ensures the currently executing run is cancelled. A rerun triggered mid-stream (`RerunException`) cancels the run the same way.

- The server stops the run and commits any partial output to the thread.
- If the run already completed, `cancel_run` raises `RunNotActiveError`; the chatbot logs this at info level. Any other cancellation error is logged as a warning without masking the user's stop action.
- If stop is pressed before the first `metadata` event arrives, no `run_id` is available and no cancel call is dispatched.
- Partial answers are not saved to session state history; the user's message remains without a reply.
- Suggestion pills bypass the chat input widget and therefore do not expose a stop button during execution.

Cancel-on-stop is validated by unit tests (`test_stop_cancels_latest_run_and_reraises`); live streaming cancellation is an API capability subject to backend support. `render_streaming_response` alone does not handle cancellation — cancellation logic is orchestrated by `CortexAgentChat`.

---

## Per-viewer tenant resolution

`CortexAgentChat(variables=...)` accepts a dictionary mapping or a zero-argument callable. The callable enables resolving tenant context per viewer at runtime via `st.context.user`.

The callable is invoked **once per prompt, before the `thread.chat` stream factory is constructed**:

```python
variables = self._resolve_variables()      # invoked once per turn
stored = self._stream_with_retry(
    lambda: thread.chat(..., variables=variables),   # closure captures resolved variables
    ...
)
```

This resolution order is critical: `_stream_with_retry` may re-invoke the factory function if a transient network or server error occurs (`CortexConnectionError`, `CortexTimeoutError`, or `ServerError`). By resolving variables outside the closure, any retry uses the exact same tenant attributes as the initial attempt, preventing session leakage.

The same resolution logic executes independently on the permission approval reply path, which runs during a subsequent user interaction.

---

## Integration and lifecycle references

For code examples and integration patterns, see the following sections in the primary documentation:

- **Minimal app and manual integration**: See [Streamlit Integration Guide: Manual Integration](../streamlit_guide.md#manual-integration).
- **Secrets configuration**: See [Streamlit Integration Guide: Secrets Configuration](../streamlit_guide.md#secrets-configuration).
- **Streamlit-in-Snowflake container runtime**: See [Streamlit-in-Snowflake](../sis.md).
- **Thread lifecycle decisions**: See [Streamlit Integration Guide: Thread Lifecycle](../streamlit_guide.md#thread-lifecycle).
