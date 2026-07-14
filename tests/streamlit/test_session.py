"""Tests for cortex_agents_client.st.session helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_streamlit(monkeypatch):
    """Provides a fake st.session_state dict for all tests."""
    import streamlit as st

    monkeypatch.setattr(st, "session_state", {})


@pytest.fixture
def mock_client():
    """Returns a MagicMock CortexAgentsClient."""
    client = MagicMock()
    client.create_thread.return_value = MagicMock(thread_id="t_123")
    return client


class TestInitSession:
    def test_creates_client_and_thread_on_first_call(self, mock_client):
        import streamlit as st

        with patch(
            "cortex_agents_client.client.CortexAgentsClient",
            return_value=mock_client,
        ):
            from cortex_agents_client.st.session import init_session

            client, thread = init_session("https://test.snowflakecomputing.com", "tok")

        assert st.session_state["_ca_client"] is mock_client
        assert st.session_state["_ca_thread"].thread_id == "t_123"
        assert st.session_state["_ca_messages"] == []

    def test_returns_cached_on_subsequent_calls(self, mock_client):
        import streamlit as st

        with patch(
            "cortex_agents_client.client.CortexAgentsClient",
            return_value=mock_client,
        ) as ctor:
            from cortex_agents_client.st.session import init_session

            init_session("https://test.snowflakecomputing.com", "tok")
            init_session("https://test.snowflakecomputing.com", "tok")

        # Client constructor called only once
        assert ctor.call_count == 1

    def test_custom_key_prefix(self, mock_client):
        import streamlit as st

        with patch(
            "cortex_agents_client.client.CortexAgentsClient",
            return_value=mock_client,
        ):
            from cortex_agents_client.st.session import init_session

            init_session(
                "https://test.snowflakecomputing.com",
                "tok",
                client_key="_my_client",
                thread_key="_my_thread",
                messages_key="_my_messages",
            )

        assert "_my_client" in st.session_state
        assert "_my_thread" in st.session_state
        assert "_my_messages" in st.session_state


class TestResetThread:
    def test_clears_messages_and_creates_new_thread(self, mock_client):
        import streamlit as st

        from cortex_agents_client.st.session import reset_thread

        st.session_state["_ca_client"] = mock_client
        st.session_state["_ca_thread"] = MagicMock(thread_id="old")
        st.session_state["_ca_messages"] = [MagicMock()]

        reset_thread()

        assert st.session_state["_ca_messages"] == []
        assert st.session_state["_ca_thread"].thread_id == "t_123"
        mock_client.create_thread.assert_called_once()

    def test_raises_key_error_if_no_client(self):
        from cortex_agents_client.st.session import reset_thread

        with pytest.raises(KeyError):
            reset_thread()


class TestGetMessages:
    def test_returns_empty_list_when_not_set(self):
        from cortex_agents_client.st.session import get_messages

        assert get_messages() == []

    def test_returns_stored_messages(self):
        import streamlit as st

        from cortex_agents_client.st.session import get_messages

        msgs = [MagicMock(), MagicMock()]
        st.session_state["_ca_messages"] = msgs
        assert get_messages() == msgs


class TestAppendMessage:
    def test_appends_to_existing_list(self):
        import streamlit as st

        from cortex_agents_client.st.session import append_message

        st.session_state["_ca_messages"] = []
        msg = MagicMock()
        append_message(msg)
        assert st.session_state["_ca_messages"] == [msg]

    def test_creates_list_if_missing(self):
        import streamlit as st

        from cortex_agents_client.st.session import append_message

        msg = MagicMock()
        append_message(msg)
        assert st.session_state["_ca_messages"] == [msg]
