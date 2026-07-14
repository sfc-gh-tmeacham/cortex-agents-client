# Plan: Starter Questions on New Thread

## Context

Agent objects have a `sample_questions: list[str]` field populated from the agent spec. When a user starts a new conversation (empty message history), we want to show the first 5 sample questions as clickable suggestion buttons — using the existing `_render_suggested_queries` helper so the UX is identical to post-response suggestions.

## Architecture

```
Agent spec (sample_questions)
    ↓ cached in session state on first render
_render_last_suggestions()
    ↓ messages empty? → show agent's sample_questions[:5]
    ↓ messages present? → show last assistant's suggested_queries (existing behavior)
_render_suggested_queries()
    ↓ button click → _ca_pending_suggestion → _process_prompt
```

## Steps

### 1. Fetch and cache agent spec on init

In `chatbot.py` `_init()`, after `init_session` returns the client+thread, call `client.agents.get(self._agent_path)` and store the `Agent` object in `st.session_state[f"{prefix}_agent_spec"]`. Only fetch once (use `setdefault` or check existence). Parse `agent_path` to extract db/schema/name.

### 2. Show sample_questions when messages list is empty

In `_render_last_suggestions`, change the early return when `not messages`:

```python
if not messages:
    # New thread — show agent's starter questions
    agent_spec = st.session_state.get(f"{self._session_key_prefix}_agent_spec")
    if agent_spec and agent_spec.sample_questions:
        _render_suggested_queries(agent_spec.sample_questions[:5], container)
    return
```

This reuses the exact same button rendering and click handling — no new code paths needed.

### 3. Add sample questions to mock agent for demo

Update `MockClient` in `streamlit_demo/mock_thread.py` so it returns an `Agent` with `sample_questions` populated. This lets the demo show starter questions on fresh threads without a real Snowflake connection.

### 4. Test and verify

- Fresh thread: starter questions visible
- After first message: starter questions gone, response suggestions appear if returned
- "New conversation" button: clears messages → starter questions reappear
- Clicking a starter question: submits as prompt, streams response
