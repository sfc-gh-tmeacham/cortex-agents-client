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
