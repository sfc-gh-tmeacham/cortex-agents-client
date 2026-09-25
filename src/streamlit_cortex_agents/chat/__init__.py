"""Streamlit integration for the Cortex Agents library.

Provides session state management, event rendering helpers, and a high-level
drop-in chatbot component.

Requires ``pip install "streamlit-cortex-agents[streamlit]"`` (installs ``streamlit``
and ``pandas``).

Example::

    from streamlit_cortex_agents.chat import CortexAgentChat

    bot = CortexAgentChat(
        account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
        auth=st.secrets["SNOWFLAKE_PAT"],
        agent_path="DB.SCHEMA.MY_AGENT",
    )
    bot.render()
"""

from streamlit_cortex_agents.chat.chatbot import CortexAgentChat
from streamlit_cortex_agents.chat.render import render_stored_message, render_streaming_response, result_set_to_dataframe, escape_dollars
from streamlit_cortex_agents.chat.session import (
    append_message,
    get_messages,
    init_session,
    reset_thread,
    sis_init_session,
)

__all__ = [
    "CortexAgentChat",
    "init_session",
    "sis_init_session",
    "reset_thread",
    "get_messages",
    "append_message",
    "render_streaming_response",
    "render_stored_message",
    "result_set_to_dataframe",
    "escape_dollars",
]
