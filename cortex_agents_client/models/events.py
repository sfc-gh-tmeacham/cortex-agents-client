"""Typed dataclasses for all Cortex Agents SSE event types.

16 event dataclasses (emitted by the ``agent:run`` endpoint) plus
``UnknownEvent`` (catch-all for unknown types) and three token-usage models
(``InputTokens``, ``OutputTokens``, ``TokensConsumed``) used by
``ResponseEvent.usage``.

Each event class has a ``_from_payload`` class method that constructs the
instance from the raw SSE JSON dict.

The factory function :func:`cortex_agents_client.sse.event_from_sse` uses these
classes to dispatch events by type string.

Unknown event types are represented by :class:`UnknownEvent` and never
raise an exception — ensuring forward-compatibility with new tool types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _parse_bool(value: Any) -> bool:
    """Coerce a value that may be a JSON boolean or the strings ``"true"``/``"false"``
    to a Python bool.

    The Cortex Agents API occasionally sends ``"client_side_execute": "true"``
    as a JSON string rather than a boolean literal. ``bool("false")`` evaluates
    to ``True`` in Python (non-empty string), which would silently invert the flag.
    """
    if isinstance(value, str):
        return value.lower() == "true"
    return bool(value)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


@dataclass
class SSEEvent:
    """Base class for all SSE event types.

    Attributes:
        event_type: The raw SSE event type string
            (e.g. ``"response.text.delta"``).
    """

    event_type: str


# ---------------------------------------------------------------------------
# Text events
# ---------------------------------------------------------------------------


@dataclass
class TextDeltaEvent(SSEEvent):
    """A token-by-token text streaming delta.

    Emitted as the agent generates its response text. Accumulate consecutive
    deltas for the same ``content_index`` to reconstruct the full text.

    Attributes:
        event_type: Always ``"response.text.delta"``.
        content_index: Index of this content block in the response array.
        text: The incremental text token. The API field name is ``text``;
            the legacy name ``delta`` is available as an alias for backward
            compatibility.
        is_elicitation: If ``True``, this text is the agent asking the user
            for more information (a clarifying question). Render differently
            from regular assistant text — see
            :func:`cortex_agents_client.st.render.render_streaming_response`.
    """

    content_index: int = 0
    text: str = ""
    is_elicitation: bool = False

    @property
    def delta(self) -> str:
        """Alias for :attr:`text` kept for backward compatibility.

        Returns:
            The text token.
        """
        return self.text

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> TextDeltaEvent:
        """Constructs a TextDeltaEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated TextDeltaEvent instance.
        """
        return cls(
            event_type="response.text.delta",
            content_index=payload.get("content_index", 0),
            text=payload.get("text", ""),
            is_elicitation=bool(payload.get("is_elicitation", False)),
        )


@dataclass
class TextEvent(SSEEvent):
    """A complete text content block after all deltas have been sent.

    Attributes:
        event_type: Always ``"response.text"``.
        content_index: Index of this content block in the response array.
        text: The full assembled text (may contain ``[^N]`` citation markers).
        annotations: Inline citation annotations attached to this text block.
            These are also delivered as separate ``response.text.annotation``
            events; both sources reference the same citations.
        is_elicitation: If ``True``, the agent is asking the user for more
            information (a clarifying question) rather than providing an
            answer. Render differently from regular assistant text.
    """

    content_index: int = 0
    text: str = ""
    annotations: list[dict[str, Any]] = field(default_factory=list)
    is_elicitation: bool = False

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> TextEvent:
        """Constructs a TextEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated TextEvent instance.
        """
        return cls(
            event_type="response.text",
            content_index=payload.get("content_index", 0),
            text=payload.get("text", ""),
            annotations=payload.get("annotations") or [],
            is_elicitation=bool(payload.get("is_elicitation", False)),
        )


@dataclass
class TextAnnotationEvent(SSEEvent):
    """A citation annotation embedded within a text block.

    Emitted alongside ``response.text`` events. The ``index`` field
    corresponds to ``[^N]`` citation markers in the text.

    Attributes:
        event_type: Always ``"response.text.annotation"``.
        content_index: Index of the text block this annotation belongs to.
        annotation_type: Type of annotation; currently always
            ``"cortex_search_citation"``.
        index: Citation index matching ``[^N]`` markers in the text.
        search_result_id: Unique ID of the Cortex Search result.
        doc_id: Unique ID of the source document.
        doc_title: Title of the source document.
        text: Text excerpt from the document used as the citation.
    """

    content_index: int = 0
    annotation_index: int = 0
    annotation_type: str = ""
    index: int = 0
    search_result_id: str = ""
    doc_id: str = ""
    doc_title: str = ""
    text: str = ""

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> TextAnnotationEvent:
        """Constructs a TextAnnotationEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated TextAnnotationEvent instance.
        """
        annotation = payload.get("annotation", {})
        return cls(
            event_type="response.text.annotation",
            content_index=payload.get("content_index", 0),
            annotation_index=payload.get("annotation_index", 0),
            annotation_type=annotation.get("type", ""),
            index=annotation.get("index", 0),
            search_result_id=annotation.get("search_result_id", ""),
            doc_id=annotation.get("doc_id", ""),
            doc_title=annotation.get("doc_title", ""),
            text=annotation.get("text", ""),
        )


# ---------------------------------------------------------------------------
# Thinking events
# ---------------------------------------------------------------------------


@dataclass
class ThinkingDeltaEvent(SSEEvent):
    """A streaming thinking token from the agent's reasoning process.

    Only emitted by models that support extended thinking (Claude 3.5+).
    Accumulate deltas for the same ``content_index`` to build the full
    ``ThinkingEvent.text``.

    Attributes:
        event_type: Always ``"response.thinking.delta"``.
        content_index: Index of this thinking block in the response array.
        text: The incremental thinking token.
        signature: Authentication signature for the thinking block.
    """

    content_index: int = 0
    text: str = ""
    signature: str = ""

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> ThinkingDeltaEvent:
        """Constructs a ThinkingDeltaEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated ThinkingDeltaEvent instance.
        """
        return cls(
            event_type="response.thinking.delta",
            content_index=payload.get("content_index", 0),
            text=payload.get("text", ""),
            signature=payload.get("signature", ""),
        )


@dataclass
class ThinkingEvent(SSEEvent):
    """A complete agent reasoning block after all deltas have been sent.

    Attributes:
        event_type: Always ``"response.thinking"``.
        content_index: Index of this thinking block in the response array.
        text: The full assembled thinking text.
        signature: Authentication signature for the thinking block.
    """

    content_index: int = 0
    text: str = ""
    signature: str = ""

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> ThinkingEvent:
        """Constructs a ThinkingEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated ThinkingEvent instance.
        """
        return cls(
            event_type="response.thinking",
            content_index=payload.get("content_index", 0),
            text=payload.get("text", ""),
            signature=payload.get("signature", ""),
        )


# ---------------------------------------------------------------------------
# Tool events
# ---------------------------------------------------------------------------


@dataclass
class ToolUseEvent(SSEEvent):
    """The agent is requesting execution of a tool.

    If ``permission_options`` is non-empty, the client must send a
    ``permission_decision`` message before the tool executes.

    Attributes:
        event_type: Always ``"response.tool_use"``.
        content_index: Index of this content block in the response array.
        tool_use_id: Unique identifier for this tool invocation.
        type: The tool type (e.g. ``"system_execute_sql"``, ``"cortex_search"``,
            ``"generic"``). As of Apr 2026, Cortex Analyst uses
            ``"system_execute_sql"`` (previously ``"cortex_analyst_text_to_sql"``).
            The generated SQL is in ``input["sql"]``.
        name: The tool instance name configured on the agent.
        input: The structured input arguments for the tool.
        client_side_execute: If ``True``, the client must execute this tool
            and return results in the next request.
        permission_options: Non-empty list means user approval is required
            before execution (e.g. ``["Allow Once", "Deny"]``).
    """

    content_index: int = 0
    tool_use_id: str = ""
    type: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    client_side_execute: bool = False
    permission_options: list[str] = field(default_factory=list)

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> ToolUseEvent:
        """Constructs a ToolUseEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated ToolUseEvent instance.
        """
        permission = payload.get("permission") or {}
        return cls(
            event_type="response.tool_use",
            content_index=payload.get("content_index", 0),
            tool_use_id=payload.get("tool_use_id", ""),
            type=payload.get("type", ""),
            name=payload.get("name", ""),
            input=payload.get("input") or {},
            # The API may send "true"/"false" as a JSON string instead of a boolean.
            # bool("false") == True in Python, so we need a string-aware coercion.
            client_side_execute=_parse_bool(payload.get("client_side_execute", False)),
            permission_options=permission.get("options") or [],
        )


@dataclass
class ToolResultEvent(SSEEvent):
    """Tool execution is complete.

    Attributes:
        event_type: Always ``"response.tool_result"``.
        content_index: Index of this content block in the response array.
        tool_use_id: ID matching the corresponding :class:`ToolUseEvent`.
        type: The tool type.
        name: The tool instance name.
        content: List of result content items. Each item has a ``type``
            field (``"json"`` or ``"text"``) and a corresponding value.
        status: ``"success"`` or ``"error"``.
    """

    content_index: int = 0
    tool_use_id: str = ""
    type: str = ""
    name: str = ""
    content: list[dict[str, Any]] = field(default_factory=list)
    status: str = ""

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> ToolResultEvent:
        """Constructs a ToolResultEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated ToolResultEvent instance.
        """
        return cls(
            event_type="response.tool_result",
            content_index=payload.get("content_index", 0),
            tool_use_id=payload.get("tool_use_id", ""),
            type=payload.get("type", ""),
            name=payload.get("name", ""),
            content=payload.get("content") or [],
            status=payload.get("status", ""),
        )


@dataclass
class ToolResultStatusEvent(SSEEvent):
    """In-progress status update for a running tool.

    Useful for showing progress spinners or status text while a long-running
    tool (e.g. a SQL query) is executing.

    Attributes:
        event_type: Always ``"response.tool_result.status"``.
        tool_use_id: ID of the running tool invocation.
        tool_type: The tool type string.
        status: Short status description (e.g. ``"Executing SQL"``).
        message: Longer human-readable status message.
        details: Tool-specific details dict (may be empty).
    """

    tool_use_id: str = ""
    tool_type: str = ""
    status: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> ToolResultStatusEvent:
        """Constructs a ToolResultStatusEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated ToolResultStatusEvent instance.
        """
        return cls(
            event_type="response.tool_result.status",
            tool_use_id=payload.get("tool_use_id", ""),
            tool_type=payload.get("tool_type", ""),
            status=payload.get("status", ""),
            message=payload.get("message", ""),
            details=payload.get("details") or {},
        )


# ---------------------------------------------------------------------------
# Cortex Analyst delta
# ---------------------------------------------------------------------------


@dataclass
class AnalystDeltaEvent(SSEEvent):
    """Streaming delta from the Cortex Analyst tool.

    .. deprecated:: Apr 2026
        As of the Apr 13, 2026 API update, Cortex Analyst no longer emits
        ``response.tool_result.analyst.delta`` events. SQL is now delivered in
        ``ToolUseEvent.input["sql"]`` for events with ``type="system_execute_sql"``.
        This class is retained for backward compatibility with older deployments.

    Contains progressive output as Analyst generates SQL, executes it, and
    returns results. All delta fields are optional — not every delta
    contains all fields.

    Attributes:
        event_type: Always ``"response.tool_result.analyst.delta"``.
        content_index: Index of this content block in the response array.
        tool_use_id: ID of the Analyst tool invocation.
        tool_type: The Analyst tool type string (``"system_execute_sql"`` on
            Apr 2026+ deployments; ``"cortex_analyst_text_to_sql"`` on older ones).
        tool_name: The Analyst tool instance name.
        text: Incremental text from Analyst's narrative response.
        think: Incremental text from Analyst's reasoning process.
        sql: The generated SQL query (sent whole, not incrementally).
        sql_explanation: Human-readable explanation of the SQL.
        query_id: Snowflake query ID once SQL execution begins.
        verified_query_used: Whether a pre-verified query was used.
        result_set: SQL execution results in Snowflake jsonv2 format.
        suggestion_index: Index of a suggested question when Analyst cannot
            answer the original question.
        suggestion_delta: Incremental text for a suggested question.
    """

    content_index: int = 0
    tool_use_id: str = ""
    tool_type: str = ""
    tool_name: str = ""
    text: str | None = None
    think: str | None = None
    sql: str | None = None
    sql_explanation: str | None = None
    query_id: str | None = None
    verified_query_used: bool | None = None
    result_set: dict[str, Any] | None = None
    suggestion_index: int | None = None
    suggestion_delta: str | None = None

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> AnalystDeltaEvent:
        """Constructs an AnalystDeltaEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated AnalystDeltaEvent instance.
        """
        delta = payload.get("delta") or {}
        suggestions = delta.get("suggestions")
        return cls(
            event_type="response.tool_result.analyst.delta",
            content_index=payload.get("content_index", 0),
            tool_use_id=payload.get("tool_use_id", ""),
            tool_type=payload.get("tool_type", ""),
            tool_name=payload.get("tool_name", ""),
            text=delta.get("text"),
            think=delta.get("think"),
            sql=delta.get("sql"),
            sql_explanation=delta.get("sql_explanation"),
            query_id=delta.get("query_id"),
            verified_query_used=delta.get("verified_query_used"),
            result_set=delta.get("result_set"),
            suggestion_index=suggestions.get("index") if isinstance(suggestions, dict) else None,
            suggestion_delta=suggestions.get("delta") if isinstance(suggestions, dict) else None,
        )


# ---------------------------------------------------------------------------
# Table and chart events
# ---------------------------------------------------------------------------


@dataclass
class TableEvent(SSEEvent):
    """A SQL result table.

    Emitted when a tool (typically Cortex Analyst) returns tabular data.
    The ``result_set`` follows the Snowflake SQL API ``jsonv2`` format.

    Attributes:
        event_type: Always ``"response.table"``.
        content_index: Index of this content block in the response array.
        tool_use_id: ID of the tool that generated this table.
        query_id: Snowflake query ID of the SQL that produced the data.
        result_set: Dict containing ``resultSetMetaData`` (with ``rowType``
            describing columns) and ``data`` (list of string rows).
        title: Optional human-readable title for the table.
    """

    content_index: int = 0
    tool_use_id: str = ""
    query_id: str = ""
    result_set: dict[str, Any] = field(default_factory=dict)
    title: str | None = None

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> TableEvent:
        """Constructs a TableEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated TableEvent instance.
        """
        return cls(
            event_type="response.table",
            content_index=payload.get("content_index", 0),
            tool_use_id=payload.get("tool_use_id", ""),
            query_id=payload.get("query_id", ""),
            result_set=payload.get("result_set") or {},
            title=payload.get("title"),
        )


@dataclass
class ChartEvent(SSEEvent):
    """A Vega-Lite chart specification.

    Emitted by the "Data to Chart" tool. ``chart_spec`` is a JSON *string*
    (not a dict) and must be parsed with ``json.loads()`` before rendering.

    Attributes:
        event_type: Always ``"response.chart"``.
        content_index: Index of this content block in the response array.
        tool_use_id: ID of the tool that generated this chart.
        chart_spec: Vega-Lite v5 specification serialised as a JSON string.
    """

    content_index: int = 0
    tool_use_id: str = ""
    chart_spec: str = ""

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> ChartEvent:
        """Constructs a ChartEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated ChartEvent instance.
        """
        return cls(
            event_type="response.chart",
            content_index=payload.get("content_index", 0),
            tool_use_id=payload.get("tool_use_id", ""),
            chart_spec=payload.get("chart_spec", ""),
        )


# ---------------------------------------------------------------------------
# Suggested queries
# ---------------------------------------------------------------------------


@dataclass
class SuggestedQueriesEvent(SSEEvent):
    """Follow-up question suggestions from the agent.

    Emitted near the end of a response with suggested follow-up queries the
    user might ask next. Useful for building "quick reply" buttons in chat UIs.

    Attributes:
        event_type: Always ``"response.suggested_queries"``.
        content_index: Index of this content block in the response array.
        queries: List of suggested question strings.
    """

    content_index: int = 0
    queries: list[str] = field(default_factory=list)

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> SuggestedQueriesEvent:
        """Constructs a SuggestedQueriesEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated SuggestedQueriesEvent instance.
        """
        items = payload.get("suggested_queries") or []
        return cls(
            event_type="response.suggested_queries",
            content_index=payload.get("content_index", 0),
            queries=[item["query"] for item in items if isinstance(item, dict) and "query" in item],
        )


# ---------------------------------------------------------------------------
# Status, warning, error, metadata
# ---------------------------------------------------------------------------


@dataclass
class StatusEvent(SSEEvent):
    """High-level execution status update.

    Not tied to a specific tool. Used to track overall agent progress.

    Attributes:
        event_type: Always ``"response.status"``.
        status: Status identifier (e.g. ``"executing_tool"``).
        message: Human-readable description of the current state.
    """

    status: str = ""
    message: str = ""

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> StatusEvent:
        """Constructs a StatusEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated StatusEvent instance.
        """
        return cls(
            event_type="response.status",
            status=payload.get("status", ""),
            message=payload.get("message", ""),
        )


@dataclass
class WarningEvent(SSEEvent):
    """A non-fatal warning. The stream continues after this event.

    Attributes:
        event_type: Always ``"response.warning"``.
        message: Human-readable warning message.
        code: Optional structured warning code for programmatic handling.
    """

    message: str = ""
    code: str | None = None

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> WarningEvent:
        """Constructs a WarningEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated WarningEvent instance.
        """
        return cls(
            event_type="response.warning",
            message=payload.get("message", ""),
            code=payload.get("code"),
        )


@dataclass
class ErrorEvent(SSEEvent):
    """A fatal error that terminates the stream.

    When the :class:`cortex_agents_client.resources.RunsResource` encounters this
    event, it raises :class:`cortex_agents_client.exceptions.RunError`.

    Attributes:
        event_type: Always ``"error"``.
        code: Snowflake error code string.
        message: Human-readable error description.
        request_id: Snowflake request ID for tracing.
    """

    code: str = ""
    message: str = ""
    request_id: str = ""

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> ErrorEvent:
        """Constructs an ErrorEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated ErrorEvent instance.
        """
        # ``error_code`` is a deprecated alias for ``code``.
        code = payload.get("code") or payload.get("error_code", "")
        return cls(
            event_type="error",
            code=str(code),
            message=payload.get("message", ""),
            request_id=payload.get("request_id", ""),
        )


@dataclass
class MetadataEvent(SSEEvent):
    """Thread message persistence confirmation.

    Sent twice per run: once for the user message and once for the assistant
    message. The assistant ``message_id`` is the ``parent_message_id`` for
    the next conversation turn.

    Attributes:
        event_type: Always ``"metadata"``.
        role: ``"user"`` or ``"assistant"``.
        message_id: The persisted thread message ID.
        run_id: Identifier for this run.
    """

    role: str = ""
    message_id: int = 0
    run_id: str | None = None

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> MetadataEvent:
        """Constructs a MetadataEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated MetadataEvent instance.
        """
        meta = payload.get("metadata") or {}
        return cls(
            event_type="metadata",
            role=meta.get("role", ""),
            message_id=int(meta.get("message_id", 0)),
            run_id=meta.get("run_id"),
        )


# ---------------------------------------------------------------------------
# Token usage types (used by ResponseEvent)
# ---------------------------------------------------------------------------


@dataclass
class InputTokens:
    """Input token breakdown for one model call.

    Attributes:
        total: Total input tokens processed (including cached tokens).
        cache_read: Input tokens read from cache.
        cache_write: Input tokens written to cache.
        uncached: Input tokens that were not cached.
    """

    total: int = 0
    cache_read: int = 0
    cache_write: int = 0
    uncached: int = 0

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> InputTokens:
        """Constructs from a raw input_tokens dict."""
        return cls(
            total=int(d.get("total", 0)),
            cache_read=int(d.get("cache_read", 0)),
            cache_write=int(d.get("cache_write", 0)),
            uncached=int(d.get("uncached", 0)),
        )


@dataclass
class OutputTokens:
    """Output token details for one model call.

    Attributes:
        total: Total output tokens generated.
    """

    total: int = 0

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> OutputTokens:
        """Constructs from a raw output_tokens dict."""
        return cls(total=int(d.get("total", 0)))


@dataclass
class TokensConsumed:
    """Token consumption for a specific model used during the run.

    One entry per model. A run may use more than one model (e.g. a planning
    model and a tool-execution model).

    Attributes:
        model_name: Name of the model (e.g. ``"claude-3-5-sonnet"``).
        input_tokens: Input token breakdown.
        output_tokens: Output token details.
        context_window: The model's context window size in tokens.
    """

    model_name: str = ""
    input_tokens: InputTokens = field(default_factory=InputTokens)
    output_tokens: OutputTokens = field(default_factory=OutputTokens)
    context_window: int = 0

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> TokensConsumed:
        """Constructs from a raw tokens_consumed dict."""
        return cls(
            model_name=d.get("model_name", ""),
            input_tokens=InputTokens._from_dict(d.get("input_tokens") or {}),
            output_tokens=OutputTokens._from_dict(d.get("output_tokens") or {}),
            context_window=int(d.get("context_window", 0)),
        )


# ---------------------------------------------------------------------------
# Final aggregated response event
# ---------------------------------------------------------------------------


@dataclass
class ResponseEvent(SSEEvent):
    """The final aggregated response — always the last event in the stream.

    Emitted once, after all other events. For streaming clients this is
    largely redundant (all content has already been delivered via individual
    events), but it is the only source of:

    - ``status``: set to ``"cancelled"`` when the run was terminated early
      via CancelAgentRun; "completed" for normal completion.
    - ``usage``: per-model token counts for the entire run.
    - ``run_id`` / ``thread_id``: stable IDs for the run and thread.
    - ``user_message_id`` / ``assistant_message_id``: persisted message IDs
      (also available from :class:`MetadataEvent`, but repeated here).

    ``content`` and ``warnings`` are kept as raw dicts because they mirror
    the full nested MessageContentItem / Warning schemas; use the individual
    typed events for structured access to those values.

    Attributes:
        event_type: Always ``"response"``.
        role: Always ``"assistant"``.
        content: All content blocks produced during the run (raw dicts).
        warnings: All non-fatal warnings produced during the run (raw dicts).
        status: Completion status. ``"cancelled"`` if the run was stopped
            early via CancelAgentRun; "completed" for normal completion.
        usage: Per-model token consumption for this run. One
            :class:`TokensConsumed` entry per model used.
        run_id: Unique identifier for this run.
        thread_id: ID of the thread this run belongs to.
        user_message_id: Persisted ID of the user message.
        assistant_message_id: Persisted ID of the assistant message.
    """

    role: str = "assistant"
    content: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    status: str = ""
    usage: list[TokensConsumed] = field(default_factory=list)
    run_id: str | None = None
    thread_id: int | None = None
    user_message_id: int | None = None
    assistant_message_id: int | None = None

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> ResponseEvent:
        """Constructs a ResponseEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.

        Returns:
            A populated ResponseEvent instance.
        """
        meta = payload.get("metadata") or {}
        usage_meta = meta.get("usage") or {}
        tokens_consumed = [
            TokensConsumed._from_dict(t)
            for t in (usage_meta.get("tokens_consumed") or [])
        ]
        return cls(
            event_type="response",
            role=payload.get("role", "assistant"),
            content=payload.get("content") or [],
            warnings=payload.get("warnings") or [],
            status=payload.get("status", ""),
            usage=tokens_consumed,
            run_id=meta.get("run_id"),
            thread_id=meta.get("thread_id"),
            user_message_id=meta.get("user_message_id"),
            assistant_message_id=meta.get("assistant_message_id"),
        )


# ---------------------------------------------------------------------------
# Unknown / parse error events
# ---------------------------------------------------------------------------


@dataclass
class UnknownEvent(SSEEvent):
    """An event with an unrecognised type or unparseable payload.

    Ensures forward-compatibility with new event types introduced in future
    Snowflake releases. The library never raises on unknown types.

    Attributes:
        event_type: The raw event type string.
        raw_payload: The unparsed payload dict (or ``{"raw": "..."}`` if
            JSON parsing failed).
    """

    raw_payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def _from_payload(cls, payload: dict[str, Any], *, event_type: str = "unknown") -> UnknownEvent:
        """Constructs an UnknownEvent from a raw SSE payload.

        Args:
            payload: Parsed JSON dict from the SSE data field.
            event_type: The original SSE event type string. Defaults to
                ``"unknown"`` for backward compatibility but should always
                be provided so the actual type is preserved.

        Returns:
            A populated UnknownEvent instance.
        """
        return cls(event_type=event_type, raw_payload=payload)
