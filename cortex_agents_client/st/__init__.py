"""Streamlit integration for the Cortex Agents library.

Provides session state management, event rendering helpers, and a high-level
drop-in chatbot component.

Requires ``pip install cortex-agents[streamlit]`` (installs ``streamlit``
and ``pandas``).

Example::

    from cortex_agents_client.st import StreamlitChatbot

    bot = StreamlitChatbot(
        account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
        auth=st.secrets["SNOWFLAKE_PAT"],
        agent_path=st.secrets["AGENT_PATH"],
    )
    bot.render()
"""

from cortex_agents_client.st.chatbot import StreamlitChatbot
from cortex_agents_client.st.render import render_stored_message, render_streaming_response
from cortex_agents_client.st.session import (
    append_message,
    get_messages,
    init_session,
    reset_thread,
    sis_init_session,
)

__all__ = [
    "StreamlitChatbot",
    "init_session",
    "sis_init_session",
    "reset_thread",
    "get_messages",
    "append_message",
    "render_streaming_response",
    "render_stored_message",
]
