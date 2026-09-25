"""Live tests: web search agent — ToolUseEvent (web_search), ToolResultEvent.

These tests require LIVE_AGENT_WEB to be set and:
  1. The web search agent to be deployed (tests/live/seed/06_web_search_agent.sql)
  2. Web search enabled at the account level by an ACCOUNTADMIN
     (Snowsight → AI & ML → Agents → Settings → Web search toggle)

Web search results are non-deterministic, so tests assert only that the
correct events are emitted and that a response is produced — not the content.

Skipped automatically if LIVE_AGENT_WEB is not set.
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

# A question that should reliably trigger a web search.
# Phrased as a current-events question so the agent uses the tool
# rather than answering from its training data.
_WEB_QUERY = "What are some recent developments in artificial intelligence?"


@pytest.mark.live
class TestWebSearchToolUse:
    """Verify the web_search tool is invoked."""

    def test_tool_use_event_is_emitted(
        self,
        live_thread: Thread,
        agent_path_web: str,
    ) -> None:
        """At least one ToolUseEvent with type='web_search' is yielded."""
        events = list(live_thread.chat(agent_path_web, _WEB_QUERY))
        tool_use_events = [e for e in events if isinstance(e, ToolUseEvent)]
        assert len(tool_use_events) >= 1
        tool_types = {e.type for e in tool_use_events}
        assert "web_search" in tool_types, (
            f"Expected 'web_search' in tool types, got: {tool_types}"
        )

    def test_tool_result_event_follows_tool_use(
        self,
        live_thread: Thread,
        agent_path_web: str,
    ) -> None:
        """Every ToolUseEvent has a corresponding ToolResultEvent."""
        events = list(live_thread.chat(agent_path_web, _WEB_QUERY))
        tool_use_ids = {e.tool_use_id for e in events if isinstance(e, ToolUseEvent)}
        tool_result_ids = {e.tool_use_id for e in events if isinstance(e, ToolResultEvent)}
        assert tool_use_ids, "No ToolUseEvent was emitted"
        assert tool_use_ids == tool_result_ids, (
            f"Mismatched tool_use_ids: uses={tool_use_ids}, results={tool_result_ids}"
        )

    def test_tool_result_status_is_success(
        self,
        live_thread: Thread,
        agent_path_web: str,
    ) -> None:
        """All ToolResultEvents have status='success'."""
        events = list(live_thread.chat(agent_path_web, _WEB_QUERY))
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
        assert tool_results, "No ToolResultEvent was emitted"
        for result in tool_results:
            assert result.status == "success", (
                f"ToolResultEvent status was {result.status!r}"
            )


@pytest.mark.live
class TestWebSearchStreaming:
    """General streaming checks for the web search agent."""

    def test_response_event_completed(
        self,
        live_thread: Thread,
        agent_path_web: str,
    ) -> None:
        """Final ResponseEvent has status='completed'."""
        events = list(live_thread.chat(agent_path_web, _WEB_QUERY))
        response_events = [e for e in events if isinstance(e, ResponseEvent)]
        assert response_events, "No ResponseEvent was emitted"
        assert response_events[-1].status == "completed"

    def test_text_is_non_empty(
        self,
        live_thread: Thread,
        agent_path_web: str,
    ) -> None:
        """The agent produces a non-empty text response after the web search."""
        events = list(live_thread.chat(agent_path_web, _WEB_QUERY))
        text_deltas = [e for e in events if isinstance(e, TextDeltaEvent)]
        full_text = "".join(e.text for e in text_deltas)
        assert full_text.strip(), "Agent returned empty text response"
