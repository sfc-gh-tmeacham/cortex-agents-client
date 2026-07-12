"""Minimal Streamlit chatbot application using the cortex_agents_client library.

Run with:
    streamlit run examples/streamlit_app.py

Requires .streamlit/secrets.toml with:
    SNOWFLAKE_ACCOUNT_URL = "https://myorg-myaccount.snowflakecomputing.com"
    SNOWFLAKE_PAT = "v2:my_pat_token"
"""

import streamlit as st
from cortex_agents_client.st import StreamlitChatbot

AGENT_PATH = "MY_DB.MY_SCHEMA.MY_AGENT"

st.set_page_config(page_title="Cortex Agent Chat", page_icon=":material/smart_toy:", layout="wide")
st.title("Cortex Agent Chat")

bot = StreamlitChatbot(
    account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
    auth=st.secrets["SNOWFLAKE_PAT"],
    agent_path=AGENT_PATH,
    show_thinking=st.sidebar.toggle("Show reasoning", value=False),
    show_tool_status=True,
    origin_application="streamlit_example",
)
bot.render()
