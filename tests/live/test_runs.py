"""Live tests: streaming, non-streaming, and multi-turn runs using the minimal agent.

These tests do not assert specific response text — LLM responses are
non-deterministic. They assert event types, event ordering, and structural
properties of the response.
"""
from __future__ import annotations

import pytest

from cortex_agents_client import CortexAgentsClient
from cortex_agents_client.client import Thread
from cortex_agents_client.models.events import (
    MetadataEvent,
    ResponseEvent,
    TextDeltaEvent,
    TextEvent,
)


@pytest.mark.live
class TestStreaming:
    """Streaming chat runs against the minimal agent."""

    def test_streaming_yields_text_delta_events(
        self,
        live_thread: Thread,
        agent_path_minimal: str,
    ) -> None:
        """A chat turn produces at least one TextDeltaEvent."""
        events = list(live_thread.chat(agent_path_minimal, "hello"))
        text_deltas = [e for e in events if isinstance(e, TextDeltaEvent)]
        assert len(text_deltas) >= 1

    def test_streaming_last_event_is_response_event_completed(
        self,
        live_thread: Thread,
        agent_path_minimal: str,
    ) -> None:
        """The final event is a ResponseEvent with status='completed'."""
        events = list(live_thread.chat(agent_path_minimal, "hello"))
        response_events = [e for e in events if isinstance(e, ResponseEvent)]
        assert len(response_events) == 1
        assert response_events[-1].status == "completed"

    def test_streaming_yields_text_event(
        self,
        live_thread: Thread,
        agent_path_minimal: str,
    ) -> None:
        """A TextEvent (assembled full text) is emitted after deltas."""
        events = list(live_thread.chat(agent_path_minimal, "hello"))
        text_events = [e for e in events if isinstance(e, TextEvent)]
        assert len(text_events) >= 1
        assert text_events[0].text  # non-empty

    def test_streaming_emits_metadata_events_for_user_and_assistant(
        self,
        live_thread: Thread,
        agent_path_minimal: str,
    ) -> None:
        """MetadataEvent is emitted for both the user and assistant messages."""
        events = list(live_thread.chat(agent_path_minimal, "hello"))
        meta_events = [e for e in events if isinstance(e, MetadataEvent)]
        roles = {e.role for e in meta_events}
        assert "user" in roles
        assert "assistant" in roles

    def test_streaming_response_contains_token_usage(
        self,
        live_thread: Thread,
        agent_path_minimal: str,
    ) -> None:
        """ResponseEvent includes non-zero token usage."""
        events = list(live_thread.chat(agent_path_minimal, "hello"))
        response_event = next(e for e in events if isinstance(e, ResponseEvent))
        assert len(response_event.usage) >= 1
        total_tokens = sum(u.input_tokens.total + u.output_tokens.total for u in response_event.usage)
        assert total_tokens > 0


@pytest.mark.live
class TestNonStreaming:
    """Non-streaming run via client.run()."""

    def test_run_returns_result_with_text(
        self,
        live_client: CortexAgentsClient,
        agent_path_minimal: str,
    ) -> None:
        """client.run() returns a RunResult with non-empty text."""
        result = live_client.run(agent_path_minimal, "hello")
        assert result.text
        assert result.status == "completed"

    def test_run_result_status_completed(
        self,
        live_client: CortexAgentsClient,
        agent_path_minimal: str,
    ) -> None:
        """RunResult.status is 'completed' for a successful run."""
        result = live_client.run(agent_path_minimal, "hello")
        assert result.status == "completed"


@pytest.mark.live
class TestMultiTurn:
    """Multi-turn conversation using the minimal agent."""

    def test_second_turn_succeeds(
        self,
        live_thread: Thread,
        agent_path_minimal: str,
    ) -> None:
        """A second chat() call on the same thread completes without error."""
        list(live_thread.chat(agent_path_minimal, "hello"))
        events2 = list(live_thread.chat(agent_path_minimal, "and again"))
        assert any(isinstance(e, TextDeltaEvent) for e in events2)

    def test_parent_message_id_advances(
        self,
        live_thread: Thread,
        agent_path_minimal: str,
    ) -> None:
        """parent_message_id is updated after each turn."""
        initial_parent = live_thread.parent_message_id
        list(live_thread.chat(agent_path_minimal, "first"))
        after_first = live_thread.parent_message_id
        assert after_first != initial_parent

        list(live_thread.chat(agent_path_minimal, "second"))
        after_second = live_thread.parent_message_id
        assert after_second != after_first
