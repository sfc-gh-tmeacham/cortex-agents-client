"""Live tests for the agent CRUD lifecycle and feedback submission.

AgentsResource is otherwise mock-only: nothing verified that the server
accepts the request bodies this client builds for create and update, or that
the createMode / ifExists query parameters behave as documented.

Every test object is named with the ``cac_live_crud`` prefix and dropped in a
fixture ``finally`` block, so an interrupted run does not leak an agent. The
DROP is also in seed/teardown.sql as a backstop.

Requires the environment described in tests/live/README.md. Always run with
LIVE_SKIP_TEARDOWN=1.
"""
from __future__ import annotations

import uuid

import pytest

from cortex_agents_client.exceptions import AgentNotFoundError, CortexAgentError

pytestmark = pytest.mark.live

_SPEC_INSTRUCTIONS = {
    "response": "You are a disposable test agent. Reply in one short sentence.",
}


def _crud_db_schema(agent_path_minimal: str) -> tuple[str, str]:
    """Derives the target database and schema from the seeded agent path.

    Args:
        agent_path_minimal: Fully-qualified path of the minimal agent.

    Returns:
        Tuple of (database, schema).
    """
    parts = agent_path_minimal.split(".")
    if len(parts) < 3:
        pytest.skip(f"LIVE_AGENT_MINIMAL is not fully qualified: {agent_path_minimal}")
    return parts[0], parts[1]


@pytest.fixture
def crud_agent_name(live_client, agent_path_minimal):
    """Yields a unique disposable agent name and guarantees its removal.

    The name includes a short uuid so concurrent runs cannot collide on the
    same object.
    """
    db, schema = _crud_db_schema(agent_path_minimal)
    name = f"cac_live_crud_{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        # Best-effort teardown; runs even if the test raised mid-way.
        try:
            live_client.agents.delete(
                name, database=db, schema=schema, if_exists=True
            )
        except Exception:
            pass


class TestAgentLifecycle:
    """Create, describe, update, list, and delete against the live API."""

    def test_create_then_get(self, live_client, agent_path_minimal, crud_agent_name):
        """A created agent is retrievable and carries its comment."""
        db, schema = _crud_db_schema(agent_path_minimal)
        created = live_client.agents.create(
            crud_agent_name,
            database=db,
            schema=schema,
            comment="cortex-agents-client live CRUD test",
            instructions=_SPEC_INSTRUCTIONS,
        )
        assert created.name.upper() == crud_agent_name.upper()

        fetched = live_client.agents.get(crud_agent_name, database=db, schema=schema)
        assert fetched.name.upper() == crud_agent_name.upper()
        assert fetched.instructions.response, (
            "Instructions did not round-trip through create; "
            f"got {fetched.instructions!r}"
        )

    def test_update_changes_the_spec(
        self, live_client, agent_path_minimal, crud_agent_name
    ):
        """An update is persisted and visible on a subsequent describe."""
        db, schema = _crud_db_schema(agent_path_minimal)
        live_client.agents.create(
            crud_agent_name,
            database=db,
            schema=schema,
            comment="before",
            instructions=_SPEC_INSTRUCTIONS,
        )

        live_client.agents.update(
            crud_agent_name,
            database=db,
            schema=schema,
            comment="after",
            instructions={"response": "Reply with exactly one word."},
        )

        fetched = live_client.agents.get(crud_agent_name, database=db, schema=schema)
        assert "one word" in fetched.instructions.response.lower(), (
            f"Update did not persist; instructions are {fetched.instructions.response!r}"
        )

    def test_list_finds_the_agent_with_like_filter(
        self, live_client, agent_path_minimal, crud_agent_name
    ):
        """The like filter is applied server-side and matches the new agent."""
        db, schema = _crud_db_schema(agent_path_minimal)
        live_client.agents.create(
            crud_agent_name,
            database=db,
            schema=schema,
            instructions=_SPEC_INSTRUCTIONS,
        )

        results = live_client.agents.list(
            database=db, schema=schema, like=f"{crud_agent_name}%"
        )
        names = {a.name.upper() for a in results}
        assert crud_agent_name.upper() in names, (
            f"like filter did not return the agent; got {sorted(names)}"
        )

    def test_delete_removes_the_agent(
        self, live_client, agent_path_minimal, crud_agent_name
    ):
        """After delete, describe raises AgentNotFoundError."""
        db, schema = _crud_db_schema(agent_path_minimal)
        live_client.agents.create(
            crud_agent_name,
            database=db,
            schema=schema,
            instructions=_SPEC_INSTRUCTIONS,
        )
        live_client.agents.delete(crud_agent_name, database=db, schema=schema)

        with pytest.raises(AgentNotFoundError):
            live_client.agents.get(crud_agent_name, database=db, schema=schema)


class TestCreateMode:
    """The createMode query parameter."""

    def test_create_twice_raises_by_default(
        self, live_client, agent_path_minimal, crud_agent_name
    ):
        """errorIfExists (the default) rejects a duplicate name."""
        db, schema = _crud_db_schema(agent_path_minimal)
        live_client.agents.create(
            crud_agent_name,
            database=db,
            schema=schema,
            instructions=_SPEC_INSTRUCTIONS,
        )
        with pytest.raises(CortexAgentError):
            live_client.agents.create(
                crud_agent_name,
                database=db,
                schema=schema,
                instructions=_SPEC_INSTRUCTIONS,
            )

    def test_or_replace_succeeds_on_existing(
        self, live_client, agent_path_minimal, crud_agent_name
    ):
        """orReplace overwrites an existing agent instead of failing."""
        db, schema = _crud_db_schema(agent_path_minimal)
        live_client.agents.create(
            crud_agent_name,
            database=db,
            schema=schema,
            comment="first",
            instructions=_SPEC_INSTRUCTIONS,
        )
        replaced = live_client.agents.create(
            crud_agent_name,
            database=db,
            schema=schema,
            comment="replaced",
            instructions={"response": "Reply with exactly one word."},
            create_mode="orReplace",
        )
        assert replaced.name.upper() == crud_agent_name.upper()


class TestDeleteIfExists:
    """The ifExists query parameter."""

    def test_delete_missing_with_if_exists_succeeds(
        self, live_client, agent_path_minimal
    ):
        """ifExists=true is a no-op for an agent that does not exist."""
        db, schema = _crud_db_schema(agent_path_minimal)
        missing = f"cac_live_crud_absent_{uuid.uuid4().hex[:8]}"
        live_client.agents.delete(missing, database=db, schema=schema, if_exists=True)

    def test_delete_missing_without_if_exists_raises(
        self, live_client, agent_path_minimal
    ):
        """ifExists=false surfaces the missing agent as an error."""
        db, schema = _crud_db_schema(agent_path_minimal)
        missing = f"cac_live_crud_absent_{uuid.uuid4().hex[:8]}"
        with pytest.raises(CortexAgentError):
            live_client.agents.delete(
                missing, database=db, schema=schema, if_exists=False
            )


class TestFeedback:
    """Feedback submission, including the request-level form."""

    def test_agent_level_feedback_accepted(self, live_client, agent_path_minimal):
        """Feedback without a request_id is accepted for the agent."""
        db, schema, name = agent_path_minimal.split(".")
        live_client.agents.feedback(
            name,
            database=db,
            schema=schema,
            positive=True,
            feedback_message="cortex-agents-client live test (agent level)",
        )

    def test_request_level_feedback_accepted(
        self, live_client, agent_path_minimal, live_thread
    ):
        """Feedback tied to a real run's request_id is accepted.

        Request-level feedback cannot be verified any other way: the
        request_id has to come from an actual run.
        """
        db, schema, name = agent_path_minimal.split(".")
        result = live_client.runs.run(
            [{"role": "user", "content": [{"type": "text", "text": "Say hello."}]}],
            agent_path=agent_path_minimal,
            thread_id=live_thread.thread_id,
            parent_message_id=0,
        )
        request_id = result.error.request_id if result.error else None
        if not request_id:
            # The run succeeded, so pull the request id from the thread message.
            messages = live_client.threads.list_messages(live_thread.thread_id)
            request_id = next(
                (m.request_id for m in reversed(messages) if m.request_id), None
            )
        if not request_id:
            pytest.skip("No request_id available from the run or thread messages")

        live_client.agents.feedback(
            name,
            database=db,
            schema=schema,
            positive=True,
            request_id=request_id,
            thread_id=live_thread.thread_id,
            feedback_message="cortex-agents-client live test (request level)",
            categories=["accuracy"],
        )
