"""Live tests: Cortex Analyst agent — SQL generation via system_execute_sql.

These tests require LIVE_AGENT_ANALYST to be set and the analyst agent to be
deployed (see tests/live/seed/04_semantic_view.sql and 05_analyst_agent.sql).
They verify that the agent calls system_execute_sql with generated SQL when
answering aggregation questions.

As of Apr 2026, tool use blocks of type ``cortex_analyst_text_to_sql`` were
replaced by ``system_execute_sql``. The SQL is in ``ToolUseEvent.input["sql"]``
and results (when successful) are in ``ToolResultEvent.content``.

Skipped automatically if LIVE_AGENT_ANALYST is not set.
"""
from __future__ import annotations

import pytest

from streamlit_cortex_agents.client.core import Thread
from streamlit_cortex_agents.client.models.events import (
    ResponseEvent,
    TextDeltaEvent,
    ToolResultEvent,
    ToolUseEvent,
)

# A question that should cause the agent to query the sales semantic view.
_ANALYST_QUERY = "What is the total revenue by product?"

# The new tool types emitted by agentic Cortex Analyst (Apr 2026+).
_ANALYST_TOOL_TYPES = {"system_execute_sql", "system_agentic_semantic_context"}


@pytest.mark.live
class TestAnalystToolUse:
    """Verify the Cortex Analyst tool is invoked."""

    def test_tool_use_event_is_emitted(
        self,
        live_thread: Thread,
        agent_path_analyst: str,
    ) -> None:
        """At least one ToolUseEvent with a recognized analyst tool type is yielded."""
        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        tool_use_events = [e for e in events if isinstance(e, ToolUseEvent)]
        assert len(tool_use_events) >= 1
        tool_types = {e.type for e in tool_use_events}
        assert tool_types & _ANALYST_TOOL_TYPES, (
            f"Expected one of {_ANALYST_TOOL_TYPES} but got {tool_types}"
        )

    def test_tool_result_event_follows_tool_use(
        self,
        live_thread: Thread,
        agent_path_analyst: str,
    ) -> None:
        """Every ToolUseEvent has a corresponding ToolResultEvent."""
        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        tool_use_ids = {e.tool_use_id for e in events if isinstance(e, ToolUseEvent)}
        tool_result_ids = {e.tool_use_id for e in events if isinstance(e, ToolResultEvent)}
        assert tool_use_ids
        assert tool_use_ids == tool_result_ids


@pytest.mark.live
class TestAnalystSQL:
    """Verify SQL generation in tool use events."""

    def test_system_execute_sql_contains_sql(
        self,
        live_thread: Thread,
        agent_path_analyst: str,
    ) -> None:
        """At least one system_execute_sql ToolUseEvent has a non-empty SQL field."""
        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        sql_events = [
            e for e in events
            if isinstance(e, ToolUseEvent)
            and e.type == "system_execute_sql"
            and e.input.get("sql")
        ]
        assert len(sql_events) >= 1, "No system_execute_sql ToolUseEvent with SQL was emitted"
        combined_sql = " ".join(e.input["sql"] for e in sql_events).upper()
        assert "REVENUE" in combined_sql or "SALES" in combined_sql, (
            f"Generated SQL does not mention expected tables/columns: {combined_sql[:200]}"
        )

    def test_verified_query_used(
        self,
        live_thread: Thread,
        agent_path_analyst: str,
    ) -> None:
        """The agent uses the verified query (verified_query_used=True)."""
        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        sql_events = [
            e for e in events
            if isinstance(e, ToolUseEvent)
            and e.type == "system_execute_sql"
            and e.input.get("sql")
        ]
        if not sql_events:
            pytest.skip("No system_execute_sql events emitted")
        # At least one should mark verified_query_used
        verified = [e for e in sql_events if e.input.get("verified_query_used")]
        assert verified, "Agent did not use verified query"


@pytest.mark.live
class TestAnalystStreaming:
    """General streaming checks for the analyst agent."""

    def test_response_event_completed(
        self,
        live_thread: Thread,
        agent_path_analyst: str,
    ) -> None:
        """Final ResponseEvent has status='completed'."""
        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        response_events = [e for e in events if isinstance(e, ResponseEvent)]
        assert response_events
        assert response_events[-1].status == "completed"

    def test_text_is_non_empty(
        self,
        live_thread: Thread,
        agent_path_analyst: str,
    ) -> None:
        """The agent produces a non-empty text response."""
        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        text_deltas = [e for e in events if isinstance(e, TextDeltaEvent)]
        full_text = "".join(e.text for e in text_deltas)
        assert full_text.strip()
