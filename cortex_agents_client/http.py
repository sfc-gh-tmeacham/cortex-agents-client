"""Low-level HTTP client wrapping httpx.

Provides authenticated request methods and a streaming context manager for
SSE (Server-Sent Events) responses. All HTTP errors are translated into
typed exceptions from :mod:`cortex_agents_client.exceptions`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator, Iterator
from typing import Any

import httpx

from cortex_agents_client.auth import AuthProvider
from cortex_agents_client.exceptions import (
    AgentNotFoundError,
    AuthError,
    CortexAgentError,
    CortexPermissionError,
    CortexTimeoutError,
    NotFoundError,
    RateLimitError,
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
        RateLimitError: On HTTP 429.
        ServerError: On HTTP 5xx.
        CortexAgentError: On any other non-2xx status.
    """
    if response.is_success:
        return

    request_id = response.headers.get("X-Snowflake-Request-ID")
    try:
        body = response.json()
        message = body.get("message", response.text)
    except Exception:
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

    Args:
        base_url: Full base URL including scheme and host
            (e.g. ``"https://myorg-myaccount.snowflakecomputing.com"``).
        auth: Authentication provider supplying request headers.
        timeout: Request timeout in seconds. Defaults to 900 (15 minutes),
            matching the API's maximum allowed duration.

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
        timeout: float = 900.0,
    ) -> None:
        """Initialises the HTTP client.

        Args:
            base_url: Base URL for all requests.
            auth: Authentication provider.
            timeout: Request timeout in seconds.
        """
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._timeout = timeout

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
    ) -> Any:
        """Performs a synchronous HTTP request and returns the parsed JSON body.

        Args:
            method: HTTP method (``"GET"``, ``"POST"``, ``"PUT"``, ``"DELETE"``).
            path: API path (e.g. ``"/api/v2/cortex/threads"``).
            params: Optional query string parameters.
            json: Optional request body, serialised as JSON.
            resource: Resource type used to choose the right 404 exception
                (``"agent"``, ``"thread"``, or ``"resource"``).

        Returns:
            Parsed JSON response body (dict, list, or primitive).

        Raises:
            AuthError: On HTTP 401.
            CortexPermissionError: On HTTP 403.
            AgentNotFoundError: On HTTP 404 for agents.
            ThreadNotFoundError: On HTTP 404 for threads.
            NotFoundError: On HTTP 404 for other resource types.
            RateLimitError: On HTTP 429.
            ServerError: On HTTP 5xx.
            CortexTimeoutError: On request timeout.
            CortexAgentError: On connection or other HTTP errors.
        """
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.request(
                    method,
                    self._url(path),
                    headers=self._build_headers(),
                    params=params,
                    json=json,
                )
        except httpx.TimeoutException as exc:
            raise CortexTimeoutError(f"Request timed out after {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise CortexAgentError(f"HTTP error: {exc}") from exc

        _raise_for_status(response, resource=resource)
        return response.json()

    @contextlib.contextmanager
    def stream(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Generator[Iterator[str], None, None]:
        """Context manager that opens a streaming SSE connection.

        Yields an iterator of raw text lines from the response body.
        The connection is kept open until the context exits.

        Args:
            method: HTTP method (typically ``"POST"``).
            path: API path for the streaming endpoint.
            params: Optional query string parameters.
            json: Optional request body, serialised as JSON.

        Yields:
            An iterator of raw line strings from the SSE stream.

        Raises:
            AuthError: On HTTP 401.
            CortexPermissionError: On HTTP 403.
            CortexTimeoutError: On request timeout.
            CortexAgentError: On connection or other HTTP errors.

        Example::

            with client.stream("POST", "/api/v2/cortex/agent:run", json=body) as lines:
                for event_type, payload in parse_sse_stream(lines):
                    ...
        """
        headers = self._build_headers({"Accept": "text/event-stream"})
        try:
            with httpx.Client(timeout=self._timeout) as client:
                with client.stream(
                    method,
                    self._url(path),
                    headers=headers,
                    params=params,
                    json=json,
                ) as response:
                    if not response.is_success:
                        # Read the error body before accessing .text / .json()
                        # to avoid ResponseNotRead in streaming context.
                        response.read()
                    _raise_for_status(response)
                    yield response.iter_lines()
        except httpx.TimeoutException as exc:
            raise CortexTimeoutError(f"Stream timed out after {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise CortexAgentError(f"Stream HTTP error: {exc}") from exc
