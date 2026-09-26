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

    # A session state flag keeps the dialog open across the chatbot's own
    # reruns; without it the dialog closes after the first message.
    if "chat_dialog_open" not in st.session_state:
        st.session_state.chat_dialog_open = False

    # Pre-seed messages so st.chat_input renders on the first dialog open.
    st.session_state.setdefault("_ca_dlg_messages", [])

    @st.dialog("Cortex Agent", width="large", dismissible=False)
    def _chat_dialog() -> None:
        if st.button("Close", icon=":material/close:", type="tertiary"):
            st.session_state.chat_dialog_open = False
            st.rerun()
        # A CSS height makes the chat fill the viewport; 340px covers the
        # dialog title, the Close and New conversation buttons and the chat input.
        _make_bot("dlg", height="calc(100vh - 340px)").render()

    if st.button(
        "Ask the agent",
        icon=":material/chat:",
        type="primary",
    ):
        st.session_state.chat_dialog_open = True

    # Open the dialog last, after all other page content.
    if st.session_state.chat_dialog_open:
        _chat_dialog()
