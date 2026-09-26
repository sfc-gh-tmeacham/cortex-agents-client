"""Unit tests for render.py — SSE event rendering and StoredMessage assembly.

These tests verify that render_streaming_response() accumulates events
correctly and that render_stored_message() is consistent with it.
Streamlit calls are mocked to avoid requiring a running Streamlit context.
"""
from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch


from streamlit_cortex_agents.client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    MetadataEvent,
    TableEvent,
    TextAnnotationEvent,
    TextDeltaEvent,
    TextEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
    ToolResultEvent,
    ToolUseEvent,
    WarningEvent,
)
from streamlit_cortex_agents.client.models.thread import StoredMessage
from streamlit_cortex_agents.chat.render import render_stored_message, render_streaming_response, escape_dollars
from tests.fixtures.sse_streams import (
    ANALYST_DELTA_PAYLOAD,
    CHART_PAYLOAD,
    TABLE_PAYLOAD,
    TEXT_ANNOTATION_PAYLOAD,
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
    # Steps are nested statuses inside the outer timeline status.
    step_ctx = MagicMock()
    status_ctx.status.return_value = step_ctx
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

        with patch("streamlit_cortex_agents.chat.render.result_set_to_dataframe") as mock_df:
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
        """ThinkingEvent renders a thinking step in the Reasoning timeline when show_thinking=True."""
        container = make_container()
        thinking = ThinkingEvent._from_payload(
            {"content_index": 1, "text": "Reasoning...", "signature": ""}
        )

        render_streaming_response(
            event_stream(thinking), container, show_thinking=True
        )
        container.status.assert_called_once()
        assert container.status.call_args.args[0] == "Reasoning"
        container.status.return_value.status.assert_called_once()
        container.expander.assert_not_called()

    def test_streaming_default_show_thinking_false_suppresses_expander(self):
        """render_streaming_response default show_thinking=False renders no timeline."""
        container = make_container()
        thinking = ThinkingEvent._from_payload(
            {"content_index": 1, "text": "Hidden...", "signature": ""}
        )
        render_streaming_response(event_stream(thinking), container)  # default show_thinking=False
        container.expander.assert_not_called()
        container.status.assert_not_called()

    def test_warning_event_stored_and_rendered(self):
        """WarningEvent → stored in warnings and rendered via container.warning."""
        container = make_container()
        warning = WarningEvent._from_payload(WARNING_PAYLOAD)

        stored = render_streaming_response(event_stream(warning), container)

        assert len(stored.warnings) == 1
        container.warning.assert_called_once_with(
            escape_dollars(WARNING_PAYLOAD["message"]),
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

    def test_annotations_render_sources_expander(self):
        """Annotations present → Sources expander created after streaming."""
        container = make_container()
        annotation = TextAnnotationEvent._from_payload(TEXT_ANNOTATION_PAYLOAD)

        render_streaming_response(event_stream(annotation), container)

        container.expander.assert_called_once()
        label = container.expander.call_args[0][0]
        assert "Sources" in label

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

    def test_verified_query_used_sets_flag(self):
        """AnalystDeltaEvent with verified_query_used=True → tool_use_id in verified_tool_uses."""
        container = make_container()
        delta = AnalystDeltaEvent._from_payload({
            **ANALYST_DELTA_PAYLOAD,
            "delta": {**ANALYST_DELTA_PAYLOAD["delta"], "verified_query_used": True},
        })

        stored = render_streaming_response(event_stream(delta), container)

        assert delta.tool_use_id in stored.verified_tool_uses

    def test_verified_query_status_label_uses_verified_icon(self):
        """When verified_query_used=True, completed status shows :material/verified: icon."""
        container = make_container()
        use = ToolUseEvent(
            event_type="response.tool_use",
            tool_use_id="tid",
            type="cortex_analyst_text_to_sql",
            name="MY_ANALYST",
            input={},
        )
        delta = AnalystDeltaEvent._from_payload({
            "content_index": 0,
            "tool_use_id": "tid",
            "tool_type": "cortex_analyst_text_to_sql",
            "tool_name": "MY_ANALYST",
            "delta": {"sql": "SELECT 1", "verified_query_used": True},
        })
        result = ToolResultEvent(
            event_type="response.tool_result",
            tool_use_id="tid",
            type="cortex_analyst_text_to_sql",
            name="MY_ANALYST",
            status="success",
            content=[],
        )

        render_streaming_response(event_stream(use, delta, result), container)

        step_ctx = container.status.return_value.status.return_value
        final_call = step_ctx.update.call_args_list[-1]
        label = final_call.kwargs.get("label") or final_call.args[0]
        assert ":material/verified:" in label
        assert ":material/check_circle:" not in label

    def test_non_verified_query_status_label_uses_check_circle_icon(self):
        """When verified_query_used=False, completed status shows :material/check_circle: icon."""
        container = make_container()
        use = ToolUseEvent(
            event_type="response.tool_use",
            tool_use_id="tid2",
            type="cortex_analyst_text_to_sql",
            name="MY_ANALYST",
            input={},
        )
        result = ToolResultEvent(
            event_type="response.tool_result",
            tool_use_id="tid2",
            type="cortex_analyst_text_to_sql",
            name="MY_ANALYST",
            status="success",
            content=[],
        )

        render_streaming_response(event_stream(use, result), container)

        step_ctx = container.status.return_value.status.return_value
        final_call = step_ctx.update.call_args_list[-1]
        label = final_call.kwargs.get("label") or final_call.args[0]
        assert ":material/check_circle:" in label
        assert ":material/verified:" not in label


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

        with patch("streamlit_cortex_agents.chat.render.result_set_to_dataframe") as mock_df:
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
        """StoredMessage with thinking → collapsed Reasoning timeline when show_thinking=True."""
        container = make_container()
        msg = StoredMessage(role="assistant", text="", thinking="Let me think.")

        render_stored_message(msg, container, show_thinking=True)
        container.status.assert_called_once()
        assert container.status.call_args.kwargs["expanded"] is False
        step = container.status.return_value.status.return_value
        step.markdown.assert_called_once_with("Let me think.")
        container.expander.assert_not_called()

    def test_does_not_render_thinking_when_show_thinking_false(self):
        """StoredMessage with thinking → no timeline when show_thinking=False (default)."""
        container = make_container()
        msg = StoredMessage(role="assistant", text="", thinking="Hidden reasoning.")

        render_stored_message(msg, container, show_thinking=False)
        container.expander.assert_not_called()
        container.status.assert_not_called()

    def test_default_show_thinking_is_false(self):
        """render_stored_message default show_thinking=False matches render_streaming_response default."""
        container = make_container()
        msg = StoredMessage(role="assistant", text="", thinking="Hidden reasoning.")

        render_stored_message(msg, container)  # no show_thinking arg
        container.expander.assert_not_called()

    def test_elicitation_renders_info_not_markdown(self):
        """render_stored_message with is_elicitation=True uses container.info, not markdown."""
        container = make_container()
        msg = StoredMessage(role="assistant", text="Could you clarify?", is_elicitation=True)

        render_stored_message(msg, container)
        container.info.assert_called_once()
        container.markdown.assert_not_called()

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

    def test_pending_permission_renders_warning(self):
        """StoredMessage with pending_permission → container.warning called."""
        container = make_container()
        perm_use = ToolUseEvent._from_payload({
            **TOOL_USE_PAYLOAD,
            "permission": {"options": ["Allow Once", "Deny"]},
        })
        msg = StoredMessage(role="assistant", pending_permission=perm_use)

        render_stored_message(msg, container)
        container.warning.assert_called()
        call_kwargs = container.warning.call_args
        assert "Analyst1" in str(call_kwargs)

    def test_annotations_render_sources_expander_in_stored_message(self):
        """render_stored_message with annotations → Sources expander created."""
        container = make_container()
        annotation = TextAnnotationEvent._from_payload(TEXT_ANNOTATION_PAYLOAD)
        msg = StoredMessage(role="assistant", text="See [^1].", annotations=[annotation])

        render_stored_message(msg, container)

        container.expander.assert_called_once()
        label = container.expander.call_args[0][0]
        assert "Sources" in label

    def test_url_doc_id_rendered_with_unsafe_html(self):
        """Annotation with http doc_id → unsafe_allow_html=True on the expander."""
        from streamlit_cortex_agents.chat.render import _render_annotations_expander

        ann = TextAnnotationEvent._from_payload({
            "content_index": 0,
            "annotation_index": 0,
            "annotation": {
                "type": "cortex_search_citation",
                "index": 1,
                "search_result_id": "sr1",
                "doc_id": "https://example.com/report",
                "doc_title": "Q4 Report",
                "text": "Revenue grew 12%.",
            },
        })
        container = make_container()
        exp = container.expander.return_value
        _render_annotations_expander([ann], container)

        # Markdown with unsafe_allow_html is called on the expander, not container
        html_calls = [
            c for c in exp.markdown.call_args_list
            if c.kwargs.get("unsafe_allow_html")
        ]
        assert len(html_calls) == 1
        html_content = html_calls[0].args[0]
        assert "https://example.com/report" in html_content
        assert 'target="_blank"' in html_content

    def test_non_url_doc_id_no_html(self):
        """Annotation with non-URL doc_id → plain markdown on expander, no unsafe_allow_html."""
        from streamlit_cortex_agents.chat.render import _render_annotations_expander

        ann = TextAnnotationEvent._from_payload({
            "content_index": 0,
            "annotation_index": 0,
            "annotation": {
                "type": "cortex_search_citation",
                "index": 1,
                "search_result_id": "sr1",
                "doc_id": "internal_doc_456",
                "doc_title": "Internal Policy Doc",
                "text": "Excerpt.",
            },
        })
        container = make_container()
        exp = container.expander.return_value
        _render_annotations_expander([ann], container)

        html_calls = [
            c for c in exp.markdown.call_args_list
            if c.kwargs.get("unsafe_allow_html")
        ]
        assert len(html_calls) == 0


class TestAuditRegressions:
    """Regression tests for defects found in the repo health audit."""

    def test_system_execute_sql_verified_query_used_sets_flag(self):
        """ToolUseEvent (Apr 2026+ API) with verified_query_used → flag recorded."""
        container = make_container()
        use = ToolUseEvent._from_payload({
            "content_index": 0,
            "tool_use_id": "toolu_sql",
            "type": "system_execute_sql",
            "name": "execute_sql",
            "input": {"sql": "SELECT 1", "verified_query_used": True},
        })

        stored = render_streaming_response(event_stream(use), container)

        assert "toolu_sql" in stored.verified_tool_uses

    def test_system_execute_sql_without_verified_flag_not_recorded(self):
        """ToolUseEvent without verified_query_used → flag not recorded."""
        container = make_container()
        use = ToolUseEvent._from_payload({
            "content_index": 0,
            "tool_use_id": "toolu_sql",
            "type": "system_execute_sql",
            "name": "execute_sql",
            "input": {"sql": "SELECT 1"},
        })

        stored = render_streaming_response(event_stream(use), container)

        assert stored.verified_tool_uses == set()

    def test_suggestion_widget_keys_follow_suggestion_key(self):
        """Two chatbots with different prefixes get distinct suggestion widget keys."""
        from streamlit_cortex_agents.chat.render import _render_suggested_queries

        container = make_container()
        with patch("streamlit.session_state", {}):
            _render_suggested_queries(["Q"], container, suggestion_key="a_pending")
            _render_suggested_queries(["Q"], container, suggestion_key="b_pending")

        keys = [c.kwargs["key"] for c in container.pills.call_args_list]
        assert keys == ["a_pending_pills", "b_pending_pills"]

    def test_suggestion_pill_selection_sets_pending_and_clears(self):
        """Selecting a pill stores the query and resets the pill so it can be reused."""
        from streamlit_cortex_agents.chat.render import _render_suggested_queries

        container = make_container()
        state: dict = {}
        with patch("streamlit.session_state", state):
            _render_suggested_queries(["Q1", "Q2"], container, suggestion_key="p")
            call = container.pills.call_args
            assert call.kwargs["options"] == ["Q1", "Q2"]
            state["p_pills"] = "Q2"
            call.kwargs["on_change"]()

        assert state["p"] == "Q2"
        assert state["p_pills"] is None

    def test_stored_text_holds_all_text_segments(self):
        """text → table → text: StoredMessage.text contains both segments."""
        container = make_container()
        t1 = TextEvent._from_payload({"content_index": 0, "text": "Before. "})
        t2 = TextEvent._from_payload({"content_index": 2, "text": "After."})

        stored = render_streaming_response(event_stream(t1, t2), container)

        assert stored.text == "Before. After."


def _think_delta(text: str) -> ThinkingDeltaEvent:
    return ThinkingDeltaEvent(event_type="response.thinking.delta", text=text)


def _step_labels(container) -> list[str]:
    """Returns the labels of steps nested in the outer timeline status."""
    return [c.args[0] for c in container.status.return_value.status.call_args_list]


class TestReasoningTimeline:
    """Reasoning and tool steps share one collapsible st.status timeline."""

    def _stream(self):
        return [
            _think_delta("First "),
            _think_delta("thought."),
            ToolUseEvent._from_payload(TOOL_USE_PAYLOAD),
            ToolResultEvent._from_payload(TOOL_RESULT_PAYLOAD),
            _think_delta("Second thought."),
            TextDeltaEvent._from_payload({"content_index": 3, "text": "Answer"}),
        ]

    def test_thinking_split_into_segments_around_tool_calls(self):
        """Thinking before and after a tool call is stored as two ordered segments."""
        stored = render_streaming_response(
            event_stream(*self._stream()), make_container(), show_thinking=True
        )
        assert stored.thinking_segments == ["First thought.", "Second thought."]
        assert stored.timeline == [("thinking", 0), ("tool", "toolu_01"), ("thinking", 1)]
        assert stored.thinking == "First thought.\n\nSecond thought."

    def test_segments_stored_when_show_flags_off(self):
        """Segments and timeline are recorded even when nothing is rendered."""
        container = make_container()
        stored = render_streaming_response(
            event_stream(*self._stream()), container,
            show_thinking=False, show_tool_status=False,
        )
        assert len(stored.thinking_segments) == 2
        assert len(stored.timeline) == 3
        container.status.assert_not_called()

    def test_all_steps_nest_in_one_outer_status(self):
        """One outer status holds thinking, tool, thinking steps in order."""
        container = make_container()
        render_streaming_response(
            event_stream(*self._stream()), container, show_thinking=True
        )
        container.status.assert_called_once()
        labels = _step_labels(container)
        assert len(labels) == 3
        assert "Thinking" in labels[0]
        assert "Using Analyst1" in labels[1]
        assert "Thinking" in labels[2]
        for c in container.status.return_value.status.call_args_list:
            assert c.kwargs["type"] == "step"

    def test_outer_starts_expanded_and_collapses_when_answer_starts(self):
        """Outer status opens expanded, then completes collapsed on the first answer text."""
        container = make_container()
        events = [_think_delta("Hmm."), TextDeltaEvent._from_payload({"content_index": 1, "text": "Hi"})]
        render_streaming_response(event_stream(*events), container, show_thinking=True)

        assert container.status.call_args.kwargs["expanded"] is True
        outer = container.status.return_value
        final = outer.update.call_args_list[-1].kwargs
        assert final["state"] == "complete"
        assert final["expanded"] is False

    def test_collapse_happens_before_answer_text_renders(self):
        """The timeline collapses before the answer placeholder is written."""
        container = make_container()
        order: list[str] = []
        outer = container.status.return_value
        outer.update.side_effect = lambda **kw: order.append(f"update:{kw.get('state')}")
        container.empty.return_value.markdown.side_effect = lambda *a, **k: order.append("text")
        events = [_think_delta("Hmm."), TextDeltaEvent._from_payload({"content_index": 1, "text": "Hi"})]
        render_streaming_response(event_stream(*events), container, show_thinking=True)
        assert order.index("update:complete") < order.index("text")

    def test_tool_only_timeline_uses_neutral_label(self):
        """With no thinking, the outer status is labelled Working."""
        container = make_container()
        render_streaming_response(
            event_stream(
                ToolUseEvent._from_payload(TOOL_USE_PAYLOAD),
                ToolResultEvent._from_payload(TOOL_RESULT_PAYLOAD),
            ),
            container,
        )
        assert container.status.call_args.args[0] == "Working"

    def test_failed_tool_leaves_outer_open_in_error_state(self):
        """A failed tool ends the outer status in the error state, expanded."""
        container = make_container()
        render_streaming_response(
            event_stream(
                ToolUseEvent._from_payload(TOOL_USE_PAYLOAD),
                ToolResultEvent._from_payload({**TOOL_RESULT_PAYLOAD, "status": "error"}),
            ),
            container,
        )
        final = container.status.return_value.update.call_args_list[-1].kwargs
        assert final["state"] == "error"
        assert final["expanded"] is True

    def test_key_prefix_wraps_timeline_in_keyed_container(self):
        """key_prefix keeps the .st-key-{prefix}-thinking CSS class via st.container."""
        container = make_container()
        keyed = container.container.return_value
        render_streaming_response(
            event_stream(_think_delta("Hmm.")), container,
            show_thinking=True, key_prefix="p",
        )
        container.container.assert_called_once_with(key="p-thinking")
        keyed.status.assert_called_once()

    def test_interrupted_tool_recorded_and_replayed_as_error(self):
        """A tool with no result is stored with None and replayed as an error step."""
        stored = render_streaming_response(
            event_stream(ToolUseEvent._from_payload(TOOL_USE_PAYLOAD)), make_container()
        )
        assert stored.tool_executions[0][1] is None

        replay = make_container()
        render_stored_message(stored, replay)
        step_call = replay.status.return_value.status.call_args
        assert step_call.args[0] == "Tool interrupted"
        assert step_call.kwargs["state"] == "error"

    def test_replay_matches_live_step_order(self):
        """Replay builds the same step sequence as the live stream, collapsed."""
        live = make_container()
        stored = render_streaming_response(
            event_stream(*self._stream()), live, show_thinking=True
        )
        replay = make_container()
        render_stored_message(stored, replay, show_thinking=True)

        replay.status.assert_called_once()
        assert replay.status.call_args.args[0] == "Reasoning"
        assert replay.status.call_args.kwargs["expanded"] is False
        labels = _step_labels(replay)
        assert "Thinking" in labels[0]
        assert labels[1] == ":material/check_circle: Analyst1 complete"
        assert "Thinking" in labels[2]
        steps = replay.status.return_value.status.return_value
        steps.markdown.assert_any_call("First thought.")
        steps.markdown.assert_any_call("Second thought.")

    def test_replay_respects_show_tool_status_false(self):
        """show_tool_status=False omits tool steps from replay."""
        stored = render_streaming_response(
            event_stream(*self._stream()), make_container(), show_thinking=True
        )
        replay = make_container()
        render_stored_message(stored, replay, show_thinking=True, show_tool_status=False)
        labels = _step_labels(replay)
        assert len(labels) == 2
        assert all("Thinking" in label for label in labels)

    def test_legacy_message_replays_thinking_then_tools(self):
        """Messages without a timeline replay one thinking step, then tool steps."""
        use = ToolUseEvent._from_payload(TOOL_USE_PAYLOAD)
        result = ToolResultEvent._from_payload(TOOL_RESULT_PAYLOAD)
        msg = StoredMessage(
            role="assistant", thinking="Old reasoning.", tool_executions=[(use, result)],
            analyst_sql={"toolu_01": "SELECT 1"},
        )
        replay = make_container()
        render_stored_message(msg, replay, show_thinking=True)
        labels = _step_labels(replay)
        assert len(labels) == 2
        assert "Thinking" in labels[0]
        assert "Analyst1 complete" in labels[1]
        replay.status.return_value.status.return_value.code.assert_called_once_with(
            "SELECT 1", language="sql"
        )
