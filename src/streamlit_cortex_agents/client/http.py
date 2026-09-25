"""Low-level HTTP client wrapping httpx.

Provides authenticated request methods and a streaming context manager for
SSE (Server-Sent Events) responses. All HTTP errors are translated into
typed exceptions from :mod:`streamlit_cortex_agents.client.exceptions`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator, Iterator
from typing import Any

import httpx

from streamlit_cortex_agents.client.auth import AuthProvider
from streamlit_cortex_agents.client.exceptions import (
    AgentNotFoundError,
    AuthError,
    ConflictError,
    CortexAgentError,
    CortexConnectionError,
    CortexPermissionError,
    CortexTimeoutError,
    NotFoundError,
    RateLimitError,
    RunNotActiveError,
    ServerError,
    ThreadNotFoundError,
)

__all__ = ["HttpClient"]

def _raise_for_status(response: httpx.Response, *, resource: str = "resource") -> None:
    """Raises a typed exception for non-2xx HTTP responses.

    Args:
        response: The httpx response object to check.
        resource: Human-readable resource name for error messages
            (e.g. ``"agent"`` or ``"thread"``).

    Raises:
        AuthError: On HTTP 401.
        CortexPermissionError: On HTTP 403.
        AgentNotFoundError: On HTTP 404 when resource is ``"agent"``.
        ThreadNotFoundError: On HTTP 404 when resource is ``"thread"``.
        NotFoundError: On HTTP 404 for other resource types.
        RunNotActiveError: On HTTP 409 when resource is ``"run"``.
        ConflictError: On HTTP 409 for other resource types.
        RateLimitError: On HTTP 429.
        ServerError: On HTTP 5xx.
        CortexAgentError: On any other non-2xx status.
    """
    if response.is_success:
        return

    request_id = response.headers.get("X-Snowflake-Request-ID")
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("message"):
        message = body["message"]
    else:
        message = response.text or f"HTTP {response.status_code}"

    kwargs: dict[str, Any] = {
        "status_code": response.status_code,
        "request_id": request_id,
    }

    if response.status_code == 401:
        raise AuthError(f"Authentication failed: {message}", **kwargs)
    if response.status_code == 403:
        raise CortexPermissionError(f"Permission denied: {message}", **kwargs)
    if response.status_code == 404:
        if resource == "agent":
            raise AgentNotFoundError(f"Agent not found: {message}", **kwargs)
        if resource == "thread":
            raise ThreadNotFoundError(f"Thread not found: {message}", **kwargs)
        raise NotFoundError(f"Not found: {message}", **kwargs)
    if response.status_code == 409:
        if resource == "run":
            raise RunNotActiveError(
                f"Run is no longer active: {message}", **kwargs
            )
        raise ConflictError(f"Conflict: {message}", **kwargs)
    if response.status_code == 429:
        raise RateLimitError(f"Rate limit exceeded: {message}", **kwargs)
    if response.status_code >= 500:
        raise ServerError(f"Server error {response.status_code}: {message}", **kwargs)
    raise CortexAgentError(
        f"Unexpected HTTP {response.status_code}: {message}", **kwargs
    )


class HttpClient:
    """Authenticated HTTP client for the Cortex Agents REST API.

    Wraps :class:`httpx.Client` with automatic authentication headers,
    base URL construction, and typed error raising.

    Connection pooling is disabled — each request opens a fresh TCP
    connection — to prevent stale pooled connections from silently hanging
    in long-lived Streamlit sessions.

    Args:
        base_url: Full base URL including scheme and host
            (e.g. ``"https://myorg-myaccount.snowflakecomputing.com"``).
        auth: Authentication provider supplying request headers.
        timeout: Read timeout in seconds. Defaults to 120 (2 minutes).
            Controls the maximum silence between data chunks in an SSE
            stream. Connect, write, and pool timeouts use shorter fixed
            defaults.
        role: Optional Snowflake role to run requests under, sent as the
            ``X-Snowflake-Role`` header. Without it, requests run under the
            user's default role.

    Example::

        client = HttpClient(
            base_url="https://myorg.snowflakecomputing.com",
            auth=PATAuth("my_token"),
        )
        data = client.request("GET", "/api/v2/cortex/threads")
    """

    def __init__(
        self,
        base_url: str,
        auth: AuthProvider,
        timeout: float = 120.0,
        role: str | None = None,
    ) -> None:
        """Initialises the HTTP client.

        Args:
            base_url: Base URL for all requests.
            auth: Authentication provider.
            timeout: Read timeout in seconds — the maximum duration to wait
                for a chunk of data (e.g. an SSE event) to arrive. Other
                timeout phases use shorter defaults (connect=10s, write=30s,
                pool=5s). Pass a higher value for agents with known long
                processing times.
            role: Optional Snowflake role for the ``X-Snowflake-Role``
                header. Note that Cortex Agents derives tool permissions
                from the user's default role regardless of this header.
        """
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._timeout = timeout
        self._role = role
        self._timeout_config = httpx.Timeout(
            connect=10.0,
            read=timeout,
            write=30.0,
            pool=5.0,
        )
        self._client = httpx.Client(
            timeout=self._timeout_config,
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    def close(self) -> None:
        """Closes the underlying HTTP transport."""
        self._client.close()

    def _build_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Builds the complete request header dict.

        Args:
            extra: Additional headers to merge in. These take precedence
                over auth headers on conflict.

        Returns:
            Complete headers dict including auth and content type.
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **self._auth.headers(),
        }
        if self._role:
            headers["X-Snowflake-Role"] = self._role
        if extra:
            headers.update(extra)
        return headers

    def _url(self, path: str) -> str:
        """Constructs the full URL from a relative path.

        Args:
            path: Relative path starting with ``/``.

        Returns:
            Absolute URL string.
        """
        return f"{self._base_url}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        resource: str = "resource",
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Performs a synchronous HTTP request and returns the parsed JSON body.

        Args:
            method: HTTP method (``"GET"``, ``"POST"``, ``"PUT"``, ``"DELETE"``).
            path: API path (e.g. ``"/api/v2/cortex/threads"``).
            params: Optional query string parameters.
            json: Optional request body, serialised as JSON.
            resource: Resource type used to choose the right 404 exception
                (``"agent"``, ``"thread"``, ``"run"``, or ``"resource"``).
            headers: Optional extra headers, merged over the auth headers.

        Returns:
            Parsed JSON response body (dict, list, or primitive).

        Raises:
            AuthError: On HTTP 401.
            CortexPermissionError: On HTTP 403.
            AgentNotFoundError: On HTTP 404 for agents.
            ThreadNotFoundError: On HTTP 404 for threads.
            NotFoundError: On HTTP 404 for other resource types.
            RunNotActiveError: On HTTP 409 for runs.
            ConflictError: On HTTP 409 for other resource types.
            RateLimitError: On HTTP 429.
            ServerError: On HTTP 5xx.
            CortexTimeoutError: On request timeout.
            CortexAgentError: On connection or other HTTP errors.
        """
        try:
            response = self._client.request(
                method,
                self._url(path),
                headers=self._build_headers(headers),
                params=params,
                json=json,
            )
        except httpx.TimeoutException as exc:
            raise CortexTimeoutError(f"Request timed out after {self._timeout}s") from exc
        except httpx.ConnectError as exc:
            raise CortexConnectionError(f"Connection failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise CortexAgentError(f"HTTP error: {exc}") from exc

        _raise_for_status(response, resource=resource)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    @contextlib.contextmanager
    def stream(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        resource: str = "resource",
        headers: dict[str, str] | None = None,
    ) -> Generator[Iterator[str], None, None]:
        """Context manager that opens a streaming SSE connection.

        Yields an iterator of raw text lines from the response body.
        The connection is kept open until the context exits.

        Args:
            method: HTTP method (``"POST"`` for ``agent:run``, ``"GET"`` for
                reconnecting to an existing run).
            path: API path for the streaming endpoint.
            params: Optional query string parameters.
            json: Optional request body, serialised as JSON.
            resource: Resource type used to choose the right 404/409
                exception (``"agent"``, ``"thread"``, ``"run"``, or
                ``"resource"``).
            headers: Optional extra headers, merged over the auth headers.

        Yields:
            An iterator of raw line strings from the SSE stream.

        Raises:
            AuthError: On HTTP 401.
            CortexPermissionError: On HTTP 403.
            RunNotActiveError: On HTTP 409 when ``resource`` is ``"run"``.
            CortexTimeoutError: On request timeout.
            CortexAgentError: On connection or other HTTP errors.

        Example::

            with client.stream("POST", "/api/v2/cortex/agent:run", json=body) as lines:
                for event_type, payload in parse_sse_stream(lines):
                    ...
        """
        stream_headers = {"Accept": "text/event-stream"}
        if headers:
            stream_headers.update(headers)
        try:
            with self._client.stream(
                method,
                self._url(path),
                headers=self._build_headers(stream_headers),
                params=params,
                json=json,
            ) as response:
                if not response.is_success:
                    response.read()
                _raise_for_status(response, resource=resource)
                yield response.iter_lines()
        except httpx.TimeoutException as exc:
            raise CortexTimeoutError(f"Stream timed out after {self._timeout}s") from exc
        except httpx.ConnectError as exc:
            raise CortexConnectionError(f"Connection failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise CortexAgentError(f"Stream HTTP error: {exc}") from exc
