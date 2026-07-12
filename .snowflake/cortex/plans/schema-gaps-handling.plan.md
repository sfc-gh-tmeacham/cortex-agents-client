# Plan: Handle schema gaps — ToolResultContent.text, Permission Decisions, Client-side Tools

## Overview

Three schema gaps identified during the audit. All three affect both the raw API and the Streamlit integration.

---

## Gap 1 — `ToolResultContent.text` (low effort)

### What the API sends

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_abc",
  "content": [
    {"type": "text", "text": "Here are the top 5 results: ..."}
  ],
  "status": "success"
}
```

Generic and web_search tools commonly return `type: "text"` content instead of `type: "json"`. Currently this text is silently dropped.

### Changes

**`models/thread.py` — `StoredMessage`:**
```python
tool_result_text: dict[str, str] = field(default_factory=dict)
# Maps tool_use_id → concatenated text from ToolResultContent.text items
```

**`st/render.py` — `render_streaming_response`:**

In the `ToolResultEvent` handler, after updating the status spinner, extract text content:
```python
elif isinstance(event, ToolResultEvent):
    use_event = pending_tool_uses.pop(event.tool_use_id, None)
    if use_event is not None:
        stored.tool_executions.append((use_event, event))
    
    # Extract text content items
    text_parts = [
        item["text"] for item in event.content
        if item.get("type") == "text" and item.get("text")
    ]
    if text_parts:
        result_text = "\n\n".join(text_parts)
        stored.tool_result_text[event.tool_use_id] = result_text
        # Render inside the (already-closed) status context or directly
        container.markdown(result_text)
    
    if show_tool_status and event.tool_use_id in tool_status_contexts:
        # ... existing status update
```

**`st/render.py` — `render_stored_message`:**
```python
for tool_use, tool_result in msg.tool_executions:
    if tool_result and tool_use.tool_use_id in msg.tool_result_text:
        container.markdown(msg.tool_result_text[tool_use.tool_use_id])
```

---

## Gap 2 — Permission Decisions (medium effort)

### API flow

1. Agent emits `ToolUseEvent` with `permission_options = ["Allow Once", "Deny"]`
2. Stream stalls — agent waits for a decision
3. Client interrupts the stream, shows options to user
4. User picks; client sends a **new** run request with the decision embedded as a `MessageContentItem`:
   ```json
   {
     "role": "user",
     "content": [{
       "type": "permission_decision",
       "permission_decision": {
         "tool_use_id": "toolu_abc",
         "decision": "Allow Once"
       }
     }]
   }
   ```

### Streamlit approach

Streamlit's execution model (reruns on widget interaction) makes mid-stream pausing natural:

1. **During streaming:** when `ToolUseEvent.permission_options` is non-empty, `render_streaming_response` stops consuming the stream and sets `stored.pending_permission = event`.
2. **After streaming:** the Streamlit chatbot checks if the last assistant message has `pending_permission`. If so, it renders the approval UI (radio + button) instead of the chat input.
3. **On user action:** the button press causes a rerun. Session state holds the pending decision. On the next render cycle, `Thread.chat()` is called with the permission decision injected into the messages.

### Changes

**`models/thread.py` — `StoredMessage`:**
```python
pending_permission: ToolUseEvent | None = None
```

**`st/render.py` — `render_streaming_response`:**
```python
elif isinstance(event, ToolUseEvent):
    pending_tool_uses[event.tool_use_id] = event
    if event.permission_options:
        # Stop streaming — permission required
        stored.pending_permission = event
        # Show the options inline while we still have the container
        container.warning(
            f"**{event.name}** is requesting permission to run.",
            icon=":material/security:"
        )
        break  # Stop consuming the stream
    # ... existing spinner logic
```

**`st/session.py` — new helpers:**
```python
def get_pending_permission() -> ToolUseEvent | None:
    """Returns the pending permission event if any, else None."""
    msgs = get_messages()
    if msgs and msgs[-1].pending_permission:
        return msgs[-1].pending_permission
    return None

def resolve_permission(tool_use_id: str, decision: str) -> None:
    """Records the user's decision in session state."""
    st.session_state[f"_permission_decision_{tool_use_id}"] = decision
```

**`st/chatbot.py` — `StreamlitChatbot.render()`:**

Before the chat input, check for pending permission:
```python
pending = get_pending_permission()
if pending:
    st.info(f"**{pending.name}** is requesting permission.")
    decision = st.radio("Decision:", pending.permission_options, key=f"perm_{pending.tool_use_id}")
    if st.button("Confirm", key=f"perm_confirm_{pending.tool_use_id}"):
        resolve_permission(pending.tool_use_id, decision)
        st.rerun()
```

On the next rerun, the permission decision is passed to `Thread.chat()` as a special content item.

**`client.py` — `Thread.chat()`:**
```python
def chat(
    self,
    agent_path: str,
    message: str,
    *,
    permission_decision: dict[str, Any] | None = None,
) -> Iterator[SSEEvent]:
    content = [{"type": "text", "text": message}]
    if permission_decision:
        content.append({"type": "permission_decision", "permission_decision": permission_decision})
    messages = [{"role": "user", "content": content}]
    # ...
```

---

## Gap 3 — Client-side Tool Execution (medium-high effort)

### API flow

When `ToolUseEvent.client_side_execute=True`:
1. Agent emits the `ToolUseEvent` with the input it wants the client to execute
2. Stream ends (or stalls)
3. Client executes the tool locally
4. Client sends a **new** run request with the tool result in the messages:
   ```json
   {
     "role": "user",
     "content": [{
       "type": "tool_result",
       "tool_result": {
         "tool_use_id": "toolu_abc",
         "content": [{"type": "json", "json": {"result": "..."}}],
         "status": "success"
       }
     }]
   }
   ```

### Design

Add an optional `tool_executor` callback to `Thread.chat()`:

```python
ToolExecutor = Callable[[ToolUseEvent], list[dict[str, Any]]]
# Returns list of ToolResultContent dicts, e.g. [{"type": "json", "json": {...}}]
```

`Thread.chat()` wraps the stream in a loop that handles client-side tools automatically:
```python
def chat(
    self,
    agent_path: str,
    message: str,
    *,
    tool_executor: ToolExecutor | None = None,
    permission_decision: dict[str, Any] | None = None,
) -> Iterator[SSEEvent]:
    # ... build messages
    for event in self._client.runs.stream(messages, ...):
        if (
            isinstance(event, ToolUseEvent)
            and event.client_side_execute
            and tool_executor is not None
        ):
            yield event
            # Execute the tool
            try:
                result_content = tool_executor(event)
                status = "success"
            except Exception as exc:
                result_content = [{"type": "text", "text": str(exc)}]
                status = "error"
            # Build the follow-up messages and restart the stream
            # (handled by looping with new messages including the tool_result)
        else:
            yield event
```

For Streamlit, `StreamlitChatbot` accepts `tool_executor` at construction time and passes it through to `Thread.chat()`. The spinner shows while the executor runs.

---

## Scope notes

- **Permission decisions** in Streamlit require stopping mid-stream and using session state to resume on the next rerun. The stream is deliberately broken; the connection to the API is abandoned (the API will eventually timeout on its end). The next Streamlit interaction sends a fresh request with the decision embedded.
- **Client-side tools** use a callback that must be synchronous (no async). For long-running tools, the caller is responsible for showing progress externally.
- **`StoredMessage.pending_permission`** is cleared once the decision is submitted (the resolved message gets a normal `tool_execution` entry instead).
- All three gaps need both `render_streaming_response` (live) and `render_stored_message` (replay) updates to maintain the render-equivalence invariant.
