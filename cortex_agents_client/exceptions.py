"""Custom exceptions for the Cortex Agents library."""

from __future__ import annotations


class CortexAgentError(Exception):
    """Base exception for all Cortex Agents errors.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code if the error originated from an API call.
        request_id: Snowflake request ID from the response headers, if available.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        """Initialises the error.

        Args:
            message: Human-readable description of what went wrong.
            status_code: HTTP status code from the API response, if applicable.
            request_id: Snowflake request ID for tracing, if available.
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.request_id = request_id


class AuthError(CortexAgentError):
    """Raised when authentication fails (HTTP 401).

    Typically means the token is invalid, expired, or missing.
    """


class PermissionError(CortexAgentError):  # noqa: A001
    """Raised when the caller lacks the required privilege (HTTP 403)."""


class RateLimitError(CortexAgentError):
    """Raised when the API rate limit is exceeded (HTTP 429)."""


class ServerError(CortexAgentError):
    """Raised on unexpected server errors (HTTP 5xx)."""


class TimeoutError(CortexAgentError):  # noqa: A001
    """Raised when a request exceeds the configured timeout."""


class AgentNotFoundError(CortexAgentError):
    """Raised when the specified agent does not exist (HTTP 404)."""


class ThreadNotFoundError(CortexAgentError):
    """Raised when the specified thread does not exist (HTTP 404)."""


class RunError(CortexAgentError):
    """Raised when an agent run terminates with a fatal error event.

    Attributes:
        code: Snowflake error code from the error SSE event.
        request_id: Request ID from the error SSE event.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Initialises the run error.

        Args:
            message: Error message from the agent.
            code: Snowflake error code string.
            request_id: Request ID for tracing.
        """
        super().__init__(message, request_id=request_id)
        self.code = code
