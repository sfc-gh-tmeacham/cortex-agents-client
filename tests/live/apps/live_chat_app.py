"""Streamlit app used by the live AppTest coverage in test_streamlit_live.py.

Builds a real :class:`~streamlit_cortex_agents.chat.StreamlitChatbot` against a live
agent, so the whole render pipeline executes against real API payloads. The
mock-based tests in tests/streamlit/ never run this path.

Driven by ``streamlit.testing.v1.AppTest``, not launched by hand. Reads its
configuration from the same environment variables as the rest of the live
suite:

    SNOWFLAKE_ACCOUNT_URL
    SNOWFLAKE_PAT
    LIVE_APPTEST_AGENT   (falls back to LIVE_AGENT_MINIMAL)

``LIVE_APPTEST_AGENT`` lets a single test point this app at a different agent
(for example the Analyst agent, to exercise table rendering) without a second
copy of the script.
"""

from __future__ import annotations

import os

import streamlit as st

from streamlit_cortex_agents.chat import StreamlitChatbot

AGENT_PATH = os.environ.get("LIVE_APPTEST_AGENT") or os.environ["LIVE_AGENT_MINIMAL"]

st.title("cac live apptest")

StreamlitChatbot(
    account_url=os.environ["SNOWFLAKE_ACCOUNT_URL"],
    auth=os.environ["SNOWFLAKE_PAT"],
    agent_path=AGENT_PATH,
    show_thinking=True,
    show_tool_status=True,
    origin_application="cac_live",
).render()
