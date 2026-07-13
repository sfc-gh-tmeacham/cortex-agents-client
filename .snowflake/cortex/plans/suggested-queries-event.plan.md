# Plan: SuggestedQueriesEvent + Clickable Suggestion Buttons

## Context

The Cortex Agents API emits `response.suggested_queries` events with follow-up questions:
```json
{
  "content_index": 6,
  "sequence_number": 30,
  "suggested_queries": [
    {"query": "How does the total quantity sold break down by product?"},
    {"query": "How does revenue break down by region for each product?"},
    {"query": "How many transactions were there for each product?"}
  ]
}
```

Currently falls through to `UnknownEvent`. We want to:
1. Parse it into a typed `SuggestedQueriesEvent`
2. Store suggestions on `StoredMessage`
3. Render as clickable pill buttons that submit the chosen query as the next user message

## Changes

### 1. Add `SuggestedQueriesEvent` dataclass (`models/events.py`)

```python
@dataclass
class SuggestedQueriesEvent(SSEEvent):
    content_index: int = 0
    queries: list[str] = field(default_factory=list)

    @classmethod
    def _from_payload(cls, payload):
        items = payload.get("suggested_queries") or []
        return cls(
            event_type="response.suggested_queries",
            content_index=payload.get("content_index", 0),
            queries=[item["query"] for item in items if "query" in item],
        )
```

### 2. Register in SSE dispatch table (`sse.py`)

```python
"response.suggested_queries": SuggestedQueriesEvent._from_payload,
```

### 3. Add `suggested_queries: list[str]` to `StoredMessage` (`models/thread.py`)

A new field at the end of the dataclass. Populated from the event during streaming; persisted in session state so buttons appear on rerun too.

### 4. Capture in `render_streaming_response` (`st/render.py`)

After the existing event handlers, add:
```python
elif isinstance(event, SuggestedQueriesEvent):
    stored.suggested_queries = event.queries
```

No UI rendering during streaming — the buttons appear after the response completes.

### 5. Render buttons after response completes (`st/render.py`)

At the end of `render_streaming_response` (after annotations but before `return stored`), and in `render_stored_message` (after the last section but before `pending_permission`):

```python
if stored.suggested_queries:
    _render_suggested_queries(stored.suggested_queries, container)
```

The helper:
```python
def _render_suggested_queries(queries: list[str], container) -> None:
    cols = container.columns(len(queries))
    for col, query in zip(cols, queries):
        if col.button(query, icon=":material/arrow_forward:", use_container_width=True):
            st.session_state["_ca_pending_suggestion"] = query
            st.rerun()
```

### 6. Handle suggestion button clicks in chatbot (`st/chatbot.py`)

In both `_render_fullpage` and `_render_embedded`, check for a pending suggestion before `st.chat_input`:

```python
suggestion = st.session_state.pop("_ca_pending_suggestion", None)
if suggestion:
    self._process_prompt(suggestion, thread, append_message)
elif prompt := st.chat_input(...):
    self._process_prompt(prompt, thread, append_message)
```

This uses the same session state key prefix pattern the chatbot already uses. The key is global because only one suggestion can be active at a time.

### 7. Export + re-exports (`models/__init__.py`, `__init__.py`)

Add `SuggestedQueriesEvent` to both `__all__` lists.

### 8. Capture in `RunResult` (`resources/runs.py`)

In `stream_and_collect`:
```python
elif isinstance(event, SuggestedQueriesEvent):
    result.suggested_queries = event.queries
```

Add `suggested_queries: list[str] = field(default_factory=list)` to `RunResult`.
