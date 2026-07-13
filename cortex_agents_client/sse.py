"""SSE (Server-Sent Events) parser and event factory.

Parses the ``text/event-stream`` wire format emitted by the Cortex Agents
``agent:run`` endpoint and dispatches each event to the appropriate typed
dataclass.

The SSE wire format is::

    event: <event_type>
    data: <json_payload>

    event: <next_event_type>
    data: <next_json_payload>

    ...

Each ``event``/``data`` pair is separated from the next by a blank line.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from cortex_agents_client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    MetadataEvent,
    ResponseEvent,
    SSEEvent,
    StatusEvent,
    SuggestedQueriesEvent,
    TableEvent,
    TextAnnotationEvent,
    TextDeltaEvent,
    TextEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
    ToolResultEvent,
    ToolResultStatusEvent,
    ToolUseEvent,
    UnknownEvent,
    WarningEvent,
)

__all__ = ["parse_sse_stream", "event_from_sse"]

logger = logging.getLogger(__name__)

# Maps SSE event type strings to their factory functions.
_EVENT_FACTORIES: dict[str, Any] = {
    "response.text": TextEvent._from_payload,
    "response.text.delta": TextDeltaEvent._from_payload,
    "response.text.annotation": TextAnnotationEvent._from_payload,
    "response.thinking": ThinkingEvent._from_payload,
    "response.thinking.delta": ThinkingDeltaEvent._from_payload,
    "response.tool_use": ToolUseEvent._from_payload,
    "response.tool_result": ToolResultEvent._from_payload,
    "response.tool_result.status": ToolResultStatusEvent._from_payload,
    "response.tool_result.analyst.delta": AnalystDeltaEvent._from_payload,
    "response.table": TableEvent._from_payload,
    "response.chart": ChartEvent._from_payload,
    "response.suggested_queries": SuggestedQueriesEvent._from_payload,
    "response.status": StatusEvent._from_payload,
    "response.warning": WarningEvent._from_payload,
    "response": ResponseEvent._from_payload,
    "error": ErrorEvent._from_payload,
    "metadata": MetadataEvent._from_payload,
}


def parse_sse_stream(lines: Iterator[str]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Parses a raw SSE line stream into (event_type, payload) tuples.

    Implements the SSE parsing algorithm per the W3C spec:
    - Lines starting with ``:`` are comments and ignored.
    - ``retry:`` lines are ignored.
    - ``event:`` lines set the event type for the next dispatch.
    - ``data:`` lines accumulate the payload (joined with newlines).
    - A blank line dispatches the accumulated event and resets state.
    - Incomplete events at stream end (no trailing blank line) are discarded.

    Args:
        lines: Iterator of raw text lines from the SSE stream. Lines should
            not include trailing newline characters (as returned by
            ``httpx.Response.iter_lines()``).

    Yields:
        Tuples of ``(event_type, payload_dict)`` for each complete SSE event.
        ``event_type`` defaults to ``"message"`` if no ``event:`` line was seen.
        Invalid JSON in the data field is yielded as
        ``("_parse_error", {"raw": "..."})`` rather than raising.

    Example::

        with client.stream("POST", path, json=body) as lines:
            for event_type, payload in parse_sse_stream(lines):
                event = event_from_sse(event_type, payload)
    """
    event_type: str | None = None
    data_parts: list[str] = []

    for line in lines:
        if line.startswith(":") or line.startswith("retry:"):
            # Comment or retry directive — skip.
            continue

        if line == "":
            # Blank line: dispatch accumulated event if we have data.
            if data_parts:
                raw_data = "\n".join(data_parts)
                dispatch_type = event_type or "message"
                try:
                    payload = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to parse SSE data as JSON for event '%s': %.200s",
                        dispatch_type,
                        raw_data,
                    )
                    payload = {"raw": raw_data}
                    dispatch_type = "_parse_error"
                yield dispatch_type, payload
            # Reset state for the next event.
            event_type = None
            data_parts = []
            continue

        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_parts.append(line[5:].strip())
        # Unknown field names (id:, etc.) are silently ignored per SSE spec.


def event_from_sse(event_type: str, payload: dict[str, Any]) -> SSEEvent:
    """Creates a typed SSEEvent from a raw event type and payload dict.

    Unknown event types are returned as :class:`UnknownEvent` rather than
    raising an exception. This ensures forward-compatibility as Snowflake
    introduces new event types with new tools.

    Args:
        event_type: The SSE event type string (e.g. ``"response.text.delta"``).
        payload: The parsed JSON payload dict.

    Returns:
        A typed SSEEvent subclass instance. For unknown types, returns
        :class:`UnknownEvent` containing the raw payload.

    Example::

        for event_type, payload in parse_sse_stream(lines):
            event = event_from_sse(event_type, payload)
            if isinstance(event, TextDeltaEvent):
                print(event.text, end="")
    """
    factory = _EVENT_FACTORIES.get(event_type)
    if factory is None:
        logger.debug("Unknown SSE event type '%s'; yielding as UnknownEvent", event_type)
        return UnknownEvent(event_type=event_type, raw_payload=payload)

    try:
        return factory(payload)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning(
            "Failed to parse event '%s': %s. Falling back to UnknownEvent.",
            event_type,
            exc,
        )
        return UnknownEvent(event_type=event_type, raw_payload=payload)
