"""Integration tests for RunsResource and Thread class using pytest-httpx."""
from __future__ import annotations

import json

import httpx
import pytest
from pytest_httpx import HTTPXMock

from cortex_agents_client.client import Thread
from cortex_agents_client.exceptions import AuthError, RunError, RunNotActiveError
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
    ERROR_PAYLOAD,
    METADATA_ASSISTANT_PAYLOAD,
    METADATA_USER_PAYLOAD,
    RESPONSE_PAYLOAD,
    TEXT_DELTA_PAYLOAD,
    TEXT_PAYLOAD,
    THINKING_DELTA_PAYLOAD,
    WARNING_PAYLOAD,
)


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
        from cortex_agents_client.exceptions import NotFoundError
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


class TestBackgroundRun:
    """Tests for asynchronous (background) agent runs."""

    def test_background_run_sends_flag_in_body(self, ca_client, httpx_mock: HTTPXMock):
        """background=True reaches the request body, not just the signature."""
        httpx_mock.add_response(json={"role": "assistant", "content": [], "status": "in_progress"})
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        ca_client.runs.run(
            messages, agent_path="DB.SC.AGENT", thread_id=1234, background=True
        )
        body = json.loads(httpx_mock.get_request().content)
        assert body["background"] is True
        assert body["stream"] is False
        assert body["thread_id"] == 1234

    def test_background_run_returns_in_progress_and_run_id(
        self, ca_client, httpx_mock: HTTPXMock
    ):
        """An in_progress response exposes the run_id needed to reconnect."""
        httpx_mock.add_response(
            json={
                "role": "assistant",
                "content": [],
                "status": "in_progress",
                "metadata": {
                    "run_id": "4264-83472",
                    "thread_id": 4264,
                    "user_message_id": 83472,
                },
            }
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        result = ca_client.runs.run(
            messages, agent_path="DB.SC.AGENT", thread_id=4264, background=True
        )
        assert result.status == "in_progress"
        assert result.run_id == "4264-83472"
        assert result.metadata is not None
        assert result.metadata.thread_id == 4264
        assert result.metadata.user_message_id == 83472

    def test_non_streaming_run_parses_usage_metadata(
        self, ca_client, httpx_mock: HTTPXMock
    ):
        """Token usage in the metadata block is parsed for a completed run."""
        httpx_mock.add_response(
            json={
                "role": "assistant",
                "content": [{"type": "text", "text": "42"}],
                "status": "completed",
                "metadata": {
                    "run_id": "1-2",
                    "assistant_message_id": 3,
                    "usage": {
                        "tokens_consumed": [
                            {
                                "model_name": "claude-4-sonnet",
                                "input_tokens": {"total": 175},
                                "output_tokens": {"total": 75},
                                "context_window": 128000,
                            }
                        ]
                    },
                },
            }
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        result = ca_client.runs.run(messages, agent_path="DB.SC.AGENT")
        assert result.metadata.assistant_message_id == 3
        assert len(result.metadata.usage) == 1
        assert result.metadata.usage[0].model_name == "claude-4-sonnet"
        assert result.metadata.usage[0].input_tokens.total == 175
        assert result.metadata.usage[0].context_window == 128000

    def test_run_without_metadata_leaves_run_id_none(
        self, ca_client, httpx_mock: HTTPXMock
    ):
        """A response with no metadata block does not fabricate a run_id."""
        httpx_mock.add_response(
            json={"role": "assistant", "content": [], "status": "completed"}
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        result = ca_client.runs.run(messages, agent_path="DB.SC.AGENT")
        assert result.metadata is None
        assert result.run_id is None


class TestStreamRun:
    """Tests for reconnecting to an existing run (Stream Agent Run)."""

    def test_stream_run_uses_get_on_run_path(self, ca_client, httpx_mock: HTTPXMock):
        """Reconnect issues GET against /api/v2/cortex/agent/runs/{run_id}."""
        httpx_mock.add_response(content=sse_response([("response.text", TEXT_PAYLOAD)]).content)
        list(ca_client.runs.stream_run("4264-83472"))
        request = httpx_mock.get_request()
        assert request.method == "GET"
        assert request.url.path == "/api/v2/cortex/agent/runs/4264-83472"
        assert request.headers["Accept"] == "text/event-stream"

    def test_stream_run_omits_starting_after_by_default(
        self, ca_client, httpx_mock: HTTPXMock
    ):
        """Without starting_after, the whole output is replayed."""
        httpx_mock.add_response(content=sse_response([("response.text", TEXT_PAYLOAD)]).content)
        list(ca_client.runs.stream_run("4264-83472"))
        assert "starting_after" not in httpx_mock.get_request().url.query.decode()

    def test_stream_run_sends_starting_after(self, ca_client, httpx_mock: HTTPXMock):
        """starting_after is passed as a query parameter."""
        httpx_mock.add_response(content=sse_response([("response.text", TEXT_PAYLOAD)]).content)
        list(ca_client.runs.stream_run("4264-83472", starting_after=12))
        assert httpx_mock.get_request().url.params["starting_after"] == "12"

    def test_stream_run_yields_typed_events(self, ca_client, httpx_mock: HTTPXMock):
        """Reconnected events are parsed with the same factory as agent:run."""
        httpx_mock.add_response(content=sse_response(ALL_EVENT_TYPES).content)
        events = list(ca_client.runs.stream_run("4264-83472"))
        assert len(events) == 17

    def test_stream_run_409_raises_run_not_active(self, ca_client, httpx_mock: HTTPXMock):
        """A run finished more than 5 minutes ago raises RunNotActiveError."""
        httpx_mock.add_response(status_code=409, json={"message": "run completed"})
        with pytest.raises(RunNotActiveError):
            list(ca_client.runs.stream_run("4264-83472"))

    def test_stream_run_via_client_facade(self, ca_client, httpx_mock: HTTPXMock):
        """The facade delegate hits the same endpoint."""
        httpx_mock.add_response(content=sse_response([("response.text", TEXT_PAYLOAD)]).content)
        events = list(ca_client.stream_run("4264-83472"))
        assert len(events) == 1
        assert httpx_mock.get_request().url.path == "/api/v2/cortex/agent/runs/4264-83472"


class TestCancelRun:
    """Tests for cancelling an active run."""

    def test_cancel_run_posts_to_cancel_path(self, ca_client, httpx_mock: HTTPXMock):
        """Cancel issues POST against the run's /cancel sub-path."""
        httpx_mock.add_response(json={"metadata": {"run_id": "4264-83472"}})
        ca_client.runs.cancel_run("4264-83472")
        request = httpx_mock.get_request()
        assert request.method == "POST"
        assert request.url.path == "/api/v2/cortex/agent/runs/4264-83472/cancel"

    def test_cancel_run_returns_metadata(self, ca_client, httpx_mock: HTTPXMock):
        """Partial output yields an assistant_message_id for the next turn."""
        httpx_mock.add_response(
            json={
                "metadata": {
                    "run_id": "4264-83472",
                    "thread_id": 4264,
                    "user_message_id": 83472,
                    "assistant_message_id": 83473,
                    "usage": {
                        "tokens_consumed": [
                            {"model_name": "claude-4-sonnet", "output_tokens": {"total": 75}}
                        ]
                    },
                }
            }
        )
        metadata = ca_client.runs.cancel_run("4264-83472")
        assert metadata.run_id == "4264-83472"
        assert metadata.assistant_message_id == 83473
        assert metadata.usage[0].output_tokens.total == 75

    def test_cancel_run_without_partial_output(self, ca_client, httpx_mock: HTTPXMock):
        """No saved partial output leaves assistant_message_id unset."""
        httpx_mock.add_response(json={"metadata": {"run_id": "4264-83472", "thread_id": 4264}})
        metadata = ca_client.runs.cancel_run("4264-83472")
        assert metadata.assistant_message_id is None

    def test_cancel_run_409_raises_run_not_active(self, ca_client, httpx_mock: HTTPXMock):
        """Cancelling an already-finished run raises RunNotActiveError."""
        httpx_mock.add_response(status_code=409, json={"message": "already completed"})
        with pytest.raises(RunNotActiveError):
            ca_client.runs.cancel_run("4264-83472")

    def test_cancel_run_via_client_facade(self, ca_client, httpx_mock: HTTPXMock):
        """The facade delegate returns the same metadata."""
        httpx_mock.add_response(json={"metadata": {"run_id": "4264-83472"}})
        assert ca_client.cancel_run("4264-83472").run_id == "4264-83472"


class TestLiteRunConfig:
    """Tests the inline (lite) config fields reach the request body."""

    def test_models_object_sent_not_bare_model(self, ca_client, httpx_mock: HTTPXMock):
        """The wire format is a models object, per the current API schema."""
        httpx_mock.add_response(json={"role": "assistant", "content": [], "status": "completed"})
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        ca_client.runs.run(messages, models={"orchestration": "claude-4-sonnet"})
        body = json.loads(httpx_mock.get_request().content)
        assert body["models"] == {"orchestration": "claude-4-sonnet"}
        assert "model" not in body

    def test_lite_run_uses_cortex_agent_run_path(self, ca_client, httpx_mock: HTTPXMock):
        """With no agent_path, the lite endpoint is used."""
        httpx_mock.add_response(json={"role": "assistant", "content": [], "status": "completed"})
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        ca_client.runs.run(messages, models={"orchestration": "claude-4-sonnet"})
        assert httpx_mock.get_request().url.path == "/api/v2/cortex/agent:run"

    def test_orchestration_budget_sent(self, ca_client, httpx_mock: HTTPXMock):
        """The orchestration budget reaches the request body."""
        httpx_mock.add_response(json={"role": "assistant", "content": [], "status": "completed"})
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        ca_client.runs.run(
            messages, orchestration={"budget": {"seconds": 30, "tokens": 16000}}
        )
        body = json.loads(httpx_mock.get_request().content)
        assert body["orchestration"] == {"budget": {"seconds": 30, "tokens": 16000}}


class TestThreadBackgroundChat:
    """Tests that Thread.chat forwards the background flag."""

    def test_chat_background_reaches_body(self, ca_client, httpx_mock: HTTPXMock):
        """Thread.chat(background=True) sets background on the run request."""
        httpx_mock.add_response(
            content=sse_response([("metadata", METADATA_ASSISTANT_PAYLOAD)]).content
        )
        thread = Thread(ca_client, thread_id=4264)
        list(thread.chat("DB.SC.AGENT", "Hi", background=True))
        body = json.loads(httpx_mock.get_request().content)
        assert body["background"] is True
        assert body["thread_id"] == 4264

    def test_chat_default_omits_background(self, ca_client, httpx_mock: HTTPXMock):
        """The default synchronous path sends no background field."""
        httpx_mock.add_response(
            content=sse_response([("metadata", METADATA_ASSISTANT_PAYLOAD)]).content
        )
        thread = Thread(ca_client, thread_id=4264)
        list(thread.chat("DB.SC.AGENT", "Hi"))
        assert "background" not in json.loads(httpx_mock.get_request().content)

