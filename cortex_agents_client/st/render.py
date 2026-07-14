"""Streamlit rendering functions for Cortex Agent SSE events.

Provides two rendering code paths that produce equivalent content:

1. :func:`render_streaming_response`: Used during live streaming of a new
   assistant turn. Renders each event type as it arrives and returns a
   :class:`~cortex_agents_client.models.thread.StoredMessage` for session state.
   Transient elements (tool-execution spinners) are shown here but not stored.

2. :func:`render_stored_message`: Used on every Streamlit rerun to replay
   stored messages from ``st.session_state``. Reproduces the final content
   of path 1; transient spinners are not replayed.

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

from cortex_agents_client.models.events import (
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
from cortex_agents_client.models.thread import StoredMessage

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


def escape_dollars(text: str) -> str:
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
            ``expander()``, ``warning()``, ``error()``, ``info()``, ``status()``, and ``caption()`` methods.
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

    # Text accumulation — placeholder created lazily so thinking expander
    # (which arrives first) occupies the top position.
    text_placeholder = None
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
            stored.text = event.text
            stored.is_elicitation = event.is_elicitation
            if text_placeholder is not None:
                if event.is_elicitation:
                    text_placeholder.info(escape_dollars(accumulated_text), icon=":material/contact_support:", title="Clarification needed")
                else:
                    text_placeholder.markdown(escape_dollars(accumulated_text))

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
                    thinking_placeholder.markdown(escape_dollars(accumulated_thinking))

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
                    thinking_expander.markdown(escape_dollars(event.text))

        elif isinstance(event, ToolUseEvent):
            pending_tool_uses[event.tool_use_id] = event
            # Extract SQL from system_execute_sql (Apr 2026+ Cortex Analyst)
            if event.type == "system_execute_sql" and event.input.get("sql"):
                stored.analyst_sql[event.tool_use_id] = event.input["sql"]
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
                if event.status == "success":
                    if event.tool_use_id in stored.verified_tool_uses:
                        icon = ":material/verified:"
                        label = f"{icon} {event.name} (verified query)"
                    else:
                        icon = ":material/check_circle:"
                        label = f"{icon} {event.name} complete"
                    ctx.update(label=label, state="complete", expanded=False)
                else:
                    ctx.update(
                        label=f":material/error: {event.name} failed",
                        state="error",
                        expanded=True,
                    )

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
                container.vega_lite_chart(spec, use_container_width=True)
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
        if stored.is_elicitation:
            text_placeholder.info(escape_dollars(accumulated_text), icon=":material/contact_support:", title="Clarification needed")
        else:
            text_placeholder.markdown(escape_dollars(accumulated_text))

    # Record trailing text segment for ordered replay.
    if accumulated_text:
        stored.text_segments.append(accumulated_text)
        stored.content_blocks.append(("text", len(stored.text_segments) - 1))

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

    # Show fallback when the stream produced no visible content.
    if (
        not stored.text
        and not stored.tables
        and not stored.charts
        and not stored.error
        and not stored.tool_result_text
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
    """Renders suggested follow-up queries as clickable pill buttons.

    When a button is clicked, the query text is stored in session state
    under *suggestion_key* and a rerun is triggered. The chatbot
    component picks this up and submits it as the next user message.

    Args:
        queries: List of suggested question strings from the agent.
        container: Streamlit container to render into.
        suggestion_key: Session state key for the pending suggestion.
    """
    import streamlit as st

    if not queries:
        return

    container.markdown(
        "<style>"
        "[data-testid='stButton']:has(button[kind='tertiary']) { margin-top: -1.25rem; }"
        "[data-testid='stButton']:has(button[kind='tertiary']) button { justify-content: flex-start; }"
        "[data-testid='stButton']:has(button[kind='tertiary']) button p { opacity: 0.6; text-align: left; }"
        "</style>",
        unsafe_allow_html=True,
    )
    container.caption("Suggested questions")
    for i, query in enumerate(queries):
        if container.button(
            query,
            icon=":material/arrow_forward:",
            type="tertiary",
            key=f"_ca_suggestion_{hash(query)}_{i}",
        ):
            st.session_state[suggestion_key] = query
            st.rerun()


def render_stored_message(msg: StoredMessage, container: Any, *, show_thinking: bool = False) -> None:
    """Renders a stored message from session state into Streamlit elements.

    Produces equivalent content to :func:`render_streaming_response` for the
    same message content. Called on every Streamlit rerun to replay history.
    Transient elements such as tool-execution spinners are not replayed.

    Args:
        msg: A :class:`~cortex_agents_client.models.thread.StoredMessage` from
            session state.
        container: Streamlit container (e.g. ``st`` or the return value of
            ``st.chat_message()``).
        show_thinking: If ``True``, render agent reasoning in a collapsible
            expander. Defaults to ``False`` — pass the same value you passed
            to :func:`render_streaming_response` so the replay matches what
            the user saw during streaming.

    Raises:
        ImportError: If ``streamlit`` or ``pandas`` is not installed
            when the message contains tables.

    Example::

        for msg in get_messages():
            with st.chat_message(msg.role):
                render_stored_message(msg, st, show_thinking=False)
    """
    if show_thinking and msg.thinking:
        exp = container.expander(
            "Reasoning",
            icon=":material/psychology:",
            expanded=False,
            type="compact",
        )
        exp.markdown(escape_dollars(msg.thinking))

    # Tool result text appears before the main answer (tools execute first).
    for tool_use, _tool_result in msg.tool_executions:
        sql = msg.analyst_sql.get(tool_use.tool_use_id)
        if sql:
            with container.status(
                f":material/check_circle: {tool_use.name} complete",
                state="complete",
                expanded=False,
                type="compact",
            ) as ctx:
                ctx.code(sql, language="sql")
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
                    )
                except Exception:
                    logger.warning("Failed to render stored table.", exc_info=True)
            elif block_type == "chart":
                chart_event = msg.charts[idx]
                try:
                    spec = json.loads(chart_event.chart_spec)
                    container.vega_lite_chart(spec, use_container_width=True)
                except Exception:
                    logger.warning("Failed to render stored chart.", exc_info=True)
    else:
        # Legacy fallback: messages stored before content_blocks was added.
        if msg.text:
            if msg.is_elicitation:
                container.info(escape_dollars(msg.text), icon=":material/contact_support:", title="Clarification needed")
            else:
                container.markdown(escape_dollars(msg.text))

        for table_event in msg.tables:
            try:
                df = result_set_to_dataframe(table_event)
                if table_event.title:
                    container.caption(escape_dollars(table_event.title))
                container.dataframe(
                    df,
                    hide_index=True,
                    width="stretch",
                    column_config=_markdown_column_config(df),
                )
            except Exception:
                logger.warning("Failed to render stored table.", exc_info=True)

        for chart_event in msg.charts:
            try:
                spec = json.loads(chart_event.chart_spec)
                container.vega_lite_chart(spec, use_container_width=True)
            except Exception:
                logger.warning("Failed to render stored chart.", exc_info=True)

    if msg.annotations:
        _render_annotations_expander(msg.annotations, container)

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
