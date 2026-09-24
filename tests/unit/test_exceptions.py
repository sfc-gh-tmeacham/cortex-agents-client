"""Tests for exception hierarchy and deprecated aliases."""
from __future__ import annotations

import pytest

from cortex_agents_client.exceptions import (
    AgentNotFoundError,
    AuthError,
    ConflictError,
    CortexAgentError,
    CortexPermissionError,
    CortexTimeoutError,
    NotFoundError,
    RateLimitError,
    RunError,
    RunNotActiveError,
    ServerError,
    ThreadNotFoundError,
)


class TestExceptionHierarchy:
    """Tests for exception class inheritance chains."""

    def test_agent_not_found_is_not_found_error(self):
        """AgentNotFoundError is catchable as NotFoundError."""
        exc = AgentNotFoundError("agent missing")
        assert isinstance(exc, NotFoundError)
        assert isinstance(exc, CortexAgentError)

    def test_thread_not_found_is_not_found_error(self):
        """ThreadNotFoundError is catchable as NotFoundError."""
        exc = ThreadNotFoundError("thread missing")
        assert isinstance(exc, NotFoundError)
        assert isinstance(exc, CortexAgentError)

    def test_run_not_active_is_conflict_error(self):
        """RunNotActiveError is catchable as ConflictError."""
        exc = RunNotActiveError("run finished")
        assert isinstance(exc, ConflictError)
        assert isinstance(exc, CortexAgentError)

    def test_conflict_error_is_not_a_not_found_error(self):
        """409 and 404 hierarchies stay distinct."""
        exc = ConflictError("conflict")
        assert not isinstance(exc, NotFoundError)

    def test_cortex_permission_error_is_cortex_agent_error(self):
        """CortexPermissionError is catchable as CortexAgentError."""
        exc = CortexPermissionError("denied")
        assert isinstance(exc, CortexAgentError)

    def test_cortex_timeout_error_is_cortex_agent_error(self):
        """CortexTimeoutError is catchable as CortexAgentError."""
        exc = CortexTimeoutError("timed out")
        assert isinstance(exc, CortexAgentError)

    def test_auth_error_is_cortex_agent_error(self):
        assert isinstance(AuthError("bad token"), CortexAgentError)

    def test_rate_limit_error_is_cortex_agent_error(self):
        assert isinstance(RateLimitError("429"), CortexAgentError)

    def test_server_error_is_cortex_agent_error(self):
        assert isinstance(ServerError("500"), CortexAgentError)

    def test_run_error_is_cortex_agent_error(self):
        assert isinstance(RunError("run failed"), CortexAgentError)

    def test_not_found_catchall_catches_agent_variant(self):
        """Catching NotFoundError catches AgentNotFoundError."""
        with pytest.raises(NotFoundError):
            raise AgentNotFoundError("not found")

    def test_not_found_catchall_catches_thread_variant(self):
        """Catching NotFoundError catches ThreadNotFoundError."""
        with pytest.raises(NotFoundError):
            raise ThreadNotFoundError("not found")


class TestDeprecatedAliases:
    """Tests that deprecated exception aliases emit DeprecationWarning."""

    def test_permission_error_alias_emits_deprecation_warning(self):
        """Instantiating the old PermissionError alias warns about deprecation."""
        from cortex_agents_client.exceptions import PermissionError as _PE  # noqa: A001

        with pytest.warns(DeprecationWarning, match="CortexPermissionError"):
            exc = _PE("test")
        assert isinstance(exc, CortexPermissionError)

    def test_timeout_error_alias_emits_deprecation_warning(self):
        """Instantiating the old TimeoutError alias warns about deprecation."""
        from cortex_agents_client.exceptions import TimeoutError as _TE  # noqa: A001

        with pytest.warns(DeprecationWarning, match="CortexTimeoutError"):
            exc = _TE("test")
        assert isinstance(exc, CortexTimeoutError)


def test_deprecated_aliases_not_star_exported():
    """Star import must not shadow builtin PermissionError/TimeoutError."""
    import cortex_agents_client

    assert "PermissionError" not in cortex_agents_client.__all__
    assert "TimeoutError" not in cortex_agents_client.__all__
    # Still importable by name for existing callers.
    assert cortex_agents_client.PermissionError is not PermissionError
    assert cortex_agents_client.TimeoutError is not TimeoutError
