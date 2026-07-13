"""Live tests: full agent with Cortex Search tool.

These tests require LIVE_AGENT_FULL to be set and the full search-enabled
agent to be deployed (see tests/live/seed/). They verify that tool-use events,
tool-result events, and citation annotations are emitted correctly.

Skipped automatically if LIVE_AGENT_FULL is not set.
"""
from __future__ import annotations

import pytest

from cortex_agents_client.client import Thread
from cortex_agents_client.models.events import (
    ResponseEvent,
    TextAnnotationEvent,
    TextDeltaEvent,
    ToolResultEvent,
    ToolUseEvent,
)

# A query that should cause the agent to use the DocSearch tool.
# Matches documents in the fixed corpus seeded by 02_search_service.sql.
_SEARCH_QUERY = "What is the price of Widget Alpha?"


@pytest.mark.live
class TestToolUse:
    """Verify tool-use events are emitted when the search agent answers a query."""

    def test_tool_use_event_is_emitted(
        self,
        live_thread: Thread,
        agent_path_full: str,
    ) -> None:
        """At least one ToolUseEvent with type='cortex_search' is yielded."""
        events = list(live_thread.chat(agent_path_full, _SEARCH_QUERY))
        tool_use_events = [e for e in events if isinstance(e, ToolUseEvent)]
        assert len(tool_use_events) >= 1
        tool_types = {e.type for e in tool_use_events}
        assert "cortex_search" in tool_types

    def test_tool_result_event_follows_tool_use(
        self,
        live_thread: Thread,
        agent_path_full: str,
    ) -> None:
        """A ToolResultEvent is emitted for each ToolUseEvent."""
        events = list(live_thread.chat(agent_path_full, _SEARCH_QUERY))
        tool_use_ids = {e.tool_use_id for e in events if isinstance(e, ToolUseEvent)}
        tool_result_ids = {e.tool_use_id for e in events if isinstance(e, ToolResultEvent)}
        assert tool_use_ids  # at least one tool was used
        assert tool_use_ids == tool_result_ids  # every use has a result

    def test_tool_result_status_is_success(
        self,
        live_thread: Thread,
        agent_path_full: str,
    ) -> None:
        """All ToolResultEvents have status='success'."""
        events = list(live_thread.chat(agent_path_full, _SEARCH_QUERY))
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
        assert tool_results
        for result in tool_results:
            assert result.status == "success", f"ToolResultEvent status was {result.status!r}"


@pytest.mark.live
class TestCitationAnnotations:
    """Verify citation annotations are emitted when the search agent cites sources."""

    def test_text_annotation_events_are_emitted(
        self,
        live_thread: Thread,
        agent_path_full: str,
    ) -> None:
        """At least one TextAnnotationEvent is emitted for a query that triggers search."""
        events = list(live_thread.chat(agent_path_full, _SEARCH_QUERY))
        annotations = [e for e in events if isinstance(e, TextAnnotationEvent)]
        assert len(annotations) >= 1

    def test_annotation_has_doc_id_and_title(
        self,
        live_thread: Thread,
        agent_path_full: str,
    ) -> None:
        """Each TextAnnotationEvent has a non-empty doc_id and doc_title."""
        events = list(live_thread.chat(agent_path_full, _SEARCH_QUERY))
        annotations = [e for e in events if isinstance(e, TextAnnotationEvent)]
        if not annotations:
            pytest.skip("No annotation events received — agent may not have cited sources")
        for ann in annotations:
            assert ann.doc_id, "doc_id should be non-empty"
            assert ann.doc_title, "doc_title should be non-empty"


@pytest.mark.live
class TestFullAgentStreaming:
    """General streaming checks against the full agent."""

    def test_response_event_completed(
        self,
        live_thread: Thread,
        agent_path_full: str,
    ) -> None:
        """Final ResponseEvent has status='completed'."""
        events = list(live_thread.chat(agent_path_full, _SEARCH_QUERY))
        response_events = [e for e in events if isinstance(e, ResponseEvent)]
        assert response_events
        assert response_events[-1].status == "completed"

    def test_text_is_non_empty(
        self,
        live_thread: Thread,
        agent_path_full: str,
    ) -> None:
        """The agent produces a non-empty text response."""
        events = list(live_thread.chat(agent_path_full, _SEARCH_QUERY))
        text_deltas = [e for e in events if isinstance(e, TextDeltaEvent)]
        full_text = "".join(e.text for e in text_deltas)
        assert full_text.strip()
