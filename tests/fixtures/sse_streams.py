"""SSE stream fixtures for testing.

Provides helper functions that generate synthetic SSE byte streams
covering all 17 event types and common edge cases.
"""
from __future__ import annotations

import json


def make_sse_event(event_type: str, payload: dict) -> str:
    """Builds a single SSE event string.

    Args:
        event_type: The SSE event type.
        payload: The JSON payload dict.

    Returns:
        A complete SSE event string including trailing blank line.
    """
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


def stream_of(*events: tuple[str, dict]) -> list[str]:
    """Converts a sequence of (event_type, payload) pairs to SSE lines.

    Args:
        *events: Variable number of (event_type, payload) tuples.

    Returns:
        List of SSE line strings (without newlines; as returned by
        ``httpx.Response.iter_lines()``).
    """
    lines: list[str] = []
    for event_type, payload in events:
        lines.append(f"event: {event_type}")
        lines.append(f"data: {json.dumps(payload)}")
        lines.append("")  # blank line separator
    return lines


# Sample payloads for all 17 event types
TEXT_DELTA_PAYLOAD = {"content_index": 0, "text": "Hello ", "is_elicitation": False}
TEXT_PAYLOAD = {"content_index": 0, "text": "Hello world"}
TEXT_ANNOTATION_PAYLOAD = {
    "content_index": 0,
    "annotation_index": 0,
    "annotation": {
        "type": "cortex_search_citation",
        "index": 1,
        "search_result_id": "cs_abc123",
        "doc_id": "doc_456",
        "doc_title": "Annual Report 2025",
        "text": "Revenue was $4.2B",
    },
}
THINKING_DELTA_PAYLOAD = {
    "content_index": 1,
    "text": "Let me think...",
    "signature": "sig123",
}
THINKING_PAYLOAD = {
    "content_index": 1,
    "text": "I need to use the Analyst tool.",
    "signature": "sig_full",
}
TOOL_USE_PAYLOAD = {
    "content_index": 2,
    "tool_use_id": "toolu_01",
    "type": "cortex_analyst_text_to_sql",
    "name": "Analyst1",
    "input": {"query": "total revenue 2025"},
    "client_side_execute": False,
    "permission": {"options": []},
}
TOOL_USE_WITH_PERMISSION_PAYLOAD = {
    **TOOL_USE_PAYLOAD,
    "permission": {"options": ["Allow Once", "Deny"]},
}
TOOL_RESULT_PAYLOAD = {
    "content_index": 2,
    "tool_use_id": "toolu_01",
    "type": "cortex_analyst_text_to_sql",
    "name": "Analyst1",
    "content": [{"type": "json", "json": {"answer": "Revenue was $4.2B"}}],
    "status": "success",
}
TOOL_RESULT_ERROR_PAYLOAD = {**TOOL_RESULT_PAYLOAD, "status": "error"}
TOOL_RESULT_STATUS_PAYLOAD = {
    "tool_use_id": "toolu_01",
    "tool_type": "cortex_analyst_text_to_sql",
    "status": "Executing SQL",
    "message": "Running SELECT ...",
    "details": {},
}
ANALYST_DELTA_PAYLOAD = {
    "content_index": 2,
    "tool_use_id": "toolu_01",
    "tool_type": "cortex_analyst_text_to_sql",
    "tool_name": "Analyst1",
    "delta": {
        "text": "Based on the data,",
        "think": "I'll aggregate revenue.",
        "sql": "SELECT SUM(revenue) FROM sales WHERE year = 2025",
        "sql_explanation": "Sums revenue for 2025.",
        "query_id": "qid_789",
        "verified_query_used": False,
        "result_set": {
            "statementHandle": "stmnt_abc",
            "resultSetMetaData": {
                "partition": 0,
                "numRows": 1,
                "format": "jsonv2",
                "rowType": [
                    {"name": "REVENUE", "type": "FLOAT", "length": 0,
                     "precision": 15, "scale": 2, "nullable": True}
                ],
            },
            "data": [["4200000000.00"]],
        },
        "suggestions": None,
    },
}
TABLE_PAYLOAD = {
    "content_index": 3,
    "tool_use_id": "toolu_01",
    "query_id": "qid_789",
    "result_set": {
        "statementHandle": "stmnt_abc",
        "resultSetMetaData": {
            "partition": 0,
            "numRows": 2,
            "format": "jsonv2",
            "rowType": [
                {"name": "YEAR", "type": "INTEGER", "length": 0,
                 "precision": 10, "scale": 0, "nullable": False},
                {"name": "REVENUE", "type": "FLOAT", "length": 0,
                 "precision": 15, "scale": 2, "nullable": True},
            ],
        },
        "data": [["2025", "4200000000.00"], ["2024", "4000000000.00"]],
    },
    "title": "Annual Revenue",
}
CHART_PAYLOAD = {
    "content_index": 4,
    "tool_use_id": "toolu_chart_01",
    "chart_spec": json.dumps({
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": [{"year": 2025, "revenue": 4200000000}]},
        "mark": "bar",
        "encoding": {
            "x": {"field": "year", "type": "ordinal"},
            "y": {"field": "revenue", "type": "quantitative"},
        },
    }),
}
STATUS_PAYLOAD = {"status": "executing_tool", "message": "Executing tool `Analyst1`"}
WARNING_PAYLOAD = {
    "message": "Unable to connect to MCP server 'jira'.",
    "code": "003001",
}
ERROR_PAYLOAD = {
    "code": "399504",
    "error_code": "399504",
    "message": "Agent execution failed.",
    "request_id": "req_abc123",
}
METADATA_USER_PAYLOAD = {"metadata": {"role": "user", "message_id": 123, "run_id": "run_1"}}
METADATA_ASSISTANT_PAYLOAD = {"metadata": {"role": "assistant", "message_id": 456, "run_id": "run_1"}}
RESPONSE_PAYLOAD = {
    "role": "assistant",
    "content": [
        {"type": "text", "text": {"text": "Revenue was $4.2B", "annotations": []}},
    ],
    "warnings": [],
    "status": "completed",
    "metadata": {
        "run_id": "run_1",
        "thread_id": 99,
        "user_message_id": 123,
        "assistant_message_id": 456,
        "usage": {
            "tokens_consumed": [
                {
                    "model_name": "claude-3-5-sonnet",
                    "input_tokens": {
                        "total": 1500,
                        "cache_read": 1200,
                        "cache_write": 100,
                        "uncached": 200,
                    },
                    "output_tokens": {"total": 250},
                    "context_window": 200000,
                }
            ]
        },
    },
}

SUGGESTED_QUERIES_PAYLOAD = {
    "content_index": 0,
    "suggested_queries": [
        {"query": "What is Q2 revenue?"},
        {"query": "Show top products by region"},
    ],
}

ALL_EVENT_TYPES = [
    ("response.text.delta", TEXT_DELTA_PAYLOAD),
    ("response.text", TEXT_PAYLOAD),
    ("response.text.annotation", TEXT_ANNOTATION_PAYLOAD),
    ("response.thinking.delta", THINKING_DELTA_PAYLOAD),
    ("response.thinking", THINKING_PAYLOAD),
    ("response.tool_use", TOOL_USE_PAYLOAD),
    ("response.tool_result", TOOL_RESULT_PAYLOAD),
    ("response.tool_result.status", TOOL_RESULT_STATUS_PAYLOAD),
    ("response.tool_result.analyst.delta", ANALYST_DELTA_PAYLOAD),
    ("response.table", TABLE_PAYLOAD),
    ("response.chart", CHART_PAYLOAD),
    ("response.suggested_queries", SUGGESTED_QUERIES_PAYLOAD),
    ("response.status", STATUS_PAYLOAD),
    ("response.warning", WARNING_PAYLOAD),
    ("error", ERROR_PAYLOAD),
    ("metadata", METADATA_USER_PAYLOAD),
    ("response", RESPONSE_PAYLOAD),
]
