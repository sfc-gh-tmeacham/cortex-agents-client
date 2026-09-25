"""Examples of embedded chat mode: column layout and dialog overlay.

Run with:
    streamlit run examples/embedded_chat.py

Requires .streamlit/secrets.toml with:
    SNOWFLAKE_ACCOUNT_URL = "https://myorg-myaccount.snowflakecomputing.com"
    SNOWFLAKE_PAT = "v2:my_pat_token"
"""

import streamlit as st
from streamlit_cortex_agents.chat import CortexAgentChat

AGENT_PATH = "MY_DB.MY_SCHEMA.MY_AGENT"

st.set_page_config(
    page_title="Dashboard + Chat",
    page_icon=":material/dashboard:",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar: choose the embedded layout style
# ---------------------------------------------------------------------------
layout = st.sidebar.radio(
    "Chat layout",
    options=["Column (side by side)", "Dialog (modal)"],
    index=0,
)

# ---------------------------------------------------------------------------
# Main content: a placeholder dashboard
# ---------------------------------------------------------------------------
st.title("Sales Dashboard")

col_a, col_b, col_c = st.columns(3)
col_a.metric("Revenue", "$1.2M", "+8%")
col_b.metric("Orders", "4,320", "+12%")
col_c.metric("Avg order value", "$278", "-2%")

st.divider()

# ---------------------------------------------------------------------------
# Shared chatbot factory
# ---------------------------------------------------------------------------
def _make_bot(prefix: str, height: int | str = 450) -> CortexAgentChat:
    return CortexAgentChat(
        account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
        auth=st.secrets["SNOWFLAKE_PAT"],
        agent_path=AGENT_PATH,
        mode="embedded",
        height=height,
        show_thinking=False,
        show_tool_status=True,
        origin_application="embedded_example",
        # Unique prefix avoids session key collisions when switching layouts.
        session_key_prefix=f"_ca_{prefix}",
    )


# ---------------------------------------------------------------------------
# Layout: column
# ---------------------------------------------------------------------------
if layout == "Column (side by side)":
    dash_col, chat_col = st.columns([3, 2], gap="large")

    with dash_col:
        st.subheader("Monthly revenue")
        st.bar_chart(
            {"Jan": 95, "Feb": 110, "Mar": 102, "Apr": 118, "May": 130, "Jun": 125},
            color="#29b5e8",
        )
        st.subheader("Top products")
        st.dataframe(
            {
                "Product": ["Widget A", "Widget B", "Widget C"],
                "Units": [1_240, 980, 650],
                "Revenue": ["$248k", "$196k", "$130k"],
            },
            hide_index=True,
            width="stretch",
        )

    with chat_col:
        st.subheader(":material/smart_toy: Ask the agent")
        _make_bot("col").render()

# ---------------------------------------------------------------------------
# Layout: dialog
# ---------------------------------------------------------------------------
else:
    st.subheader("Monthly revenue")
    st.bar_chart(
        {"Jan": 95, "Feb": 110, "Mar": 102, "Apr": 118, "May": 130, "Jun": 125},
        color="#29b5e8",
    )

    # @st.dialog must be at module scope so Streamlit can persist the dialog
    # across reruns. Calling the decorated function opens the modal.
    @st.dialog("Cortex Agent", width="large")
    def _chat_dialog() -> None:
        # A CSS height makes the chat fill the viewport; 300px covers the
        # dialog title, the New conversation button and the chat input.
        _make_bot("dlg", height="calc(100vh - 300px)").render()

    if st.button(
        "Ask the agent",
        icon=":material/chat:",
        type="primary",
    ):
        _chat_dialog()
