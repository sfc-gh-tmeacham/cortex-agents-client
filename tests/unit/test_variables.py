"""Unit tests for multi-tenancy ``variables`` (session attributes).

Covers normalisation of both input forms, validation errors, the request
body shape, and forwarding through every run entry point including the
Thread.chat client-side tool loop.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cortex_agents_client._variables import normalize_variables
from cortex_agents_client.auth import PATAuth
from cortex_agents_client.client import CortexAgentsClient, Thread
from cortex_agents_client.http import HttpClient
from cortex_agents_client.models.events import MetadataEvent, ToolUseEvent
from cortex_agents_client.resources.runs import RunsResource

MESSAGES = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
NORTH = {
    "region": {
        "value": "NORTH",
        "type": "string",
        "is_immutable_session_attribute": True,
    }
}


@pytest.fixture
def runs() -> RunsResource:
    http = HttpClient(
        base_url="https://testorg.snowflakecomputing.com",
        auth=PATAuth("v2:test_token"),
        timeout=5.0,
    )
    return RunsResource(http, "TEST_DB", "TEST_SCHEMA")


class TestNormalize:
    def test_none_and_empty_return_none(self):
        assert normalize_variables(None) is None
        assert normalize_variables({}) is None

    def test_shorthand_string(self):
        assert normalize_variables({"region": "NORTH"}) == NORTH

    @pytest.mark.parametrize(
        ("value", "expected_type"),
        [(True, "boolean"), (False, "boolean"), (7, "number"), (1.5, "number")],
    )
    def test_shorthand_type_inference(self, value, expected_type):
        out = normalize_variables({"x": value})
        assert out == {
            "x": {
                "value": value,
                "type": expected_type,
                "is_immutable_session_attribute": True,
            }
        }

    def test_full_form_passthrough(self):
        spec = {"value": "NORTH", "type": "string", "is_immutable_session_attribute": True}
        assert normalize_variables({"region": spec}) == {"region": spec}

    def test_full_form_defaults_type_and_immutable(self):
        assert normalize_variables({"region": {"value": "NORTH"}}) == NORTH

    def test_full_form_explicit_false_respected(self):
        out = normalize_variables(
            {"region": {"value": "NORTH", "is_immutable_session_attribute": False}}
        )
        assert out is not None
        assert out["region"]["is_immutable_session_attribute"] is False

    def test_full_form_explicit_type_kept(self):
        out = normalize_variables({"n": {"value": 5, "type": "string"}})
        assert out is not None
        assert out["n"]["type"] == "string"

    def test_input_not_mutated(self):
        spec = {"value": "NORTH"}
        variables = {"region": spec}
        normalize_variables(variables)
        assert spec == {"value": "NORTH"}
        assert variables == {"region": {"value": "NORTH"}}

    @pytest.mark.parametrize(
        "bad",
        [
            {"": "x"},
            {1: "x"},
            {"region": None},
            {"region": {"type": "string"}},
            {"region": {"value": None}},
            {"region": ["NORTH"]},
            {"region": {"value": ["NORTH"]}},
            {"region": {"value": ["NORTH"], "type": "string"}},
            {"x": float("nan")},
            {"x": float("inf")},
            {"x": {"value": float("-inf")}},
        ],
    )
    def test_invalid_raises_value_error(self, bad):
        with pytest.raises(ValueError):
            normalize_variables(bad)

    @pytest.mark.parametrize("bad", [["region"], "region=NORTH", 5])
    def test_non_mapping_raises_value_error(self, bad):
        with pytest.raises(ValueError, match="must be a mapping"):
            normalize_variables(bad)


class TestBuildBody:
    def test_omitted_has_no_variables_key(self, runs):
        assert "variables" not in runs._build_body(MESSAGES)
        assert "variables" not in runs._build_body(MESSAGES, variables={})

    def test_omitted_body_unchanged(self, runs):
        assert runs._build_body(MESSAGES, thread_id=5) == runs._build_body(
            MESSAGES, thread_id=5, variables=None
        )

    def test_shorthand_normalised_into_body(self, runs):
        body = runs._build_body(MESSAGES, variables={"region": "NORTH"})
        assert body["variables"] == NORTH

    def test_invalid_raises_before_http(self, runs):
        runs._http = MagicMock()
        with pytest.raises(ValueError):
            list(runs.stream(MESSAGES, agent_path="DB.SC.AGENT", variables={"r": None}))
        runs._http.stream.assert_not_called()


class TestRunsForwarding:
    def test_stream_sends_variables(self, runs):
        runs._http = MagicMock()
        runs._http.stream.return_value.__enter__.return_value = iter([])
        list(runs.stream(MESSAGES, agent_path="DB.SC.AGENT", variables={"region": "NORTH"}))
        assert runs._http.stream.call_args.kwargs["json"]["variables"] == NORTH

    def test_run_sends_variables(self, runs):
        runs._http = MagicMock()
        runs._http.request.return_value = {"role": "assistant", "content": []}
        runs.run(MESSAGES, agent_path="DB.SC.AGENT", variables={"region": "NORTH"})
        assert runs._http.request.call_args.kwargs["json"]["variables"] == NORTH

    def test_stream_and_collect_forwards_variables(self, runs):
        runs._http = MagicMock()
        runs._http.stream.return_value.__enter__.return_value = iter([])
        runs.stream_and_collect(
            MESSAGES, agent_path="DB.SC.AGENT", variables={"region": "NORTH"}
        )
        assert runs._http.stream.call_args.kwargs["json"]["variables"] == NORTH


def _mock_client() -> CortexAgentsClient:
    client = CortexAgentsClient.__new__(CortexAgentsClient)
    client.runs = MagicMock()
    return client


class TestClientForwarding:
    def test_stream_without_thread(self):
        client = _mock_client()
        client.runs.stream.return_value = iter([])
        list(client.stream("DB.SC.AGENT", "Hi", variables={"region": "NORTH"}))
        assert client.runs.stream.call_args.kwargs["variables"] == {"region": "NORTH"}

    def test_stream_with_thread_forwards_to_chat(self):
        client = _mock_client()
        thread = MagicMock()
        thread.chat.return_value = iter([])
        list(client.stream("DB.SC.AGENT", "Hi", thread=thread, variables={"region": "NORTH"}))
        assert thread.chat.call_args.kwargs["variables"] == {"region": "NORTH"}

    def test_run_forwards(self):
        client = _mock_client()
        client.run("DB.SC.AGENT", "Hi", variables={"region": "NORTH"})
        assert client.runs.run.call_args.kwargs["variables"] == {"region": "NORTH"}

    def test_run_with_thread_forwards(self):
        client = _mock_client()
        thread = MagicMock(thread_id=7, parent_message_id=3)
        client.run("DB.SC.AGENT", "Hi", thread=thread, variables={"region": "NORTH"})
        kwargs = client.runs.run.call_args.kwargs
        assert kwargs["variables"] == {"region": "NORTH"}
        assert kwargs["thread_id"] == 7


class TestThreadChat:
    def _make_thread(self):
        client = MagicMock(spec=CortexAgentsClient)
        client.runs = MagicMock()
        return Thread(client, thread_id=1, parent_message_id=0), client

    def test_chat_forwards_variables(self):
        thread, client = self._make_thread()
        client.runs.stream.return_value = iter([])
        list(thread.chat("DB.SC.AGENT", "Hi", variables={"region": "NORTH"}))
        assert client.runs.stream.call_args.kwargs["variables"] == {"region": "NORTH"}

    def test_chat_default_sends_none(self):
        thread, client = self._make_thread()
        client.runs.stream.return_value = iter([])
        list(thread.chat("DB.SC.AGENT", "Hi"))
        assert client.runs.stream.call_args.kwargs["variables"] is None

    def test_tool_loop_follow_up_carries_variables(self):
        """Every agent:run in a turn, including tool follow-ups, is filtered."""
        thread, client = self._make_thread()
        tool_event = ToolUseEvent._from_payload({
            "content_index": 0,
            "tool_use_id": "toolu_client",
            "type": "generic",
            "name": "MyUDF",
            "input": {},
            "client_side_execute": True,
        })
        meta = MetadataEvent._from_payload(
            {"metadata": {"role": "assistant", "message_id": 99, "run_id": "r1"}}
        )
        streams = iter([iter([tool_event]), iter([meta])])
        client.runs.stream.side_effect = lambda *a, **kw: next(streams)

        list(thread.chat(
            "DB.SC.AGENT",
            "Hi",
            tool_executor=MagicMock(return_value=[{"type": "text", "text": "42"}]),
            variables={"region": "NORTH"},
        ))

        calls = client.runs.stream.call_args_list
        assert len(calls) == 2
        assert all(c.kwargs["variables"] == {"region": "NORTH"} for c in calls)
