"""Streamlit-in-Snowflake (SiS) container runtime chatbot application.

Deploy this as a Streamlit app in Snowflake using container runtime.
No secrets.toml needed — credentials are injected by Snowflake automatically.

Snowflake injects two things into the container:
  - SNOWFLAKE_HOST env var (the account host)
  - /snowflake/session/token file (OAuth token, auto-refreshed)

The library's SiSContainerAuth reads the token file on every request so
tokens are always current even in long-running sessions.

To create the SiS app, run in Snowflake:
    CREATE OR REPLACE STREAMLIT my_db.my_schema.my_agent_app
      FROM '@my_db.my_schema.my_stage/app'
      MAIN_FILE                    = 'sis_app.py'
      RUNTIME_NAME                 = 'SYSTEM$ST_CONTAINER_RUNTIME_PY3_11'
      COMPUTE_POOL                 = my_compute_pool
      QUERY_WAREHOUSE              = 'MY_WH'
      EXTERNAL_ACCESS_INTEGRATIONS = (cortex_agents_api_eai);

Upload this file and your cortex_agents_client/ directory to the stage path above.
"""

import os

import streamlit as st
from cortex_agents_client.st import StreamlitChatbot
from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

# Agent path — set as a constant or read from an environment variable.
# Set it in snowflake.yml under `environment:` when deploying via Workspaces,
# or hardcode it directly if you only target one agent.
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
