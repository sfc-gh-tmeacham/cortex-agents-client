"""Streamlit rendering functions for Cortex Agent SSE events.

Provides two rendering code paths that produce identical output:

1. :func:`render_streaming_response`: Used during live streaming of a new
   assistant turn. Renders each event type as it arrives and returns a
   :class:`~cortex_agents_client.models.thread.StoredMessage` for session state.

2. :func:`render_stored_message`: Used on every Streamlit rerun to replay
   stored messages from ``st.session_state``. Produces the same visual
   output as path 1.

Also provides :func:`result_set_to_dataframe` for converting Snowflake
``jsonv2`` result sets to pandas DataFrames.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

from cortex_agents_client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    MetadataEvent,
    ResponseEvent,
    SSEEvent,
    StatusEvent,
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
from cortex_agents_client.models.thread import StoredMessage

logger = logging.getLogger(__name__)

# Snowflake SQL API type → pandas dtype mapping.
_SNOWFLAKE_DTYPE_MAP: dict[str, str] = {
    "FIXED": "Int64",          # nullable integer
    "INTEGER": "Int64",
    "INT": "Int64",
    "BIGINT": "Int64",
    "SMALLINT": "Int64",
    "REAL": "float64",
    "FLOAT": "float64",
    "FLOAT4": "float64",
    "FLOAT8": "float64",
    "DOUBLE": "float64",
    "DECIMAL": "float64",
    "NUMERIC": "float64",
    "BOOLEAN": "boolean",      # nullable boolean
    "TIMESTAMP_NTZ": "datetime64[ns]",
    "TIMESTAMP_LTZ": "datetime64[ns]",
    "TIMESTAMP_TZ": "datetime64[ns]",
    "DATE": "datetime64[ns]",
}


def result_set_to_dataframe(event: TableEvent) -> pd.DataFrame:
    """Converts a Snowflake jsonv2 result set to a pandas DataFrame.

    All values in the Snowflake ``jsonv2`` wire format are strings. This
    function uses the ``rowType`` metadata to cast each column to the
    appropriate dtype.

    Args:
        event: A :class:`~cortex_agents_client.models.events.TableEvent` containing
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


def _escape_dollars(text: str) -> str:
    """Escapes currency dollar signs ($<digit>) to prevent Streamlit LaTeX rendering."""
    return _CURRENCY_RE.sub(r"\\$", text)


def render_streaming_response(
    events: Iterator[SSEEvent],
    container: Any,
    *,
    show_thinking: bool = False,
    show_tool_status: bool = True,
) -> StoredMessage:
    """Renders an SSE event stream into Streamlit elements as events arrive.

    Intended to be called inside a ``with st.chat_message("assistant"):``
    block. Renders each event type progressively, then returns a
    :class:`~cortex_agents_client.models.thread.StoredMessage` suitable for storing
    in ``st.session_state`` for history replay.

    Args:
        events: Iterator of :class:`~cortex_agents_client.models.events.SSEEvent`
            objects from :meth:`~cortex_agents_client.Thread.chat` or
            :meth:`~cortex_agents_client.resources.RunsResource.stream`.
        container: A Streamlit container (e.g. ``st``, or the return value
            of ``st.chat_message()``). Must support ``empty()``,
            ``markdown()``, ``dataframe()``, ``vega_lite_chart()``,
            ``expander()``, ``warning()``, and ``error()`` methods.
        show_thinking: If ``True``, renders thinking content in an
            expander. Thinking is always captured in the returned
            :class:`~cortex_agents_client.models.thread.StoredMessage` regardless
            of this flag.
        show_tool_status: If ``True``, shows ``st.status()`` spinners for
            tool execution progress.

    Returns:
        A :class:`~cortex_agents_client.models.thread.StoredMessage` populated
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
    import streamlit as st

    stored = StoredMessage(role="assistant")

    # Text accumulation — show a skeleton loading bar while waiting for the first token
    text_placeholder = container.empty()
    text_placeholder.skeleton(height=40)
    accumulated_text = ""

    # Thinking accumulation
    thinking_placeholder = None
    thinking_expander = None
    accumulated_thinking = ""

    # Tool status tracking: tool_use_id → st.status context
    tool_status_contexts: dict[str, Any] = {}
    pending_tool_uses: dict[str, ToolUseEvent] = {}

    for event in events:
        if isinstance(event, TextDeltaEvent):
            accumulated_text += event.text
            if event.is_elicitation:
                text_placeholder.info(_escape_dollars(accumulated_text) + " :shimmer[▌]", icon=":material/contact_support:", title="Clarification needed")
            else:
                text_placeholder.markdown(_escape_dollars(accumulated_text) + " :shimmer[▌]")

        elif isinstance(event, TextEvent):
            accumulated_text = event.text
            stored.text = event.text
            stored.is_elicitation = event.is_elicitation
            if event.is_elicitation:
                # Agent is asking the user for more information
                text_placeholder.info(_escape_dollars(event.text), icon=":material/contact_support:", title="Clarification needed")
            else:
                text_placeholder.markdown(_escape_dollars(event.text))

        elif isinstance(event, TextAnnotationEvent):
            stored.annotations.append(event)

        elif isinstance(event, ThinkingDeltaEvent):
            accumulated_thinking += event.text
            if show_thinking:
                if thinking_expander is None:
                    thinking_expander = container.expander(
                        "Reasoning",
                        icon=":material/psychology:",
                        expanded=False,
                        type="compact",
                    )
                    thinking_placeholder = thinking_expander.empty()
                if thinking_placeholder is not None:
                    thinking_placeholder.markdown(accumulated_thinking)

        elif isinstance(event, ThinkingEvent):
            accumulated_thinking = event.text
            stored.thinking = event.text
            if show_thinking:
                if thinking_placeholder is not None:
                    # ThinkingDeltaEvents already rendered the full text into
                    # thinking_placeholder. The final ThinkingEvent text is
                    # identical — no render update needed, just record the text.
                    pass
                else:
                    # No deltas arrived before the final ThinkingEvent —
                    # create expander and render the full text directly.
                    if thinking_expander is None:
                        thinking_expander = container.expander(
                            "Reasoning",
                            icon=":material/psychology:",
                            expanded=False,
                            type="compact",
                        )
                    with thinking_expander:
                        st.markdown(event.text)

        elif isinstance(event, ToolUseEvent):
            pending_tool_uses[event.tool_use_id] = event
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
            # Paired with result event later
            if show_tool_status:
                status_ctx = container.status(
                    f":material/build: Using {event.name}...",
                    expanded=False,
                    type="compact",
                )
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
                container.markdown(result_text)
            if show_tool_status and event.tool_use_id in tool_status_contexts:
                ctx = tool_status_contexts.pop(event.tool_use_id)
                if event.status == "success":
                    ctx.update(
                        label=f":material/check_circle: {event.name} complete",
                        state="complete",
                        expanded=False,
                    )
                else:
                    ctx.update(
                        label=f":material/error: {event.name} failed",
                        state="error",
                        expanded=True,
                    )

        elif isinstance(event, AnalystDeltaEvent):
            if event.sql:
                stored.analyst_sql[event.tool_use_id] = event.sql

        elif isinstance(event, TableEvent):
            stored.tables.append(event)
            try:
                df = result_set_to_dataframe(event)
                if event.title:
                    container.caption(event.title)
                container.dataframe(
                    df,
                    use_container_width=True,
                    column_config=_markdown_column_config(df),
                )
            except Exception:
                logger.warning("Failed to render table event.", exc_info=True)

        elif isinstance(event, ChartEvent):
            stored.charts.append(event)
            try:
                spec = json.loads(event.chart_spec)
                container.vega_lite_chart(spec)
            except (json.JSONDecodeError, Exception):
                logger.warning("Failed to render chart event.", exc_info=True)

        elif isinstance(event, StatusEvent):
            # Transient — not stored or rendered permanently
            logger.debug("Status event: %s — %s", event.status, event.message)

        elif isinstance(event, WarningEvent):
            stored.warnings.append(event)
            container.warning(event.message, icon=":material/warning:", title="Warning")

        elif isinstance(event, ErrorEvent):
            stored.error = event
            container.error(f"{event.message}", icon=":material/error:", title=f"Error {event.code}")
            break

        elif isinstance(event, MetadataEvent):
            if event.role == "assistant":
                stored.message_id = event.message_id

    # Clear the skeleton placeholder if no text was ever accumulated
    # (e.g. tool-only or error-only responses).
    if not accumulated_text:
        text_placeholder.empty()

    # If text deltas came in but no final TextEvent, persist accumulated text.
    # is_elicitation is only known from the final TextEvent; deltas may have set
    # it on the StoredMessage if any delta carried it True.
    if accumulated_text and not stored.text:
        stored.text = accumulated_text
        if stored.is_elicitation:
            text_placeholder.info(_escape_dollars(accumulated_text), icon=":material/contact_support:", title="Clarification needed")
        else:
            text_placeholder.markdown(_escape_dollars(accumulated_text))

    if accumulated_thinking and not stored.thinking:
        stored.thinking = accumulated_thinking

    # Close any still-open tool status contexts (edge case: stream ended
    # before tool_result arrived)
    for ctx in tool_status_contexts.values():
        try:
            ctx.update(label="Tool interrupted", state="error", expanded=False)
        except Exception:
            pass

    if stored.annotations:
        _render_annotations_expander(stored.annotations, container)

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
    import streamlit as st

    cfg = {
        col: st.column_config.MarkdownColumn(col)
        for col in df.select_dtypes(include="object").columns
    }
    return cfg or None


def _render_annotations_expander(
    annotations: list[TextAnnotationEvent],
    container: Any,
) -> None:
    """Renders citation annotations in a collapsible 'Sources' expander.

    Each citation shows its title (or doc_id) and the relevant text excerpt.
    If ``doc_id`` is an http/https URL it is rendered as a hyperlink that
    opens in a new browser tab.

    Args:
        annotations: List of :class:`~cortex_agents_client.models.events.TextAnnotationEvent`
            objects collected during the response.
        container: Streamlit container to render into.
    """
    if not annotations:
        return

    exp = container.expander(
        f"Sources ({len(annotations)})",
        icon=":material/library_books:",
        expanded=False,
    )
    for ann in annotations:
        is_url = ann.doc_id.startswith("http://") or ann.doc_id.startswith("https://")
        label = ann.doc_title or ann.doc_id or f"Source {ann.index}"
        if is_url:
            exp.markdown(
                f"**[{ann.index}]** "
                f'<a href="{ann.doc_id}" target="_blank" rel="noopener noreferrer">'
                f"{label}</a>",
                unsafe_allow_html=True,
            )
        else:
            exp.markdown(f"**[{ann.index}]** {label}")
        if ann.text:
            exp.caption(f'"{ann.text}"')


def render_stored_message(msg: StoredMessage, container: Any) -> None:
    """Renders a stored message from session state into Streamlit elements.

    Produces output identical to :func:`render_streaming_response` for the
    same message content. Called on every Streamlit rerun to replay history.

    Args:
        msg: A :class:`~cortex_agents_client.models.thread.StoredMessage` from
            session state.
        container: Streamlit container (e.g. ``st`` or the return value of
            ``st.chat_message()``).

    Raises:
        ImportError: If ``streamlit`` or ``pandas`` is not installed
            when the message contains tables.

    Example::

        for msg in get_messages():
            with st.chat_message(msg.role):
                render_stored_message(msg, st)
    """
    if msg.thinking:
        with container.expander(
            "Reasoning",
            icon=":material/psychology:",
            expanded=False,
            type="compact",
        ):
            container.markdown(msg.thinking)

    # Tool result text appears before the main answer (tools execute first).
    for tool_use, _tool_result in msg.tool_executions:
        text = msg.tool_result_text.get(tool_use.tool_use_id)
        if text:
            container.markdown(text)

    if msg.text:
        if msg.is_elicitation:
            # Agent was asking the user a question — render as info box
            container.info(msg.text, icon=":material/contact_support:", title="Clarification needed")
        else:
            container.markdown(_escape_dollars(msg.text))

    if msg.annotations:
        _render_annotations_expander(msg.annotations, container)

    for table_event in msg.tables:
        try:
            df = result_set_to_dataframe(table_event)
            if table_event.title:
                container.caption(table_event.title)
            container.dataframe(
                df,
                use_container_width=True,
                column_config=_markdown_column_config(df),
            )
        except Exception:
            logger.warning("Failed to render stored table.", exc_info=True)

    for chart_event in msg.charts:
        try:
            spec = json.loads(chart_event.chart_spec)
            container.vega_lite_chart(spec)
        except (json.JSONDecodeError, Exception):
            logger.warning("Failed to render stored chart.", exc_info=True)

    for warning in msg.warnings:
        container.warning(warning.message, icon=":material/warning:", title="Warning")

    if msg.error:
        container.error(msg.error.message, icon=":material/error:", title=f"Error {msg.error.code}")

    if msg.pending_permission:
        container.info(
            f"Permission for **{msg.pending_permission.name}** was required during this turn.",
            icon=":material/security:",
        )
