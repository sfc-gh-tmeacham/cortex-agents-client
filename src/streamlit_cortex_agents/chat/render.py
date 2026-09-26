"""Streamlit rendering functions for Cortex Agent SSE events.

Provides two rendering code paths that produce equivalent content:

1. :func:`render_streaming_response`: Used during live streaming of a new
   assistant turn. Renders each event type as it arrives and returns a
   :class:`~streamlit_cortex_agents.client.models.thread.StoredMessage` for session state.
   Reasoning and tool calls render as steps in one collapsible timeline.

2. :func:`render_stored_message`: Used on every Streamlit rerun to replay
   stored messages from ``st.session_state``. Reproduces the final content
   of path 1, with the reasoning timeline collapsed.

Also provides :func:`result_set_to_dataframe` for converting Snowflake
``jsonv2`` result sets to pandas DataFrames.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from html import escape as html_escape
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

from streamlit_cortex_agents.client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    MetadataEvent,
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
    WarningEvent,
)
from streamlit_cortex_agents.client.models.thread import StoredMessage

logger = logging.getLogger(__name__)

# Snowflake SQL API type → pandas dtype mapping.
_SNOWFLAKE_DTYPE_MAP: dict[str, str] = {
    "FIXED": "Int64",          # nullable integer
    "INTEGER": "Int64",
    "INT": "Int64",
    "BIGINT": "Int64",
    "SMALLINT": "Int64",
    "TINYINT": "Int64",
    "BYTEINT": "Int64",
    "REAL": "float64",
    "FLOAT": "float64",
    "FLOAT4": "float64",
    "FLOAT8": "float64",
    "DOUBLE": "float64",
    "DECIMAL": "float64",
    "NUMERIC": "float64",
    "NUMBER": "float64",       # generic Snowflake numeric (float64 is safe regardless of scale)
    "BOOLEAN": "boolean",      # nullable boolean
    "TIMESTAMP_NTZ": "datetime64[ns]",
    "TIMESTAMP_LTZ": "datetime64[ns]",
    "TIMESTAMP_TZ": "datetime64[ns]",
    "DATE": "datetime64[ns]",
    # TIME is intentionally absent — stays as object string (no pandas time type)
}


def result_set_to_dataframe(event: TableEvent) -> pd.DataFrame:
    """Converts a Snowflake jsonv2 result set to a pandas DataFrame.

    All values in the Snowflake ``jsonv2`` wire format are strings. This
    function uses the ``rowType`` metadata to cast each column to the
    appropriate dtype.

    Args:
        event: A :class:`~streamlit_cortex_agents.client.models.events.TableEvent` containing
            the result set.

    Returns:
        A pandas DataFrame with correctly typed columns.

    Raises:
        ImportError: If ``pandas`` is not installed.

    Example::

        df = result_set_to_dataframe(table_event)
        st.dataframe(df)
    """
    import pandas as pd

    result_set = event.result_set
    metadata = result_set.get("resultSetMetaData") or {}
    row_types = metadata.get("rowType") or []
    data = result_set.get("data") or []

    if not row_types:
        return pd.DataFrame()

    columns = [rt["name"] for rt in row_types]
    df = pd.DataFrame(data, columns=columns)

    for row_type in row_types:
        col_name = row_type["name"]
        sf_type = row_type.get("type", "").upper()
        dtype = _SNOWFLAKE_DTYPE_MAP.get(sf_type)
        if dtype and col_name in df.columns:
            try:
                df[col_name] = df[col_name].astype(dtype)
            except (ValueError, TypeError):
                logger.debug(
                    "Could not cast column '%s' to dtype '%s'; keeping as string.",
                    col_name,
                    dtype,
                )

    return df


# Streamlit's markdown renderer treats $...$ as inline LaTeX delimiters.
# Agent responses that contain currency amounts like "$452K revenue ... $381K"
# are therefore parsed as math expressions, rendering the text between the two
# dollar signs as italicised math notation rather than plain text.
#
# Fix: escape any $ that is immediately followed by a digit before passing text
# to st.markdown(). This covers all common currency patterns ($452K, $1,850,
# $250–$267) while leaving genuine LaTeX untouched — real LaTeX inline math
# starts with a letter, digit group, or backslash (e.g. $x^2$, $\alpha$),
# never with a bare digit like $452.
#
# If you ever need to support LaTeX in agent responses, remove the escaping
# and instead sanitise currency values upstream before they reach the renderer.
_CURRENCY_RE = re.compile(r"\$(?=\d)")


def escape_dollars(text: str) -> str:
    """Escapes currency dollar signs ($<digit>) to prevent Streamlit LaTeX rendering."""
    return _CURRENCY_RE.sub(r"\\$", text)


_THINKING_STEP_LABEL = ":material/psychology: Thinking"


class _StepTimeline:
    """Groups reasoning and tool steps into one collapsible ``st.status``.

    The outer status is created lazily on the first step, so a response with
    no visible steps renders nothing. Each step is a nested
    ``st.status(type="step")``, which Streamlit joins into one timeline.

    Args:
        container: Streamlit container that holds the timeline.
        key_prefix: When provided, the timeline is wrapped in
            ``st.container(key=f"{key_prefix}-thinking")`` so it keeps the
            stable ``.st-key-{prefix}-thinking`` CSS class.
        expanded: Whether the outer status starts expanded.
    """

    def __init__(self, container: Any, *, key_prefix: str | None, expanded: bool) -> None:
        self._container = container
        self._key_prefix = key_prefix
        self._expanded = expanded
        self._outer: Any = None
        self._finished = False
        self._has_thinking = False
        self._failed = False

    def _label(self) -> str:
        return "Reasoning" if self._has_thinking else "Working"

    def add_step(self, label: str, *, thinking: bool = False, state: str = "running") -> Any:
        """Adds a step and returns its status container.

        Args:
            label: Step label.
            thinking: ``True`` for a reasoning step. Switches the outer label
                from "Working" to "Reasoning".
            state: Initial step state.

        Returns:
            The step's ``st.status`` container.
        """
        if thinking and not self._has_thinking:
            self._has_thinking = True
            if self._outer is not None:
                self._outer.update(label=self._label())
        if self._outer is None:
            parent = (
                self._container.container(key=f"{self._key_prefix}-thinking")
                if self._key_prefix
                else self._container
            )
            self._outer = parent.status(self._label(), expanded=self._expanded, state="running")
        elif self._finished:
            # A step arrived after the answer started: reopen until it finishes.
            self._finished = False
            self._outer.update(state="running", expanded=True)
        return self._outer.status(label, expanded=False, state=state, type="step")

    def mark_failed(self) -> None:
        """Records that a step failed, so the outer status ends in the error state."""
        self._failed = True
        if self._finished:
            # Already collapsed: reopen so the failure is visible.
            self._outer.update(state="error", expanded=True)

    def finish(self) -> None:
        """Completes the outer status and collapses it (stays open on failure)."""
        if self._outer is None or self._finished:
            return
        self._finished = True
        self._outer.update(
            label=self._label(),
            state="error" if self._failed else "complete",
            expanded=self._failed,
        )


def _tool_step_outcome(
    result: ToolResultEvent | None, verified: bool
) -> tuple[str, str]:
    """Returns the final ``(label, state)`` for a tool step.

    Args:
        result: The tool's result event, or ``None`` if it never arrived.
        verified: Whether the tool used a verified query.

    Returns:
        The step label and its ``st.status`` state.
    """
    if result is None:
        return "Tool interrupted", "error"
    if result.status == "success":
        if verified:
            return f":material/verified: {result.name} (verified query)", "complete"
        return f":material/check_circle: {result.name} complete", "complete"
    return f":material/error: {result.name} failed", "error"


def render_streaming_response(
    events: Iterator[SSEEvent],
    container: Any,
    *,
    show_thinking: bool = False,
    show_tool_status: bool = True,
    key_prefix: str | None = None,
    loading_placeholder: Any | None = None,
) -> StoredMessage:
    """Renders an SSE event stream into Streamlit elements as events arrive.

    Intended to be called inside a ``with st.chat_message("assistant"):``
    block. Renders each event type progressively, then returns a
    :class:`~streamlit_cortex_agents.client.models.thread.StoredMessage` suitable for storing
    in ``st.session_state`` for history replay.

    Args:
        events: Iterator of :class:`~streamlit_cortex_agents.client.models.events.SSEEvent`
            objects from :meth:`~streamlit_cortex_agents.Thread.chat` or
            :meth:`~streamlit_cortex_agents.client.resources.RunsResource.stream`.
        container: A Streamlit container (e.g. ``st``, or the return value
            of ``st.chat_message()``). Must support ``empty()``,
            ``markdown()``, ``dataframe()``, ``vega_lite_chart()``,
            ``expander()``, ``warning()``, ``error()``, ``info()``, ``status()``, and ``caption()`` methods.
        show_thinking: If ``True``, renders each run of thinking as a step
            in the reasoning timeline. Thinking is always captured in the
            returned
            :class:`~streamlit_cortex_agents.client.models.thread.StoredMessage` regardless
            of this flag.
        show_tool_status: If ``True``, renders each tool call as a step in
            the reasoning timeline. The timeline is one ``st.status()`` that
            starts expanded and collapses when the answer starts.
        key_prefix: Optional prefix for widget keys. When provided, widgets
            that accept ``key`` get a stable CSS class (e.g.
            ``.st-key-{prefix}-thinking``). Pass a unique value per message
            to avoid key collisions across multiple messages.
        loading_placeholder: Optional ``st.empty()`` placeholder shown while
            waiting for the first SSE event. Cleared automatically on the
            first event that arrives.

    Returns:
        A :class:`~streamlit_cortex_agents.client.models.thread.StoredMessage` populated
        with all content encountered during the stream.

    Raises:
        ImportError: If ``streamlit`` is not installed.

    Example::

        with st.chat_message("assistant"):
            stored = render_streaming_response(
                thread.chat("DB.SCHEMA.MY_AGENT", prompt),
                container=st,
                show_thinking=True,
            )
        append_message(stored)
    """

    stored = StoredMessage(role="assistant")

    # Text accumulation — placeholder created lazily so thinking expander
    # (which arrives first) occupies the top position.
    text_placeholder = None
    accumulated_text = ""

    # Reasoning and tool steps share one collapsible timeline.
    timeline = _StepTimeline(container, key_prefix=key_prefix, expanded=True)

    # Open thinking segment: index into stored.thinking_segments, its step,
    # and the placeholder inside that step.
    thinking_idx: int | None = None
    thinking_step: Any = None
    thinking_placeholder = None

    def _close_thinking() -> None:
        nonlocal thinking_idx, thinking_step, thinking_placeholder
        if thinking_step is not None:
            thinking_step.update(state="complete")
        thinking_idx = None
        thinking_step = None
        thinking_placeholder = None

    def _open_thinking() -> int:
        nonlocal thinking_idx, thinking_step, thinking_placeholder
        stored.thinking_segments.append("")
        thinking_idx = len(stored.thinking_segments) - 1
        stored.timeline.append(("thinking", thinking_idx))
        if show_thinking:
            thinking_step = timeline.add_step(_THINKING_STEP_LABEL, thinking=True)
            thinking_placeholder = thinking_step.empty()
        return thinking_idx

    # Tool status tracking: tool_use_id → st.status context
    tool_status_contexts: dict[str, Any] = {}
    pending_tool_uses: dict[str, ToolUseEvent] = {}

    for event in events:
        if loading_placeholder is not None:
            loading_placeholder.empty()
            loading_placeholder = None

        if isinstance(event, (TextDeltaEvent, TableEvent, ChartEvent)):
            # The answer has started: reasoning is done, so collapse the timeline.
            _close_thinking()
            timeline.finish()

        if isinstance(event, TextDeltaEvent):
            accumulated_text += event.text
            if text_placeholder is None:
                text_placeholder = container.empty()
            if event.is_elicitation:
                stored.is_elicitation = True
                text_placeholder.info(escape_dollars(accumulated_text) + " :shimmer[▌]", icon=":material/contact_support:", title="Clarification needed")
            else:
                text_placeholder.markdown(escape_dollars(accumulated_text) + " :shimmer[▌]")

        elif isinstance(event, TextEvent):
            # Final assembled text — store for history replay. Only update
            # the current placeholder to remove the shimmer cursor; don't
            # re-render all text into one slot (which would break interleaved
            # table/chart positioning).
            stored.text += event.text
            stored.is_elicitation = event.is_elicitation
            if text_placeholder is not None:
                if event.is_elicitation:
                    text_placeholder.info(escape_dollars(accumulated_text), icon=":material/contact_support:", title="Clarification needed")
                else:
                    text_placeholder.markdown(escape_dollars(accumulated_text))

        elif isinstance(event, TextAnnotationEvent):
            stored.annotations.append(event)

        elif isinstance(event, ThinkingDeltaEvent):
            idx = thinking_idx if thinking_idx is not None else _open_thinking()
            stored.thinking_segments[idx] += event.text
            if thinking_placeholder is not None:
                thinking_placeholder.markdown(escape_dollars(stored.thinking_segments[idx]))

        elif isinstance(event, ThinkingEvent):
            # Final text for the open segment. When no deltas arrived, this
            # opens and fills a new segment.
            idx = thinking_idx if thinking_idx is not None else _open_thinking()
            stored.thinking_segments[idx] = event.text
            if thinking_placeholder is not None:
                thinking_placeholder.markdown(escape_dollars(event.text))
            _close_thinking()

        elif isinstance(event, ToolUseEvent):
            pending_tool_uses[event.tool_use_id] = event
            # Extract SQL from system_execute_sql (Apr 2026+ Cortex Analyst)
            if event.type == "system_execute_sql" and event.input.get("sql"):
                stored.analyst_sql[event.tool_use_id] = event.input["sql"]
            if event.type == "system_execute_sql" and event.input.get(
                "verified_query_used"
            ):
                stored.verified_tool_uses.add(event.tool_use_id)
            if event.permission_options:
                # Tool requires user approval — stop consuming the stream.
                # The Streamlit chatbot will show the approval UI on the next
                # rerun and send the permission_decision in a follow-up request.
                stored.pending_permission = event
                container.warning(
                    f"**{event.name}** is requesting permission before executing.",
                    icon=":material/security:",
                )
                break
            # A tool call ends the current run of thinking.
            _close_thinking()
            stored.timeline.append(("tool", event.tool_use_id))
            # Paired with result event later
            if show_tool_status:
                status_ctx = timeline.add_step(f":material/build: Using {event.name}...")
                # Show SQL inside the expander if available
                if event.tool_use_id in stored.analyst_sql:
                    status_ctx.code(stored.analyst_sql[event.tool_use_id], language="sql")
                tool_status_contexts[event.tool_use_id] = status_ctx

        elif isinstance(event, ToolResultStatusEvent):
            if show_tool_status and event.tool_use_id in tool_status_contexts:
                tool_status_contexts[event.tool_use_id].update(
                    label=event.message or f"Running {event.tool_type}...",
                )

        elif isinstance(event, ToolResultEvent):
            use_event = pending_tool_uses.pop(event.tool_use_id, None)
            if use_event is not None:
                stored.tool_executions.append((use_event, event))
            # Extract and render text content items (e.g. from generic/web_search tools)
            text_parts = [
                item["text"]
                for item in event.content
                if isinstance(item, dict)
                and item.get("type") == "text"
                and item.get("text")
            ]
            if text_parts:
                result_text = "\n\n".join(text_parts)
                stored.tool_result_text[event.tool_use_id] = result_text
                container.markdown(escape_dollars(result_text))
            if show_tool_status and event.tool_use_id in tool_status_contexts:
                ctx = tool_status_contexts.pop(event.tool_use_id)
                label, state = _tool_step_outcome(
                    event, event.tool_use_id in stored.verified_tool_uses
                )
                if state == "error":
                    timeline.mark_failed()
                ctx.update(label=label, state=state, expanded=state == "error")

        elif isinstance(event, AnalystDeltaEvent):
            # Legacy path: pre-Apr 2026 deployments still emit analyst.delta
            if event.sql:
                stored.analyst_sql[event.tool_use_id] = event.sql
            if event.verified_query_used:
                stored.verified_tool_uses.add(event.tool_use_id)

        elif isinstance(event, TableEvent):
            stored.tables.append(event)
            # Seal current text segment and record ordering.
            if accumulated_text:
                stored.text_segments.append(accumulated_text)
                stored.content_blocks.append(("text", len(stored.text_segments) - 1))
                accumulated_text = ""
                text_placeholder = None
            stored.content_blocks.append(("table", len(stored.tables) - 1))
            try:
                df = result_set_to_dataframe(event)
                if event.title:
                    container.caption(escape_dollars(event.title))
                container.dataframe(
                    df,
                    hide_index=True,
                    width="stretch",
                    column_config=_markdown_column_config(df),
                    **({"key": f"{key_prefix}-table-{len(stored.tables) - 1}"} if key_prefix else {}),
                )
            except Exception:
                logger.warning("Failed to render table event.", exc_info=True)

        elif isinstance(event, ChartEvent):
            stored.charts.append(event)
            # Seal current text segment and record ordering.
            if accumulated_text:
                stored.text_segments.append(accumulated_text)
                stored.content_blocks.append(("text", len(stored.text_segments) - 1))
                accumulated_text = ""
                text_placeholder = None
            stored.content_blocks.append(("chart", len(stored.charts) - 1))
            try:
                spec = json.loads(event.chart_spec)
                container.vega_lite_chart(
                    spec,
                    width="stretch",
                    **({"key": f"{key_prefix}-chart-{len(stored.charts) - 1}"} if key_prefix else {}),
                )
            except Exception:
                logger.warning("Failed to render chart event.", exc_info=True)

        elif isinstance(event, StatusEvent):
            # Transient — not stored or rendered permanently
            logger.debug("Status event: %s — %s", event.status, event.message)

        elif isinstance(event, WarningEvent):
            stored.warnings.append(event)
            container.warning(escape_dollars(event.message), icon=":material/warning:", title="Warning")

        elif isinstance(event, SuggestedQueriesEvent):
            stored.suggested_queries = event.queries

        elif isinstance(event, ErrorEvent):
            stored.error = event
            container.error(escape_dollars(event.message), icon=":material/error:", title=f"Error {event.code}")
            break

        elif isinstance(event, MetadataEvent):
            if event.role == "assistant":
                stored.message_id = event.message_id

    # Clear the placeholder if no text was ever accumulated
    # (e.g. tool-only or error-only responses).
    if not accumulated_text and text_placeholder is not None:
        text_placeholder.empty()

    # If text deltas came in but no final TextEvent, persist accumulated text.
    # is_elicitation is only known from the final TextEvent; deltas may have set
    # it on the StoredMessage if any delta carried it True.
    if accumulated_text and not stored.text:
        stored.text = accumulated_text
        if text_placeholder is None:
            pass  # deltas always create the placeholder; guard for type safety
        elif stored.is_elicitation:
            text_placeholder.info(escape_dollars(accumulated_text), icon=":material/contact_support:", title="Clarification needed")
        else:
            text_placeholder.markdown(escape_dollars(accumulated_text))

    # Record trailing text segment for ordered replay.
    if accumulated_text:
        stored.text_segments.append(accumulated_text)
        stored.content_blocks.append(("text", len(stored.text_segments) - 1))

    _close_thinking()
    if any(stored.thinking_segments):
        stored.thinking = "\n\n".join(s for s in stored.thinking_segments if s)

    # Close any still-open tool status contexts (edge case: stream ended
    # before tool_result arrived)
    for use_event in pending_tool_uses.values():
        if use_event is not stored.pending_permission:
            stored.tool_executions.append((use_event, None))
    for ctx in tool_status_contexts.values():
        timeline.mark_failed()
        try:
            ctx.update(label="Tool interrupted", state="error", expanded=False)
        except Exception:
            logger.debug("Failed to close tool status context", exc_info=True)

    timeline.finish()

    if stored.annotations:
        _render_annotations_expander(stored.annotations, container, key_prefix=key_prefix)

    # Show fallback when the stream produced no visible content.
    if (
        not stored.text
        and not stored.tables
        and not stored.charts
        and not stored.error
        and not stored.tool_result_text
        and not stored.warnings
        and not stored.pending_permission
    ):
        container.warning(
            "The agent returned an empty response. Try rephrasing your question.",
            icon=":material/info:",
        )

    return stored


def _markdown_column_config(df: pd.DataFrame) -> dict[str, Any] | None:
    """Builds a column_config dict applying MarkdownColumn to all string columns.

    Markdown in Analyst result cells (e.g. ``**bold**``, links) renders
    correctly. Plain-text cells are unaffected.

    Args:
        df: The DataFrame whose columns will be inspected.

    Returns:
        A ``column_config`` dict for ``st.dataframe``, or ``None`` if there
        are no string columns.
    """
    import pandas as pd
    import streamlit as st

    # Selecting text columns without select_dtypes(include="object"), which
    # emits a Pandas4Warning: under pandas 3 the "object" selector no longer
    # implies the new "str" dtype, so that call would silently stop matching
    # string columns. Testing each column covers both dtypes on pandas 2 and 3.
    text_columns = [
        col
        for col in df.columns
        if pd.api.types.is_object_dtype(df[col])
        or pd.api.types.is_string_dtype(df[col])
    ]

    cfg = {col: st.column_config.MarkdownColumn(col) for col in text_columns}
    return cfg or None


def _render_annotations_expander(
    annotations: list[TextAnnotationEvent],
    container: Any,
    *,
    key_prefix: str | None = None,
) -> None:
    """Renders citation annotations in a collapsible 'Sources' expander.

    Each citation shows its title (or doc_id) and the relevant text excerpt.
    If ``doc_id`` is an http/https URL it is rendered as a hyperlink that
    opens in a new browser tab.

    Args:
        annotations: List of :class:`~streamlit_cortex_agents.client.models.events.TextAnnotationEvent`
            objects collected during the response.
        container: Streamlit container to render into.
    """
    if not annotations:
        return

    # Deduplicate: multiple chunks from the same document with the same text
    # are collapsed into a single source entry.
    seen: set[tuple[str, str]] = set()
    unique_annotations = []
    for ann in annotations:
        key = (ann.doc_id, ann.text or "")
        if key not in seen:
            seen.add(key)
            unique_annotations.append(ann)

    exp = container.expander(
        f"Sources ({len(unique_annotations)})",
        icon=":material/library_books:",
        expanded=False,
        **({"key": f"{key_prefix}-sources"} if key_prefix else {}),
    )
    for ann in unique_annotations:
        is_url = ann.doc_id.startswith("http://") or ann.doc_id.startswith("https://")
        label = ann.doc_title or ann.doc_id or f"Source {ann.index}"
        if is_url:
            safe_url = html_escape(ann.doc_id, quote=True)
            safe_label = html_escape(escape_dollars(label))
            exp.markdown(
                f"**[{ann.index}]** "
                f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">'
                f"{safe_label}</a>",
                unsafe_allow_html=True,
            )
        else:
            exp.markdown(f"**[{ann.index}]** {escape_dollars(label)}")
        if ann.text:
            exp.caption(f'"{escape_dollars(ann.text)}"')


def _render_suggested_queries(
    queries: list[str],
    container: Any,
    suggestion_key: str = "_ca_pending_suggestion",
) -> None:
    """Renders suggested follow-up queries as native ``st.pills``.

    Selecting a pill stores the query text in session state under
    *suggestion_key* and clears the pill selection, so the same
    suggestion can be picked again later. The chatbot component picks up
    the stored query on the resulting rerun and submits it as the next
    user message.

    Args:
        queries: List of suggested question strings from the agent.
        container: Streamlit container to render into.
        suggestion_key: Session state key for the pending suggestion.
    """
    import streamlit as st

    if not queries:
        return

    pills_key = f"{suggestion_key}_pills"

    def _on_select() -> None:
        # Callbacks run before the rerun, so the widget value can be cleared
        # here; otherwise the pill would stay selected and resubmit.
        selected = st.session_state.get(pills_key)
        if selected:
            st.session_state[suggestion_key] = selected
            st.session_state[pills_key] = None

    container.pills(
        "Suggested questions",
        options=queries,
        key=pills_key,
        on_change=_on_select,
    )


def _render_stored_timeline(
    msg: StoredMessage,
    container: Any,
    *,
    show_thinking: bool,
    show_tool_status: bool,
    key_prefix: str | None,
) -> None:
    """Replays the reasoning and tool steps of a stored message, collapsed.

    Args:
        msg: The stored message.
        container: Streamlit container to render into.
        show_thinking: Whether to include reasoning steps.
        show_tool_status: Whether to include tool steps.
        key_prefix: Optional prefix for the timeline's stable CSS class.
    """
    segments = msg.thinking_segments or ([msg.thinking] if msg.thinking else [])
    entries: list[tuple[str, int | str]] = list(msg.timeline)
    if not entries:
        # Legacy messages: one reasoning step, then the tool steps.
        entries = [("thinking", i) for i in range(len(segments))]
        entries += [("tool", use.tool_use_id) for use, _ in msg.tool_executions]

    executions = {use.tool_use_id: (use, result) for use, result in msg.tool_executions}
    timeline = _StepTimeline(container, key_prefix=key_prefix, expanded=False)
    for kind, ref in entries:
        if kind == "thinking" and show_thinking:
            if not isinstance(ref, int) or ref >= len(segments) or not segments[ref]:
                continue
            step = timeline.add_step(_THINKING_STEP_LABEL, thinking=True, state="complete")
            step.markdown(escape_dollars(segments[ref]))
        elif kind == "tool" and show_tool_status and ref in executions:
            _use, result = executions[ref]
            label, state = _tool_step_outcome(result, ref in msg.verified_tool_uses)
            if state == "error":
                timeline.mark_failed()
            step = timeline.add_step(label, state=state)
            sql = msg.analyst_sql.get(ref)
            if sql:
                step.code(sql, language="sql")
    timeline.finish()


def render_stored_message(
    msg: StoredMessage,
    container: Any,
    *,
    show_thinking: bool = False,
    show_tool_status: bool = True,
    key_prefix: str | None = None,
) -> None:
    """Renders a stored message from session state into Streamlit elements.

    Produces equivalent content to :func:`render_streaming_response` for the
    same message content. Called on every Streamlit rerun to replay history.
    The reasoning timeline is replayed collapsed.

    Args:
        msg: A :class:`~streamlit_cortex_agents.client.models.thread.StoredMessage` from
            session state.
        container: Streamlit container (e.g. ``st`` or the return value of
            ``st.chat_message()``).
        show_thinking: If ``True``, render agent reasoning as steps in the
            collapsed reasoning timeline. Defaults to ``False`` — pass the
            same value you passed to :func:`render_streaming_response` so the
            replay matches what the user saw during streaming.
        show_tool_status: If ``True``, render tool calls as steps in the
            reasoning timeline. Pass the same value you passed to
            :func:`render_streaming_response`.
        key_prefix: Optional prefix for widget keys. When provided, widgets
            that accept ``key`` get a stable CSS class (e.g.
            ``.st-key-{prefix}-thinking``). Pass the same prefix used during
            streaming to maintain consistent keys across reruns.

    Raises:
        ImportError: If ``streamlit`` or ``pandas`` is not installed
            when the message contains tables.

    Example::

        for msg in get_messages():
            with st.chat_message(msg.role):
                render_stored_message(msg, st, show_thinking=False)
    """
    if show_thinking or show_tool_status:
        _render_stored_timeline(
            msg,
            container,
            show_thinking=show_thinking,
            show_tool_status=show_tool_status,
            key_prefix=key_prefix,
        )

    # Tool result text appears before the main answer (tools execute first).
    for tool_use, _tool_result in msg.tool_executions:
        text = msg.tool_result_text.get(tool_use.tool_use_id)
        if text:
            container.markdown(escape_dollars(text))

    if msg.content_blocks:
        # Ordered replay: render text segments, tables, and charts in arrival order.
        for block_type, idx in msg.content_blocks:
            if block_type == "text":
                segment = msg.text_segments[idx]
                if msg.is_elicitation:
                    container.info(escape_dollars(segment), icon=":material/contact_support:", title="Clarification needed")
                else:
                    container.markdown(escape_dollars(segment))
            elif block_type == "table":
                table_event = msg.tables[idx]
                try:
                    df = result_set_to_dataframe(table_event)
                    if table_event.title:
                        container.caption(escape_dollars(table_event.title))
                    container.dataframe(
                        df,
                        hide_index=True,
                        width="stretch",
                        column_config=_markdown_column_config(df),
                        **({"key": f"{key_prefix}-table-{idx}"} if key_prefix else {}),
                    )
                except Exception:
                    logger.warning("Failed to render stored table.", exc_info=True)
            elif block_type == "chart":
                chart_event = msg.charts[idx]
                try:
                    spec = json.loads(chart_event.chart_spec)
                    container.vega_lite_chart(
                        spec,
                        width="stretch",
                        **({"key": f"{key_prefix}-chart-{idx}"} if key_prefix else {}),
                    )
                except Exception:
                    logger.warning("Failed to render stored chart.", exc_info=True)
    else:
        # Legacy fallback: messages stored before content_blocks was added.
        if msg.text:
            if msg.is_elicitation:
                container.info(escape_dollars(msg.text), icon=":material/contact_support:", title="Clarification needed")
            else:
                container.markdown(escape_dollars(msg.text))

        for i, table_event in enumerate(msg.tables):
            try:
                df = result_set_to_dataframe(table_event)
                if table_event.title:
                    container.caption(escape_dollars(table_event.title))
                container.dataframe(
                    df,
                    hide_index=True,
                    width="stretch",
                    column_config=_markdown_column_config(df),
                    **({"key": f"{key_prefix}-table-{i}"} if key_prefix else {}),
                )
            except Exception:
                logger.warning("Failed to render stored table.", exc_info=True)

        for i, chart_event in enumerate(msg.charts):
            try:
                spec = json.loads(chart_event.chart_spec)
                container.vega_lite_chart(
                    spec,
                    width="stretch",
                    **({"key": f"{key_prefix}-chart-{i}"} if key_prefix else {}),
                )
            except Exception:
                logger.warning("Failed to render stored chart.", exc_info=True)

    if msg.annotations:
        _render_annotations_expander(msg.annotations, container, key_prefix=key_prefix)

    for warning in msg.warnings:
        container.warning(escape_dollars(warning.message), icon=":material/warning:", title="Warning")

    if msg.error:
        container.error(escape_dollars(msg.error.message), icon=":material/error:", title=f"Error {msg.error.code}")

    # Suggested queries are NOT rendered during history replay — they are only
    # shown live after the most recent streaming response (via render_streaming_response).
    # Old suggestions become stale once the conversation continues.

    if msg.pending_permission:
        container.warning(
            f"Permission for **{msg.pending_permission.name}** was required during this turn.",
            icon=":material/security:",
        )
