"""Streamlit-in-Snowflake (SiS) container runtime chatbot application.

Deploy this as a Streamlit app in Snowflake using container runtime.
No secrets.toml needed — credentials are injected by Snowflake automatically.

Snowflake injects two things into the container:
  - SNOWFLAKE_HOST env var (the account host)
  - /snowflake/session/token file (OAuth token, auto-refreshed)

The library's SiSContainerAuth reads the token file on every request so
tokens are always current even in long-running sessions.

To create the SiS app, run in Snowflake:
    CREATE STREAMLIT my_agent_app
      ROOT_LOCATION = '@my_db.my_schema.my_stage'
      MAIN_FILE = 'sis_app.py'
      QUERY_WAREHOUSE = 'MY_WH'
      RUNTIME_NAME = 'SYSTEM$CONTAINER_RUNTIME';

Then upload this file and a packages.txt listing your dependencies to the stage.
"""

import os

import streamlit as st
from cortex_agents_client.st import StreamlitChatbot
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

# Agent path — set as a constant or read from an environment variable.
# In a real app you might inject this via an environment variable set on
# the STREAMLIT object:
#   ALTER STREAMLIT my_agent_app SET EXTERNAL_ACCESS_INTEGRATIONS = (...)
AGENT_PATH = os.environ.get("AGENT_PATH", "MY_DB.MY_SCHEMA.MY_AGENT")

st.set_page_config(page_title="Cortex Agent Chat", page_icon=":material/smart_toy:", layout="wide")
st.title("Cortex Agent Chat")

bot = StreamlitChatbot(
    account_url=account_url_from_env(),
    auth=SiSContainerAuth(),
    agent_path=AGENT_PATH,
    show_thinking=st.sidebar.toggle("Show reasoning", value=False),
    show_tool_status=True,
    origin_application="sis_container_app",
)
bot.render()
