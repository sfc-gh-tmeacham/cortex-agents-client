"""Resource class for running Cortex Agent interactions.

Provides streaming and non-streaming invocations of the ``agent:run``
endpoint, supporting both agent-object and inline (lite) configurations.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from cortex_agents_client._variables import normalize_variables
from cortex_agents_client.exceptions import RunError
from cortex_agents_client.http import HttpClient
from cortex_agents_client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    MetadataEvent,
    ResponseEvent,
    RunMetadata,
    SSEEvent,
    SuggestedQueriesEvent,
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

_RUNS_BASE = "/api/v2/cortex/agent/runs"

__all__ = ["RunsResource", "RunResult"]


@dataclass
class RunResult:
    """The assembled result of a non-streaming agent run.

    Contains all content types emitted during the run, fully accumulated.
    If the agent returns a fatal error, :meth:`RunsResource.run` and
    :meth:`RunsResource.stream_and_collect` both raise
    :class:`~cortex_agents_client.exceptions.RunError`. Inspect the
    exception's ``code`` and ``request_id`` attributes for details.

    Attributes:
        text: Final assembled text from all ``response.text`` events.
        thinking: Agent reasoning text, or ``None`` if not emitted.
        status: Completion status from the response body.
            ``"completed"`` for a normal non-streaming run;
            ``"cancelled"`` if the run was stopped early;
            ``"timed_out"`` if it exceeded its maximum run length;
            ``"in_progress"`` for a background run that has not finished.
            Empty string when assembled via :meth:`RunsResource.stream_and_collect`.
        tables: List of table events in order of appearance.
        charts: List of chart events in order of appearance.
        tool_uses: List of all tool use events.
        tool_results: List of all tool result events.
        annotations: List of citation annotations.
        warnings: List of warning events.
        metadata_events: Both metadata events (user + assistant message IDs).
        error: Fatal error event, or ``None`` if the run succeeded.
        analyst_sql: Maps tool_use_id to generated SQL strings.
        metadata: Run and message IDs plus token usage, or ``None`` when the
            response carried no ``metadata`` block. For a background run this
            is the only source of the ``run_id`` needed by
            :meth:`RunsResource.stream_run`.
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
    suggested_queries: list[str] = field(default_factory=list)
    metadata: RunMetadata | None = None

    @property
    def run_id(self) -> str | None:
        """The run ID, or ``None`` if the response carried no metadata.

        Returns:
            Run ID string in ``{thread_id}-{user_message_id}`` form.
        """
        return self.metadata.run_id if self.metadata else None


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

    metadata_raw = data.get("metadata")
    if isinstance(metadata_raw, dict):
        result.metadata = RunMetadata._from_dict(metadata_raw)

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

        Raises:
            ValueError: If both *agent_path* and *agent* are given, or the
                path cannot be resolved.
        """
        if agent_path and agent:
            raise ValueError("Pass exactly one of agent_path or agent, not both.")
        db: str | None
        sc: str | None
        if agent_path:
            parts = agent_path.rsplit(".", 2)
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
            return f"/api/v2/databases/{quote(db, safe='')}/schemas/{quote(sc, safe='')}/agents/{quote(name, safe='')}:run"

        if agent:
            db = database or self._default_database
            sc = schema or self._default_schema
            if not db or not sc:
                raise ValueError(
                    "database and schema are required for agent-object runs."
                )
            return f"/api/v2/databases/{quote(db, safe='')}/schemas/{quote(sc, safe='')}/agents/{quote(agent, safe='')}:run"

        return None  # Lite run

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        *,
        thread_id: int | None = None,
        parent_message_id: int = 0,
        tool_choice: dict[str, Any] | None = None,
        stream: bool = True,
        background: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_resources: dict[str, Any] | None = None,
        instructions: dict[str, Any] | None = None,
        orchestration: dict[str, Any] | None = None,
        models: dict[str, Any] | None = None,
        model: str | None = None,
        variables: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Builds the request body for an agent:run call.

        Args:
            messages: List of message dicts with ``role`` and ``content``.
            thread_id: Optional thread ID for context persistence.
            parent_message_id: Parent message ID. Use ``0`` for the first
                turn in a thread.
            tool_choice: Optional tool selection constraint.
            stream: Whether to request streaming SSE response.
            background: Whether to run asynchronously with a 6-hour timeout.
                Only emitted when ``True``.
            tools: Inline tool specs for lite runs.
            tool_resources: Inline tool resources for lite runs.
            instructions: Inline instructions for lite runs.
            orchestration: Inline orchestration config (budget) for lite runs.
            models: Inline model config for lite runs, e.g.
                ``{"orchestration": "claude-4-sonnet"}``.
            model: Deprecated. Bare orchestration model name, mapped to
                ``models``. Ignored when ``models`` is also given.
            variables: Optional session attributes for multi-tenancy. See
                :meth:`stream`. Omitted from the body when empty.

        Returns:
            Request body dict.

        Raises:
            ValueError: If *background* is ``True`` without a *thread_id*, or
                if *variables* is malformed.
        """
        if background and thread_id is None:
            raise ValueError("background=True requires a thread_id.")
        body: dict[str, Any] = {
            "messages": messages,
            "stream": stream,
        }
        if thread_id is not None:
            body["thread_id"] = thread_id
            body["parent_message_id"] = parent_message_id
        if tool_choice:
            body["tool_choice"] = tool_choice
        if background:
            body["background"] = True
        # Inline (lite) config fields
        if tools:
            body["tools"] = tools
        if tool_resources:
            body["tool_resources"] = tool_resources
        if instructions:
            body["instructions"] = instructions
        if orchestration:
            body["orchestration"] = orchestration

        resolved_models = self._resolve_models(models, model)
        if resolved_models:
            body["models"] = resolved_models
        resolved_variables = normalize_variables(variables)
        if resolved_variables:
            body["variables"] = resolved_variables
        return body

    @staticmethod
    def _resolve_models(
        models: dict[str, Any] | None,
        model: str | None,
    ) -> dict[str, Any] | None:
        """Resolves the ``models`` request field from both supported inputs.

        The API expects a ``models`` object (``ModelConfig``). The bare
        ``model`` string is the pre-September-2025 legacy schema and is
        retained only as a deprecated alias.

        Args:
            models: Model config dict, used verbatim when provided.
            model: Deprecated bare orchestration model name.

        Returns:
            The resolved model config dict, or ``None`` when neither
            argument was supplied.
        """
        if models and model:
            warnings.warn(
                "Both 'models' and the deprecated 'model' were given; "
                "'model' is ignored. Pass only "
                "models={'orchestration': ...}.",
                DeprecationWarning,
                stacklevel=3,
            )
            return models
        if models:
            return models
        if model:
            warnings.warn(
                "The 'model' argument is deprecated and reflects the "
                "pre-September-2025 API schema. Use "
                "models={'orchestration': 'claude-4-sonnet'} instead.",
                DeprecationWarning,
                stacklevel=3,
            )
            return {"orchestration": model}
        return None

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
        background: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_resources: dict[str, Any] | None = None,
        instructions: dict[str, Any] | None = None,
        orchestration: dict[str, Any] | None = None,
        models: dict[str, Any] | None = None,
        model: str | None = None,
        variables: Mapping[str, Any] | None = None,
    ) -> Iterator[SSEEvent]:
        """Sends a streaming request to the agent:run endpoint.

        Yields typed SSEEvent objects as they arrive from the server. All 17
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
            background: Run asynchronously with a 6-hour timeout instead of
                the default 15-minute synchronous timeout. Requires
                ``thread_id``. The run survives a client disconnect and can
                be resumed with :meth:`stream_run`.
            tools: Inline tool specs for lite (no-agent-object) runs.
            tool_resources: Inline tool resources for lite runs.
            instructions: Inline instructions for lite runs.
            orchestration: Inline orchestration config for lite runs, e.g.
                ``{"budget": {"seconds": 30, "tokens": 16000}}``.
            models: Inline model config for lite runs, e.g.
                ``{"orchestration": "claude-4-sonnet"}``.
            model: Deprecated alias for ``models``. Pass ``models`` instead.
            variables: Optional session attributes for multi-tenancy, set on
                the Snowflake session before any generated SQL runs so row
                access policies can read them with
                ``SYS_CONTEXT('SNOWFLAKE$SESSION_ATTRIBUTES', '<name>')``.
                Each value is a scalar (``{"region": "NORTH"}``) or a dict in
                the REST shape (``{"value": ..., "type": ...,
                "is_immutable_session_attribute": ...}``). Both forms default
                to immutable. Works on agent-object and lite runs.

        Note:
            ``tools``, ``tool_resources``, ``instructions``, ``orchestration``,
            and ``models`` apply only to lite runs. The API rejects attempts
            to set them on an agent-object run; change the agent object with
            :meth:`~cortex_agents_client.resources.agents.AgentsResource.update`
            instead.

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
            background=background,
            tools=tools,
            tool_resources=tool_resources,
            instructions=instructions,
            orchestration=orchestration,
            models=models,
            model=model,
            variables=variables,
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
        background: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_resources: dict[str, Any] | None = None,
        instructions: dict[str, Any] | None = None,
        orchestration: dict[str, Any] | None = None,
        models: dict[str, Any] | None = None,
        model: str | None = None,
        variables: Mapping[str, Any] | None = None,
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
            background: Run asynchronously with a 6-hour timeout. Requires
                ``thread_id``. The call returns immediately with
                ``status="in_progress"`` and a populated ``run_id``; collect
                the output later with :meth:`stream_run`.
            tools: Inline tool specs for lite runs.
            tool_resources: Inline tool resources for lite runs.
            instructions: Inline instructions for lite runs.
            orchestration: Inline orchestration config for lite runs.
            models: Inline model config for lite runs, e.g.
                ``{"orchestration": "claude-4-sonnet"}``.
            model: Deprecated alias for ``models``.
            variables: Optional session attributes for multi-tenancy. See
                :meth:`stream`.

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
            background=background,
            tools=tools,
            tool_resources=tool_resources,
            instructions=instructions,
            orchestration=orchestration,
            models=models,
            model=model,
            variables=variables,
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

    def stream_run(
        self,
        run_id: str,
        *,
        starting_after: int | None = None,
    ) -> Iterator[SSEEvent]:
        """Reconnects to an agent run and streams its output.

        Yields the same typed events as :meth:`stream`. Use this to resume a
        background run, or to recover from a dropped connection.

        A run's events are available only while it is active and for up to
        5 minutes after it completes. Past that window, this raises
        :class:`~cortex_agents_client.exceptions.RunNotActiveError`; retrieve
        the response from the thread instead (see
        :meth:`~cortex_agents_client.resources.threads.ThreadsResource.list_messages`).
        Note that the 5-minute window is the documented contract and was not
        enforced in live testing, so treat it as a lower bound rather than a
        guarantee that the run has become unavailable.

        Args:
            run_id: The run identifier, in ``{thread_id}-{user_message_id}``
                form. Available from :attr:`RunResult.run_id`,
                :attr:`~cortex_agents_client.models.events.ResponseEvent.run_id`,
                or :attr:`~cortex_agents_client.models.events.MetadataEvent.run_id`.
            starting_after: Sequence number to resume from, exclusive. Omit
                to replay the entire output from the beginning.

        Yields:
            Typed :class:`~cortex_agents_client.models.events.SSEEvent`
            subclass instances in the order they are received.

        Raises:
            cortex_agents_client.exceptions.RunNotActiveError: On HTTP 409 if
                the run finished more than 5 minutes ago.
            cortex_agents_client.exceptions.AuthError: On HTTP 401.
            cortex_agents_client.exceptions.CortexPermissionError: On HTTP 403.

        Example::

            result = client.runs.run(
                messages=[...], agent_path="DB.SCHEMA.MY_AGENT",
                thread_id=thread.thread_id, background=True,
            )
            for event in client.runs.stream_run(result.run_id):
                ...
        """
        params: dict[str, Any] | None = None
        if starting_after is not None:
            params = {"starting_after": starting_after}

        with self._http.stream(
            "GET",
            f"{_RUNS_BASE}/{quote(run_id, safe='')}",
            params=params,
            resource="run",
        ) as lines:
            for event_type, payload in parse_sse_stream(lines):
                yield event_from_sse(event_type, payload)

    def cancel_run(self, run_id: str) -> RunMetadata:
        """Cancels an actively running agent run.

        Any partial output produced before cancellation is saved to the
        thread and billed. When partial output was saved,
        :attr:`~cortex_agents_client.models.events.RunMetadata.assistant_message_id`
        is populated and can be used as the ``parent_message_id`` for the
        next turn.

        Args:
            run_id: The run identifier, in ``{thread_id}-{user_message_id}``
                form.

        Returns:
            :class:`~cortex_agents_client.models.events.RunMetadata` for the
            cancelled run.

        Raises:
            cortex_agents_client.exceptions.RunNotActiveError: On HTTP 409 if
                the run has already completed or been cancelled.
            cortex_agents_client.exceptions.AuthError: On HTTP 401.
            cortex_agents_client.exceptions.CortexPermissionError: On HTTP 403.
        """
        data = self._http.request(
            "POST",
            f"{_RUNS_BASE}/{quote(run_id, safe='')}/cancel",
            resource="run",
        )
        metadata_raw = data.get("metadata") if isinstance(data, dict) else None
        return RunMetadata._from_dict(metadata_raw or {})

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
            **kwargs: All keyword arguments accepted by :meth:`stream`,
                including ``variables``.

        Returns:
            Fully assembled :class:`RunResult`.

        Raises:
            cortex_agents_client.exceptions.RunError: If the agent emits a fatal
                error event.
        """
        result = RunResult()
        # Per-block ordered segments. Deltas accumulate into a block's entry
        # until its summary event replaces them, so a block that never gets a
        # summary event still contributes its deltas.
        text_blocks: dict[int, str] = {}
        thinking_blocks: dict[int, str] = {}
        text_final: set[int] = set()
        thinking_final: set[int] = set()

        for event in self.stream(messages, **kwargs):
            if isinstance(event, TextDeltaEvent):
                if event.content_index not in text_final:
                    text_blocks[event.content_index] = (
                        text_blocks.get(event.content_index, "") + event.text
                    )
            elif isinstance(event, TextEvent):
                if event.content_index in text_final:
                    text_blocks[event.content_index] += event.text
                else:
                    text_blocks[event.content_index] = event.text
                    text_final.add(event.content_index)
            elif isinstance(event, ThinkingDeltaEvent):
                if event.content_index not in thinking_final:
                    thinking_blocks[event.content_index] = (
                        thinking_blocks.get(event.content_index, "") + event.text
                    )
            elif isinstance(event, ThinkingEvent):
                if event.content_index in thinking_final:
                    thinking_blocks[event.content_index] += event.text
                else:
                    thinking_blocks[event.content_index] = event.text
                    thinking_final.add(event.content_index)
            elif isinstance(event, TextAnnotationEvent):
                result.annotations.append(event)
            elif isinstance(event, ToolUseEvent):
                result.tool_uses.append(event)
                # Extract SQL from system_execute_sql (Apr 2026+ Cortex Analyst)
                if event.type == "system_execute_sql" and event.input.get("sql"):
                    result.analyst_sql[event.tool_use_id] = event.input["sql"]
            elif isinstance(event, ToolResultEvent):
                result.tool_results.append(event)
            elif isinstance(event, AnalystDeltaEvent):
                # Legacy path: pre-Apr 2026 deployments still emit analyst.delta
                if event.sql:
                    result.analyst_sql[event.tool_use_id] = event.sql
            elif isinstance(event, TableEvent):
                result.tables.append(event)
            elif isinstance(event, ChartEvent):
                result.charts.append(event)
            elif isinstance(event, WarningEvent):
                result.warnings.append(event)
            elif isinstance(event, SuggestedQueriesEvent):
                result.suggested_queries = event.queries
            elif isinstance(event, MetadataEvent):
                result.metadata_events.append(event)
            elif isinstance(event, ResponseEvent):
                result.status = event.status
                result.metadata = RunMetadata(
                    run_id=event.run_id,
                    thread_id=event.thread_id,
                    user_message_id=event.user_message_id,
                    assistant_message_id=event.assistant_message_id,
                    usage=event.usage,
                )
            elif isinstance(event, ErrorEvent):
                result.error = event
                break

        result.text = "".join(text_blocks[i] for i in sorted(text_blocks))
        if thinking_blocks:
            result.thinking = "".join(
                thinking_blocks[i] for i in sorted(thinking_blocks)
            )

        if result.error:
            raise RunError(
                result.error.message,
                code=result.error.code,
                request_id=result.error.request_id,
            )
        return result
