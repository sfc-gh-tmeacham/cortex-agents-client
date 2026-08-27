"""Live coverage for the Streamlit render pipeline via AppTest.

Everything in tests/streamlit/ mocks Streamlit with MagicMock, so the real
render path has never executed in a test. That is the gap the ``[DONE]``
sentinel defect fell through: a spurious ``UnknownEvent`` was handed to the
renderer on every single turn and no test noticed.

These tests drive the actual app script in apps/live_chat_app.py with
``streamlit.testing.v1.AppTest``, against a live agent, and assert on the
elements the renderer produces.

``default_timeout`` must be well above the AppTest default of a few seconds,
because each script run makes a real agent call.

Requires the environment described in tests/live/README.md. Always run with
LIVE_SKIP_TEARDOWN=1.
"""
from __future__ import annotations

import os
import pathlib

import pytest

pytestmark = pytest.mark.live

_APP = str(pathlib.Path(__file__).parent / "apps" / "live_chat_app.py")

# Each run performs a live agent call; the AppTest default is far too short.
_TIMEOUT = float(os.environ.get("LIVE_TIMEOUT", "180"))


def _app_test(agent_env: str | None = None):
    """Builds an AppTest for the live chat app.

    Args:
        agent_env: Optional agent path to point the app at, overriding
            ``LIVE_AGENT_MINIMAL`` via ``LIVE_APPTEST_AGENT``.

    Returns:
        An unstarted ``AppTest`` instance.
    """
    from streamlit.testing.v1 import AppTest

    for required in ("SNOWFLAKE_ACCOUNT_URL", "SNOWFLAKE_PAT", "LIVE_AGENT_MINIMAL"):
        if not os.environ.get(required):
            pytest.skip(f"Environment variable {required!r} is not set")

    if agent_env:
        os.environ["LIVE_APPTEST_AGENT"] = agent_env
    else:
        os.environ.pop("LIVE_APPTEST_AGENT", None)

    return AppTest.from_file(_APP, default_timeout=_TIMEOUT)


def _assert_no_error_surface(at) -> None:
    """Fails if the app rendered an error or exception surface.

    Args:
        at: A run AppTest instance.
    """
    assert not at.exception, f"App raised: {[e.value for e in at.exception]}"
    assert not at.error, f"App rendered st.error: {[e.value for e in at.error]}"


class TestAppLoads:
    """The app script runs without error before any input."""

    def test_initial_render_succeeds(self):
        """Loading the app creates a thread and renders without raising."""
        at = _app_test()
        at.run()
        _assert_no_error_surface(at)

    def test_chat_input_is_present(self):
        """The chat input widget exists, so a turn can be driven."""
        at = _app_test()
        at.run()
        assert len(at.chat_input) >= 1, "No chat_input widget rendered"


class TestLiveTurn:
    """A full turn through the real render pipeline."""

    def test_turn_renders_assistant_text(self):
        """Submitting a message renders non-empty assistant markdown."""
        at = _app_test()
        at.run()
        at.chat_input[0].set_value("Name one primary colour.").run()
        _assert_no_error_surface(at)

        markdown_values = [m.value for m in at.markdown if m.value and m.value.strip()]
        assert markdown_values, (
            "No markdown rendered after a turn. "
            f"Elements present: {sorted({type(e).__name__ for e in at.main})}"
        )

    def test_turn_renders_no_parse_error_text(self):
        """No internal parse-error artefact leaks into the rendered output.

        This is the assertion that covers the ``[DONE]`` class of defect: an
        unhandled terminal marker became an ``UnknownEvent`` with
        ``event_type='_parse_error'``, which a renderer could surface.
        """
        at = _app_test()
        at.run()
        at.chat_input[0].set_value("Say hello.").run()
        _assert_no_error_surface(at)

        rendered = " ".join(m.value for m in at.markdown if m.value)
        for artefact in ("_parse_error", "UnknownEvent", "[DONE]"):
            assert artefact not in rendered, (
                f"Internal artefact {artefact!r} leaked into rendered output"
            )

    def test_second_turn_replays_history(self):
        """A second turn keeps the first, exercising render_stored_message.

        History replay is a different code path from live streaming and is
        otherwise only mock-tested.
        """
        at = _app_test()
        at.run()
        at.chat_input[0].set_value("Say the word apple.").run()
        _assert_no_error_surface(at)
        after_first = len([m for m in at.markdown if m.value and m.value.strip()])

        at.chat_input[0].set_value("Say the word banana.").run()
        _assert_no_error_surface(at)
        after_second = len([m for m in at.markdown if m.value and m.value.strip()])

        assert after_second > after_first, (
            f"Second turn did not add rendered content ({after_first} -> "
            f"{after_second}); history may not be replaying"
        )


class TestAnalystTableRendering:
    """Table rendering depends on real result_set payload shape."""

    def test_analyst_turn_renders_dataframe(self):
        """An Analyst answer renders a dataframe via result_set_to_dataframe."""
        agent = os.environ.get("LIVE_AGENT_ANALYST")
        if not agent:
            pytest.skip("LIVE_AGENT_ANALYST is not set")

        at = _app_test(agent_env=agent)
        at.run()
        at.chat_input[0].set_value("What is total revenue by region?").run()
        _assert_no_error_surface(at)

        assert len(at.dataframe) >= 1, (
            "No dataframe rendered for an Analyst answer. Markdown seen: "
            f"{[m.value[:80] for m in at.markdown if m.value][:3]}"
        )
