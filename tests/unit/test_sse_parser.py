"""Unit tests for the SSE parser."""
from __future__ import annotations

import pytest

from cortex_agents_client.sse import parse_sse_stream
from tests.fixtures.sse_streams import ALL_EVENT_TYPES, stream_of


def test_empty_stream_yields_nothing():
    """An empty iterator yields no events."""
    result = list(parse_sse_stream(iter([])))
    assert result == []


def test_single_text_delta_event():
    """A single text delta event is parsed correctly."""
    lines = stream_of(("response.text.delta", {"content_index": 0, "text": "hello"}))
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 1
    event_type, payload = events[0]
    assert event_type == "response.text.delta"
    assert payload["text"] == "hello"


def test_multiple_events_all_yielded():
    """Two consecutive events are both yielded."""
    lines = stream_of(
        ("response.text.delta", {"text": "hi"}),
        ("response.status", {"status": "done", "message": ""}),
    )
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 2
    assert events[0][0] == "response.text.delta"
    assert events[1][0] == "response.status"


def test_comment_lines_ignored():
    """Lines starting with ':' are silently ignored."""
    lines = [
        ": this is a comment",
        "event: response.text",
        "data: {\"content_index\": 0, \"text\": \"hi\"}",
        "",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 1
    assert events[0][0] == "response.text"


def test_retry_lines_ignored():
    """'retry:' lines are silently ignored."""
    lines = [
        "retry: 3000",
        "event: response.text",
        "data: {\"content_index\": 0, \"text\": \"hi\"}",
        "",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 1


def test_blank_line_dispatches_accumulated_event():
    """Blank line triggers dispatch of the accumulated event."""
    lines = [
        "event: response.text",
        "data: {\"content_index\": 0, \"text\": \"hello world\"}",
        "",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 1
    assert events[0][1]["text"] == "hello world"


def test_all_17_event_types_parsed():
    """One fixture event of each type yields 16 tuples."""
    lines = stream_of(*ALL_EVENT_TYPES)
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 17
    parsed_types = [e[0] for e in events]
    expected_types = [et for et, _ in ALL_EVENT_TYPES]
    assert parsed_types == expected_types


def test_truncated_stream_discards_partial_event():
    """Stream ending without a blank line discards the incomplete event."""
    lines = [
        "event: response.text",
        "data: {\"content_index\": 0, \"text\": \"incomplete\"}",
        # No trailing blank line
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert events == []


def test_invalid_json_in_data_yields_parse_error():
    """Malformed JSON yields a '_parse_error' event rather than raising."""
    lines = [
        "event: response.text",
        "data: {not valid json",
        "",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 1
    event_type, payload = events[0]
    assert event_type == "_parse_error"
    assert "raw" in payload


def test_missing_event_line_uses_message_default():
    """A 'data:' line without a preceding 'event:' dispatches as 'message'."""
    lines = [
        "data: {\"foo\": \"bar\"}",
        "",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 1
    assert events[0][0] == "message"


def test_event_without_data_not_dispatched():
    """An 'event:' line with no 'data:' line does not produce an event."""
    lines = [
        "event: response.text",
        "",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert events == []


def test_data_field_whitespace_stripped():
    """Leading space after 'data: ' is stripped from the payload."""
    lines = [
        "event: response.text.delta",
        "data: {\"content_index\": 0, \"text\": \"hi\"}",
        "",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert events[0][1]["text"] == "hi"
