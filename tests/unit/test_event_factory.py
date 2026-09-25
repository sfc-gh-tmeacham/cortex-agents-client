"""Unit tests for the SSE event factory."""
from __future__ import annotations


from streamlit_cortex_agents.client.models.events import (
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
    TokensConsumed,
    ToolResultEvent,
    ToolResultStatusEvent,
    ToolUseEvent,
    UnknownEvent,
    WarningEvent,
)
from streamlit_cortex_agents.client.sse import event_from_sse
from tests.fixtures.sse_streams import (
    ANALYST_DELTA_PAYLOAD,
    CHART_PAYLOAD,
    ERROR_PAYLOAD,
    METADATA_ASSISTANT_PAYLOAD,
    METADATA_USER_PAYLOAD,
    RESPONSE_PAYLOAD,
    STATUS_PAYLOAD,
    TABLE_PAYLOAD,
    TEXT_ANNOTATION_PAYLOAD,
    TEXT_DELTA_PAYLOAD,
    TEXT_PAYLOAD,
    THINKING_DELTA_PAYLOAD,
    THINKING_PAYLOAD,
    TOOL_RESULT_ERROR_PAYLOAD,
    TOOL_RESULT_PAYLOAD,
    TOOL_RESULT_STATUS_PAYLOAD,
    TOOL_USE_PAYLOAD,
    TOOL_USE_WITH_PERMISSION_PAYLOAD,
    WARNING_PAYLOAD,
)


def test_text_delta_event():
    """response.text.delta → TextDeltaEvent with correct fields."""
    event = event_from_sse("response.text.delta", TEXT_DELTA_PAYLOAD)
    assert isinstance(event, TextDeltaEvent)
    assert event.text == "Hello "          # primary field name
    assert event.delta == "Hello "         # backward-compat alias
    assert event.content_index == 0
    assert event.is_elicitation is False


def test_text_delta_event_is_elicitation():
    """response.text.delta with is_elicitation=True is captured."""
    payload = {"content_index": 0, "text": "Could you clarify?", "is_elicitation": True}
    event = event_from_sse("response.text.delta", payload)
    assert event.is_elicitation is True


def test_text_event():
    """response.text → TextEvent with full text and is_elicitation flag."""
    event = event_from_sse("response.text", TEXT_PAYLOAD)
    assert isinstance(event, TextEvent)
    assert event.text == "Hello world"
    assert event.content_index == 0
    assert event.is_elicitation is False
    assert event.annotations == []


def test_text_event_is_elicitation():
    """response.text with is_elicitation=True is captured."""
    payload = {"content_index": 0, "text": "What time period?", "is_elicitation": True, "annotations": []}
    event = event_from_sse("response.text", payload)
    assert event.is_elicitation is True


def test_text_event_inline_annotations():
    """response.text with inline annotations array is parsed."""
    payload = {
        "content_index": 0,
        "text": "Revenue was $4.2B [^1]",
        "is_elicitation": False,
        "annotations": [{"type": "cortex_search_citation", "index": 1, "doc_id": "d1", "doc_title": "Report", "text": "..."}],
    }
    event = event_from_sse("response.text", payload)
    assert len(event.annotations) == 1


def test_text_annotation_event():
    """response.text.annotation → TextAnnotationEvent with all citation fields including annotation_index."""
    event = event_from_sse("response.text.annotation", TEXT_ANNOTATION_PAYLOAD)
    assert isinstance(event, TextAnnotationEvent)
    assert event.annotation_type == "cortex_search_citation"
    assert event.annotation_index == 0   # from top-level payload
    assert event.index == 1
    assert event.doc_id == "doc_456"
    assert event.doc_title == "Annual Report 2025"
    assert event.search_result_id == "cs_abc123"
    assert event.text == "Revenue was $4.2B"


def test_thinking_delta_event():
    """response.thinking.delta → ThinkingDeltaEvent."""
    event = event_from_sse("response.thinking.delta", THINKING_DELTA_PAYLOAD)
    assert isinstance(event, ThinkingDeltaEvent)
    assert event.text == "Let me think..."
    assert event.signature == "sig123"
    assert event.content_index == 1


def test_thinking_event():
    """response.thinking → ThinkingEvent with signature."""
    event = event_from_sse("response.thinking", THINKING_PAYLOAD)
    assert isinstance(event, ThinkingEvent)
    assert event.text == "I need to use the Analyst tool."
    assert event.signature == "sig_full"


def test_tool_use_event_no_permission():
    """response.tool_use with empty options → permission_options=[]."""
    event = event_from_sse("response.tool_use", TOOL_USE_PAYLOAD)
    assert isinstance(event, ToolUseEvent)
    assert event.tool_use_id == "toolu_01"
    assert event.type == "cortex_analyst_text_to_sql"
    assert event.name == "Analyst1"
    assert event.permission_options == []
    assert event.client_side_execute is False


def test_tool_use_client_side_execute_string_true():
    """The API sends client_side_execute as the string \"true\" (not a boolean) — must parse to True."""
    payload = {**TOOL_USE_PAYLOAD, "client_side_execute": "true"}
    event = event_from_sse("response.tool_use", payload)
    assert event.client_side_execute is True


def test_tool_use_client_side_execute_string_false():
    """String \"false\" must not be coerced to True via bool(\"false\")."""
    payload = {**TOOL_USE_PAYLOAD, "client_side_execute": "false"}
    event = event_from_sse("response.tool_use", payload)
    assert event.client_side_execute is False


def test_tool_use_client_side_execute_bool_true():
    """Boolean True (JSON literal) must still parse to True."""
    payload = {**TOOL_USE_PAYLOAD, "client_side_execute": True}
    event = event_from_sse("response.tool_use", payload)
    assert event.client_side_execute is True


def test_tool_use_event_with_permission():
    """response.tool_use with permission options populated."""
    event = event_from_sse("response.tool_use", TOOL_USE_WITH_PERMISSION_PAYLOAD)
    assert isinstance(event, ToolUseEvent)
    assert event.permission_options == ["Allow Once", "Deny"]


def test_tool_result_success():
    """response.tool_result with status=success."""
    event = event_from_sse("response.tool_result", TOOL_RESULT_PAYLOAD)
    assert isinstance(event, ToolResultEvent)
    assert event.status == "success"
    assert event.tool_use_id == "toolu_01"
    assert len(event.content) == 1
    assert event.content[0]["type"] == "json"


def test_tool_result_error():
    """response.tool_result with status=error."""
    event = event_from_sse("response.tool_result", TOOL_RESULT_ERROR_PAYLOAD)
    assert isinstance(event, ToolResultEvent)
    assert event.status == "error"


def test_tool_result_status_event():
    """response.tool_result.status → ToolResultStatusEvent."""
    event = event_from_sse("response.tool_result.status", TOOL_RESULT_STATUS_PAYLOAD)
    assert isinstance(event, ToolResultStatusEvent)
    assert event.tool_use_id == "toolu_01"
    assert event.tool_type == "cortex_analyst_text_to_sql"
    assert event.status == "Executing SQL"
    assert event.message == "Running SELECT ..."


def test_analyst_delta_all_fields():
    """response.tool_result.analyst.delta with all delta fields."""
    event = event_from_sse("response.tool_result.analyst.delta", ANALYST_DELTA_PAYLOAD)
    assert isinstance(event, AnalystDeltaEvent)
    assert event.sql == "SELECT SUM(revenue) FROM sales WHERE year = 2025"
    assert event.text == "Based on the data,"
    assert event.query_id == "qid_789"
    assert event.verified_query_used is False
    assert event.result_set is not None
    assert event.suggestion_index is None


def test_analyst_delta_sql_only():
    """AnalystDeltaEvent with only sql field populated."""
    payload = {
        "content_index": 0,
        "tool_use_id": "toolu_01",
        "tool_type": "cortex_analyst_text_to_sql",
        "tool_name": "A1",
        "delta": {"sql": "SELECT 1"},
    }
    event = event_from_sse("response.tool_result.analyst.delta", payload)
    assert isinstance(event, AnalystDeltaEvent)
    assert event.sql == "SELECT 1"
    assert event.text is None
    assert event.result_set is None


def test_analyst_delta_with_suggestions():
    """AnalystDeltaEvent with suggestions field."""
    payload = {
        "content_index": 0,
        "tool_use_id": "toolu_01",
        "tool_type": "cortex_analyst_text_to_sql",
        "tool_name": "A1",
        "delta": {"suggestions": {"index": 0, "delta": "What about costs?"}},
    }
    event = event_from_sse("response.tool_result.analyst.delta", payload)
    assert isinstance(event, AnalystDeltaEvent)
    assert event.suggestion_index == 0
    assert event.suggestion_delta == "What about costs?"


def test_table_event():
    """response.table → TableEvent with result_set and title."""
    event = event_from_sse("response.table", TABLE_PAYLOAD)
    assert isinstance(event, TableEvent)
    assert event.title == "Annual Revenue"
    assert event.query_id == "qid_789"
    assert "resultSetMetaData" in event.result_set
    assert len(event.result_set["resultSetMetaData"]["rowType"]) == 2


def test_table_event_no_title():
    """TableEvent with null title → title=None."""
    payload = {**TABLE_PAYLOAD, "title": None}
    event = event_from_sse("response.table", payload)
    assert isinstance(event, TableEvent)
    assert event.title is None


def test_chart_event():
    """response.chart → ChartEvent with chart_spec string."""
    event = event_from_sse("response.chart", CHART_PAYLOAD)
    assert isinstance(event, ChartEvent)
    assert event.tool_use_id == "toolu_chart_01"
    assert isinstance(event.chart_spec, str)
    import json
    spec = json.loads(event.chart_spec)
    assert "$schema" in spec


def test_status_event():
    """response.status → StatusEvent."""
    event = event_from_sse("response.status", STATUS_PAYLOAD)
    assert isinstance(event, StatusEvent)
    assert event.status == "executing_tool"
    assert "Analyst1" in event.message


def test_warning_event_with_code():
    """response.warning with code field."""
    event = event_from_sse("response.warning", WARNING_PAYLOAD)
    assert isinstance(event, WarningEvent)
    assert "MCP" in event.message
    assert event.code == "003001"


def test_warning_event_without_code():
    """response.warning without code → code=None."""
    event = event_from_sse("response.warning", {"message": "Something degraded"})
    assert isinstance(event, WarningEvent)
    assert event.code is None


def test_error_event():
    """error → ErrorEvent with code, message, request_id."""
    event = event_from_sse("error", ERROR_PAYLOAD)
    assert isinstance(event, ErrorEvent)
    assert event.code == "399504"
    assert "failed" in event.message.lower()
    assert event.request_id == "req_abc123"


def test_error_event_uses_error_code_alias():
    """ErrorEvent falls back to error_code when code is missing."""
    payload = {"error_code": "12345", "message": "test", "request_id": "r1"}
    event = event_from_sse("error", payload)
    assert isinstance(event, ErrorEvent)
    assert event.code == "12345"


def test_metadata_user_event():
    """metadata with role=user → MetadataEvent."""
    event = event_from_sse("metadata", METADATA_USER_PAYLOAD)
    assert isinstance(event, MetadataEvent)
    assert event.role == "user"
    assert event.message_id == 123
    assert event.run_id == "run_1"


def test_metadata_assistant_event():
    """metadata with role=assistant → MetadataEvent."""
    event = event_from_sse("metadata", METADATA_ASSISTANT_PAYLOAD)
    assert isinstance(event, MetadataEvent)
    assert event.role == "assistant"
    assert event.message_id == 456


def test_response_event():
    """response → ResponseEvent with all top-level fields including usage."""
    event = event_from_sse("response", RESPONSE_PAYLOAD)
    assert isinstance(event, ResponseEvent)
    assert event.role == "assistant"
    assert len(event.content) == 1
    assert event.warnings == []
    assert event.status == "completed"
    assert event.run_id == "run_1"
    assert event.thread_id == 99
    assert event.user_message_id == 123
    assert event.assistant_message_id == 456
    # usage / token counts
    assert len(event.usage) == 1
    tc = event.usage[0]
    assert isinstance(tc, TokensConsumed)
    assert tc.model_name == "claude-3-5-sonnet"
    assert tc.input_tokens.total == 1500
    assert tc.input_tokens.cache_read == 1200
    assert tc.input_tokens.cache_write == 100
    assert tc.input_tokens.uncached == 200
    assert tc.output_tokens.total == 250
    assert tc.context_window == 200000


def test_response_event_cancelled():
    """response with status=cancelled is captured."""
    payload = {**RESPONSE_PAYLOAD, "status": "cancelled"}
    event = event_from_sse("response", payload)
    assert isinstance(event, ResponseEvent)
    assert event.status == "cancelled"


def test_response_event_missing_metadata():
    """response with no metadata fields defaults gracefully."""
    event = event_from_sse("response", {"role": "assistant", "content": [], "warnings": []})
    assert isinstance(event, ResponseEvent)
    assert event.run_id is None
    assert event.thread_id is None
    assert event.user_message_id is None
    assert event.assistant_message_id is None
    assert event.usage == []

def test_suggested_queries_event():
    """SuggestedQueriesEvent extracts query strings from payload."""
    from streamlit_cortex_agents.client.models.events import SuggestedQueriesEvent

    payload = {
        "content_index": 0,
        "suggested_queries": [
            {"query": "What is Q2 revenue?"},
            {"query": "Show top products"},
        ],
    }
    event = event_from_sse("response.suggested_queries", payload)
    assert isinstance(event, SuggestedQueriesEvent)
    assert event.queries == ["What is Q2 revenue?", "Show top products"]
    assert event.content_index == 0


def test_suggested_queries_event_empty():
    """SuggestedQueriesEvent with empty list returns empty queries."""
    from streamlit_cortex_agents.client.models.events import SuggestedQueriesEvent

    event = event_from_sse("response.suggested_queries", {"suggested_queries": []})
    assert isinstance(event, SuggestedQueriesEvent)
    assert event.queries == []


def test_unknown_event_type_returns_unknown_event():
    """An unrecognised event type returns UnknownEvent."""
    event = event_from_sse("response.new_future_type", {"some": "data"})
    assert isinstance(event, UnknownEvent)
    assert event.event_type == "response.new_future_type"
    assert event.raw_payload == {"some": "data"}


def test_unknown_event_does_not_raise():
    """Unknown event type never raises any exception."""
    # Should not raise even with an unusual type string
    event = event_from_sse("completely_unknown:::type", {"x": 1})
    assert isinstance(event, UnknownEvent)


# ---------------------------------------------------------------------------
# sequence_number
#
# Live streams carry a `sequence_number` on each event. It is the cursor value
# consumed by stream_run(starting_after=...), so without exposing it a caller
# has no way to resume from a known point.
# ---------------------------------------------------------------------------


def test_sequence_number_captured_from_payload():
    """sequence_number is populated on a typed event."""
    event = event_from_sse(
        "response.text", {"content_index": 0, "text": "hi", "sequence_number": 7}
    )
    assert event.sequence_number == 7


def test_sequence_number_none_when_absent():
    """An event without sequence_number reports None, not 0."""
    event = event_from_sse("response.text", {"content_index": 0, "text": "hi"})
    assert event.sequence_number is None


def test_sequence_number_on_status_event():
    """The cursor is applied to every event type, not just text."""
    event = event_from_sse(
        "response.status", {"status": "planning", "message": "x", "sequence_number": 3}
    )
    assert event.sequence_number == 3


def test_non_integer_sequence_number_ignored():
    """A malformed sequence_number does not corrupt the field."""
    event = event_from_sse(
        "response.text", {"content_index": 0, "text": "hi", "sequence_number": "bad"}
    )
    assert event.sequence_number is None
