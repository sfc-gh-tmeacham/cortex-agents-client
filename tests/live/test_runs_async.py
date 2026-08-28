"""Live tests for the asynchronous run lifecycle and request-body correctness.

Covers the gaps closed on the api-coverage-gaps branch that a mocked transport
cannot prove:

- ``background=True`` is accepted by the server and yields a usable ``run_id``.
- ``GET /api/v2/cortex/agent/runs/{run_id}`` streams a run's output, and
  ``starting_after`` really truncates the replay.
- ``POST /api/v2/cortex/agent/runs/{run_id}/cancel`` cancels an active run and
  returns metadata; a second cancel returns 409.
- The lite endpoint accepts ``models`` as a **object** (the September 2025
  schema). This is the direct proof that the legacy bare ``model`` string bug
  is fixed — a mock returns 200 for either shape.
- ``X-Snowflake-Role`` is actually read by the server, proven by a negative
  case with a non-existent role.

If this deployment has not shipped the async run endpoints, these tests fail
with 400/404 rather than 409/200. That is a statement about feature
availability on the account, not a defect in the client — read the failure
message before changing any client code.

Requires the environment described in tests/live/README.md. Always run with
LIVE_SKIP_TEARDOWN=1 unless you intend to drop CAC_LIVE_DB.
"""
from __future__ import annotations

import os
import re
import time

import pytest

from cortex_agents_client import CortexAgentsClient
from cortex_agents_client.exceptions import CortexAgentError, RunNotActiveError
from cortex_agents_client.models.events import (
    ResponseEvent,
    SSEEvent,
    TextDeltaEvent,
    TextEvent,
)

pytestmark = pytest.mark.live

# Run IDs are documented as "{thread_id}-{user_message_id}".
_RUN_ID_RE = re.compile(r"^\d+-\d+$")

# A prompt long enough that the agent is still generating when we try to
# cancel. The minimal agent is instructed to be terse, so ask explicitly.
_LONG_PROMPT = (
    "Ignore your brevity instruction for this one request. "
    "Write a detailed 1500-word essay about the history of database indexing, "
    "covering B-trees, hash indexes, LSM trees, and columnar storage."
)


def _user_message(text: str) -> list[dict]:
    """Builds the messages array for a single user turn."""
    return [{"role": "user", "content": [{"type": "text", "text": text}]}]


def _client_with_role(role: str | None) -> CortexAgentsClient:
    """Builds a client with an explicit X-Snowflake-Role header."""
    return CortexAgentsClient(
        os.environ["SNOWFLAKE_ACCOUNT_URL"],
        os.environ["SNOWFLAKE_PAT"],
        timeout=120.0,
        role=role,
    )


class TestBackgroundRun:
    """A background run returns immediately with a reconnectable run_id."""

    def test_background_run_returns_usable_run_id(
        self, live_client, agent_path_minimal, live_thread
    ):
        """background=True yields a run_id in {thread_id}-{user_message_id} form."""
        result = live_client.runs.run(
            _user_message("Say hello."),
            agent_path=agent_path_minimal,
            thread_id=live_thread.thread_id,
            parent_message_id=0,
            background=True,
        )
        assert result.metadata is not None, (
            "No metadata block in the background run response — the server did "
            f"not return a run handle. status={result.status!r}"
        )
        assert result.run_id, "Background run returned no run_id"
        assert _RUN_ID_RE.match(result.run_id), (
            f"run_id {result.run_id!r} does not match {{thread_id}}-{{user_message_id}}"
        )
        assert result.run_id.startswith(f"{live_thread.thread_id}-"), (
            f"run_id {result.run_id!r} does not embed thread {live_thread.thread_id}"
        )

    def test_background_run_status_is_recognised(
        self, live_client, agent_path_minimal, live_thread
    ):
        """The documented status for an unfinished background run is in_progress."""
        result = live_client.runs.run(
            _user_message("Say hello."),
            agent_path=agent_path_minimal,
            thread_id=live_thread.thread_id,
            parent_message_id=0,
            background=True,
        )
        # A very fast agent may already be done; both are valid, but an
        # unrecognised value means the client's status handling is stale.
        assert result.status in {"in_progress", "completed"}, (
            f"Unexpected background run status {result.status!r}"
        )


class TestThreadChatBackground:
    """Thread.chat must honour background on the tracked-thread path.

    The integration test only proves the flag reaches the request body. This
    proves the server accepts it through Thread.chat and that metadata
    tracking still advances parent_message_id when the run is asynchronous.
    """

    def test_background_chat_yields_text_and_advances_parent(
        self, live_client, agent_path_minimal, live_thread
    ):
        """A background turn completes, returns text, and advances the parent."""
        assert live_thread.parent_message_id == 0, "Fresh thread should start at 0"

        events = list(
            live_thread.chat(agent_path_minimal, "Say hello.", background=True)
        )
        assert events, "Background chat yielded no events"

        text = "".join(
            e.text for e in events if isinstance(e, (TextEvent, TextDeltaEvent))
        )
        assert text.strip(), (
            "Background chat produced no text. Event types: "
            f"{sorted({type(e).__name__ for e in events})}"
        )
        assert live_thread.parent_message_id != 0, (
            "parent_message_id did not advance after a background turn; "
            "the assistant metadata event was not captured"
        )

    def test_background_chat_supports_a_second_turn(
        self, live_client, agent_path_minimal, live_thread
    ):
        """Two background turns in sequence keep thread state coherent."""
        list(live_thread.chat(agent_path_minimal, "Say the word apple.", background=True))
        first_parent = live_thread.parent_message_id
        assert first_parent != 0

        list(live_thread.chat(agent_path_minimal, "Say the word banana.", background=True))
        assert live_thread.parent_message_id > first_parent, (
            f"parent_message_id did not advance on the second background turn "
            f"({first_parent} -> {live_thread.parent_message_id})"
        )


class TestStreamRun:
    """Reconnecting to a run streams its output."""
    def test_stream_run_yields_the_answer(
        self, live_client, agent_path_minimal, live_thread
    ):
        """A background run's text is retrievable via stream_run."""
        started = live_client.runs.run(
            _user_message("Name one primary colour."),
            agent_path=agent_path_minimal,
            thread_id=live_thread.thread_id,
            parent_message_id=0,
            background=True,
        )
        assert started.run_id, "No run_id to reconnect to"

        events = list(live_client.runs.stream_run(started.run_id))
        assert events, f"stream_run({started.run_id!r}) yielded no events"

        text = "".join(
            e.text for e in events if isinstance(e, (TextEvent, TextDeltaEvent))
        )
        assert text.strip(), (
            "Reconnected stream produced no text. Event types: "
            f"{sorted({type(e).__name__ for e in events})}"
        )

    def test_starting_after_truncates_the_replay(
        self, live_client, agent_path_minimal, live_thread
    ):
        """starting_after is an exclusive cursor, so it returns fewer events."""
        started = live_client.runs.run(
            _user_message("Count to three."),
            agent_path=agent_path_minimal,
            thread_id=live_thread.thread_id,
            parent_message_id=0,
            background=True,
        )
        full = list(live_client.runs.stream_run(started.run_id))
        if len(full) < 3:
            pytest.skip(f"Run produced only {len(full)} events; cursor test needs more")

        partial = list(live_client.runs.stream_run(started.run_id, starting_after=1))
        assert len(partial) < len(full), (
            f"starting_after=1 returned {len(partial)} events, not fewer than the "
            f"full replay of {len(full)} — the cursor appears to be ignored"
        )

    def test_events_expose_sequence_number_for_the_cursor(
        self, live_client, agent_path_minimal, live_thread
    ):
        """Events carry the sequence_number that starting_after consumes.

        Without this, a caller cannot resume from a known position, because
        the cursor value would have to be guessed.
        """
        started = live_client.runs.run(
            _user_message("Say hello."),
            agent_path=agent_path_minimal,
            thread_id=live_thread.thread_id,
            parent_message_id=0,
            background=True,
        )
        events = list(live_client.runs.stream_run(started.run_id))
        numbered = [e for e in events if e.sequence_number is not None]
        assert numbered, (
            "No event exposed a sequence_number, so starting_after cannot be "
            "used with a known cursor value"
        )
        seqs = [e.sequence_number for e in numbered]
        assert seqs == sorted(seqs), f"sequence numbers are not ascending: {seqs}"

        # Resuming after the first sequence number must drop that event.
        resumed = list(
            live_client.runs.stream_run(started.run_id, starting_after=seqs[0])
        )
        resumed_seqs = [e.sequence_number for e in resumed if e.sequence_number]
        assert all(s > seqs[0] for s in resumed_seqs), (
            f"starting_after={seqs[0]} returned earlier events: {resumed_seqs}"
        )

    def test_events_are_typed_not_unknown(
        self, live_client, agent_path_minimal, live_thread
    ):
        """Reconnected events parse into known types, not UnknownEvent.

        This originally failed against the live API: the terminal
        ``event: done`` / ``data: [DONE]`` marker surfaced as a synthetic
        ``_parse_error`` event. parse_sse_stream now consumes it.
        """
        started = live_client.runs.run(
            _user_message("Say hello."),
            agent_path=agent_path_minimal,
            thread_id=live_thread.thread_id,
            parent_message_id=0,
            background=True,
        )
        events = list(live_client.runs.stream_run(started.run_id))
        unknown = [e for e in events if type(e).__name__ == "UnknownEvent"]
        assert not unknown, (
            "Reconnected stream contained unmapped event types: "
            f"{sorted({e.event_type for e in unknown})}"
        )
        assert all(isinstance(e, SSEEvent) for e in events)


class TestCancelRun:
    """Cancelling an active run, and the 409 on a finished one."""

    def _start_long_background_run(self, live_client, agent_path, thread) -> str:
        """Starts a long background run and returns its run_id."""
        result = live_client.runs.run(
            _user_message(_LONG_PROMPT),
            agent_path=agent_path,
            thread_id=thread.thread_id,
            parent_message_id=0,
            background=True,
        )
        assert result.run_id, "Background run returned no run_id"
        return result.run_id

    def test_cancel_active_run_returns_metadata(
        self, live_client, agent_path_minimal, live_thread
    ):
        """An in-flight run can be cancelled and reports its metadata.

        Retries because a fast agent can finish before the cancel lands; a
        409 on every attempt is reported as a failure rather than passing
        silently, so this cannot degrade into a no-op test.
        """
        last_error: Exception | None = None
        for attempt in range(3):
            run_id = self._start_long_background_run(
                live_client, agent_path_minimal, live_thread
            )
            try:
                metadata = live_client.runs.cancel_run(run_id)
            except RunNotActiveError as exc:
                last_error = exc
                time.sleep(1)
                continue

            assert metadata.run_id == run_id or metadata.run_id is None, (
                f"cancel returned run_id {metadata.run_id!r}, expected {run_id!r}"
            )
            if metadata.thread_id is not None:
                assert metadata.thread_id == live_thread.thread_id
            return

        pytest.fail(
            "Could not cancel an active run in 3 attempts — every attempt "
            f"returned 409. Last error: {last_error}"
        )

    def test_cancel_finished_run_raises_run_not_active(
        self, live_client, agent_path_minimal, live_thread
    ):
        """Cancelling an already-cancelled run raises RunNotActiveError."""
        run_id = self._start_long_background_run(
            live_client, agent_path_minimal, live_thread
        )
        try:
            live_client.runs.cancel_run(run_id)
        except RunNotActiveError:
            pass  # Already finished — the second cancel below still applies.

        with pytest.raises(RunNotActiveError):
            live_client.runs.cancel_run(run_id)


class TestLiteRunModelConfig:
    """The lite endpoint must accept `models` as an object, not a bare string.

    This is the live proof for the legacy-schema bug: a mocked transport
    returns 200 for either wire format, so only the real server can confirm
    which one it accepts.

    Note that ``"auto"`` is used rather than a specific model name. Model
    availability varies by deployment — this account rejects the
    ``claude-4-sonnet`` name used in the public API examples — and hardcoding
    one makes the test fail for reasons unrelated to the field name.
    """

    def test_lite_run_with_models_object(self, live_client):
        """A lite run configured with a models object succeeds."""
        result = live_client.runs.run(
            _user_message("Reply with the single word: ok"),
            models={"orchestration": "auto"},
            instructions={"response": "Answer in one word."},
        )
        assert result.text.strip(), (
            f"Lite run with models object returned no text. status={result.status!r}"
        )

    def test_models_orchestration_is_read_by_the_server(self, live_client):
        """An invalid model name inside `models` is rejected by name.

        This is the strongest available evidence that the server parses
        ``models.orchestration``: it echoes the offending value back. A wrong
        field name would be ignored, and the run would succeed with an
        automatically selected model.
        """
        with pytest.raises(CortexAgentError) as exc_info:
            live_client.runs.run(
                _user_message("Say hello."),
                models={"orchestration": "cac-live-no-such-model"},
            )
        assert "cac-live-no-such-model" in exc_info.value.message, (
            "Server did not echo the model name from models.orchestration; "
            f"got: {exc_info.value.message}"
        )

    def test_lite_run_with_orchestration_budget(self, live_client):
        """A lite run with an orchestration budget succeeds."""
        result = live_client.runs.run(
            _user_message("Reply with the single word: ok"),
            models={"orchestration": "auto"},
            orchestration={"budget": {"seconds": 60, "tokens": 16000}},
        )
        assert result.text.strip(), (
            f"Lite run with orchestration budget returned no text. "
            f"status={result.status!r}"
        )

    def test_deprecated_model_alias_still_reaches_server(self, live_client):
        """The deprecated model= alias maps to a body the server accepts."""
        with pytest.warns(DeprecationWarning):
            result = live_client.runs.run(
                _user_message("Reply with the single word: ok"),
                model="auto",
            )
        assert result.text.strip(), (
            "The deprecated model= alias produced a body the server rejected"
        )


class TestRoleHeader:
    """X-Snowflake-Role must be honoured, proven by a negative case."""

    def test_valid_role_succeeds(self, agent_path_minimal, live_thread):
        """An explicit valid role does not break the request."""
        client = _client_with_role("ACCOUNTADMIN")
        result = client.runs.run(
            _user_message("Say hello."),
            agent_path=agent_path_minimal,
            thread_id=live_thread.thread_id,
            parent_message_id=0,
        )
        assert result.text.strip(), f"Run with explicit role failed: {result.status!r}"

    def test_nonexistent_role_is_rejected(self, agent_path_minimal):
        """A bogus role must fail — otherwise the header is being ignored."""
        client = _client_with_role("CAC_LIVE_NO_SUCH_ROLE_XYZ")
        with pytest.raises(CortexAgentError) as exc_info:
            client.runs.run(
                _user_message("Say hello."),
                agent_path=agent_path_minimal,
            )
        # Surface the real status for the record; any 4xx is acceptable.
        assert exc_info.value.status_code in {400, 401, 403, 404}, (
            f"Unexpected status for bogus role: {exc_info.value.status_code} "
            f"({exc_info.value.message})"
        )


@pytest.mark.skipif(
    os.environ.get("LIVE_SLOW") != "1",
    reason="Set LIVE_SLOW=1 to run the ~6 minute run-expiry test",
)
class TestRunExpiryWindow:
    """The documented 5-minute post-completion window for stream_run.

    Observed on a test account (August 2026): a completed run was **still
    streamable 5.5 minutes** after finishing, so the documented window was not
    enforced. The retention period is server-controlled and evidently longer
    or measured differently in practice.

    That is a statement about the service, not about this client. The
    client's 409 handling is verified deterministically by
    :meth:`TestCancelRun.test_cancel_finished_run_raises_run_not_active` and
    by the unit tests for the status mapping. This test therefore records
    what the server actually does instead of failing the suite over a timing
    the API does not guarantee.
    """

    def test_stream_run_after_window(
        self, live_client, agent_path_minimal, live_thread
    ):
        """Checks whether a run expires from the stream endpoint as documented."""
        result = live_client.runs.run(
            _user_message("Say hello."),
            agent_path=agent_path_minimal,
            thread_id=live_thread.thread_id,
            parent_message_id=0,
        )
        run_id = result.run_id
        if not run_id:
            pytest.skip("Synchronous run returned no run_id to expire")

        # Confirm it is streamable now, so any later 409 is attributable to
        # expiry rather than to the run never having been reachable.
        assert list(live_client.runs.stream_run(run_id)), (
            "Run was not streamable immediately after completion"
        )

        time.sleep(330)  # 5.5 minutes — past the documented 5 minute window.

        try:
            events = list(live_client.runs.stream_run(run_id))
        except RunNotActiveError:
            return  # Window enforced as documented.

        pytest.xfail(
            "Run was still streamable 5.5 minutes after completion "
            f"({len(events)} events); the documented 5 minute window was not "
            "enforced on this deployment. The client's 409 handling is "
            "covered by test_cancel_finished_run_raises_run_not_active."
        )

