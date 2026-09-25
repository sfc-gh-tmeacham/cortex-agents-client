"""Unit tests for StreamlitChatbot — fullpage and embedded modes.

These tests verify:
- Constructor parameters are stored correctly.
- ``render()`` dispatches to the right rendering path.
- ``render()`` raises on invalid mode values.
- Embedded mode uses inline ``st.chat_input`` (Streamlit ≥ 1.59).
- Full-page mode uses ``st.chat_input`` and sidebar button.
- File/audio attachment parameters are stored correctly.

Streamlit and session helpers are mocked so no running Streamlit context
is required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cortex_agents_client.st.chatbot import StreamlitChatbot


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestStreamlitChatbotInit:
    """Verify __init__ stores all parameters correctly."""

    def test_defaults(self):
        bot = StreamlitChatbot(
            account_url="https://example.snowflakecomputing.com",
            auth="my_pat",
            agent_path="DB.SC.AGENT",
        )
        assert bot._account_url == "https://example.snowflakecomputing.com"
        assert bot._auth == "my_pat"
        assert bot._agent_path == "DB.SC.AGENT"
        assert bot._mode == "fullpage"
        assert bot._height == 450
        assert bot._show_thinking is True
        assert bot._show_tool_status is True
        assert bot._new_conversation_button is True
        assert bot._input_placeholder == "Ask a question..."
        assert bot._client_key == "_ca_client"
        assert bot._thread_key == "_ca_thread"
        assert bot._messages_key == "_ca_messages"
        assert bot._input_key == "_ca_input"
        assert bot._accept_file is False
        assert bot._accept_audio is False
        assert bot._file_type is None

    def test_embedded_mode_params_stored(self):
        bot = StreamlitChatbot(
            account_url="https://example.snowflakecomputing.com",
            auth="my_pat",
            agent_path="DB.SC.AGENT",
            mode="embedded",
            height=300,
            session_key_prefix="chat",
        )
        assert bot._mode == "embedded"
        assert bot._height == 300
        assert bot._client_key == "chat_client"
        assert bot._input_key == "chat_input"

    def test_session_key_prefix_propagates(self):
        bot = StreamlitChatbot(
            account_url="https://x.snowflakecomputing.com",
            auth="tok",
            agent_path="A.B.C",
            session_key_prefix="mybot",
        )
        assert bot._client_key == "mybot_client"
        assert bot._thread_key == "mybot_thread"
        assert bot._messages_key == "mybot_messages"
        assert bot._input_key == "mybot_input"

    def test_accept_file_params_stored(self):
        bot = StreamlitChatbot(
            account_url="https://x.snowflakecomputing.com",
            auth="tok",
            agent_path="A.B.C",
            accept_file="multiple",
            accept_audio=True,
            file_type=["pdf", "csv"],
        )
        assert bot._accept_file == "multiple"
        assert bot._accept_audio is True
        assert bot._file_type == ["pdf", "csv"]


# ---------------------------------------------------------------------------
# render() dispatch
# ---------------------------------------------------------------------------


class TestRenderDispatch:
    """Verify render() calls the correct private method based on mode."""

    def _make_bot(self, mode="fullpage") -> StreamlitChatbot:
        return StreamlitChatbot(
            account_url="https://x.snowflakecomputing.com",
            auth="tok",
            agent_path="A.B.C",
            mode=mode,
        )

    def test_fullpage_dispatches_to_render_fullpage(self):
        bot = self._make_bot("fullpage")
        with patch.object(bot, "_render_fullpage") as mock_fp, \
             patch.object(bot, "_render_embedded") as mock_em:
            bot.render()
            mock_fp.assert_called_once()
            mock_em.assert_not_called()

    def test_embedded_dispatches_to_render_embedded(self):
        bot = self._make_bot("embedded")
        with patch.object(bot, "_render_fullpage") as mock_fp, \
             patch.object(bot, "_render_embedded") as mock_em:
            bot.render()
            mock_em.assert_called_once()
            mock_fp.assert_not_called()

    def test_invalid_mode_raises_value_error(self):
        bot = StreamlitChatbot(
            account_url="https://x.snowflakecomputing.com",
            auth="tok",
            agent_path="A.B.C",
            mode="sidebar",  # type: ignore[arg-type]  — invalid value
        )
        with pytest.raises(ValueError, match="Invalid mode"):
            bot.render()


# ---------------------------------------------------------------------------
# Full-page rendering
# ---------------------------------------------------------------------------


def _mock_st():
    """Returns a MagicMock that acts as the ``streamlit`` module."""
    st = MagicMock()
    # __enter__/__exit__ for context managers (with st.sidebar:, etc.)
    st.sidebar.__enter__ = MagicMock(return_value=st.sidebar)
    st.sidebar.__exit__ = MagicMock(return_value=False)
    chat_msg = MagicMock()
    chat_msg.__enter__ = MagicMock(return_value=chat_msg)
    chat_msg.__exit__ = MagicMock(return_value=False)
    st.chat_message.return_value = chat_msg
    return st


class TestRenderFullpage:
    """Verify full-page rendering uses st.chat_input and sidebar button."""

    def _make_bot(self, **kw) -> StreamlitChatbot:
        return StreamlitChatbot(
            account_url="https://x.snowflakecomputing.com",
            auth="tok",
            agent_path="A.B.C",
            mode="fullpage",
            **kw,
        )

    def test_calls_chat_input(self):
        bot = self._make_bot()
        mock_thread = MagicMock()
        mock_st = _mock_st()
        mock_st.chat_input.return_value = None  # no input this run

        with patch("cortex_agents_client.st.chatbot.StreamlitChatbot._init") as mock_init, \
             patch("cortex_agents_client.st.chatbot.StreamlitChatbot._render_message_history"), \
             patch.dict("sys.modules", {"streamlit": mock_st}):
            mock_init.return_value = (mock_thread, MagicMock(), MagicMock(), MagicMock())
            bot._render_fullpage()

        mock_st.chat_input.assert_called_once()

    def test_no_sidebar_button_when_disabled(self):
        bot = self._make_bot(new_conversation_button=False)
        mock_thread = MagicMock()
        mock_st = _mock_st()
        mock_st.chat_input.return_value = None

        with patch("cortex_agents_client.st.chatbot.StreamlitChatbot._init") as mock_init, \
             patch("cortex_agents_client.st.chatbot.StreamlitChatbot._render_message_history"), \
             patch.dict("sys.modules", {"streamlit": mock_st}):
            mock_init.return_value = (mock_thread, MagicMock(), MagicMock(), MagicMock())
            bot._render_fullpage()

        # sidebar.button should never be called when new_conversation_button=False
        mock_st.sidebar.button.assert_not_called()

    def test_accept_file_passed_to_chat_input(self):
        bot = self._make_bot(accept_file="multiple", file_type=["pdf"])
        mock_st = _mock_st()
        mock_st.chat_input.return_value = None

        with patch("cortex_agents_client.st.chatbot.StreamlitChatbot._init") as mock_init, \
             patch("cortex_agents_client.st.chatbot.StreamlitChatbot._render_message_history"), \
             patch.dict("sys.modules", {"streamlit": mock_st}):
            mock_init.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock())
            bot._render_fullpage()

        call_kwargs = mock_st.chat_input.call_args.kwargs
        assert call_kwargs.get("accept_file") == "multiple"
        assert call_kwargs.get("file_type") == ["pdf"]


# ---------------------------------------------------------------------------
# Embedded rendering
# ---------------------------------------------------------------------------


class TestRenderEmbedded:
    """Verify embedded rendering uses inline st.chat_input (Streamlit ≥ 1.59)."""

    def _make_bot(self, **kw) -> StreamlitChatbot:
        return StreamlitChatbot(
            account_url="https://x.snowflakecomputing.com",
            auth="tok",
            agent_path="A.B.C",
            mode="embedded",
            height=300,
            **kw,
        )

    def _run_embedded(self, bot, mock_st, prompt=None):
        """Runs _render_embedded with mocked Streamlit and session helpers.

        Args:
            prompt: Return value for ``st.chat_input``. ``None`` means no
                user input this run; a string triggers ``_process_prompt``.

        Returns:
            The ``_process_prompt`` mock so callers can assert on it.
        """
        # Container context manager (chat area)
        container_ctx = MagicMock()
        container_ctx.__enter__ = MagicMock(return_value=container_ctx)
        container_ctx.__exit__ = MagicMock(return_value=False)
        mock_st.container.return_value = container_ctx

        mock_st.chat_input.return_value = prompt

        with patch("cortex_agents_client.st.chatbot.StreamlitChatbot._init") as mock_init, \
             patch("cortex_agents_client.st.chatbot.StreamlitChatbot._render_message_history"), \
             patch("cortex_agents_client.st.chatbot.StreamlitChatbot._process_prompt") as mock_proc, \
             patch.dict("sys.modules", {"streamlit": mock_st}):
            mock_init.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock())
            bot._render_embedded()
            return mock_proc

    def test_int_height_passed_to_container(self):
        """An int height goes straight to st.container with no injected CSS."""
        bot = self._make_bot()
        mock_st = _mock_st()
        self._run_embedded(bot, mock_st)
        mock_st.container.assert_any_call(height=300, autoscroll=True)
        assert not any(
            "chat-area" in str(c) for c in mock_st.html.call_args_list
        )

    def test_css_height_injects_scoped_style(self):
        """A string height keys the container and styles its wrapper."""
        bot = StreamlitChatbot(
            account_url="https://x.snowflakecomputing.com",
            auth="tok",
            agent_path="A.B.C",
            mode="embedded",
            height="calc(100vh - 300px)",
            session_key_prefix="_dlg",
        )
        mock_st = _mock_st()
        self._run_embedded(bot, mock_st)
        mock_st.container.assert_any_call(
            height=450, autoscroll=True, key="dlg-chat-area"
        )
        css = " ".join(str(c) for c in mock_st.html.call_args_list)
        assert ":has(> .st-key-dlg-chat-area)" in css
        assert "height:calc(100vh - 300px) !important" in css
        assert "flex-basis:calc(100vh - 300px) !important" in css

    def test_css_height_strips_rule_breakers(self):
        """Semicolons and braces cannot escape the injected rule."""
        bot = StreamlitChatbot(
            account_url="https://x.snowflakecomputing.com",
            auth="tok",
            agent_path="A.B.C",
            mode="embedded",
            height="80vh;} body{display:none",
        )
        mock_st = _mock_st()
        self._run_embedded(bot, mock_st)
        css = " ".join(str(c) for c in mock_st.html.call_args_list)
        value = css.split("{height:", 1)[1].split(" !important", 1)[0]
        assert ";" not in value and "}" not in value

    def test_uses_chat_input_not_form(self):
        """Embedded mode now uses st.chat_input, not st.form (Streamlit ≥ 1.59)."""
        bot = self._make_bot()
        mock_st = _mock_st()
        self._run_embedded(bot, mock_st)

        mock_st.chat_input.assert_called_once()
        mock_st.form.assert_not_called()

    def test_scrollable_container_with_correct_height(self):
        bot = self._make_bot()
        mock_st = _mock_st()
        self._run_embedded(bot, mock_st)

        mock_st.container.assert_called_once_with(height=300, autoscroll=True)

    def test_process_prompt_called_when_chat_input_returns_text(self):
        bot = self._make_bot()
        mock_st = _mock_st()
        mock_proc = self._run_embedded(bot, mock_st, prompt="Hello")

        mock_proc.assert_called_once()
        assert mock_proc.call_args[0][0] == "Hello"

    def test_process_prompt_not_called_when_chat_input_returns_none(self):
        bot = self._make_bot()
        mock_st = _mock_st()
        mock_proc = self._run_embedded(bot, mock_st, prompt=None)

        mock_proc.assert_not_called()

    def test_chat_input_uses_input_key(self):
        bot = self._make_bot(session_key_prefix="demo")
        mock_st = _mock_st()
        self._run_embedded(bot, mock_st)

        call_kwargs = mock_st.chat_input.call_args.kwargs
        assert call_kwargs.get("key") == "demo_input"

    def test_no_new_conversation_button_when_disabled(self):
        bot = self._make_bot(new_conversation_button=False)
        mock_st = _mock_st()
        self._run_embedded(bot, mock_st)

        mock_st.button.assert_not_called()

    def test_sidebar_not_used_in_embedded_mode(self):
        bot = self._make_bot(new_conversation_button=True)
        mock_st = _mock_st()
        self._run_embedded(bot, mock_st)

        # The sidebar context manager should never be entered in embedded mode.
        mock_st.sidebar.__enter__.assert_not_called()


# ---------------------------------------------------------------------------
# _stream_with_retry factory pattern
# ---------------------------------------------------------------------------


class TestStreamWithRetry:
    """Verifies that _stream_with_retry uses a factory callable correctly."""

    def _make_bot(self):
        return StreamlitChatbot(
            account_url="https://test.snowflakecomputing.com",
            auth="v2:tok",
            agent_path="DB.SC.AGENT",
        )

    def test_factory_called_twice_on_transient_error(self):
        """On first failure, factory is called a second time (fresh stream)."""
        from cortex_agents_client.exceptions import CortexTimeoutError
        from cortex_agents_client.models.thread import StoredMessage

        bot = self._make_bot()
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return iter([])

        with patch(
            "cortex_agents_client.st.render.render_streaming_response",
            side_effect=[
                CortexTimeoutError("read timed out"),
                StoredMessage(role="assistant"),
            ],
        ):
            result = bot._stream_with_retry(factory, container=MagicMock(), key_prefix="test-0")

        assert call_count == 2
        assert result.role == "assistant"

    def test_raises_after_second_failure(self):
        """If both attempts fail, the exception propagates."""
        from cortex_agents_client.exceptions import ServerError

        bot = self._make_bot()

        def factory():
            return iter([])

        with patch(
            "cortex_agents_client.st.render.render_streaming_response",
            side_effect=ServerError("fail"),
        ):
            with pytest.raises(ServerError):
                bot._stream_with_retry(factory, container=MagicMock(), key_prefix="test-0")


class TestStopCancelsRun:
    """Stopping the script mid-stream cancels the agent run server-side."""

    def _bot(self) -> StreamlitChatbot:
        return StreamlitChatbot(
            account_url="https://x.snowflakecomputing.com",
            auth="tok",
            agent_path="A.B.C",
        )

    def _events(self, *run_ids):
        from cortex_agents_client.models.events import MetadataEvent

        return [
            MetadataEvent._from_payload(
                {"metadata": {"role": "user", "message_id": i, "run_id": rid}}
            )
            for i, rid in enumerate(run_ids)
        ]

    def _stop_after_consuming(self, exc):
        def fake_render(events, **kwargs):
            list(events)
            raise exc
        return fake_render

    @pytest.mark.parametrize("exc_name", ["StopException", "RerunException"])
    def test_stop_cancels_latest_run_and_reraises(self, exc_name):
        from streamlit.runtime import scriptrunner

        exc_cls = getattr(scriptrunner, exc_name)
        exc = exc_cls() if exc_name == "StopException" else exc_cls(None)
        bot = self._bot()
        client = MagicMock()
        state = {bot._client_key: client}
        with patch("streamlit.session_state", state), patch(
            "cortex_agents_client.st.render.render_streaming_response",
            side_effect=self._stop_after_consuming(exc),
        ):
            with pytest.raises(exc_cls):
                bot._stream_with_retry(
                    lambda: iter(self._events("7-1", "7-3")), container=MagicMock(), key_prefix="k"
                )
        client.cancel_run.assert_called_once_with("7-3")

    def test_already_finished_run_is_not_an_error(self):
        from streamlit.runtime.scriptrunner import StopException

        from cortex_agents_client.exceptions import RunNotActiveError

        bot = self._bot()
        client = MagicMock()
        client.cancel_run.side_effect = RunNotActiveError("done", status_code=409)
        with patch("streamlit.session_state", {bot._client_key: client}), patch(
            "cortex_agents_client.st.render.render_streaming_response",
            side_effect=self._stop_after_consuming(StopException()),
        ):
            with pytest.raises(StopException):
                bot._stream_with_retry(
                    lambda: iter(self._events("7-1")), container=MagicMock(), key_prefix="k"
                )
        client.cancel_run.assert_called_once_with("7-1")

    def test_cancel_failure_does_not_replace_stop(self):
        from streamlit.runtime.scriptrunner import StopException

        bot = self._bot()
        client = MagicMock()
        client.cancel_run.side_effect = RuntimeError("network down")
        with patch("streamlit.session_state", {bot._client_key: client}), patch(
            "cortex_agents_client.st.render.render_streaming_response",
            side_effect=self._stop_after_consuming(StopException()),
        ):
            with pytest.raises(StopException):
                bot._stream_with_retry(
                    lambda: iter(self._events("7-1")), container=MagicMock(), key_prefix="k"
                )

    def test_stop_before_any_metadata_does_not_cancel(self):
        from streamlit.runtime.scriptrunner import StopException

        bot = self._bot()
        client = MagicMock()
        with patch("streamlit.session_state", {bot._client_key: client}), patch(
            "cortex_agents_client.st.render.render_streaming_response",
            side_effect=self._stop_after_consuming(StopException()),
        ):
            with pytest.raises(StopException):
                bot._stream_with_retry(lambda: iter([]), container=MagicMock(), key_prefix="k")
        client.cancel_run.assert_not_called()

    def test_normal_completion_does_not_cancel(self):
        bot = self._bot()
        client = MagicMock()
        with patch("streamlit.session_state", {bot._client_key: client}), patch(
            "cortex_agents_client.st.render.render_streaming_response",
            side_effect=lambda events, **kw: (list(events), "stored")[1],
        ):
            assert bot._stream_with_retry(
                lambda: iter(self._events("7-1")), container=MagicMock(), key_prefix="k"
            ) == "stored"
        client.cancel_run.assert_not_called()


# ---------------------------------------------------------------------------
# Multi-tenancy variables
# ---------------------------------------------------------------------------


class TestVariables:
    """``variables`` reaches thread.chat on every chat path."""

    def _make_bot(self, **kw) -> StreamlitChatbot:
        return StreamlitChatbot(
            account_url="https://x.snowflakecomputing.com",
            auth="tok",
            agent_path="A.B.C",
            mode="embedded",
            **kw,
        )

    def _prompt(self, bot, calls: int = 1):
        """Runs _process_prompt ``calls`` times; returns the thread mock."""
        thread = MagicMock()
        thread.chat.return_value = iter([])
        mock_st = _mock_st()
        mock_st.session_state = {}

        def fake_retry(factory, **_kw):
            # Invoke twice to simulate a retry reusing the same factory.
            list(factory())
            list(factory())
            return MagicMock()

        with patch.dict("sys.modules", {"streamlit": mock_st}), \
             patch.object(bot, "_stream_with_retry", side_effect=fake_retry):
            for _ in range(calls):
                bot._process_prompt("Hi", thread, MagicMock())
        return thread

    def test_default_sends_none(self):
        thread = self._prompt(self._make_bot())
        assert thread.chat.call_args.kwargs["variables"] is None

    def test_static_mapping_forwarded(self):
        thread = self._prompt(self._make_bot(variables={"region": "NORTH"}))
        assert thread.chat.call_args.kwargs["variables"] == {"region": "NORTH"}

    def test_callable_invoked_once_per_prompt_and_reused_on_retry(self):
        tenants = iter(["NORTH", "SOUTH"])
        resolver = MagicMock(side_effect=lambda: {"region": next(tenants)})
        thread = self._prompt(self._make_bot(variables=resolver), calls=2)
        assert resolver.call_count == 2  # once per prompt, not per retry
        sent = [c.kwargs["variables"] for c in thread.chat.call_args_list]
        assert sent == [{"region": "NORTH"}] * 2 + [{"region": "SOUTH"}] * 2

    def test_permission_path_forwards(self):
        from cortex_agents_client.models.events import ToolUseEvent

        bot = self._make_bot(variables={"region": "NORTH"})
        thread = MagicMock()
        thread.chat.return_value = iter([])
        mock_st = _mock_st()
        perm_event = ToolUseEvent._from_payload({
            "content_index": 0,
            "tool_use_id": "t1",
            "type": "generic",
            "name": "Tool",
            "input": {},
        })
        mock_st.session_state = {
            bot._pending_permission_key: {
                "tool_use_event": perm_event,
                "original_message": "Hi",
            }
        }
        mock_st.radio.return_value = "allow"
        mock_st.button.return_value = True

        def fake_retry(factory, **_kw):
            list(factory())
            return MagicMock()

        with patch.dict("sys.modules", {"streamlit": mock_st}), \
             patch.object(bot, "_stream_with_retry", side_effect=fake_retry):
            bot._render_permission_ui(thread, MagicMock())
        assert thread.chat.called
        assert thread.chat.call_args.kwargs["variables"] == {"region": "NORTH"}
