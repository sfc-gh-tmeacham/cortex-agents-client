"""Fixtures for live integration tests.

Requires the following environment variables:
  SNOWFLAKE_ACCOUNT_URL  — https://myorg-myaccount.snowflakecomputing.com
  SNOWFLAKE_PAT          — PAT token for a role with USAGE on both test agents
  LIVE_AGENT_MINIMAL     — fully-qualified path to the minimal (LLM-only) agent
  LIVE_AGENT_FULL        — (optional) fully-qualified path to the Cortex Search agent

Tests that need LIVE_AGENT_FULL are skipped automatically if that variable is absent.
All test threads are tagged with origin_application='cac_live' and deleted on teardown.
Any threads that leak (e.g. due to a keyboard interrupt) can be swept with:

    uv run python tests/live/seed/cleanup_leaked_threads.py

All Snowflake objects created by the seed scripts are dropped automatically when the
test session ends (via the session-scoped _teardown_live_objects fixture). To skip
teardown (e.g. for debugging), set LIVE_SKIP_TEARDOWN=1.

Set LIVE_DUMP_EVENTS=1 to always dump captured SSE events (not just on failure).
Set LIVE_TIMEOUT to raise the client read timeout in seconds (default 120) for
slow suites such as Cortex Analyst.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import time

import httpx
import pytest

from cortex_agents_client import CortexAgentsClient
from cortex_agents_client.client import Thread

# Tag applied to every thread created by live tests so leaked threads are
# easy to identify and clean up.
LIVE_ORIGIN_APP = "cac_live"

_TEARDOWN_SQL = pathlib.Path(__file__).parent / "seed" / "teardown.sql"


def _require_env(name: str) -> str:
    """Return the value of *name* or skip the test if it is unset."""
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"Environment variable {name!r} is not set")
    return value


def _live_timeout() -> float:
    """Returns the client read timeout for live tests.

    Cortex Analyst runs can take minutes when the warehouse is cold. Raise
    ``LIVE_TIMEOUT`` for those suites rather than editing this file.

    Returns:
        Read timeout in seconds. Defaults to 120.
    """
    return float(os.environ.get("LIVE_TIMEOUT", "120"))


def _run_teardown(account_url: str, pat: str) -> None:
    """Execute each DROP statement in teardown.sql via the SQL REST API."""
    statements = [
        line.strip().rstrip(";")
        for line in _TEARDOWN_SQL.read_text().splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {pat}",
        "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
    }
    with httpx.Client(timeout=60.0) as client:
        for stmt in statements:
            try:
                resp = client.post(
                    f"{account_url}/api/v2/statements",
                    headers=headers,
                    json={"statement": stmt, "timeout": 30},
                )
                if resp.status_code not in (200, 202):
                    # Non-fatal — object may not have been created if tests were skipped
                    pass
            except Exception:
                pass  # best-effort
            time.sleep(0.1)


# ---------------------------------------------------------------------------
# Session-scoped fixtures (created once per test run)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def live_client() -> CortexAgentsClient:
    """A CortexAgentsClient connected to the live test account."""
    url = _require_env("SNOWFLAKE_ACCOUNT_URL")
    pat = _require_env("SNOWFLAKE_PAT")
    # Extract database and schema from the minimal agent path (db.schema.agent)
    agent_path = _require_env("LIVE_AGENT_MINIMAL")
    parts = agent_path.split(".")
    db = parts[0] if len(parts) >= 3 else None
    schema = parts[1] if len(parts) >= 3 else None
    return CortexAgentsClient(
        url,
        pat,
        timeout=_live_timeout(),
        default_database=db,
        default_schema=schema,
    )


@pytest.fixture(scope="session")
def agent_path_minimal() -> str:
    """Fully-qualified path to the minimal (LLM-only) test agent."""
    return _require_env("LIVE_AGENT_MINIMAL")


@pytest.fixture(scope="session")
def agent_path_full() -> str:
    """Fully-qualified path to the full (Cortex Search) test agent.

    Tests using this fixture are skipped if LIVE_AGENT_FULL is not set.
    """
    return _require_env("LIVE_AGENT_FULL")


@pytest.fixture(scope="session")
def agent_path_analyst() -> str:
    """Fully-qualified path to the Cortex Analyst test agent.

    Tests using this fixture are skipped if LIVE_AGENT_ANALYST is not set.
    """
    return _require_env("LIVE_AGENT_ANALYST")


@pytest.fixture(scope="session")
def agent_path_web() -> str:
    """Fully-qualified path to the web search test agent.

    Tests using this fixture are skipped if LIVE_AGENT_WEB is not set.
    Requires web search to be enabled at the account level by an ACCOUNTADMIN.
    """
    return _require_env("LIVE_AGENT_WEB")


@pytest.fixture(scope="session")
def agent_path_multitenancy() -> str:
    """Fully-qualified path to the multi-tenancy test agent.

    Tests using this fixture are skipped if LIVE_AGENT_MULTITENANCY is not set.
    Requires the objects from seed/07_multitenancy.sql, including the row
    access policy on cac_mt_sales.
    """
    return _require_env("LIVE_AGENT_MULTITENANCY")


@pytest.fixture(scope="session", autouse=True)
def _teardown_live_objects() -> None:
    """Drops all cac_live Snowflake objects after the session ends.

    Runs the DROP statements in seed/teardown.sql via the SQL REST API.
    Set LIVE_SKIP_TEARDOWN=1 to disable (useful when debugging failures).
    """
    yield  # tests run here
    if os.environ.get("LIVE_SKIP_TEARDOWN"):
        return
    url = os.environ.get("SNOWFLAKE_ACCOUNT_URL")
    pat = os.environ.get("SNOWFLAKE_PAT")
    if url and pat:
        _run_teardown(url, pat)


# ---------------------------------------------------------------------------
# Function-scoped fixtures (created fresh for each test)
# ---------------------------------------------------------------------------

@pytest.fixture
def live_thread(live_client: CortexAgentsClient) -> Thread:
    """Creates a thread tagged 'cac_live'; deletes it on teardown (best-effort)."""
    thread = live_client.create_thread(origin_application=LIVE_ORIGIN_APP)
    yield thread
    try:
        live_client.threads.delete(thread.thread_id)
    except Exception:
        pass  # best-effort — cleanup_leaked_threads.py handles leaks


# ---------------------------------------------------------------------------
# SSE event capture (raw event recording for debugging)
# ---------------------------------------------------------------------------

_CAPTURES_DIR = pathlib.Path(__file__).parent / "captures"

# Collects events for the current test (reset per test via the fixture).
_current_test_events: list[dict] = []


def _serialize_event(event) -> dict:
    """Converts an SSEEvent to a JSON-serializable dict."""
    if dataclasses.is_dataclass(event) and not isinstance(event, type):
        d = dataclasses.asdict(event)
        d["_class"] = type(event).__name__
        return d
    return {"_class": type(event).__name__, "repr": repr(event)}


@pytest.fixture(autouse=True)
def _capture_events(request, monkeypatch):
    """Monkey-patches Thread.chat to capture all SSE events during a test.

    Events are stored in _current_test_events. On failure (or when
    LIVE_DUMP_EVENTS=1), they are written to tests/live/captures/<test_name>.json.
    """
    _current_test_events.clear()
    original_chat = Thread.chat

    def capturing_chat(self, *args, **kwargs):
        for event in original_chat(self, *args, **kwargs):
            _current_test_events.append(_serialize_event(event))
            yield event

    monkeypatch.setattr(Thread, "chat", capturing_chat)
    yield
    # monkeypatch reverts automatically


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Writes captured events to disk on test failure or when LIVE_DUMP_EVENTS=1."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    should_dump = (
        report.failed
        or os.environ.get("LIVE_DUMP_EVENTS") == "1"
    )
    if should_dump and _current_test_events:
        _CAPTURES_DIR.mkdir(exist_ok=True)
        filename = f"{item.nodeid.replace('/', '_').replace('::', '__')}.json"
        path = _CAPTURES_DIR / filename
        path.write_text(json.dumps(_current_test_events, indent=2, default=str))

