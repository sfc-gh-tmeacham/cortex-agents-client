"""Drop-in Cortex Agent chat for Streamlit.

Add a streaming Cortex Agent chat interface to a Streamlit app::

    import streamlit as st
    from streamlit_cortex_agents import StreamlitChatbot

    bot = StreamlitChatbot(
        account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
        auth=st.secrets["SNOWFLAKE_PAT"],
        agent_path="DB.SCHEMA.MY_AGENT",
    )
    bot.render()

The chat component lives in :mod:`streamlit_cortex_agents.chat`. The REST
client it is built on lives in :mod:`streamlit_cortex_agents.client` and is
usable on its own. Every public name from both is re-exported here.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("streamlit-cortex-agents")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"

from streamlit_cortex_agents import chat as _chat
from streamlit_cortex_agents import client as _client
from streamlit_cortex_agents.chat import *  # noqa: F401,F403
from streamlit_cortex_agents.client import *  # noqa: F401,F403
from streamlit_cortex_agents.client.exceptions import (  # noqa: F401
    PermissionError as PermissionError,  # deprecated alias; kept out of __all__
    TimeoutError as TimeoutError,  # deprecated alias; kept out of __all__
)

__all__ = ["__version__", *_chat.__all__, *_client.__all__]
