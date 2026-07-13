"""Live tests: Cortex Analyst agent — TableEvent, AnalystDeltaEvent, SQL generation.

These tests require LIVE_AGENT_ANALYST to be set and the analyst agent to be
deployed (see tests/live/seed/04_semantic_view.sql and 05_analyst_agent.sql).
They verify that Cortex Analyst-specific events (AnalystDeltaEvent, TableEvent)
are emitted when the agent answers an aggregation question.

Skipped automatically if LIVE_AGENT_ANALYST is not set.
"""
from __future__ import annotations

import pytest

from cortex_agents_client.client import Thread
from cortex_agents_client.models.events import (
    AnalystDeltaEvent,
    ResponseEvent,
    TableEvent,
    TextDeltaEvent,
    ToolResultEvent,
    ToolUseEvent,
)

# A question that should cause the agent to query the sales semantic view
# and return a table of results.
_ANALYST_QUERY = "What is the total revenue by product?"


@pytest.mark.live
class TestAnalystToolUse:
    """Verify the Cortex Analyst tool is invoked."""

    def test_tool_use_event_is_emitted(
        self,
        live_thread: Thread,
        agent_path_analyst: str,
    ) -> None:
        """At least one ToolUseEvent with type='cortex_analyst_text_to_sql' is yielded."""
        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        tool_use_events = [e for e in events if isinstance(e, ToolUseEvent)]
        assert len(tool_use_events) >= 1
        tool_types = {e.type for e in tool_use_events}
        assert "cortex_analyst_text_to_sql" in tool_types

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
class TestAnalystDeltaEvent:
    """Verify AnalystDeltaEvent (streaming SQL) is emitted."""

    def test_analyst_delta_event_contains_sql(
        self,
        live_thread: Thread,
        agent_path_analyst: str,
    ) -> None:
        """At least one AnalystDeltaEvent with non-empty SQL is emitted."""
        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        analyst_deltas = [e for e in events if isinstance(e, AnalystDeltaEvent) and e.sql]
        assert len(analyst_deltas) >= 1, "No AnalystDeltaEvent with SQL was emitted"
        # SQL should reference the sales table or semantic view
        combined_sql = " ".join(e.sql for e in analyst_deltas if e.sql).upper()
        assert "REVENUE" in combined_sql or "SALES" in combined_sql, (
            f"Generated SQL does not mention expected tables/columns: {combined_sql[:200]}"
        )


@pytest.mark.live
class TestTableEvent:
    """Verify TableEvent (SQL result set) is emitted."""

    def test_table_event_is_emitted(
        self,
        live_thread: Thread,
        agent_path_analyst: str,
    ) -> None:
        """At least one TableEvent is yielded containing query results."""
        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        table_events = [e for e in events if isinstance(e, TableEvent)]
        assert len(table_events) >= 1, "No TableEvent was emitted"

    def test_table_event_has_rows(
        self,
        live_thread: Thread,
        agent_path_analyst: str,
    ) -> None:
        """The TableEvent result set contains at least one row."""
        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        table_events = [e for e in events if isinstance(e, TableEvent)]
        if not table_events:
            pytest.skip("No TableEvent received")
        # numRows is inside resultSetMetaData
        num_rows = int(
            table_events[0].result_set.get("resultSetMetaData", {}).get("numRows", 0)
        )
        assert num_rows >= 1, f"TableEvent result set has no rows (numRows={num_rows})"

    def test_table_event_result_set_to_dataframe(
        self,
        live_thread: Thread,
        agent_path_analyst: str,
    ) -> None:
        """result_set_to_dataframe() converts the TableEvent to a non-empty DataFrame."""
        from cortex_agents_client.st.render import result_set_to_dataframe

        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        table_events = [e for e in events if isinstance(e, TableEvent)]
        if not table_events:
            pytest.skip("No TableEvent received")
        df = result_set_to_dataframe(table_events[0])
        assert len(df) >= 1
        assert len(df.columns) >= 1


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
        """The agent produces a non-empty text response alongside the table."""
        events = list(live_thread.chat(agent_path_analyst, _ANALYST_QUERY))
        text_deltas = [e for e in events if isinstance(e, TextDeltaEvent)]
        full_text = "".join(e.text for e in text_deltas)
        assert full_text.strip()
