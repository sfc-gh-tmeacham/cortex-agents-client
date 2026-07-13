"""Multi-turn conversation example (no Streamlit).

Demonstrates Thread-based conversation with the main event types handled.
"""
from __future__ import annotations

import os

from cortex_agents_client import CortexAgentsClient
from cortex_agents_client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    MetadataEvent,
    ResponseEvent,
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
    UnknownEvent,
    WarningEvent,
)

ACCOUNT_URL = os.environ["SNOWFLAKE_ACCOUNT_URL"]
PAT_TOKEN = os.environ["SNOWFLAKE_PAT"]
AGENT_PATH = os.environ["SNOWFLAKE_AGENT_PATH"]


def chat_turn(thread, message: str) -> None:
    """Runs a single conversation turn and prints all output.

    Args:
        thread: The Thread object.
        message: User message text.
    """
    print(f"\nUser: {message}")
    print("Assistant: ", end="")

    tables = []
    charts = []

    for event in thread.chat(AGENT_PATH, message):
        if isinstance(event, TextDeltaEvent):
            print(event.text, end="", flush=True)
        elif isinstance(event, TextEvent):
            # Complete text block after all deltas — check is_elicitation for clarification requests
            if event.is_elicitation:
                print(f"\n[Clarification needed]: {event.text}")
        elif isinstance(event, TextAnnotationEvent):
            # Citation annotation — corresponds to a [^N] marker in the text
            print(f"\n  [Citation {event.index}: {event.doc_title} — {event.doc_id}]")
        elif isinstance(event, ThinkingDeltaEvent):
            # Streaming thinking token — accumulate like TextDeltaEvent
            print(event.text, end="", flush=True)
        elif isinstance(event, ThinkingEvent):
            print(f"\n[Thinking: {event.text[:100]}...]", flush=True)
        elif isinstance(event, AnalystDeltaEvent):
            if event.sql:
                print(f"\n  [SQL: {event.sql[:80]}]", end="", flush=True)
        elif isinstance(event, TableEvent):
            tables.append(event)
        elif isinstance(event, ChartEvent):
            charts.append(event)
        elif isinstance(event, ToolUseEvent):
            print(f"\n  [Tool: {event.name}]", end="", flush=True)
        elif isinstance(event, ToolResultEvent):
            # Tool execution complete
            print(f"\n  [Tool result: {event.name} — {event.status}]")
        elif isinstance(event, ToolResultStatusEvent):
            print(f"\n  [Tool status: {event.status} — {event.message}]", end="", flush=True)
        elif isinstance(event, StatusEvent):
            print(f"\n[Status: {event.status}]", flush=True)
        elif isinstance(event, WarningEvent):
            print(f"\n[Warning]: {event.message}")
        elif isinstance(event, ErrorEvent):
            print(f"\n[Error {event.code}]: {event.message}")
        elif isinstance(event, MetadataEvent):
            pass  # thread.chat() advances parent_message_id automatically
        elif isinstance(event, ResponseEvent):
            for usage in event.usage:
                print(f"\n[Tokens — {usage.model_name}: {usage.input_tokens.total} in / {usage.output_tokens.total} out]")
        elif isinstance(event, UnknownEvent):
            # Forward-compat catch-all — new event types arrive as UnknownEvent
            print(f"\n[Unknown event: {event.event_type}]")

    print()  # newline after streaming

    for table in tables:
        print(f"\nTable: {table.title or '(untitled)'}")
        meta = table.result_set.get("resultSetMetaData", {})
        columns = [rt["name"] for rt in meta.get("rowType", [])]
        print(f"  Columns: {', '.join(columns)}")
        data = table.result_set.get("data", [])
        print(f"  Rows: {len(data)}")

    for chart in charts:
        import json
        spec = json.loads(chart.chart_spec)
        print(f"\nChart: mark={spec.get('mark')}")


def main() -> None:
    """Runs a multi-turn conversation demonstration."""
    client = CortexAgentsClient(ACCOUNT_URL, PAT_TOKEN)
    thread = client.create_thread(origin_application="multi_turn_example")

    print(f"Thread ID: {thread.thread_id}")

    chat_turn(thread, "What was total revenue for 2025?")
    chat_turn(thread, "How does that compare to the previous year?")
    chat_turn(thread, "Show me the top 5 customers by revenue as a chart.")

    print(f"\nFinal parent_message_id: {thread.parent_message_id}")
    print("Thread history:")
    for msg in thread.list_messages():
        payload_preview = str(msg.message_payload)[:60]
        print(f"  [{msg.role}] id={msg.message_id}: {payload_preview}...")


if __name__ == "__main__":
    main()
