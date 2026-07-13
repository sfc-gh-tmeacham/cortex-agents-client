# Plan: API Consistency Fixes

## Overview

Four targeted fixes applied sequentially; each is followed by a full `uv run pytest` run before moving on.

---

## Fix 1 — Rename `PermissionError` / `TimeoutError`

### Why
Both names shadow Python builtins, creating a trap where `except PermissionError` may catch file-system errors.

### Chosen names
`CortexPermissionError` and `CortexTimeoutError` — the `Cortex` prefix unambiguously scopes them.

### Files to change

**`cortex_agents_client/exceptions.py`** (lines 42, 54):
```python
# Before
class PermissionError(CortexAgentError):  # noqa: A001
class TimeoutError(CortexAgentError):     # noqa: A001

# After
class CortexPermissionError(CortexAgentError):
class CortexTimeoutError(CortexAgentError):

# Deprecated aliases (keep for transition)
PermissionError = CortexPermissionError   # noqa: A001
TimeoutError    = CortexTimeoutError      # noqa: A001
```

**`cortex_agents_client/http.py`** — 4 sites:
- Import: `from cortex_agents_client.exceptions import ..., CortexPermissionError, CortexTimeoutError`
- `raise PermissionError(...)` → `raise CortexPermissionError(...)`  (line 70)
- `raise TimeoutError(...)` ×2 (lines 197, 256) → `raise CortexTimeoutError(...)`

**`cortex_agents_client/__init__.py`** — add new names to import + `__all__`, keep old aliases:
```python
from cortex_agents_client.exceptions import (
    ...,
    CortexPermissionError,
    CortexTimeoutError,
    PermissionError,   # deprecated alias
    TimeoutError,      # deprecated alias
)
__all__ = [..., "CortexPermissionError", "CortexTimeoutError", ...]
```

**Docstrings** (`http.py`, `resources/agents.py`, `resources/runs.py`) — update all mentions of `PermissionError`/`TimeoutError` in `Raises:` sections to use new names.

**`tests/integration/test_agents.py`** (line 10, 72):
```python
from cortex_agents_client.exceptions import AgentNotFoundError, AuthError, CortexPermissionError
...
with pytest.raises(CortexPermissionError):
```

**`tests/integration/test_runs.py`** (lines 222, 229):
```python
from cortex_agents_client.exceptions import CortexPermissionError
...
with pytest.raises(CortexPermissionError):
```

### Verification
`uv run pytest --tb=short -q` — all 194 tests must pass.

---

## Fix 2 — Add `NotFoundError` base class

### Why
`AgentNotFoundError` and `ThreadNotFoundError` share no intermediate base between `CortexAgentError`. A `NotFoundError` base lets callers catch all not-found errors with a single `except NotFoundError`.

### Files to change

**`cortex_agents_client/exceptions.py`** — insert after `ServerError`:
```python
class NotFoundError(CortexAgentError):
    """Raised when a requested resource does not exist (HTTP 404)."""

class AgentNotFoundError(NotFoundError):
    ...

class ThreadNotFoundError(NotFoundError):
    ...
```

**`cortex_agents_client/__init__.py`** — add `NotFoundError` to imports and `__all__`.

### Verification
`uv run pytest --tb=short -q` — all 194 tests must pass.
Spot-check: `isinstance(AgentNotFoundError(), NotFoundError)` should be `True`.

---

## Fix 3 — Rename `Thread.get_history` → `Thread.list_messages`; add `Thread.latest_context`

### Why
`Thread.get_history()` wraps `ThreadsResource.list_messages()` — the inconsistent naming confuses users switching between the two APIs. Adding `Thread.latest_context()` fills the parity gap.

### Files to change

**`cortex_agents_client/client.py`** (around line 284):
```python
def list_messages(self) -> list[ThreadMessage]:
    """Fetches all messages for this thread in chronological order.
    Delegates to :meth:`~cortex_agents_client.resources.ThreadsResource.list_messages`.
    """
    return self._client.threads.list_messages(self._thread_id)

def latest_context(self) -> list[ThreadMessage]:
    """Returns the latest compaction summary + all subsequent conversation messages.
    Delegates to :meth:`~cortex_agents_client.resources.ThreadsResource.latest_context`.
    """
    return self._client.threads.latest_context(self._thread_id)

# Deprecated alias
def get_history(self) -> list[ThreadMessage]:
    """Deprecated: use list_messages() instead."""
    import warnings
    warnings.warn(
        "Thread.get_history() is deprecated; use Thread.list_messages() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return self.list_messages()
```

**`examples/multi_turn.py`** (line 121):
```python
# Before
for msg in thread.get_history():
# After
for msg in thread.list_messages():
```

### Verification
`uv run pytest --tb=short -q` — all 194 tests must pass.

---

## Fix 4 — `RunResult.thinking: str | None = None`

### Why
`RunResult` uses `thinking: str = ""` while `StoredMessage` uses `thinking: str | None = None`. Both mean "no thinking"; the inconsistency is a trap.

### Files to change

**`cortex_agents_client/resources/runs.py`**:

1. **Dataclass field** (line 63):
   ```python
   # Before
   thinking: str = ""
   # After
   thinking: str | None = None
   ```

2. **`_parse_non_streaming_response`** (line 104–106) — accumulation with `+=` must become conditional:
   ```python
   elif item_type == "thinking":
       thinking_data = item.get("thinking") or {}
       chunk = thinking_data.get("text", "")
       if chunk:
           result.thinking = (result.thinking or "") + chunk
   ```

3. **`stream_and_collect`** (line 454) — same pattern:
   ```python
   elif isinstance(event, ThinkingEvent):
       result.thinking = (result.thinking or "") + event.text
   ```

4. **Docstring** (line 50): update `thinking: Agent reasoning text, or ``None`` if not emitted.` — already correct, no change needed.

### Verification
`uv run pytest --tb=short -q` — all 194 tests must pass.
Check that `RunResult().thinking is None` (not `""`).

---

## Fix 5 — Update roadmap and commit

Remove or mark as resolved the four items in the "API-consistency improvements (deferred)" section of `docs/roadmap.md`, then make a single commit covering all four changes.
