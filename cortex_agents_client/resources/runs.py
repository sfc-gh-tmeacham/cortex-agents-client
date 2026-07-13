"""Resource class for running Cortex Agent interactions.

Provides streaming and non-streaming invocations of the ``agent:run``
endpoint, supporting both agent-object and inline (lite) configurations.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from cortex_agents_client.exceptions import RunError
from cortex_agents_client.http import HttpClient
from cortex_agents_client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    MetadataEvent,
    SSEEvent,
    TableEvent,
    TextAnnotationEvent,
    TextDeltaEvent,
    TextEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
    ToolResultEvent,
    ToolUseEvent,
    WarningEvent,
)
from cortex_agents_client.sse import event_from_sse, parse_sse_stream

logger = logging.getLogger(__name__)

__all__ = ["RunsResource", "RunResult"]


@dataclass
class RunResult:
    """The assembled result of a non-streaming agent run.

    Contains all content types emitted during the run, fully accumulated.
    If the agent returns a fatal error event, :meth:`RunsResource.run` and
    :meth:`RunsResource.stream_and_collect` both raise
    :class:`~cortex_agents_client.exceptions.RunError`; :attr:`error` holds
    the underlying event if you catch the exception and need more detail.

    Attributes:
        text: Final assembled text from all ``response.text`` events.
        thinking: Agent reasoning text, or ``None`` if not emitted.
        tables: List of table events in order of appearance.
        charts: List of chart events in order of appearance.
        tool_uses: List of all tool use events.
        tool_results: List of all tool result events.
        annotations: List of citation annotations.
        warnings: List of warning events.
        metadata_events: Both metadata events (user + assistant message IDs).
        error: Fatal error event, or ``None`` if the run succeeded.
        analyst_sql: Maps tool_use_id to generated SQL strings.
    """

    text: str = ""
    thinking: str | None = None
    status: str = ""  # "completed" | "cancelled" (from non-streaming response)
    tables: list[TableEvent] = field(default_factory=list)
    charts: list[ChartEvent] = field(default_factory=list)
    tool_uses: list[ToolUseEvent] = field(default_factory=list)
    tool_results: list[ToolResultEvent] = field(default_factory=list)
    annotations: list[TextAnnotationEvent] = field(default_factory=list)
    warnings: list[WarningEvent] = field(default_factory=list)
    metadata_events: list[MetadataEvent] = field(default_factory=list)
    error: ErrorEvent | None = None
    analyst_sql: dict[str, str] = field(default_factory=dict)


def _parse_non_streaming_response(data: dict[str, Any]) -> RunResult:
    """Converts a non-streaming API response dict to a RunResult.

    Args:
        data: Parsed JSON response from the ``stream=false`` run endpoint.

    Returns:
        A populated RunResult.
    """
    result = RunResult()
    if not isinstance(data, dict):
        return result

    content_items = data.get("content") or []
    for item in content_items:
        item_type = item.get("type", "")
        if item_type == "text":
            result.text += item.get("text", "")
        elif item_type == "table":
            table_data = item.get("table") or {}
            result.tables.append(
                TableEvent._from_payload({
                    "content_index": 0,
                    "tool_use_id": table_data.get("tool_use_id", ""),
                    "query_id": table_data.get("query_id", ""),
                    "result_set": table_data.get("result_set") or {},
                    "title": table_data.get("title"),
                })
            )
        elif item_type == "thinking":
            thinking_data = item.get("thinking") or {}
            chunk = thinking_data.get("text", "")
            if chunk:
                result.thinking = (result.thinking or "") + chunk
        elif item_type == "chart":
            chart_data = item.get("chart") or {}
            result.charts.append(
                ChartEvent._from_payload({
                    "content_index": 0,
                    "tool_use_id": chart_data.get("tool_use_id", ""),
                    "chart_spec": chart_data.get("chart_spec", ""),
                })
            )
        elif item_type == "tool_use":
            tool_data = item.get("tool_use") or {}
            result.tool_uses.append(ToolUseEvent._from_payload(tool_data))
        elif item_type == "tool_result":
            tool_data = item.get("tool_result") or {}
            result.tool_results.append(ToolResultEvent._from_payload(tool_data))

    for w in data.get("warnings") or []:
        if isinstance(w, dict):
            result.warnings.append(WarningEvent._from_payload(w))

    result.status = data.get("status", "")

    error_data = data.get("error")
    if error_data and isinstance(error_data, dict):
        result.error = ErrorEvent._from_payload(error_data)

    return result


class RunsResource:
    """Manages agent run invocations.

    Supports both agent-object runs and inline (lite) runs without a
    persisted agent object, in both streaming and non-streaming modes.

    Args:
        http: Authenticated HTTP client.
        default_database: Default database for agent-object runs.
        default_schema: Default schema for agent-object runs.

    Example::

        for event in client.runs.stream(
            agent_path="DB.SCHEMA.MY_AGENT",
            messages=[{"role": "user", "content": [{"type": "text", "text": "Hello"}]}],
        ):
            if isinstance(event, TextDeltaEvent):
                print(event.text, end="")
    """

    def __init__(
        self,
        http: HttpClient,
        default_database: str | None = None,
        default_schema: str | None = None,
    ) -> None:
        """Initialises the runs resource.

        Args:
            http: Authenticated HTTP client.
            default_database: Optional default database.
            default_schema: Optional default schema.
        """
        self._http = http
        self._default_database = default_database
        self._default_schema = default_schema

    def _resolve_path(
        self,
        agent_path: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        agent: str | None = None,
    ) -> str | None:
        """Resolves the agent run API path from various input forms.

        Returns ``None`` if no agent is specified (lite run).

        Args:
            agent_path: Dot-separated path ``"DB.SCHEMA.AGENT"``.
            database: Explicit database.
            schema: Explicit schema.
            agent: Bare agent name.

        Returns:
            Relative API path string for the agent run endpoint,
            or ``None`` for a lite run.
        """
        if agent_path:
            parts = agent_path.split(".")
            if len(parts) == 3:
                db, sc, name = parts
            elif len(parts) == 2:
                db = database or self._default_database
                sc, name = parts
            elif len(parts) == 1:
                db = database or self._default_database
                sc = schema or self._default_schema
                name = parts[0]
            else:
                raise ValueError(f"Invalid agent_path: {agent_path!r}")
            if not db or not sc:
                raise ValueError(
                    "Cannot resolve agent path without database/schema. "
                    "Provide them explicitly or set defaults on CortexAgentsClient."
                )
            return f"/api/v2/databases/{db}/schemas/{sc}/agents/{name}:run"

        if agent:
            db = database or self._default_database
            sc = schema or self._default_schema
            if not db or not sc:
                raise ValueError(
                    "database and schema are required for agent-object runs."
                )
            return f"/api/v2/databases/{db}/schemas/{sc}/agents/{agent}:run"

        return None  # Lite run

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        *,
        thread_id: int | None = None,
        parent_message_id: int = 0,
        tool_choice: dict[str, Any] | None = None,
        stream: bool = True,
        tools: list[dict[str, Any]] | None = None,
        tool_resources: dict[str, Any] | None = None,
        instructions: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Builds the request body for an agent:run call.

        Args:
            messages: List of message dicts with ``role`` and ``content``.
            thread_id: Optional thread ID for context persistence.
            parent_message_id: Parent message ID. Use ``0`` for the first
                turn in a thread.
            tool_choice: Optional tool selection constraint.
            stream: Whether to request streaming SSE response.
            tools: Inline tool specs for lite runs.
            tool_resources: Inline tool resources for lite runs.
            instructions: Inline instructions for lite runs.
            model: Inline model name for lite runs.

        Returns:
            Request body dict.
        """
        body: dict[str, Any] = {
            "messages": messages,
            "stream": stream,
        }
        if thread_id is not None:
            body["thread_id"] = thread_id
            body["parent_message_id"] = parent_message_id
        if tool_choice:
            body["tool_choice"] = tool_choice
        # Inline (lite) config fields
        if tools:
            body["tools"] = tools
        if tool_resources:
            body["tool_resources"] = tool_resources
        if instructions:
            body["instructions"] = instructions
        if model:
            body["model"] = model
        return body

    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        agent_path: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        agent: str | None = None,
        thread_id: int | None = None,
        parent_message_id: int = 0,
        tool_choice: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_resources: dict[str, Any] | None = None,
        instructions: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[SSEEvent]:
        """Sends a streaming request to the agent:run endpoint.

        Yields typed SSEEvent objects as they arrive from the server. All 16
        event types are possible; unknown types are yielded as
        :class:`~cortex_agents_client.models.events.UnknownEvent`.

        Provide exactly one of ``agent_path``, ``agent`` (with database/schema),
        or no agent argument (for an inline/lite run with ``tools`` supplied).

        Args:
            messages: List of message dicts. Each must have ``role`` and
                ``content`` keys. E.g.::

                    [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]

            agent_path: Dot-separated agent identifier
                (e.g. ``"DB.SCHEMA.MY_AGENT"``).
            database: Database for agent-object runs.
            schema: Schema for agent-object runs.
            agent: Bare agent name (requires database and schema).
            thread_id: Thread ID for context persistence.
            parent_message_id: Parent message ID. Use ``0`` for new threads.
            tool_choice: Tool selection dict, e.g.
                ``{"type": "required", "name": ["Analyst1"]}``.
            tools: Inline tool specs for lite (no-agent-object) runs.
            tool_resources: Inline tool resources for lite runs.
            instructions: Inline instructions for lite runs.
            model: Inline model name for lite runs.

        Yields:
            Typed :class:`~cortex_agents_client.models.events.SSEEvent` subclass
            instances in the order they are received.

        Raises:
            cortex_agents_client.exceptions.AuthError: On HTTP 401.
            cortex_agents_client.exceptions.CortexPermissionError: On HTTP 403.
            cortex_agents_client.exceptions.CortexTimeoutError: On request timeout.
            cortex_agents_client.exceptions.CortexAgentError: On other errors.

        Example::

            for event in client.runs.stream(
                agent_path="DB.SCHEMA.MY_AGENT",
                messages=[{
                    "role": "user",
                    "content": [{"type": "text", "text": "What is revenue?"}],
                }],
            ):
                if isinstance(event, TextDeltaEvent):
                    print(event.text, end="")
        """
        path = self._resolve_path(agent_path, database, schema, agent)
        api_path = path or "/api/v2/cortex/agent:run"
        body = self._build_body(
            messages,
            thread_id=thread_id,
            parent_message_id=parent_message_id,
            tool_choice=tool_choice,
            stream=True,
            tools=tools,
            tool_resources=tool_resources,
            instructions=instructions,
            model=model,
        )

        with self._http.stream("POST", api_path, json=body) as lines:
            for event_type, payload in parse_sse_stream(lines):
                event = event_from_sse(event_type, payload)
                yield event

    def run(
        self,
        messages: list[dict[str, Any]],
        *,
        agent_path: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        agent: str | None = None,
        thread_id: int | None = None,
        parent_message_id: int = 0,
        tool_choice: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_resources: dict[str, Any] | None = None,
        instructions: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> RunResult:
        """Sends a non-streaming request and returns the assembled RunResult.

        Sends a non-streaming request (``stream=False``) and parses the
        single JSON response body into a :class:`RunResult`. Raises
        :class:`~cortex_agents_client.exceptions.RunError` if the agent
        returns a fatal error.

        All arguments are the same as :meth:`stream`.

        Args:
            messages: List of message dicts.
            agent_path: Dot-separated agent identifier.
            database: Database for agent-object runs.
            schema: Schema for agent-object runs.
            agent: Bare agent name.
            thread_id: Thread ID for context persistence.
            parent_message_id: Parent message ID.
            tool_choice: Tool selection constraint dict.
            tools: Inline tool specs for lite runs.
            tool_resources: Inline tool resources for lite runs.
            instructions: Inline instructions for lite runs.
            model: Inline model name for lite runs.

        Returns:
            Fully assembled :class:`RunResult`.

        Raises:
            cortex_agents_client.exceptions.RunError: If the agent emits a fatal
                error event.
            cortex_agents_client.exceptions.AuthError: On HTTP 401.
            cortex_agents_client.exceptions.CortexPermissionError: On HTTP 403.
        """
        path = self._resolve_path(agent_path, database, schema, agent)
        api_path = path or "/api/v2/cortex/agent:run"
        body = self._build_body(
            messages,
            thread_id=thread_id,
            parent_message_id=parent_message_id,
            tool_choice=tool_choice,
            stream=False,
            tools=tools,
            tool_resources=tool_resources,
            instructions=instructions,
            model=model,
        )

        # Try non-streaming request first.
        data = self._http.request("POST", api_path, json=body, resource="agent")
        result = _parse_non_streaming_response(data)

        if result.error:
            raise RunError(
                result.error.message,
                code=result.error.code,
                request_id=result.error.request_id,
            )
        return result

    def stream_and_collect(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> RunResult:
        """Streams events and assembles them into a RunResult.

        Useful when you want the rich event stream for real-time rendering
        but also need the final assembled ``RunResult`` object.

        Args:
            messages: List of message dicts.
            **kwargs: All keyword arguments accepted by :meth:`stream`.

        Returns:
            Fully assembled :class:`RunResult`.

        Raises:
            cortex_agents_client.exceptions.RunError: If the agent emits a fatal
                error event.
        """
        result = RunResult()
        accumulated_text = ""
        accumulated_thinking = ""

        for event in self.stream(messages, **kwargs):
            if isinstance(event, TextDeltaEvent):
                accumulated_text += event.text  # fallback if no TextEvent arrives
            elif isinstance(event, TextEvent):
                result.text += event.text
                accumulated_text = ""  # consumed by the summary event
            elif isinstance(event, ThinkingDeltaEvent):
                accumulated_thinking += event.text  # fallback if no ThinkingEvent arrives
            elif isinstance(event, ThinkingEvent):
                result.thinking = (result.thinking or "") + event.text
                accumulated_thinking = ""  # consumed by the summary event
            elif isinstance(event, TextAnnotationEvent):
                result.annotations.append(event)
            elif isinstance(event, ToolUseEvent):
                result.tool_uses.append(event)
            elif isinstance(event, ToolResultEvent):
                result.tool_results.append(event)
            elif isinstance(event, AnalystDeltaEvent):
                if event.sql:
                    result.analyst_sql[event.tool_use_id] = event.sql
            elif isinstance(event, TableEvent):
                result.tables.append(event)
            elif isinstance(event, ChartEvent):
                result.charts.append(event)
            elif isinstance(event, WarningEvent):
                result.warnings.append(event)
            elif isinstance(event, MetadataEvent):
                result.metadata_events.append(event)
            elif isinstance(event, ErrorEvent):
                result.error = event
                break

        # Commit fallback accumulators — used when the server sends only deltas
        # without a final summary TextEvent/ThinkingEvent.
        if accumulated_text and not result.text:
            result.text = accumulated_text
        if accumulated_thinking and not result.thinking:
            result.thinking = accumulated_thinking

        if result.error:
            raise RunError(
                result.error.message,
                code=result.error.code,
                request_id=result.error.request_id,
            )
        return result
