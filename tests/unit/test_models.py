"""Unit tests for data models."""
from __future__ import annotations


from cortex_agents_client.models.agent import (
    Agent,
    AgentInstructions,
    AgentProfile,
    BudgetConfig,
)
from cortex_agents_client.models.thread import StoredMessage, ThreadMessage, ThreadMetadata


class TestAgentProfile:
    """Tests for AgentProfile model."""

    def test_from_dict_with_display_name(self):
        """from_dict extracts display_name correctly."""
        profile = AgentProfile.from_dict({"display_name": "My Agent"})
        assert profile.display_name == "My Agent"

    def test_from_dict_empty(self):
        """from_dict with empty dict yields empty display_name."""
        profile = AgentProfile.from_dict({})
        assert profile.display_name == ""

    def test_to_dict(self):
        """to_dict returns correct dict."""
        profile = AgentProfile(display_name="Test")
        assert profile.to_dict() == {"display_name": "Test"}


class TestAgentInstructions:
    """Tests for AgentInstructions model."""

    def test_from_dict_all_fields(self):
        """from_dict extracts all instruction fields."""
        data = {
            "response": "Be brief.",
            "orchestration": "Use Analyst.",
            "sample_questions": [{"question": "What is revenue?"}],
        }
        instructions = AgentInstructions.from_dict(data)
        assert instructions.response == "Be brief."
        assert instructions.orchestration == "Use Analyst."
        assert instructions.sample_questions == ["What is revenue?"]

    def test_to_dict_omits_empty_fields(self):
        """to_dict omits empty strings and empty lists."""
        instructions = AgentInstructions(response="Be concise.", orchestration="")
        result = instructions.to_dict()
        assert "response" in result
        assert "orchestration" not in result
        assert "sample_questions" not in result


class TestBudgetConfig:
    """Tests for BudgetConfig model."""

    def test_from_dict(self):
        """from_dict extracts seconds and tokens."""
        budget = BudgetConfig.from_dict({"seconds": 30, "tokens": 16000})
        assert budget.seconds == 30
        assert budget.tokens == 16000

    def test_to_dict_omits_none_fields(self):
        """to_dict omits fields that are None."""
        budget = BudgetConfig(seconds=30, tokens=None)
        result = budget.to_dict()
        assert result == {"seconds": 30}


class TestAgent:
    """Tests for Agent model."""

    def test_from_dict_list_response(self):
        """Agent.from_dict parses a list-endpoint response."""
        data = {
            "name": "MY_AGENT",
            "database": "DB",
            "schema": "SC",
            "owner": "ACCOUNTADMIN",
            "comment": "",
            "created_on": "2024-01-01",
            "profile": {"display_name": "My Agent"},
        }
        agent = Agent.from_dict(data)
        assert agent.name == "MY_AGENT"
        assert agent.database_name == "DB"
        assert agent.schema_name == "SC"
        assert agent.profile.display_name == "My Agent"

    def test_from_dict_describe_response_with_agent_spec(self):
        """Agent.from_dict parses agent_spec JSON string from describe endpoint."""
        import json
        spec = json.dumps({
            "models": {"orchestration": "claude-4-sonnet"},
            "instructions": {"response": "Be concise."},
            "tools": [{"tool_spec": {"type": "cortex_search", "name": "S1"}}],
        })
        data = {
            "name": "MY_AGENT",
            "database_name": "DB",
            "schema_name": "SC",
            "owner": "SYSADMIN",
            "created_on": "2024-01-01T00:00:00Z",
            "profile": {},
            "agent_spec": spec,
        }
        agent = Agent.from_dict(data)
        assert agent.models.orchestration == "claude-4-sonnet"
        assert agent.instructions.response == "Be concise."
        assert len(agent.tools) == 1
        assert agent.tools[0].tool_spec.name == "S1"

    def test_path_property(self):
        """Agent.path returns fully-qualified DB.SCHEMA.NAME string."""
        agent = Agent.from_dict({
            "name": "MY_AGENT",
            "database": "DB",
            "schema": "SC",
        })
        assert agent.path == "DB.SC.MY_AGENT"


class TestThreadMetadata:
    """Tests for ThreadMetadata model."""

    def test_from_dict(self):
        """ThreadMetadata.from_dict parses all fields."""
        data = {
            "thread_id": 123456,
            "thread_name": "My Thread",
            "origin_application": "test_app",
            "created_on": 1717000000000,
            "updated_on": 1717000100000,
        }
        meta = ThreadMetadata.from_dict(data)
        assert meta.thread_id == 123456
        assert meta.thread_name == "My Thread"
        assert meta.origin_application == "test_app"
        assert meta.created_on == 1717000000000
        assert meta.updated_on == 1717000100000


class TestThreadMessage:
    """Tests for ThreadMessage model."""

    def test_from_dict_with_parent(self):
        """ThreadMessage.from_dict with parent_id."""
        data = {
            "message_id": 2,
            "parent_id": 1,
            "created_on": 1717000001000,
            "role": "assistant",
            "message_payload": "Hello",
            "request_id": "req_1",
            "message_type": "conversation",
        }
        msg = ThreadMessage.from_dict(data)
        assert msg.message_id == 2
        assert msg.parent_id == 1
        assert msg.role == "assistant"

    def test_from_dict_without_parent(self):
        """ThreadMessage.from_dict with null parent_id."""
        data = {
            "message_id": 1,
            "parent_id": None,
            "created_on": 1717000000000,
            "role": "user",
            "message_payload": "Hi",
            "request_id": "req_0",
            "message_type": "conversation",
        }
        msg = ThreadMessage.from_dict(data)
        assert msg.parent_id is None


class TestStoredMessage:
    """Tests for StoredMessage dataclass defaults."""

    def test_default_fields_are_empty(self):
        """All list/optional fields default to empty."""
        msg = StoredMessage(role="user", text="Hello")
        assert msg.tables == []
        assert msg.charts == []
        assert msg.annotations == []
        assert msg.tool_executions == []
        assert msg.warnings == []
        assert msg.error is None
        assert msg.thinking is None
        assert msg.analyst_sql == {}
        assert msg.message_id is None


class TestRepr:
    """Tests for __repr__ implementations."""

    def test_cortex_agents_client_repr(self):
        """CortexAgentsClient repr shows account_url."""
        from cortex_agents_client import CortexAgentsClient
        client = CortexAgentsClient(
            "https://myorg-myaccount.snowflakecomputing.com",
            "v2:test_token",
        )
        r = repr(client)
        assert "CortexAgentsClient" in r
        assert "myorg-myaccount" in r

    def test_thread_repr(self):
        """Thread repr shows thread_id and parent_message_id."""
        from cortex_agents_client import CortexAgentsClient
        client = CortexAgentsClient(
            "https://myorg-myaccount.snowflakecomputing.com",
            "v2:test_token",
        )
        thread = client.get_thread(42, parent_message_id=7)
        r = repr(thread)
        assert "Thread" in r
        assert "42" in r
        assert "7" in r
