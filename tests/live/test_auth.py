"""Live tests: authentication and basic error paths.

These tests verify that PAT auth works end-to-end against a real Snowflake
account and that the correct exceptions are raised for bad credentials and
missing resources.  They use the minimal agent only (no tools required).
"""
from __future__ import annotations

import pytest

from cortex_agents_client import CortexAgentsClient
from cortex_agents_client.exceptions import AgentNotFoundError, AuthError


@pytest.mark.live
class TestPATAuth:
    """PAT authentication smoke tests."""

    def test_valid_pat_allows_agent_list(
        self,
        live_client: CortexAgentsClient,
    ) -> None:
        """A valid PAT should allow listing agents without raising."""
        agents = live_client.agents.list()
        assert isinstance(agents, list)

    def test_invalid_token_raises_auth_error(
        self,
        live_client: CortexAgentsClient,
    ) -> None:
        """A bad token should raise AuthError on the first API call."""
        import os

        bad_client = CortexAgentsClient(
            os.environ["SNOWFLAKE_ACCOUNT_URL"],
            "v2:this_is_not_a_valid_token",
            timeout=30.0,
        )
        with pytest.raises(AuthError):
            bad_client.agents.list()


@pytest.mark.live
class TestErrorPaths:
    """Error path tests — verify correct exceptions are raised."""

    def test_nonexistent_agent_raises_agent_not_found(
        self,
        live_client: CortexAgentsClient,
        live_thread,
    ) -> None:
        """Chatting with a non-existent agent path raises AgentNotFoundError."""
        with pytest.raises(AgentNotFoundError):
            # Consume the iterator to trigger the HTTP call
            list(live_thread.chat("DOES_NOT_EXIST_DB.DOES_NOT_EXIST_SCHEMA.DOES_NOT_EXIST_AGENT", "hello"))
