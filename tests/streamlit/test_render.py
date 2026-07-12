"""Unit tests for render.py — SSE event rendering and StoredMessage assembly.

These tests verify that render_streaming_response() accumulates events
correctly and that render_stored_message() is consistent with it.
Streamlit calls are mocked to avoid requiring a running Streamlit context.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from unittest.mock import MagicMock, call, patch

import pytest

from cortex_agents_client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    MetadataEvent,
    TableEvent,
    TextAnnotationEvent,
    TextDeltaEvent,
    TextEvent,
    ThinkingEvent,
    ToolResultEvent,
    ToolUseEvent,
    WarningEvent,
)
from cortex_agents_client.models.thread import StoredMessage
from cortex_agents_client.st.render import render_stored_message, render_streaming_response
from tests.fixtures.sse_streams import (
    ANALYST_DELTA_PAYLOAD,
    CHART_PAYLOAD,
    TABLE_PAYLOAD,
    TEXT_ANNOTATION_PAYLOAD,
    TEXT_DELTA_PAYLOAD,
    TEXT_PAYLOAD,
    TOOL_RESULT_PAYLOAD,
    TOOL_USE_PAYLOAD,
    WARNING_PAYLOAD,
)


def make_container():
    """Creates a MagicMock that simulates a Streamlit container."""
    container = MagicMock()
    placeholder = MagicMock()
    container.empty.return_value = placeholder
    expander = MagicMock()
    expander.__enter__ = MagicMock(return_value=expander)
    expander.__exit__ = MagicMock(return_value=False)
    container.expander.return_value = expander
    status_ctx = MagicMock()
    status_ctx.__enter__ = MagicMock(return_value=status_ctx)
    status_ctx.__exit__ = MagicMock(return_value=False)
    container.status.return_value = status_ctx
    return container


def event_stream(*events) -> Iterator:
    """Yields events directly from a list."""
    yield from events


class TestRenderStreamingResponse:
    """Tests for render_streaming_response()."""

    def test_text_only_stream_sets_stored_text(self):
        """Text deltas + TextEvent → StoredMessage.text set correctly."""
        container = make_container()
        delta1 = TextDeltaEvent._from_payload({"content_index": 0, "text": "Hello "})
        delta2 = TextDeltaEvent._from_payload({"content_index": 0, "text": "world"})
        final = TextEvent._from_payload({"content_index": 0, "text": "Hello world"})

        stored = render_streaming_response(
            event_stream(delta1, delta2, final), container
        )
        assert stored.text == "Hello world"
        assert stored.role == "assistant"

    def test_table_event_stored_and_rendered(self):
        """TableEvent → stored in StoredMessage.tables and rendered via dataframe."""
        container = make_container()
        table = TableEvent._from_payload(TABLE_PAYLOAD)

        with patch("cortex_agents_client.st.render.result_set_to_dataframe") as mock_df:
            mock_df.return_value = MagicMock()
            stored = render_streaming_response(event_stream(table), container)

        assert len(stored.tables) == 1
        assert stored.tables[0].tool_use_id == "toolu_01"
        container.dataframe.assert_called_once()

    def test_chart_event_stored_and_rendered(self):
        """ChartEvent → stored in StoredMessage.charts and rendered via vega_lite_chart."""
        container = make_container()
        chart = ChartEvent._from_payload(CHART_PAYLOAD)

        stored = render_streaming_response(event_stream(chart), container)

        assert len(stored.charts) == 1
        container.vega_lite_chart.assert_called_once()

    def test_thinking_event_stored_regardless_of_show_flag(self):
        """ThinkingEvent is always stored, even if show_thinking=False."""
        container = make_container()
        thinking = ThinkingEvent._from_payload(
            {"content_index": 1, "text": "Let me think.", "signature": ""}
        )

        stored = render_streaming_response(
            event_stream(thinking), container, show_thinking=False
        )
        assert stored.thinking == "Let me think."

    def test_thinking_event_rendered_when_show_thinking_true(self):
        """ThinkingEvent renders expander when show_thinking=True."""
        container = make_container()
        thinking = ThinkingEvent._from_payload(
            {"content_index": 1, "text": "Reasoning...", "signature": ""}
        )

        render_streaming_response(
            event_stream(thinking), container, show_thinking=True
        )
        container.expander.assert_called_once()

    def test_warning_event_stored_and_rendered(self):
        """WarningEvent → stored in warnings and rendered via container.warning."""
        container = make_container()
        warning = WarningEvent._from_payload(WARNING_PAYLOAD)

        stored = render_streaming_response(event_stream(warning), container)

        assert len(stored.warnings) == 1
        container.warning.assert_called_once_with(
            WARNING_PAYLOAD["message"],
            icon=":material/warning:",
            title="Warning",
        )

    def test_error_event_stored_and_rendered(self):
        """ErrorEvent → stored as error and rendered via container.error."""
        container = make_container()
        error = ErrorEvent._from_payload(
            {"code": "123", "message": "Something broke", "request_id": "r1"}
        )

        stored = render_streaming_response(event_stream(error), container)

        assert stored.error is not None
        assert stored.error.code == "123"
        container.error.assert_called_once()

    def test_annotation_event_stored(self):
        """TextAnnotationEvent is stored in StoredMessage.annotations."""
        container = make_container()
        annotation = TextAnnotationEvent._from_payload(TEXT_ANNOTATION_PAYLOAD)

        stored = render_streaming_response(event_stream(annotation), container)

        assert len(stored.annotations) == 1
        assert stored.annotations[0].doc_title == "Annual Report 2025"

    def test_tool_execution_stored_as_pair(self):
        """ToolUseEvent + ToolResultEvent → stored as (use, result) pair."""
        container = make_container()
        use = ToolUseEvent._from_payload(TOOL_USE_PAYLOAD)
        result = ToolResultEvent._from_payload(TOOL_RESULT_PAYLOAD)

        stored = render_streaming_response(event_stream(use, result), container)

        assert len(stored.tool_executions) == 1
        stored_use, stored_result = stored.tool_executions[0]
        assert stored_use.tool_use_id == "toolu_01"
        assert stored_result is not None
        assert stored_result.status == "success"

    def test_tool_result_text_content_stored_and_rendered(self):
        """ToolResultEvent with type='text' content → stored and rendered."""
        container = make_container()
        use = ToolUseEvent._from_payload(TOOL_USE_PAYLOAD)
        result = ToolResultEvent._from_payload({
            **TOOL_RESULT_PAYLOAD,
            "content": [{"type": "text", "text": "Top result: Snowflake Q4 report"}],
        })

        stored = render_streaming_response(event_stream(use, result), container)

        assert stored.tool_result_text == {"toolu_01": "Top result: Snowflake Q4 report"}
        container.markdown.assert_any_call("Top result: Snowflake Q4 report")

    def test_tool_result_json_content_not_rendered_as_markdown(self):
        """ToolResultEvent with only type='json' content → no markdown call for it."""
        container = make_container()
        use = ToolUseEvent._from_payload(TOOL_USE_PAYLOAD)
        result = ToolResultEvent._from_payload(TOOL_RESULT_PAYLOAD)  # json type

        stored = render_streaming_response(event_stream(use, result), container)

        assert stored.tool_result_text == {}

    def test_permission_required_stops_stream_and_sets_pending(self):
        """ToolUseEvent with permission_options → stream stops, pending_permission set."""
        container = make_container()
        perm_use = ToolUseEvent._from_payload({
            **TOOL_USE_PAYLOAD,
            "permission": {"options": ["Allow Once", "Deny"]},
        })
        # This event should never be yielded — stream breaks on permission
        later_event = ToolResultEvent._from_payload(TOOL_RESULT_PAYLOAD)

        events_consumed = []
        def counting_stream():
            for ev in [perm_use, later_event]:
                events_consumed.append(ev)
                yield ev

        stored = render_streaming_response(counting_stream(), container)

        assert stored.pending_permission is not None
        assert stored.pending_permission.tool_use_id == "toolu_01"
        assert stored.pending_permission.permission_options == ["Allow Once", "Deny"]
        # later_event should NOT have been consumed (stream broke after perm_use)
        assert len(events_consumed) == 1
        container.warning.assert_called_once()

    def test_permission_required_no_spinner_created(self):
        """ToolUseEvent with permission_options → no st.status spinner created."""
        container = make_container()
        perm_use = ToolUseEvent._from_payload({
            **TOOL_USE_PAYLOAD,
            "permission": {"options": ["Allow Once", "Deny"]},
        })

        render_streaming_response(event_stream(perm_use), container, show_tool_status=True)
        container.status.assert_not_called()

    def test_tool_use_without_permission_still_creates_spinner(self):
        """ToolUseEvent without permission_options → spinner created as normal."""
        container = make_container()
        use = ToolUseEvent._from_payload(TOOL_USE_PAYLOAD)  # empty permission options

        render_streaming_response(event_stream(use), container, show_tool_status=True)
        container.status.assert_called_once()

    def test_analyst_delta_sql_captured(self):
        """AnalystDeltaEvent with sql → stored in analyst_sql dict."""
        container = make_container()
        delta = AnalystDeltaEvent._from_payload(ANALYST_DELTA_PAYLOAD)

        stored = render_streaming_response(event_stream(delta), container)

        assert "toolu_01" in stored.analyst_sql
        assert "SELECT" in stored.analyst_sql["toolu_01"]

    def test_metadata_event_captured_as_message_id(self):
        """MetadataEvent for assistant → stored.message_id set."""
        container = make_container()
        meta = MetadataEvent._from_payload(
            {"metadata": {"role": "assistant", "message_id": 456, "run_id": "r1"}}
        )

        stored = render_streaming_response(event_stream(meta), container)
        assert stored.message_id == 456

    def test_text_deltas_without_final_text_event(self):
        """Text deltas without a closing TextEvent still populate stored.text."""
        container = make_container()
        d1 = TextDeltaEvent._from_payload({"content_index": 0, "text": "Hi "})
        d2 = TextDeltaEvent._from_payload({"content_index": 0, "text": "there"})

        stored = render_streaming_response(event_stream(d1, d2), container)
        assert stored.text == "Hi there"


class TestRenderStoredMessage:
    """Tests for render_stored_message()."""

    def test_renders_text(self):
        """render_stored_message calls container.markdown with the stored text."""
        container = make_container()
        msg = StoredMessage(role="assistant", text="Hello!")

        render_stored_message(msg, container)
        container.markdown.assert_called_with("Hello!")

    def test_renders_table(self):
        """StoredMessage with table → dataframe called."""
        container = make_container()
        table = TableEvent._from_payload(TABLE_PAYLOAD)
        msg = StoredMessage(role="assistant", text="", tables=[table])

        with patch("cortex_agents_client.st.render.result_set_to_dataframe") as mock_df:
            mock_df.return_value = MagicMock()
            render_stored_message(msg, container)

        container.dataframe.assert_called_once()

    def test_renders_chart(self):
        """StoredMessage with chart → vega_lite_chart called."""
        container = make_container()
        chart = ChartEvent._from_payload(CHART_PAYLOAD)
        msg = StoredMessage(role="assistant", text="", charts=[chart])

        render_stored_message(msg, container)
        container.vega_lite_chart.assert_called_once()

    def test_renders_thinking_expander(self):
        """StoredMessage with thinking → expander created."""
        container = make_container()
        msg = StoredMessage(role="assistant", text="", thinking="Let me think.")

        render_stored_message(msg, container)
        container.expander.assert_called_once()

    def test_renders_warning(self):
        """StoredMessage with warning → container.warning called."""
        container = make_container()
        warning = WarningEvent._from_payload(WARNING_PAYLOAD)
        msg = StoredMessage(role="assistant", text="", warnings=[warning])

        render_stored_message(msg, container)
        container.warning.assert_called_once()

    def test_renders_error(self):
        """StoredMessage with error → container.error called."""
        container = make_container()
        error = ErrorEvent._from_payload(
            {"code": "123", "message": "Failed", "request_id": "r1"}
        )
        msg = StoredMessage(role="assistant", text="", error=error)

        render_stored_message(msg, container)
        container.error.assert_called_once()

    def test_empty_message_no_calls(self):
        """StoredMessage with no content makes no render calls."""
        container = make_container()
        msg = StoredMessage(role="user", text="")

        render_stored_message(msg, container)
        container.markdown.assert_not_called()
        container.dataframe.assert_not_called()

    def test_tool_result_text_replayed(self):
        """StoredMessage with tool_result_text → markdown called for text."""
        container = make_container()
        use = ToolUseEvent._from_payload(TOOL_USE_PAYLOAD)
        result = ToolResultEvent._from_payload(TOOL_RESULT_PAYLOAD)
        msg = StoredMessage(
            role="assistant",
            tool_executions=[(use, result)],
            tool_result_text={"toolu_01": "Top result: Snowflake Q4 report"},
        )

        render_stored_message(msg, container)
        container.markdown.assert_any_call("Top result: Snowflake Q4 report")

    def test_pending_permission_renders_info(self):
        """StoredMessage with pending_permission → container.info called."""
        container = make_container()
        perm_use = ToolUseEvent._from_payload({
            **TOOL_USE_PAYLOAD,
            "permission": {"options": ["Allow Once", "Deny"]},
        })
        msg = StoredMessage(role="assistant", pending_permission=perm_use)

        render_stored_message(msg, container)
        container.info.assert_called_once()
        call_kwargs = container.info.call_args
        assert "Analyst1" in str(call_kwargs)
