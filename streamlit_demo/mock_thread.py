"""Mock thread and client for the cortex-agents-client UI demo.

Provides :class:`MockThread` and :class:`MockClient` — drop-in replacements
that are pre-seeded into ``st.session_state`` so :class:`~cortex_agents_client.st.chatbot.StreamlitChatbot`
works without a real Snowflake connection.

Each *scenario* is a generator function that yields
:class:`~cortex_agents_client.models.events.SSEEvent` objects with short
``time.sleep`` delays to simulate realistic streaming.

Usage::

    import streamlit as st
    from streamlit_demo.mock_thread import MockClient, MockThread, SCENARIO_NAMES

    # Pre-seed session state before the chatbot reads it.
    PREFIX = "_demo"
    if f"{PREFIX}_client" not in st.session_state:
        st.session_state[f"{PREFIX}_client"] = MockClient("Simple text")
    if f"{PREFIX}_thread" not in st.session_state:
        st.session_state[f"{PREFIX}_thread"] = MockThread("Simple text")
    if f"{PREFIX}_messages" not in st.session_state:
        st.session_state[f"{PREFIX}_messages"] = []
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from cortex_agents_client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    MetadataEvent,
    SSEEvent,
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

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_DELTA_DELAY: float = 0.025  # seconds between streaming chunks
_CHUNK_SIZE: int = 6          # characters per TextDeltaEvent


def _chunks(text: str, size: int = _CHUNK_SIZE) -> list[str]:
    """Splits *text* into chunks of at most *size* characters.

    Args:
        text: The full text string to split.
        size: Maximum characters per chunk.

    Returns:
        List of text chunks in order.
    """
    return [text[i : i + size] for i in range(0, len(text), size)]


def _stream_text(
    text: str,
    *,
    delay: float = _DELTA_DELAY,
    is_elicitation: bool = False,
) -> Iterator[SSEEvent]:
    """Yields ``TextDeltaEvent`` chunks then a final ``TextEvent``.

    Args:
        text: The full response text to stream.
        delay: Sleep duration in seconds between chunks.
        is_elicitation: If ``True``, marks all events as elicitation.

    Yields:
        Alternating :class:`~cortex_agents_client.models.events.TextDeltaEvent`
        instances followed by a single
        :class:`~cortex_agents_client.models.events.TextEvent`.
    """
    for chunk in _chunks(text):
        yield TextDeltaEvent(
            event_type="response.text.delta",
            text=chunk,
            is_elicitation=is_elicitation,
        )
        time.sleep(delay)
    yield TextEvent(
        event_type="response.text",
        text=text,
        is_elicitation=is_elicitation,
    )


def _stream_thinking(text: str, *, delay: float = _DELTA_DELAY) -> Iterator[SSEEvent]:
    """Yields ``ThinkingDeltaEvent`` chunks then a final ``ThinkingEvent``.

    Args:
        text: The full thinking text to stream.
        delay: Sleep duration in seconds between chunks.

    Yields:
        :class:`~cortex_agents_client.models.events.ThinkingDeltaEvent`
        instances followed by a single
        :class:`~cortex_agents_client.models.events.ThinkingEvent`.
    """
    for chunk in _chunks(text, size=10):
        yield ThinkingDeltaEvent(event_type="response.thinking.delta", text=chunk)
        time.sleep(delay)
    yield ThinkingEvent(event_type="response.thinking", text=text)


def _metadata(message_id: int = 1) -> MetadataEvent:
    """Returns a terminal ``MetadataEvent`` confirming message persistence.

    Args:
        message_id: Synthetic message ID for the assistant turn.

    Returns:
        A :class:`~cortex_agents_client.models.events.MetadataEvent`.
    """
    return MetadataEvent(
        event_type="metadata",
        role="assistant",
        message_id=message_id,
    )


# ---------------------------------------------------------------------------
# Shared canned data
# ---------------------------------------------------------------------------

_SALES_TABLE = TableEvent(
    event_type="response.table",
    tool_use_id="tool_001",
    query_id="01b9f8a0-0000-1234-0000-demo00000001",
    title="Revenue by Region — Q1 2026",
    result_set={
        "resultSetMetaData": {
            "rowType": [
                {"name": "REGION", "type": "TEXT"},
                {"name": "REVENUE", "type": "FIXED"},
                {"name": "ORDERS", "type": "FIXED"},
                {"name": "AVG_ORDER_VALUE", "type": "FIXED"},
            ]
        },
        "data": [
            ["North America", "452000", "1850", "244"],
            ["Europe", "381000", "1423", "267"],
            ["Asia Pacific", "294000", "1108", "265"],
            ["Latin America", "183000", "722", "253"],
            ["Middle East & Africa", "97000", "389", "249"],
        ],
    },
)

_TREND_CHART = ChartEvent(
    event_type="response.chart",
    tool_use_id="tool_002",
    chart_spec=json.dumps(
        {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "description": "Monthly revenue trend",
            "data": {
                "values": [
                    {"month": "Jan", "revenue": 95000},
                    {"month": "Feb", "revenue": 110000},
                    {"month": "Mar", "revenue": 102000},
                    {"month": "Apr", "revenue": 118000},
                    {"month": "May", "revenue": 130000},
                    {"month": "Jun", "revenue": 125000},
                    {"month": "Jul", "revenue": 141000},
                    {"month": "Aug", "revenue": 138000},
                    {"month": "Sep", "revenue": 152000},
                ]
            },
            "mark": {"type": "line", "point": True, "color": "#3B82F6"},
            "encoding": {
                "x": {"field": "month", "type": "nominal", "sort": None, "title": "Month"},
                "y": {
                    "field": "revenue",
                    "type": "quantitative",
                    "title": "Revenue ($)",
                    "axis": {"format": "$,.0f"},
                },
            },
            "width": "container",
        }
    ),
)

_BAR_CHART = ChartEvent(
    event_type="response.chart",
    tool_use_id="tool_003",
    chart_spec=json.dumps(
        {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "description": "Revenue by region — horizontal bar",
            "data": {
                "values": [
                    {"region": "North America", "revenue": 452000},
                    {"region": "Europe", "revenue": 381000},
                    {"region": "Asia Pacific", "revenue": 294000},
                    {"region": "Latin America", "revenue": 183000},
                    {"region": "ME & Africa", "revenue": 97000},
                ]
            },
            "mark": {"type": "bar", "color": "#3B82F6", "cornerRadiusEnd": 4},
            "encoding": {
                "y": {
                    "field": "region",
                    "type": "nominal",
                    "sort": "-x",
                    "title": None,
                },
                "x": {
                    "field": "revenue",
                    "type": "quantitative",
                    "title": "Revenue ($)",
                    "axis": {"format": "$,.0f"},
                },
                "tooltip": [
                    {"field": "region", "type": "nominal", "title": "Region"},
                    {"field": "revenue", "type": "quantitative", "title": "Revenue", "format": "$,.0f"},
                ],
            },
            "width": "container",
        }
    ),
)

_AREA_CHART = ChartEvent(
    event_type="response.chart",
    tool_use_id="tool_004",
    chart_spec=json.dumps(
        {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "description": "Cumulative revenue — area chart",
            "data": {
                "values": [
                    {"month": "Jan", "revenue": 95000},
                    {"month": "Feb", "revenue": 110000},
                    {"month": "Mar", "revenue": 102000},
                    {"month": "Apr", "revenue": 118000},
                    {"month": "May", "revenue": 130000},
                    {"month": "Jun", "revenue": 125000},
                    {"month": "Jul", "revenue": 141000},
                    {"month": "Aug", "revenue": 138000},
                    {"month": "Sep", "revenue": 152000},
                ]
            },
            "mark": {"type": "area", "color": "#3B82F6", "fillOpacity": 0.15, "line": {"color": "#3B82F6"}},
            "encoding": {
                "x": {"field": "month", "type": "nominal", "sort": None, "title": "Month"},
                "y": {
                    "field": "revenue",
                    "type": "quantitative",
                    "title": "Revenue ($)",
                    "axis": {"format": "$,.0f"},
                },
                "tooltip": [
                    {"field": "month", "type": "nominal", "title": "Month"},
                    {"field": "revenue", "type": "quantitative", "title": "Revenue", "format": "$,.0f"},
                ],
            },
            "width": "container",
        }
    ),
)

_STACKED_BAR_CHART = ChartEvent(
    event_type="response.chart",
    tool_use_id="tool_005",
    chart_spec=json.dumps(
        {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "description": "Product mix by region — stacked bar",
            "data": {
                "values": [
                    {"region": "North America", "product": "Widget A", "revenue": 198000},
                    {"region": "North America", "product": "Widget B", "revenue": 145000},
                    {"region": "North America", "product": "Widget C", "revenue": 109000},
                    {"region": "Europe", "product": "Widget A", "revenue": 152000},
                    {"region": "Europe", "product": "Widget B", "revenue": 134000},
                    {"region": "Europe", "product": "Widget C", "revenue": 95000},
                    {"region": "Asia Pacific", "product": "Widget A", "revenue": 118000},
                    {"region": "Asia Pacific", "product": "Widget B", "revenue": 102000},
                    {"region": "Asia Pacific", "product": "Widget C", "revenue": 74000},
                    {"region": "Latin America", "product": "Widget A", "revenue": 79000},
                    {"region": "Latin America", "product": "Widget B", "revenue": 64000},
                    {"region": "Latin America", "product": "Widget C", "revenue": 40000},
                    {"region": "ME & Africa", "product": "Widget A", "revenue": 41000},
                    {"region": "ME & Africa", "product": "Widget B", "revenue": 34000},
                    {"region": "ME & Africa", "product": "Widget C", "revenue": 22000},
                ]
            },
            "mark": "bar",
            "encoding": {
                "x": {"field": "region", "type": "nominal", "title": None},
                "y": {
                    "field": "revenue",
                    "type": "quantitative",
                    "title": "Revenue ($)",
                    "axis": {"format": "$,.0f"},
                },
                "color": {
                    "field": "product",
                    "type": "nominal",
                    "scale": {"range": ["#3B82F6", "#EA580C", "#16A34A"]},
                    "legend": {"title": "Product"},
                },
                "tooltip": [
                    {"field": "region", "type": "nominal", "title": "Region"},
                    {"field": "product", "type": "nominal", "title": "Product"},
                    {"field": "revenue", "type": "quantitative", "title": "Revenue", "format": "$,.0f"},
                ],
            },
            "width": "container",
        }
    ),
)

_SCATTER_CHART = ChartEvent(
    event_type="response.chart",
    tool_use_id="tool_006",
    chart_spec=json.dumps(
        {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "description": "Orders vs revenue by region — scatter",
            "data": {
                "values": [
                    {"region": "North America", "orders": 1850, "revenue": 452000, "avg_order": 244},
                    {"region": "Europe", "orders": 1423, "revenue": 381000, "avg_order": 267},
                    {"region": "Asia Pacific", "orders": 1108, "revenue": 294000, "avg_order": 265},
                    {"region": "Latin America", "orders": 722, "revenue": 183000, "avg_order": 253},
                    {"region": "ME & Africa", "orders": 389, "revenue": 97000, "avg_order": 249},
                ]
            },
            "mark": {"type": "point", "filled": True, "size": 120},
            "encoding": {
                "x": {"field": "orders", "type": "quantitative", "title": "Orders"},
                "y": {
                    "field": "revenue",
                    "type": "quantitative",
                    "title": "Revenue ($)",
                    "axis": {"format": "$,.0f"},
                },
                "color": {
                    "field": "region",
                    "type": "nominal",
                    "scale": {"range": ["#3B82F6", "#EA580C", "#16A34A", "#8B5CF6", "#EF4444"]},
                    "legend": {"title": "Region"},
                },
                "size": {"field": "avg_order", "type": "quantitative", "legend": {"title": "Avg order ($)"}},
                "tooltip": [
                    {"field": "region", "type": "nominal", "title": "Region"},
                    {"field": "orders", "type": "quantitative", "title": "Orders"},
                    {"field": "revenue", "type": "quantitative", "title": "Revenue", "format": "$,.0f"},
                    {"field": "avg_order", "type": "quantitative", "title": "Avg Order ($)"},
                ],
            },
            "width": "container",
        }
    ),
)

_HEATMAP_CHART = ChartEvent(
    event_type="response.chart",
    tool_use_id="tool_007",
    chart_spec=json.dumps(
        {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "description": "Orders by day of week and hour — heatmap",
            "data": {
                "values": [
                    {"day": d, "hour": h, "orders": v}
                    for d, hours in [
                        ("Mon", [12, 18, 24, 31, 38, 42, 45, 43, 39, 34, 28, 21, 15, 10, 7, 5]),
                        ("Tue", [10, 15, 22, 30, 40, 48, 52, 50, 44, 37, 30, 22, 16, 11, 8, 5]),
                        ("Wed", [11, 17, 25, 33, 42, 51, 55, 53, 47, 40, 32, 24, 17, 12, 8, 6]),
                        ("Thu", [13, 19, 27, 35, 44, 53, 57, 55, 49, 41, 33, 25, 18, 13, 9, 6]),
                        ("Fri", [15, 22, 30, 38, 47, 55, 58, 56, 50, 43, 35, 27, 20, 14, 10, 7]),
                        ("Sat", [8, 12, 18, 25, 32, 38, 40, 39, 35, 30, 24, 18, 13, 9, 6, 4]),
                        ("Sun", [6, 9, 14, 20, 26, 31, 33, 32, 29, 25, 20, 15, 11, 7, 5, 3]),
                    ]
                    for h, v in zip(range(6, 22), hours)
                ]
            },
            "mark": "rect",
            "encoding": {
                "x": {
                    "field": "hour",
                    "type": "ordinal",
                    "title": "Hour of day",
                    "axis": {"labelExpr": "datum.value + ':00'"},
                },
                "y": {
                    "field": "day",
                    "type": "ordinal",
                    "sort": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    "title": None,
                },
                "color": {
                    "field": "orders",
                    "type": "quantitative",
                    "title": "Orders",
                    "scale": {"scheme": "blues"},
                },
                "tooltip": [
                    {"field": "day", "type": "ordinal", "title": "Day"},
                    {"field": "hour", "type": "ordinal", "title": "Hour"},
                    {"field": "orders", "type": "quantitative", "title": "Orders"},
                ],
            },
            "width": "container",
        }
    ),
)

_ANALYST_SQL = (
    "SELECT\n"
    "    region,\n"
    "    SUM(revenue)              AS total_revenue,\n"
    "    COUNT(*)                  AS orders,\n"
    "    AVG(order_value)          AS avg_order_value\n"
    "FROM sales\n"
    "WHERE quarter = 'Q1 2026'\n"
    "GROUP BY region\n"
    "ORDER BY total_revenue DESC"
)


# ---------------------------------------------------------------------------
# Scenario generators
# ---------------------------------------------------------------------------


def _scenario_simple_text(prompt: str) -> Iterator[SSEEvent]:
    """Streams a plain text response with no tools or structured data.

    Args:
        prompt: The user's input text.

    Yields:
        :class:`~cortex_agents_client.models.events.SSEEvent` objects.
    """
    response = (
        f'You asked: **"{prompt}"**\n\n'
        "This is a simulated streaming text response. The Cortex Agent generates "
        "its reply token by token — the `:shimmer[▌]` cursor tracks the live "
        "position during streaming, then disappears when the response is complete.\n\n"
        "Try sending another message to see the conversation history replay on "
        "the next Streamlit rerun."
    )
    yield from _stream_text(response)
    yield SuggestedQueriesEvent(
        event_type="response.suggested_queries",
        queries=[
            "What regions have the highest revenue?",
            "Show me a chart of monthly trends",
            "How does Q1 compare to last year?",
        ],
    )
    yield _metadata(1)


def _scenario_thinking(prompt: str) -> Iterator[SSEEvent]:
    """Streams a reasoning block followed by a text answer.

    Args:
        prompt: The user's input text.

    Yields:
        :class:`~cortex_agents_client.models.events.SSEEvent` objects.
    """
    thinking = (
        f'The user asked: "{prompt}"\n\n'
        "Let me think step by step.\n\n"
        "First, I should understand what they're really asking. The question "
        "seems to be about sales performance. I have access to the SALES database "
        "with regional data.\n\n"
        "I can query the Q1 2026 data grouped by region and return a summary. "
        "The most relevant metric is total revenue, followed by order count. "
        "North America will likely be the top region based on historical patterns."
    )
    response = (
        "Based on Q1 2026 data, **North America** leads with $452K revenue across "
        "1,850 orders, followed closely by **Europe** at $381K.\n\n"
        "The **Asia Pacific** region shows strong growth potential at $294K. "
        "Average order values are consistent across all regions (~$250–$267), "
        "suggesting the revenue gap is driven by order volume rather than deal size."
    )
    yield from _stream_thinking(thinking)
    yield from _stream_text(response)
    yield _metadata(2)


def _scenario_cortex_search(prompt: str) -> Iterator[SSEEvent]:
    """Simulates Cortex Search tool use with citations in the response.

    Args:
        prompt: The user's input text.

    Yields:
        :class:`~cortex_agents_client.models.events.SSEEvent` objects.
    """
    yield ToolUseEvent(
        event_type="response.tool_use",
        tool_use_id="tool_001",
        type="cortex_search",
        name="PRODUCT_KNOWLEDGE_BASE",
        input={"query": prompt, "limit": 3},
    )
    time.sleep(0.1)
    yield ToolResultStatusEvent(
        event_type="response.tool_result.status",
        tool_use_id="tool_001",
        tool_type="cortex_search",
        status="searching",
        message="Searching product knowledge base...",
    )
    time.sleep(0.4)
    yield ToolResultStatusEvent(
        event_type="response.tool_result.status",
        tool_use_id="tool_001",
        tool_type="cortex_search",
        status="complete",
        message="Found 3 relevant documents",
    )
    time.sleep(0.1)
    yield ToolResultEvent(
        event_type="response.tool_result",
        tool_use_id="tool_001",
        type="cortex_search",
        name="PRODUCT_KNOWLEDGE_BASE",
        status="success",
        content=[
            {
                "type": "text",
                "text": (
                    "Doc 1: Widget A specification sheet — performance benchmarks, "
                    "compatibility matrix, pricing tiers.\n"
                    "Doc 2: Q1 2026 product release notes — new features for Widget B.\n"
                    "Doc 3: Competitive analysis — market positioning vs Gadget X and Y."
                ),
            }
        ],
    )
    response = (
        "Based on the knowledge base [^1], **Widget A** remains the top-selling "
        "product with strong performance across all benchmark categories.\n\n"
        "The Q1 2026 release notes [^2] highlight three new features for **Widget B** "
        "that close the gap with competing products.\n\n"
        "Our competitive analysis [^3] shows a 15% price advantage over Gadget X "
        "while maintaining comparable performance specs."
    )
    yield from _stream_text(response)
    # Citation annotations — emitted after the text block, one per [^N] marker
    yield TextAnnotationEvent(
        event_type="response.text.annotation",
        content_index=0,
        annotation_index=0,
        annotation_type="cortex_search_citation",
        index=1,
        search_result_id="sr_001",
        doc_id="https://docs.example.com/widget-a-spec",
        doc_title="Widget A Specification Sheet",
        text="Performance benchmarks, compatibility matrix, pricing tiers.",
    )
    yield TextAnnotationEvent(
        event_type="response.text.annotation",
        content_index=0,
        annotation_index=1,
        annotation_type="cortex_search_citation",
        index=2,
        search_result_id="sr_002",
        doc_id="internal://release-notes/q1-2026",
        doc_title="Q1 2026 Product Release Notes",
        text="New features for Widget B that close the gap with competing products.",
    )
    yield TextAnnotationEvent(
        event_type="response.text.annotation",
        content_index=0,
        annotation_index=2,
        annotation_type="cortex_search_citation",
        index=3,
        search_result_id="sr_003",
        doc_id="https://docs.example.com/competitive-analysis-2026",
        doc_title="Competitive Analysis 2026",
        text="15% price advantage over Gadget X while maintaining comparable performance specs.",
    )
    yield SuggestedQueriesEvent(
        event_type="response.suggested_queries",
        queries=[
            "What new features were added in Q1 2026?",
            "How does Widget A compare to Gadget X on price?",
        ],
    )
    yield _metadata(3)


def _scenario_cortex_analyst(prompt: str, *, verified: bool = False) -> Iterator[SSEEvent]:
    """Simulates Cortex Analyst — SQL generation via system_execute_sql.

    Models the Apr 2026+ API behavior: ToolUseEvent with type="system_execute_sql"
    and SQL in input["sql"], followed by ToolResultStatusEvent updates, a
    ToolResultEvent, and a TableEvent with the result set.

    Args:
        prompt: The user's input text.
        verified: If ``True``, sets ``verified_query_used=True`` in the
            tool use input to indicate a pre-verified query was matched.

    Yields:
        :class:`~cortex_agents_client.models.events.SSEEvent` objects.
    """
    yield ToolUseEvent(
        event_type="response.tool_use",
        tool_use_id="tool_001",
        type="system_execute_sql",
        name="system_execute_sql",
        input={
            "semantic_model": "SalesAnalyst",
            "sql": _ANALYST_SQL,
            "verified_query_used": verified,
        },
    )
    time.sleep(0.15)
    yield ToolResultStatusEvent(
        event_type="response.tool_result.status",
        tool_use_id="tool_001",
        tool_type="system_execute_sql",
        status="Validating SQL",
        message="Postprocessing and validating SQL",
    )
    time.sleep(0.2)
    yield ToolResultStatusEvent(
        event_type="response.tool_result.status",
        tool_use_id="tool_001",
        tool_type="system_execute_sql",
        status="Executing SQL",
        message="Executing SQL",
    )
    time.sleep(0.4)
    yield ToolResultEvent(
        event_type="response.tool_result",
        tool_use_id="tool_001",
        type="system_execute_sql",
        name="system_execute_sql",
        status="success",
        content=[],
    )
    # Table is emitted separately after the tool result
    yield _SALES_TABLE
    response = (
        "Here is the revenue breakdown by region for Q1 2026.\n\n"
        "**North America** leads at $452K, driven by 1,850 orders. "
        "**Europe** follows at $381K. Average order values are consistent "
        "across all regions, suggesting the gap is driven by volume, not price."
    )
    yield from _stream_text(response)
    yield SuggestedQueriesEvent(
        event_type="response.suggested_queries",
        queries=[
            "How does the total quantity sold break down by product?",
            "How does revenue break down by region for each product?",
            "How many transactions were there for each product?",
        ],
    )
    yield _metadata(4)


def _scenario_cortex_analyst_verified(prompt: str) -> Iterator[SSEEvent]:
    """Cortex Analyst with ``verified_query_used=True``.

    Identical to :func:`_scenario_cortex_analyst` but emits a verified delta,
    so the status expander shows :material/verified: instead of
    :material/check_circle:.
    """
    yield from _scenario_cortex_analyst(prompt, verified=True)


def _scenario_table(prompt: str) -> Iterator[SSEEvent]:
    """Returns a standalone table without tool use framing.

    Args:
        prompt: The user's input text.

    Yields:
        :class:`~cortex_agents_client.models.events.SSEEvent` objects.
    """
    intro = "Here is the Q1 2026 regional revenue summary:"
    yield from _stream_text(intro, delay=0.02)
    time.sleep(0.1)
    yield _SALES_TABLE
    summary = (
        "\n\nTotal Q1 revenue: **$1.41M** across **5,492 orders**. "
        "North America and Europe together account for 59% of total revenue."
    )
    yield from _stream_text(summary, delay=0.02)
    yield _metadata(5)


def _scenario_chart(prompt: str) -> Iterator[SSEEvent]:
    """Returns multiple chart types followed by text interpretations.

    Exercises line, bar, area, stacked bar, scatter, and heatmap Vega-Lite
    specs to demonstrate the full range of chart rendering in the UI.

    Args:
        prompt: The user's input text.

    Yields:
        :class:`~cortex_agents_client.models.events.SSEEvent` objects.
    """
    yield from _stream_text("**Line chart** — monthly revenue trend:", delay=0.02)
    time.sleep(0.1)
    yield _TREND_CHART

    yield from _stream_text("\n\n**Bar chart** — Q1 2026 revenue by region:", delay=0.02)
    time.sleep(0.1)
    yield _BAR_CHART

    yield from _stream_text("\n\n**Area chart** — same trend data with filled area:", delay=0.02)
    time.sleep(0.1)
    yield _AREA_CHART

    yield from _stream_text("\n\n**Stacked bar chart** — product mix breakdown by region:", delay=0.02)
    time.sleep(0.1)
    yield _STACKED_BAR_CHART

    yield from _stream_text("\n\n**Scatter plot** — orders vs revenue (bubble size = avg order value):", delay=0.02)
    time.sleep(0.1)
    yield _SCATTER_CHART

    yield from _stream_text("\n\n**Heatmap** — order volume by day of week and hour:", delay=0.02)
    time.sleep(0.1)
    yield _HEATMAP_CHART

    insight = (
        "\n\nAll six standard chart types rendered via Vega-Lite `ChartEvent`. "
        "Revenue grows **+60% YTD** Jan–Sep. Friday afternoons (14:00–17:00) are "
        "the peak ordering window across all regions."
    )
    yield from _stream_text(insight, delay=0.02)
    yield _metadata(6)


def _scenario_clarification(prompt: str) -> Iterator[SSEEvent]:
    """Agent asks the user a clarifying question (is_elicitation=True).

    This renders as an ``st.info()`` box with a contact_support icon rather
    than a plain markdown block, so the user clearly sees it is a question.

    Args:
        prompt: The user's input text.

    Yields:
        :class:`~cortex_agents_client.models.events.SSEEvent` objects.
    """
    question = (
        "To give you the most relevant answer, I need a little more context.\n\n"
        "Could you clarify:\n"
        "1. **Which time period** are you interested in? (e.g. last quarter, YTD, specific month)\n"
        "2. **Which regions** should I focus on, or would you like a global view?\n\n"
        "Once I have these details, I can pull the exact data you need."
    )
    yield from _stream_text(question, is_elicitation=True)
    yield _metadata(7)


def _scenario_warning(prompt: str) -> Iterator[SSEEvent]:
    """Emits a warning followed by a degraded-but-valid text response.

    Args:
        prompt: The user's input text.

    Yields:
        :class:`~cortex_agents_client.models.events.SSEEvent` objects.
    """
    yield WarningEvent(
        event_type="response.warning",
        message=(
            "The semantic model does not have a verified query for this question. "
            "The generated SQL may not exactly match your intent — please review "
            "the results carefully."
        ),
        code="UNVERIFIED_QUERY",
    )
    time.sleep(0.1)
    response = (
        "I was able to generate a response, but please note the warning above.\n\n"
        "The data I'm returning is based on an automatically generated SQL query "
        "that has not been pre-verified. The results shown should be treated as "
        "indicative rather than authoritative until the query has been reviewed."
    )
    yield from _stream_text(response)
    yield _metadata(8)


def _scenario_error(prompt: str) -> Iterator[SSEEvent]:
    """Emits a fatal error that terminates the stream.

    Args:
        prompt: The user's input text.

    Yields:
        :class:`~cortex_agents_client.models.events.SSEEvent` objects (one event).
    """
    time.sleep(0.3)
    yield ErrorEvent(
        event_type="error",
        code="390144",
        message=(
            "JWT token is invalid. The session token used to authenticate this "
            "request has expired or been revoked. Please re-authenticate and retry."
        ),
        request_id="demo-req-00000000-0000-0000-0000-000000000000",
    )


def _scenario_kitchen_sink(prompt: str) -> Iterator[SSEEvent]:
    """All event types in one response: thinking, tool, table, chart, text.

    This is the most comprehensive scenario for UI testing. It exercises
    every rendering path in
    :func:`~cortex_agents_client.st.render.render_streaming_response`.

    Args:
        prompt: The user's input text.

    Yields:
        :class:`~cortex_agents_client.models.events.SSEEvent` objects.
    """
    # 1. Thinking
    thinking = (
        f'The user asked: "{prompt}"\n\n'
        "I'll need to use Cortex Analyst to query the sales database and then "
        "visualise the results as both a table and a chart. I should also add "
        "a narrative interpretation to make the answer actionable."
    )
    yield from _stream_thinking(thinking)

    # 2. Tool use — Cortex Analyst
    yield ToolUseEvent(
        event_type="response.tool_use",
        tool_use_id="tool_ks_001",
        type="system_execute_sql",
        name="SALES_SEMANTIC_MODEL",
        input={"question": prompt},
    )
    time.sleep(0.1)
    yield ToolResultStatusEvent(
        event_type="response.tool_result.status",
        tool_use_id="tool_ks_001",
        tool_type="system_execute_sql",
        status="generating_sql",
        message="Generating SQL...",
    )
    time.sleep(0.3)
    yield AnalystDeltaEvent(
        event_type="response.tool_result.analyst.delta",
        tool_use_id="tool_ks_001",
        tool_type="system_execute_sql",
        sql=_ANALYST_SQL,
    )
    time.sleep(0.05)
    yield ToolResultStatusEvent(
        event_type="response.tool_result.status",
        tool_use_id="tool_ks_001",
        tool_type="system_execute_sql",
        status="executing_sql",
        message="Executing query...",
    )
    time.sleep(0.4)
    yield ToolResultEvent(
        event_type="response.tool_result",
        tool_use_id="tool_ks_001",
        type="system_execute_sql",
        name="SALES_SEMANTIC_MODEL",
        status="success",
        content=[],
    )

    # 3. Table result
    yield _SALES_TABLE

    # 4. Chart result
    yield _TREND_CHART

    # 5. Warning (non-fatal)
    yield WarningEvent(
        event_type="response.warning",
        message="Historical data for Q2 2026 is incomplete; figures may change.",
        code="PARTIAL_DATA",
    )

    # 6. Final text response
    response = (
        "Here is a complete picture of your sales performance.\n\n"
        "The **table** above shows Q1 2026 regional revenue. "
        "The **chart** tracks the monthly trend through September 2026.\n\n"
        "Key takeaway: revenue is growing +60% YTD, with North America and "
        "Europe accounting for nearly 60% of the total. Asia Pacific shows "
        "the fastest growth rate at +22% quarter-over-quarter."
    )
    yield from _stream_text(response)
    yield SuggestedQueriesEvent(
        event_type="response.suggested_queries",
        queries=[
            "Break down revenue by product",
            "Show quarter-over-quarter growth rates",
            "Which region is growing fastest?",
        ],
    )
    yield _metadata(9)


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

#: Ordered display names for the sidebar selector.
SCENARIO_NAMES: list[str] = [
    "Simple text",
    "Thinking",
    "Cortex Search",
    "Cortex Analyst",
    "Cortex Analyst (Verified)",
    "Table",
    "Chart",
    "Clarification",
    "Warning",
    "Error",
    "Kitchen sink",
]

#: Maps scenario display name → generator function.
SCENARIOS: dict[str, Any] = {
    "Simple text": _scenario_simple_text,
    "Thinking": _scenario_thinking,
    "Cortex Search": _scenario_cortex_search,
    "Cortex Analyst": _scenario_cortex_analyst,
    "Cortex Analyst (Verified)": _scenario_cortex_analyst_verified,
    "Table": _scenario_table,
    "Chart": _scenario_chart,
    "Clarification": _scenario_clarification,
    "Warning": _scenario_warning,
    "Error": _scenario_error,
    "Kitchen sink": _scenario_kitchen_sink,
}

#: One-line description shown as an info banner in the demo UI.
SCENARIO_HINTS: dict[str, str] = {
    "Simple text": "Streaming text deltas → final TextEvent + suggested follow-up queries as clickable buttons.",
    "Thinking": "ThinkingDeltaEvent blocks before the answer. Toggle 'Show reasoning' in the sidebar to show/hide the expander.",
    "Cortex Search": "ToolUse + ToolResultStatus + ToolResult + citations + suggested queries. Tests the compact status spinner and success state.",
    "Cortex Analyst": "system_execute_sql tool with SQL in input, ToolResult, TableEvent result, and suggested follow-up queries.",
    "Cortex Analyst (Verified)": "Same as Cortex Analyst but verified_query_used=True → status expander shows the verified icon instead of check_circle.",
    "Table": "A standalone TableEvent rendered as a DataFrame — no tool framing.",
    "Chart": "Six ChartEvent types: line, bar, area, stacked bar, scatter, and heatmap — all rendered via st.vega_lite_chart.",
    "Clarification": "is_elicitation=True response. Renders as st.info() with a contact_support icon instead of plain markdown.",
    "Warning": "WarningEvent (non-fatal) + text response. Tests st.warning() with title and continuation of the stream.",
    "Error": "Fatal ErrorEvent that terminates the stream. Tests st.error() rendering.",
    "Kitchen sink": "All event types: thinking + tool use + SQL + table + chart + warning + text + suggested queries.",
}


# ---------------------------------------------------------------------------
# Mock client and thread
# ---------------------------------------------------------------------------


class MockThread:
    """A Thread stub that returns canned SSEEvent streams for a given scenario.

    Attributes:
        scenario: Display name of the active scenario.

    Args:
        scenario: One of the keys in :data:`SCENARIOS`.
    """

    def __init__(self, scenario: str) -> None:
        """Initialises the mock thread for *scenario*.

        Args:
            scenario: Display name of the scenario to run.
        """
        self.scenario = scenario

    def chat(self, agent_path: str, prompt: str, **kwargs) -> Iterator[SSEEvent]:
        """Returns an event iterator for the configured scenario.

        Args:
            agent_path: Ignored in mock mode.
            prompt: The user's message, passed to the scenario generator.

        Yields:
            :class:`~cortex_agents_client.models.events.SSEEvent` objects.
        """
        gen_fn = SCENARIOS.get(self.scenario, _scenario_simple_text)
        yield from gen_fn(prompt)

    def list_messages(self) -> list:
        """Stub — returns empty list (no persisted history in mock mode)."""
        return []

    def latest_context(self) -> list:
        """Stub — returns empty list (no compaction state in mock mode)."""
        return []

    def fork(self, at_message_id: int) -> "MockThread":
        """Stub — returns a new MockThread for the same scenario."""
        return MockThread(self.scenario)

    def delete(self) -> None:
        """Stub — no-op in mock mode."""


class MockClient:
    """A CortexAgentsClient stub whose :meth:`create_thread` returns a MockThread.

    Used alongside :class:`MockThread` to satisfy :func:`~cortex_agents_client.st.session.reset_thread`
    which calls ``client.create_thread(origin_application=...)``.

    Args:
        scenario: Active scenario name forwarded to new threads.
    """

    def __init__(self, scenario: str) -> None:
        """Initialises the mock client for *scenario*.

        Args:
            scenario: Display name of the active scenario.
        """
        self.scenario = scenario
        self.agents = _MockAgentsResource()

    def create_thread(self, **kwargs: Any) -> MockThread:
        """Returns a fresh :class:`MockThread` for the current scenario.

        Args:
            **kwargs: Accepted and ignored (mirrors the real API signature).

        Returns:
            A new :class:`MockThread` for :attr:`scenario`.
        """
        return MockThread(self.scenario)


class _MockAgentsResource:
    """Stub for client.agents that returns an Agent with sample_questions."""

    def get(self, *args: Any, **kwargs: Any) -> Any:
        from cortex_agents_client.models.agent import Agent, AgentInstructions
        return Agent(
            name="DEMO_AGENT",
            instructions=AgentInstructions(
                sample_questions=[
                    "What regions have the highest revenue?",
                    "Show me monthly sales trends",
                    "How does Q1 compare to last year?",
                    "Which products have the best margins?",
                    "Summarize our top 10 customers",
                ],
            ),
        )
