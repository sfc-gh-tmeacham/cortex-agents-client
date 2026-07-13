"""Integration test fixtures using pytest-httpx."""
from __future__ import annotations

import json

import httpx
import pytest

from cortex_agents_client.client import CortexAgentsClient

ACCOUNT_URL = "https://testorg-testaccount.snowflakecomputing.com"
PAT_TOKEN = "v2:test_token_abc"


@pytest.fixture
def ca_client() -> CortexAgentsClient:
    """Returns a CortexAgentsClient for end-to-end resource testing."""
    return CortexAgentsClient(
        ACCOUNT_URL,
        PAT_TOKEN,
        timeout=30.0,
        default_database="TEST_DB",
        default_schema="TEST_SCHEMA",
    )


def make_sse_response(events: list[tuple[str, dict]]) -> str:
    """Builds an SSE response body string from a list of event tuples."""
    return "".join(
        f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
        for event_type, payload in events
    )


def make_json_response(data: dict | list, status_code: int = 200) -> httpx.Response:
    """Creates a mock httpx JSON response."""
    return httpx.Response(
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        json=data,
    )


def make_sse_httpx_response(events: list[tuple[str, dict]]) -> httpx.Response:
    """Creates a mock httpx SSE streaming response."""
    body = make_sse_response(events)
    return httpx.Response(
        status_code=200,
        headers={"Content-Type": "text/event-stream"},
        text=body,
    )

    """Builds an SSE response body string from a list of event tuples.

    Each event is terminated by a double newline (blank line separator)
    as required by the SSE specification.

    Args:
        events: List of (event_type, payload) tuples.

    Returns:
        SSE text body with proper formatting.
    """
    return "".join(
        f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
        for event_type, payload in events
    )


def make_json_response(data: dict | list, status_code: int = 200) -> httpx.Response:
    """Creates a mock httpx JSON response.

    Args:
        data: Response body dict or list.
        status_code: HTTP status code.

    Returns:
        An httpx.Response with JSON content.
    """
    return httpx.Response(
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        json=data,
    )


def make_sse_httpx_response(events: list[tuple[str, dict]]) -> httpx.Response:
    """Creates a mock httpx SSE streaming response.

    Args:
        events: List of (event_type, payload) tuples.

    Returns:
        An httpx.Response with text/event-stream content type.
    """
    body = make_sse_response(events)
    return httpx.Response(
        status_code=200,
        headers={"Content-Type": "text/event-stream"},
        text=body,
    )
