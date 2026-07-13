# Plan: Replace chat mode radio with st.navigation

## Changes to `streamlit_demo/app.py`

### Before `pg.run()` — shared on all pages

Keep in sidebar (unchanged):
- `st.set_page_config`
- Scenario selectbox
- `show_thinking`, `show_tool_status`, `accept_file`, `accept_audio` toggles
- Sidebar caption

Remove from sidebar:
- `selected_mode` radio button
- `selected_mode == "embedded"` / `"dialog"` chat height sliders (move inside page functions)

Extract helper:
```python
def _seed_state(prefix: str) -> None:
    """Pre-seeds mock client/thread/messages into session state for a prefix."""
    client_key, thread_key, messages_key, last_key = (
        f"{prefix}_client", f"{prefix}_thread",
        f"{prefix}_messages", f"{prefix}_last_scenario",
    )
    if st.session_state.get(last_key) != selected_scenario:
        for k in (client_key, thread_key, messages_key):
            st.session_state.pop(k, None)
        st.session_state[last_key] = selected_scenario
    st.session_state.setdefault(client_key, MockClient(selected_scenario))
    st.session_state.setdefault(thread_key, MockThread(selected_scenario))
    st.session_state.setdefault(messages_key, [])
```

### Three page functions

**`page_fullpage()`**
- Calls `_seed_state("_fp")`
- Hint banner
- Title + caption (drops "Mode:" since it's in the nav)
- `StreamlitChatbot(mode="fullpage", session_key_prefix="_fp", ...)`
- Footer

**`page_embedded()`**
- Calls `_seed_state("_emb")`
- Chat height slider in sidebar (only shows on this page since it's inside the page fn)
- Hint banner
- Title + caption
- 2-column layout: dashboard left, chatbot right
- `StreamlitChatbot(mode="embedded", height=chat_height, session_key_prefix="_emb", ...)`
- Footer

**`page_dialog()`**
- Calls `_seed_state("_dlg_popup")` (for the dialog overlay bot)
- Chat height slider in sidebar
- `chat_dialog_open` session state init
- `@st.dialog(...)` defined inside the function (closures over `chat_height`, etc.)
- Hint banner
- Header row with title + "Ask the agent" button
- Dashboard content
- `if st.session_state.chat_dialog_open: _chat_dialog()`
- Footer

### Navigation

```python
pg = st.navigation(
    [
        st.Page(page_fullpage, title="Full page",  icon=":material/chat:",         default=True),
        st.Page(page_embedded, title="Embedded",   icon=":material/view_sidebar:"),
        st.Page(page_dialog,   title="Dialog",     icon=":material/open_in_new:"),
    ],
    position="top",
)
pg.run()
```

### Session state prefix mapping

| Old prefix | New prefix | Page |
|---|---|---|
| `_demo` | `_fp` | Full page |
| `_demo` | `_emb` | Embedded |
| `_popup` | `_dlg_popup` | Dialog overlay |

The dialog page doesn't have a main chatbot (it's all in the overlay), so no `_dlg` main prefix needed.

## Critical file

- `streamlit_demo/app.py` — only file modified
