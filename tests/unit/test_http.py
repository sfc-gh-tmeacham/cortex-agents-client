"""Unit tests for the HttpClient transport layer."""
from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from cortex_agents_client.auth import PATAuth
from cortex_agents_client.exceptions import (
    AgentNotFoundError,
    AuthError,
    CortexAgentError,
    CortexConnectionError,
    CortexPermissionError,
    CortexTimeoutError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ThreadNotFoundError,
)
from cortex_agents_client.http import HttpClient

BASE_URL = "https://testorg.snowflakecomputing.com"
PAT = "v2:test_token"


@pytest.fixture
def http_client() -> HttpClient:
    return HttpClient(base_url=BASE_URL, auth=PATAuth(PAT), timeout=5.0)


class TestHeaderAssembly:
    """Verifies headers include auth, content-type, and accept."""

    def test_request_includes_auth_header(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"ok": True})
        http_client.request("GET", "/api/v2/test")
        request = httpx_mock.get_request()
        assert request.headers["Authorization"] == f"Bearer {PAT}"

    def test_request_includes_content_type(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"ok": True})
        http_client.request("GET", "/api/v2/test")
        request = httpx_mock.get_request()
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["Accept"] == "application/json"

    def test_stream_uses_event_stream_accept(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(text="event: done\ndata: {}\n\n")
        with http_client.stream("POST", "/api/v2/test", json={}) as lines:
            list(lines)
        request = httpx_mock.get_request()
        assert request.headers["Accept"] == "text/event-stream"


class TestErrorMapping:
    """Verifies HTTP status codes map to correct exception types."""

    @pytest.mark.parametrize(
        "status_code,resource,expected_exc",
        [
            (401, "resource", AuthError),
            (403, "resource", CortexPermissionError),
            (404, "agent", AgentNotFoundError),
            (404, "thread", ThreadNotFoundError),
            (404, "resource", NotFoundError),
            (429, "resource", RateLimitError),
            (500, "resource", ServerError),
            (502, "resource", ServerError),
            (503, "resource", ServerError),
            (418, "resource", CortexAgentError),
        ],
    )
    def test_status_code_raises_correct_exception(
        self, http_client, httpx_mock: HTTPXMock, status_code, resource, expected_exc
    ):
        httpx_mock.add_response(
            status_code=status_code,
            json={"message": "test error"},
            headers={"X-Snowflake-Request-ID": "req-123"},
        )
        with pytest.raises(expected_exc) as exc_info:
            http_client.request("GET", "/api/v2/test", resource=resource)
        assert exc_info.value.request_id == "req-123"

    def test_error_preserves_status_code(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=403, json={"message": "denied"})
        with pytest.raises(CortexPermissionError) as exc_info:
            http_client.request("GET", "/api/v2/test")
        assert exc_info.value.status_code == 403


class TestJsonParseFallback:
    """Verifies error handling when JSON response body is not parseable."""

    def test_non_json_error_body_uses_text(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            status_code=500,
            text="Internal Server Error",
            headers={"Content-Type": "text/plain"},
        )
        with pytest.raises(ServerError, match="Internal Server Error"):
            http_client.request("GET", "/api/v2/test")

    def test_empty_body_error_shows_status_code(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=500, text="")
        with pytest.raises(ServerError, match="HTTP 500"):
            http_client.request("GET", "/api/v2/test")


class TestConnectionErrors:
    """Verifies transport-level exceptions are wrapped correctly."""

    def test_timeout_raises_cortex_timeout(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
        with pytest.raises(CortexTimeoutError):
            http_client.request("GET", "/api/v2/test")

    def test_connect_error_raises_connection_error(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(httpx.ConnectError("refused"))
        with pytest.raises(CortexConnectionError):
            http_client.request("GET", "/api/v2/test")

    def test_generic_http_error_raises_agent_error(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(httpx.DecodingError("bad encoding"))
        with pytest.raises(CortexAgentError):
            http_client.request("GET", "/api/v2/test")


class TestSuccessResponses:
    """Verifies successful response handling."""

    def test_json_response_parsed(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"result": "ok"})
        data = http_client.request("GET", "/api/v2/test")
        assert data == {"result": "ok"}

    def test_204_returns_none(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=204)
        result = http_client.request("DELETE", "/api/v2/test")
        assert result is None

    def test_empty_body_returns_none(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=200, content=b"")
        result = http_client.request("GET", "/api/v2/test")
        assert result is None


class TestClose:
    """Verifies the close method works without error."""

    def test_close_does_not_raise(self, http_client):
        http_client.close()

    def test_close_idempotent(self, http_client):
        http_client.close()
        http_client.close()


class TestUrlConstruction:
    """Verifies full URL is built correctly from base_url and path."""

    def test_url_built_from_base_and_path(self, http_client, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={})
        http_client.request("GET", "/api/v2/cortex/threads")
        request = httpx_mock.get_request()
        assert str(request.url).startswith(f"{BASE_URL}/api/v2/cortex/threads")

    def test_trailing_slash_stripped_from_base(self, httpx_mock: HTTPXMock):
        client = HttpClient(base_url=f"{BASE_URL}/", auth=PATAuth(PAT))
        httpx_mock.add_response(json={})
        client.request("GET", "/api/v2/test")
        request = httpx_mock.get_request()
        assert "//" not in str(request.url).replace("https://", "")
        client.close()


class TestConnectionPooling:
    """Verifies connection pooling is disabled."""

    def test_no_keepalive_connections(self):
        client = HttpClient(base_url=BASE_URL, auth=PATAuth(PAT))
        pool = client._client._transport._pool
        assert pool._max_keepalive_connections == 0
        client.close()


class TestTimeoutConfiguration:
    """Verifies fine-grained timeout settings."""

    def test_default_read_timeout(self):
        client = HttpClient(base_url=BASE_URL, auth=PATAuth(PAT))
        assert client._timeout_config.read == 120.0
        assert client._timeout_config.connect == 10.0
        assert client._timeout_config.write == 30.0
        assert client._timeout_config.pool == 5.0
        client.close()

    def test_custom_timeout_sets_read(self):
        client = HttpClient(base_url=BASE_URL, auth=PATAuth(PAT), timeout=300.0)
        assert client._timeout_config.read == 300.0
        assert client._timeout_config.connect == 10.0
        client.close()

    def test_read_timeout_during_stream_raises_cortex_timeout(self, httpx_mock: HTTPXMock):
        client = HttpClient(base_url=BASE_URL, auth=PATAuth(PAT), timeout=5.0)
        httpx_mock.add_exception(httpx.ReadTimeout("read timed out"))
        with pytest.raises(CortexTimeoutError):
            with client.stream("POST", "/api/v2/test", json={}) as lines:
                list(lines)
        client.close()
