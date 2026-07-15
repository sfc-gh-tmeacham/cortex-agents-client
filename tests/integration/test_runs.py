"""Integration tests for RunsResource and Thread class using pytest-httpx."""
from __future__ import annotations

import json

import httpx
import pytest
from pytest_httpx import HTTPXMock

from cortex_agents_client.exceptions import AuthError, RunError
from cortex_agents_client.models.events import (
    ErrorEvent,
    MetadataEvent,
    TextDeltaEvent,
    TextEvent,
    UnknownEvent,
    WarningEvent,
)
from tests.fixtures.api_responses import NON_STREAMING_RUN_RESPONSE
from tests.fixtures.sse_streams import (
    ALL_EVENT_TYPES,
    ANALYST_DELTA_PAYLOAD,
    CHART_PAYLOAD,
    ERROR_PAYLOAD,
    METADATA_ASSISTANT_PAYLOAD,
    METADATA_USER_PAYLOAD,
    RESPONSE_PAYLOAD,
    TABLE_PAYLOAD,
    TEXT_DELTA_PAYLOAD,
    TEXT_PAYLOAD,
    THINKING_DELTA_PAYLOAD,
    TOOL_RESULT_PAYLOAD,
    TOOL_USE_PAYLOAD,
    WARNING_PAYLOAD,
)
from tests.integration.conftest import ACCOUNT_URL


def sse_response(events: list[tuple[str, dict]]) -> httpx.Response:
    """Builds an httpx Response with SSE content.

    Each event is followed by a double newline as required by the SSE spec.
    """
    body = "".join(
        f"event: {et}\ndata: {json.dumps(p)}\n\n"
        for et, p in events
    )
    return httpx.Response(
        status_code=200,
        headers={"Content-Type": "text/event-stream"},
        text=body,
    )


class TestStreamAllEventTypes:
    """Tests that all 17 SSE event types are yielded correctly."""

    def test_stream_yields_all_17_event_types(self, ca_client, httpx_mock: HTTPXMock):
        """stream() yields one event of each of the 16 types."""
        httpx_mock.add_response(content=sse_response(ALL_EVENT_TYPES).content)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]
        events = list(ca_client.runs.stream(messages, agent_path="DB.SC.AGENT"))
        assert len(events) == 17

    def test_stream_text_delta_type(self, ca_client, httpx_mock: HTTPXMock):
        """TextDeltaEvent is yielded for response.text.delta."""
        httpx_mock.add_response(content=sse_response([("response.text.delta", TEXT_DELTA_PAYLOAD)]).content)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        events = list(ca_client.runs.stream(messages, agent_path="DB.SC.AGENT"))
        assert len(events) == 1
        assert isinstance(events[0], TextDeltaEvent)
        assert events[0].text == "Hello "      # primary field
        assert events[0].delta == "Hello "     # backward-compat alias


class TestStreamMetadataTracking:
    """Tests that MetadataEvent updates parent_message_id correctly."""

    def test_metadata_events_both_yielded(self, ca_client, httpx_mock: HTTPXMock):
        """Both user and assistant metadata events are yielded."""
        events_data = [
            ("metadata", METADATA_USER_PAYLOAD),
            ("metadata", METADATA_ASSISTANT_PAYLOAD),
        ]
        httpx_mock.add_response(content=sse_response(events_data).content)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        events = list(ca_client.runs.stream(messages, agent_path="DB.SC.AGENT"))
        metadata_events = [e for e in events if isinstance(e, MetadataEvent)]
        assert len(metadata_events) == 2
        assert metadata_events[0].role == "user"
        assert metadata_events[0].message_id == 123
        assert metadata_events[1].role == "assistant"
        assert metadata_events[1].message_id == 456


class TestWarningEvent:
    """Tests that WarningEvent does not stop the stream."""

    def test_warning_followed_by_text_both_yielded(self, ca_client, httpx_mock: HTTPXMock):
        """Warning event followed by text event — both are yielded."""
        events_data = [
            ("response.warning", WARNING_PAYLOAD),
            ("response.text", TEXT_PAYLOAD),
        ]
        httpx_mock.add_response(content=sse_response(events_data).content)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        events = list(ca_client.runs.stream(messages, agent_path="DB.SC.AGENT"))
        assert len(events) == 2
        assert isinstance(events[0], WarningEvent)
        assert isinstance(events[1], TextEvent)


class TestErrorEvent:
    """Tests for fatal error event handling."""

    def test_stream_and_collect_raises_run_error(self, ca_client, httpx_mock: HTTPXMock):
        """stream_and_collect() raises RunError on error event."""
        httpx_mock.add_response(content=sse_response([("error", ERROR_PAYLOAD)]).content)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        with pytest.raises(RunError) as exc_info:
            ca_client.runs.stream_and_collect(messages, agent_path="DB.SC.AGENT")
        assert exc_info.value.code == "399504"

    def test_stream_yields_error_event_before_raising(self, ca_client, httpx_mock: HTTPXMock):
        """stream() yields ErrorEvent (consumer can inspect it)."""
        httpx_mock.add_response(content=sse_response([("error", ERROR_PAYLOAD)]).content)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        events = list(ca_client.runs.stream(messages, agent_path="DB.SC.AGENT"))
        assert len(events) == 1
        assert isinstance(events[0], ErrorEvent)


class TestUnknownEventType:
    """Tests that unknown event types are forwarded as UnknownEvent."""

    def test_unknown_type_yields_unknown_event(self, ca_client, httpx_mock: HTTPXMock):
        """Unrecognised event type → UnknownEvent yielded, no exception."""
        events_data = [("response.new_future_event", {"data": "something"})]
        httpx_mock.add_response(content=sse_response(events_data).content)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        events = list(ca_client.runs.stream(messages, agent_path="DB.SC.AGENT"))
        assert len(events) == 1
        assert isinstance(events[0], UnknownEvent)


class TestNonStreamingRun:
    """Tests for run() with stream=False."""

    def test_run_returns_run_result(self, ca_client, httpx_mock: HTTPXMock):
        """run() with stream=False returns assembled RunResult."""
        httpx_mock.add_response(json=NON_STREAMING_RUN_RESPONSE)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        result = ca_client.runs.run(messages, agent_path="DB.SC.AGENT")
        assert result.text == "The revenue was $4.2B."
        assert len(result.tables) == 1
        assert result.thinking is None  # no thinking content in response
        assert result.status == "completed"  # non-streaming response status

    def test_run_non_streaming_error_raises(self, ca_client, httpx_mock: HTTPXMock):
        """Non-streaming response with error → RunError raised."""
        error_response = {
            "role": "assistant",
            "content": [],
            "status": "error",
            "error": {"code": "399504", "message": "Failed", "request_id": "r1"},
        }
        httpx_mock.add_response(json=error_response)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        with pytest.raises(RunError):
            ca_client.runs.run(messages, agent_path="DB.SC.AGENT")


class TestRunURLs:
    """Tests that the correct API URLs are used."""

    def test_agent_object_run_uses_agent_url(self, ca_client, httpx_mock: HTTPXMock):
        """Agent-object run hits /databases/{db}/schemas/{sc}/agents/{name}:run."""
        captured_url: list[str] = []

        def responder(request):
            captured_url.append(str(request.url))
            return sse_response([("response.text", TEXT_PAYLOAD)])

        httpx_mock.add_callback(responder)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        list(ca_client.runs.stream(messages, agent_path="MY_DB.MY_SC.MY_AGENT"))
        assert "/databases/MY_DB/schemas/MY_SC/agents/MY_AGENT:run" in captured_url[0]

    def test_lite_run_uses_cortex_agent_run_url(self, ca_client, httpx_mock: HTTPXMock):
        """Lite run (no agent) hits /api/v2/cortex/agent:run."""
        captured_url: list[str] = []

        def responder(request):
            captured_url.append(str(request.url))
            return sse_response([("response.text", TEXT_PAYLOAD)])

        httpx_mock.add_callback(responder)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        list(ca_client.runs.stream(messages, tools=[]))
        assert "/cortex/agent:run" in captured_url[0]


class TestHttpErrors:
    """Tests for HTTP error code → exception mapping."""

    def test_http_401_raises_auth_error(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 401 raises AuthError."""
        httpx_mock.add_response(
            status_code=401,
            headers={"Content-Type": "application/json"},
            json={"message": "Unauthorized"},
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        with pytest.raises(AuthError):
            list(ca_client.runs.stream(messages, agent_path="DB.SC.A"))

    def test_http_403_raises_permission_error(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 403 raises CortexPermissionError."""
        from cortex_agents_client.exceptions import CortexPermissionError
        httpx_mock.add_response(
            status_code=403,
            headers={"Content-Type": "application/json"},
            json={"message": "Forbidden"},
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        with pytest.raises(CortexPermissionError):
            list(ca_client.runs.stream(messages, agent_path="DB.SC.A"))

    def test_http_429_raises_rate_limit_error(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 429 raises RateLimitError."""
        from cortex_agents_client.exceptions import RateLimitError
        httpx_mock.add_response(
            status_code=429,
            headers={"Content-Type": "application/json"},
            json={"message": "Rate limit exceeded. Retry after 60 seconds."},
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        with pytest.raises(RateLimitError):
            list(ca_client.runs.stream(messages, agent_path="DB.SC.A"))

    def test_http_500_raises_server_error(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 500 raises ServerError."""
        from cortex_agents_client.exceptions import ServerError
        httpx_mock.add_response(
            status_code=500,
            headers={"Content-Type": "application/json"},
            json={"message": "Internal server error"},
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        with pytest.raises(ServerError):
            list(ca_client.runs.stream(messages, agent_path="DB.SC.A"))


class TestThreadClass:
    """Integration tests for the Thread convenience class."""

    def test_first_turn_uses_parent_message_id_zero(self, ca_client, httpx_mock: HTTPXMock):
        """Thread starts with parent_message_id=0."""
        captured: dict = {}

        def responder(request):
            captured["body"] = json.loads(request.content)
            return sse_response([
                ("metadata", METADATA_USER_PAYLOAD),
                ("metadata", METADATA_ASSISTANT_PAYLOAD),
            ])

        httpx_mock.add_response(method="POST", json={"thread_id": 999, "thread_name": "", "origin_application": "", "created_on": 0, "updated_on": 0})
        httpx_mock.add_callback(responder)

        thread = ca_client.create_thread()
        list(thread.chat("DB.SC.MY_AGENT", "Hello"))

        assert captured["body"]["parent_message_id"] == 0
        assert captured["body"]["thread_id"] == 999

    def test_second_turn_uses_assistant_message_id(self, ca_client, httpx_mock: HTTPXMock):
        """After first turn, parent_message_id is the assistant message_id."""
        request_bodies: list[dict] = []

        def responder(request):
            request_bodies.append(json.loads(request.content))
            return sse_response([
                ("metadata", METADATA_USER_PAYLOAD),
                ("metadata", METADATA_ASSISTANT_PAYLOAD),
            ])

        thread_resp = httpx.Response(
            200, json={"thread_id": 777, "thread_name": "", "origin_application": "", "created_on": 0, "updated_on": 0}
        )
        httpx_mock.add_response(json=thread_resp.json())
        httpx_mock.add_callback(responder)
        httpx_mock.add_callback(responder)

        thread = ca_client.create_thread()
        list(thread.chat("DB.SC.AGENT", "First question"))
        list(thread.chat("DB.SC.AGENT", "Follow-up question"))

        assert request_bodies[0]["parent_message_id"] == 0
        assert request_bodies[1]["parent_message_id"] == 456  # assistant message_id

    def test_fork_creates_new_thread_at_message_id(self, ca_client, httpx_mock: HTTPXMock):
        """fork() creates a Thread with the correct parent_message_id."""
        httpx_mock.add_response(json={"thread_id": 555, "thread_name": "", "origin_application": "", "created_on": 0, "updated_on": 0})

        thread = ca_client.create_thread()
        fork = thread.fork(at_message_id=42)

        assert fork.thread_id == thread.thread_id
        assert fork.parent_message_id == 42
        assert thread.parent_message_id == 0  # unchanged

    def test_missing_assistant_metadata_preserves_id(self, ca_client, httpx_mock: HTTPXMock):
        """If assistant metadata is missing, parent_message_id stays unchanged."""
        httpx_mock.add_response(json={"thread_id": 888, "thread_name": "", "origin_application": "", "created_on": 0, "updated_on": 0})
        # Only user metadata, no assistant metadata
        httpx_mock.add_response(content=sse_response([("metadata", METADATA_USER_PAYLOAD)]).content)

        thread = ca_client.create_thread()
        assert thread.parent_message_id == 0
        list(thread.chat("DB.SC.AGENT", "Hello"))
        assert thread.parent_message_id == 0  # unchanged


class TestNotFoundErrorHierarchy:
    """Tests that NotFoundError is a catch-all for agent/thread not-found variants."""

    def test_agent_not_found_catchable_as_not_found_error(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 404 on an agent endpoint raises AgentNotFoundError, catchable as NotFoundError."""
        from cortex_agents_client.exceptions import NotFoundError
        httpx_mock.add_response(
            status_code=404,
            json={"message": "Agent not found", "request_id": "r1"},
        )
        with pytest.raises(NotFoundError):
            ca_client.agents.get("MISSING_AGENT")

    def test_thread_not_found_catchable_as_not_found_error(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 404 on a thread endpoint raises ThreadNotFoundError, catchable as NotFoundError."""
        from cortex_agents_client.exceptions import NotFoundError, ThreadNotFoundError
        httpx_mock.add_response(
            status_code=404,
            json={"message": "Thread not found", "request_id": "r1"},
        )
        with pytest.raises(NotFoundError):
            ca_client.threads.get(9999999999)


class TestCortexTimeoutError:
    """Tests that httpx timeouts map to CortexTimeoutError."""

    def test_request_timeout_raises_cortex_timeout_error(self, ca_client, httpx_mock: HTTPXMock):
        """httpx.TimeoutException propagates as CortexTimeoutError."""
        from cortex_agents_client.exceptions import CortexTimeoutError
        httpx_mock.add_exception(httpx.TimeoutException("connection timed out"))
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        with pytest.raises(CortexTimeoutError):
            list(ca_client.runs.stream(messages, agent_path="DB.SC.AGENT"))


class TestStreamAndCollectFallback:
    """Tests that stream_and_collect accumulates delta events when no summary event arrives."""

    def test_text_delta_fallback_when_no_text_event(self, ca_client, httpx_mock: HTTPXMock):
        """stream_and_collect uses accumulated TextDeltaEvents if no TextEvent arrives."""
        # Only send a delta — no final TextEvent
        httpx_mock.add_response(
            content=sse_response([("response.text.delta", TEXT_DELTA_PAYLOAD)]).content
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        result = ca_client.runs.stream_and_collect(messages, agent_path="DB.SC.AGENT")
        assert result.text == TEXT_DELTA_PAYLOAD["text"]

    def test_thinking_delta_fallback_when_no_thinking_event(self, ca_client, httpx_mock: HTTPXMock):
        """stream_and_collect uses accumulated ThinkingDeltaEvents if no ThinkingEvent arrives."""
        httpx_mock.add_response(
            content=sse_response([("response.thinking.delta", THINKING_DELTA_PAYLOAD)]).content
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        result = ca_client.runs.stream_and_collect(messages, agent_path="DB.SC.AGENT")
        assert result.thinking == THINKING_DELTA_PAYLOAD["text"]

    def test_summary_event_takes_precedence_over_deltas(self, ca_client, httpx_mock: HTTPXMock):
        """When both delta and summary TextEvent arrive, result.text uses the summary value."""
        httpx_mock.add_response(
            content=sse_response([
                ("response.text.delta", TEXT_DELTA_PAYLOAD),
                ("response.text", TEXT_PAYLOAD),
            ]).content
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        result = ca_client.runs.stream_and_collect(messages, agent_path="DB.SC.AGENT")
        assert result.text == TEXT_PAYLOAD["text"]


class TestStreamAndCollectResponseEvent:
    """Tests that stream_and_collect captures ResponseEvent status."""

    def test_response_event_populates_status(self, ca_client, httpx_mock: HTTPXMock):
        """stream_and_collect sets RunResult.status from ResponseEvent."""
        httpx_mock.add_response(
            content=sse_response([
                ("response.text.delta", TEXT_DELTA_PAYLOAD),
                ("response", RESPONSE_PAYLOAD),
            ]).content
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        result = ca_client.runs.stream_and_collect(messages, agent_path="DB.SC.AGENT")
        assert result.status == "completed"


class TestNonStreamingThinking:
    """Tests for _parse_non_streaming_response thinking content branch."""

    def test_run_with_thinking_content_in_response(self, ca_client, httpx_mock: HTTPXMock):
        """Non-streaming response with a thinking content item populates result.thinking."""
        response = {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": {"text": "Let me reason through this."}},
                {"type": "text", "text": "The answer is 42."},
            ],
            "status": "completed",
            "error": None,
        }
        httpx_mock.add_response(json=response)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        result = ca_client.runs.run(messages, agent_path="DB.SC.AGENT")
        assert result.thinking == "Let me reason through this."
        assert result.text == "The answer is 42."


class TestNonStreamingToolParsing:
    """Tests that _parse_non_streaming_response handles tool_use and tool_result items."""

    def test_run_parses_tool_use_and_tool_result(self, ca_client, httpx_mock: HTTPXMock):
        """Non-streaming response with tool_use and tool_result items populates RunResult."""
        response = {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "tool_use": {
                        "tool_use_id": "toolu_01",
                        "type": "cortex_analyst_text_to_sql",
                        "name": "Analyst1",
                        "input": {"query": "total revenue"},
                        "client_side_execute": False,
                        "permission": {"options": []},
                    },
                },
                {
                    "type": "tool_result",
                    "tool_result": {
                        "tool_use_id": "toolu_01",
                        "type": "cortex_analyst_text_to_sql",
                        "name": "Analyst1",
                        "content": [{"type": "json", "json": {"answer": 42}}],
                        "status": "success",
                    },
                },
                {"type": "text", "text": "The answer is 42."},
            ],
            "status": "completed",
            "error": None,
        }
        httpx_mock.add_response(json=response)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        result = ca_client.runs.run(messages, agent_path="DB.SC.AGENT")
        assert len(result.tool_uses) == 1
        assert result.tool_uses[0].tool_use_id == "toolu_01"
        assert len(result.tool_results) == 1
        assert result.tool_results[0].status == "success"
        assert result.text == "The answer is 42."
        assert result.status == "completed"

    def test_run_parses_top_level_warnings(self, ca_client, httpx_mock: HTTPXMock):
        """Non-streaming response top-level warnings array is parsed into result.warnings."""
        response = {
            "role": "assistant",
            "content": [{"type": "text", "text": "Here is the answer."}],
            "warnings": [{"message": "MCP server unavailable", "code": "003001"}],
            "status": "completed",
            "error": None,
        }
        httpx_mock.add_response(json=response)
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        result = ca_client.runs.run(messages, agent_path="DB.SC.AGENT")
        assert len(result.warnings) == 1
        assert result.warnings[0].message == "MCP server unavailable"
        assert result.warnings[0].code == "003001"
