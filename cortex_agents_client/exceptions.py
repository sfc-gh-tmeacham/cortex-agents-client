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


class CortexPermissionError(CortexAgentError):
    """Raised when the caller lacks the required privilege (HTTP 403)."""


class RateLimitError(CortexAgentError):
    """Raised when the API rate limit is exceeded (HTTP 429)."""


class CortexTimeoutError(CortexAgentError):
    """Raised when a request exceeds the configured timeout.

    Triggered by a transport-level ``httpx.TimeoutException``, not an HTTP
    status code (there is no HTTP 408 equivalent in this API).
    """


class CortexConnectionError(CortexAgentError):
    """Raised when a network connection cannot be established.

    Covers DNS failures, connection refused, TLS errors, and mid-stream
    disconnects. Distinct from timeouts (:class:`CortexTimeoutError`) and
    server errors (:class:`ServerError`).
    """


class ServerError(CortexAgentError):
    """Raised on unexpected server errors (HTTP 5xx)."""


class NotFoundError(CortexAgentError):
    """Raised when a requested resource does not exist (HTTP 404).

    Use this as the catch-all for any not-found error::

        except NotFoundError:
            ...

    Specific subclasses (:class:`AgentNotFoundError`,
    :class:`ThreadNotFoundError`) are raised when the resource type is known.
    """


class AgentNotFoundError(NotFoundError):
    """Raised when the specified agent does not exist (HTTP 404)."""


class ThreadNotFoundError(NotFoundError):
    """Raised when the specified thread does not exist (HTTP 404)."""


class ConflictError(CortexAgentError):
    """Raised when a request conflicts with the current resource state (HTTP 409).

    Use this as the catch-all for any conflict error. The specific subclass
    :class:`RunNotActiveError` is raised when the resource type is known to
    be an agent run.
    """


class RunNotActiveError(ConflictError):
    """Raised when an agent run is no longer streamable or cancellable (HTTP 409).

    The events of an agent run are available only while the run is active and
    for up to 5 minutes after it completes. After that window, and for a run
    that has already completed or been cancelled, both
    :meth:`~cortex_agents_client.resources.runs.RunsResource.stream_run` and
    :meth:`~cortex_agents_client.resources.runs.RunsResource.cancel_run`
    raise this error. Retrieve the full response from the thread instead.
    """


class RunError(CortexAgentError):
    """Raised when an agent run terminates with a fatal error event.

    Triggered by a fatal ``error`` event in the SSE stream, not by an HTTP
    error status code. Raised by :meth:`~cortex_agents_client.RunsResource.run`
    and :meth:`~cortex_agents_client.RunsResource.stream_and_collect`.

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


# ---------------------------------------------------------------------------
# Deprecated aliases — use the Cortex-prefixed names instead
# ---------------------------------------------------------------------------

def _make_deprecated(new_cls: type, old_name: str) -> type:
    """Creates a subclass that emits a DeprecationWarning on instantiation."""
    import warnings

    class _Deprecated(new_cls):  # type: ignore[valid-type]
        def __init_subclass__(cls, **kwargs: object) -> None:
            super().__init_subclass__(**kwargs)

        def __init__(self, *args: object, **kwargs: object) -> None:
            warnings.warn(
                f"{old_name} is deprecated; use {new_cls.__name__} instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            super().__init__(*args, **kwargs)

    _Deprecated.__name__ = old_name
    _Deprecated.__qualname__ = old_name
    return _Deprecated


PermissionError = _make_deprecated(CortexPermissionError, "PermissionError")  # noqa: A001
TimeoutError    = _make_deprecated(CortexTimeoutError,    "TimeoutError")     # noqa: A001
