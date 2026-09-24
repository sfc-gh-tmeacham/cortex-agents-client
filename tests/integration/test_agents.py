"""Integration tests for AgentsResource using pytest-httpx."""
from __future__ import annotations

import json

import httpx
import pytest
from pytest_httpx import HTTPXMock

from cortex_agents_client.exceptions import AgentNotFoundError, AuthError, CortexPermissionError
from tests.fixtures.api_responses import AGENT_DESCRIBE_RESPONSE, AGENT_LIST_RESPONSE
from tests.integration.conftest import make_json_response


class TestCreateAgent:
    """Tests for agents.create()."""

    def test_create_returns_agent(self, ca_client, httpx_mock: HTTPXMock):
        """Successful create followed by describe returns an Agent."""
        httpx_mock.add_response(json={"status": "Agent MY_AGENT successfully created."})
        httpx_mock.add_response(json=AGENT_DESCRIBE_RESPONSE)
        agent = ca_client.agents.create("MY_AGENT")
        assert agent.name == "MY_AGENT"

    def test_create_with_or_replace_sends_query_param(self, ca_client, httpx_mock: HTTPXMock):
        """create_mode='orReplace' is sent as ?createMode=orReplace."""
        captured: list[str] = []

        def responder(request):
            captured.append(str(request.url))
            return make_json_response({"status": "ok"})

        httpx_mock.add_callback(responder)
        httpx_mock.add_response(json=AGENT_DESCRIBE_RESPONSE)
        ca_client.agents.create("MY_AGENT", create_mode="orReplace")
        assert "createMode=orReplace" in captured[0]

    def test_create_with_if_not_exists(self, ca_client, httpx_mock: HTTPXMock):
        """create_mode='ifNotExists' is sent as ?createMode=ifNotExists."""
        captured: list[str] = []

        def responder(request):
            captured.append(str(request.url))
            return make_json_response({"status": "ok"})

        httpx_mock.add_callback(responder)
        httpx_mock.add_response(json=AGENT_DESCRIBE_RESPONSE)
        ca_client.agents.create("MY_AGENT", create_mode="ifNotExists")
        assert "createMode=ifNotExists" in captured[0]


class TestGetAgent:
    """Tests for agents.get()."""

    def test_get_happy_path(self, ca_client, httpx_mock: HTTPXMock):
        """Successful get returns a populated Agent."""
        httpx_mock.add_response(method="GET", json=AGENT_DESCRIBE_RESPONSE)
        agent = ca_client.agents.get("MY_AGENT")
        assert agent.name == "MY_AGENT"
        assert agent.database_name == "TEST_DB"
        assert len(agent.tools) == 1

    def test_get_404_raises_agent_not_found(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 404 raises AgentNotFoundError."""
        httpx_mock.add_response(status_code=404, json={"message": "Agent not found"})
        with pytest.raises(AgentNotFoundError):
            ca_client.agents.get("NONEXISTENT")

    def test_get_403_raises_permission_error(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 403 raises CortexPermissionError."""
        httpx_mock.add_response(status_code=403, json={"message": "Insufficient privileges"})
        with pytest.raises(CortexPermissionError):
            ca_client.agents.get("MY_AGENT")

    def test_get_401_raises_auth_error(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 401 raises AuthError."""
        httpx_mock.add_response(status_code=401, json={"message": "Unauthorized"})
        with pytest.raises(AuthError):
            ca_client.agents.get("MY_AGENT")


class TestUpdateAgent:
    """Tests for agents.update()."""

    def test_update_happy_path(self, ca_client, httpx_mock: HTTPXMock):
        """Successful update returns without error."""
        httpx_mock.add_response(
            method="PUT", json={"status": "Agent MY_AGENT successfully updated."}
        )
        ca_client.agents.update("MY_AGENT", comment="Updated comment")

    def test_update_only_sends_provided_fields(self, ca_client, httpx_mock: HTTPXMock):
        """Only provided kwargs are included in the request body."""
        captured_request = {}

        def responder(request):
            captured_request["body"] = request.content
            return make_json_response({"status": "ok"})

        httpx_mock.add_callback(responder)
        ca_client.agents.update("MY_AGENT", comment="New comment")

        body = json.loads(captured_request["body"])
        assert "comment" in body
        assert "profile" not in body


class TestListAgents:
    """Tests for agents.list()."""

    def test_list_returns_all_agents(self, ca_client, httpx_mock: HTTPXMock):
        """Successful list returns list of Agent objects."""
        httpx_mock.add_response(json=AGENT_LIST_RESPONSE)
        agents = ca_client.agents.list()
        assert len(agents) == 2
        assert agents[0].name == "AGENT_ONE"
        assert agents[1].name == "AGENT_TWO"

    def test_list_empty_returns_empty_list(self, ca_client, httpx_mock: HTTPXMock):
        """Empty response returns []."""
        httpx_mock.add_response(json=[])
        agents = ca_client.agents.list()
        assert agents == []

    def test_list_with_like_filter_sends_query_param(self, ca_client, httpx_mock: HTTPXMock):
        """like= param is sent as ?like=..."""
        captured: list[str] = []

        def responder(request):
            captured.append(str(request.url))
            return make_json_response([])

        httpx_mock.add_callback(responder)
        ca_client.agents.list(like="MY_%")
        assert "like=" in captured[0]


class TestDeleteAgent:
    """Tests for agents.delete()."""

    def test_delete_happy_path(self, ca_client, httpx_mock: HTTPXMock):
        """Successful delete returns without error."""
        httpx_mock.add_response(
            method="DELETE", json={"status": "Request successfully completed"}
        )
        ca_client.agents.delete("MY_AGENT")

    def test_delete_if_exists_sends_query_param(self, ca_client, httpx_mock: HTTPXMock):
        """if_exists=True sends ?ifExists=true."""
        captured: list[str] = []

        def responder(request):
            captured.append(str(request.url))
            return make_json_response({"status": "ok"})

        httpx_mock.add_callback(responder)
        ca_client.agents.delete("MY_AGENT", if_exists=True)
        assert "ifExists=true" in captured[0]

    def test_delete_missing_without_if_exists_raises(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 404 without if_exists raises AgentNotFoundError."""
        httpx_mock.add_response(status_code=404, json={"message": "not found"})
        with pytest.raises(AgentNotFoundError):
            ca_client.agents.delete("MISSING")


class TestFeedback:
    """Tests for agents.feedback()."""

    def test_feedback_request_level(self, ca_client, httpx_mock: HTTPXMock):
        """Request-level feedback sends orig_request_id in body."""
        captured: dict = {}

        def responder(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"status": "Feedback submitted successfully"})

        httpx_mock.add_callback(responder)
        ca_client.agents.feedback(
            "MY_AGENT",
            positive=True,
            request_id="req_abc",
            thread_id=1234,
            feedback_message="Great answer!",
            categories=["accurate"],
        )
        assert captured["body"]["orig_request_id"] == "req_abc"
        assert captured["body"]["thread_id"] == 1234   # integer, not string
        assert "request_id" not in captured["body"]    # old field name gone

    def test_feedback_agent_level_no_request_id(self, ca_client, httpx_mock: HTTPXMock):
        """Agent-level feedback omits orig_request_id when not provided."""
        captured: dict = {}

        def responder(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"status": "Feedback submitted successfully"})

        httpx_mock.add_callback(responder)
        ca_client.agents.feedback("MY_AGENT", positive=False)
        assert "orig_request_id" not in captured["body"]

    def test_feedback_url_no_trailing_colon(self, ca_client, httpx_mock: HTTPXMock):
        """Feedback endpoint URL ends with :feedback, not :feedback:."""
        captured: list[str] = []

        def responder(request):
            import httpx
            captured.append(str(request.url))
            return httpx.Response(200, json={"status": "ok"})

        httpx_mock.add_callback(responder)
        ca_client.agents.feedback("MY_AGENT", positive=True)
        assert captured[0].endswith(":feedback")
        assert not captured[0].endswith(":feedback:")
