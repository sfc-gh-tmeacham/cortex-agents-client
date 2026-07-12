"""High-level Streamlit chatbot component for Cortex Agents.

Provides :class:`StreamlitChatbot`, a drop-in component that renders a
complete chat UI in two modes:

- ``"fullpage"`` (default): traditional full-page chat with ``st.chat_input``
  pinned to the bottom of the page.
- ``"embedded"``: self-contained chat that fits inside any Streamlit container
  — a column, ``st.dialog``, ``st.sidebar``, ``st.expander``, etc. Uses a
  fixed-height scrollable message area and an inline ``st.chat_input`` so
  everything stays within the container bounds.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal

from cortex_agents_client.models.thread import StoredMessage

logger = logging.getLogger(__name__)


class StreamlitChatbot:
    """A drop-in Streamlit chatbot component backed by a Cortex Agent.

    Renders a complete chat interface including message history replay,
    streaming response rendering, and an optional "New conversation" button.
    Manages client and thread lifecycle via ``st.session_state`` so all
    state persists correctly across Streamlit reruns.

    Two rendering modes are available:

    **fullpage** (default)
        Traditional full-page chat. ``st.chat_input`` is pinned to the bottom
        of the page (Streamlit's default behaviour). The "New conversation"
        button appears in the sidebar.

        .. code-block:: python

            bot = StreamlitChatbot(account_url=..., auth=..., agent_path=...)
            bot.render()

    **embedded**
        Self-contained chat that fits inside any Streamlit container — a
        column, ``st.dialog``, ``st.sidebar``, ``st.expander``, etc. Uses a
        fixed-height scrollable message area (``st.container(height=...,
        autoscroll=True)``) and an inline ``st.chat_input`` (requires
        Streamlit ≥ 1.59) so all elements stay within the container.
        The "New conversation" button appears inline at the top of the
        component, not in the sidebar.

        .. code-block:: python

            # Column layout: dashboard on the left, chat on the right
            dash_col, chat_col = st.columns([2, 1])
            with dash_col:
                st.write("Your dashboard content here")
            with chat_col:
                bot = StreamlitChatbot(
                    account_url=..., auth=..., agent_path=...,
                    mode="embedded",
                    height=500,
                )
                bot.render()

            # Dialog: chat opens in a modal overlay
            @st.dialog("Ask the agent", width="large")
            def open_chat():
                bot = StreamlitChatbot(
                    account_url=..., auth=..., agent_path=...,
                    mode="embedded",
                    height=400,
                )
                bot.render()

            if st.button("Open chat", icon=":material/chat:"):
                open_chat()

    Args:
        account_url: Snowflake account base URL.
        auth: PAT token string or
            :class:`~cortex_agents_client.auth.AuthProvider` instance.
        agent_path: Dot-separated agent path (e.g. ``"DB.SCHEMA.MY_AGENT"``).
        mode: Rendering mode. ``"fullpage"`` (default) uses ``st.chat_input``
            pinned to the page bottom. ``"embedded"`` uses a scrollable message
            area and an inline ``st.chat_input`` so the chatbot fits inside any
            container.
        height: Height in pixels of the scrollable message area when
            ``mode="embedded"``. Ignored in fullpage mode. Default 450.
        show_thinking: If ``True``, renders agent thinking in an expander.
            Defaults to ``False``.
        show_tool_status: If ``True``, shows ``st.status()`` spinners during
            tool execution. Defaults to ``True``.
        new_conversation_button: If ``True``, adds a "New conversation" button.
            In fullpage mode it appears in the sidebar; in embedded mode it
            appears inline above the message area. Defaults to ``True``.
        origin_application: Label attached to threads for monitoring.
        input_placeholder: Placeholder text for the chat input widget.
        session_key_prefix: Prefix for all session state keys. Change this
            to avoid collisions when using multiple chatbots on one page.
        default_database: Default database for agent runs.
        default_schema: Default schema for agent runs.
        accept_file: If ``True`` or ``"multiple"``, adds a file-attachment
            button to ``st.chat_input``. ``"multiple"`` allows uploading
            several files at once. Defaults to ``False``.
        accept_audio: If ``True``, adds a microphone button to
            ``st.chat_input`` for voice messages. Defaults to ``False``.
        file_type: List of accepted file extensions or MIME types when
            ``accept_file`` is enabled (e.g. ``["pdf", "csv"]``).
            ``None`` accepts all file types.
        tool_executor: Optional callable for ``client_side_execute=True`` tools.
            Receives a :class:`~cortex_agents_client.models.events.ToolUseEvent`
            and returns a list of ``ToolResultContent`` dicts (e.g.
            ``[{"type": "json", "json": {...}}]``). Passed to
            :meth:`~cortex_agents_client.client.Thread.chat` on every run.
    """

    def __init__(
        self,
        account_url: str,
        auth: Any,
        agent_path: str,
        *,
        mode: Literal["fullpage", "embedded"] = "fullpage",
        height: int = 450,
        show_thinking: bool = False,
        show_tool_status: bool = True,
        new_conversation_button: bool = True,
        origin_application: str | None = None,
        input_placeholder: str = "Ask a question...",
        session_key_prefix: str = "_ca",
        default_database: str | None = None,
        default_schema: str | None = None,
        accept_file: bool | Literal["multiple", "directory"] = False,
        accept_audio: bool = False,
        file_type: list[str] | str | None = None,
        tool_executor: Callable | None = None,
    ) -> None:
        """Initialises the chatbot component.

        Args:
            account_url: Snowflake account base URL.
            auth: Auth provider or PAT token string.
            agent_path: Dot-separated agent path.
            mode: ``"fullpage"`` or ``"embedded"``.
            height: Message area height (pixels) for embedded mode.
            show_thinking: Whether to render thinking content.
            show_tool_status: Whether to show tool execution spinners.
            new_conversation_button: Whether to add a new conversation button.
            origin_application: Thread origin application label.
            input_placeholder: Chat input placeholder text.
            session_key_prefix: Prefix for session state keys.
            default_database: Default database.
            default_schema: Default schema.
            accept_file: Enable file attachments (``True``, ``"multiple"``,
                or ``"directory"``).
            accept_audio: Enable microphone / voice input.
            file_type: Allowed file types when ``accept_file`` is enabled.
        """
        self._account_url = account_url
        self._auth = auth
        self._agent_path = agent_path
        self._mode = mode
        self._height = height
        self._show_thinking = show_thinking
        self._show_tool_status = show_tool_status
        self._new_conversation_button = new_conversation_button
        self._origin_application = origin_application
        self._input_placeholder = input_placeholder
        self._client_key = f"{session_key_prefix}_client"
        self._thread_key = f"{session_key_prefix}_thread"
        self._messages_key = f"{session_key_prefix}_messages"
        self._input_key = f"{session_key_prefix}_input"
        self._default_database = default_database
        self._default_schema = default_schema
        self._accept_file = accept_file
        self._accept_audio = accept_audio
        self._file_type = file_type
        self._tool_executor = tool_executor
        self._pending_permission_key = f"{session_key_prefix}_pending_perm"

    def render(self) -> None:
        """Renders the complete chat UI in the configured mode.

        Call this once per Streamlit script execution. In ``"fullpage"`` mode,
        call it at the top level of your script. In ``"embedded"`` mode, call
        it inside the container you want the chat to occupy (e.g.
        ``with col2: bot.render()``).

        Raises:
            ImportError: If ``streamlit`` is not installed.
            ValueError: If ``mode`` is not ``"fullpage"`` or ``"embedded"``.
        """
        if self._mode == "fullpage":
            self._render_fullpage()
        elif self._mode == "embedded":
            self._render_embedded()
        else:
            raise ValueError(
                f"Invalid mode {self._mode!r}. Expected 'fullpage' or 'embedded'."
            )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _init(self):
        """Initialises session state and returns (thread, helpers).

        Returns:
            Tuple of ``(thread, get_messages, append_message, reset_thread)``.
        """
        from cortex_agents_client.st.session import (
            append_message,
            get_messages,
            init_session,
            reset_thread,
        )

        _, thread = init_session(
            self._account_url,
            self._auth,
            origin_application=self._origin_application,
            client_key=self._client_key,
            thread_key=self._thread_key,
            messages_key=self._messages_key,
            default_database=self._default_database,
            default_schema=self._default_schema,
        )
        return thread, get_messages, append_message, reset_thread

    def _render_message_history(self, get_messages_fn) -> None:
        """Renders existing message history into the current Streamlit context.

        Args:
            get_messages_fn: The ``get_messages`` helper from session module.
        """
        import streamlit as st

        from cortex_agents_client.st.render import render_stored_message

        for msg in get_messages_fn(self._messages_key):
            with st.chat_message(msg.role):
                if msg.role == "user":
                    # Re-display any stored file/audio attachments
                    for att in msg.attachments:
                        att_type = getattr(att, "type", "") or ""
                        if att_type.startswith("image/"):
                            st.image(att)
                        elif att_type.startswith("audio/"):
                            st.audio(att)
                        elif att_type:
                            st.write(f":material/attach_file: {att.name}")
                    if msg.text:
                        st.markdown(msg.text)
                else:
                    render_stored_message(msg, st)

    def _process_prompt(self, raw: Any, thread, append_message_fn) -> None:
        """Sends a prompt to the agent and renders the response.

        Accepts either a plain string (no file/audio attachments) or the
        dict-like object returned by ``st.chat_input`` when
        ``accept_file=True`` or ``accept_audio=True``. In the latter case
        the text is extracted from ``.text``, files from ``.files``, and
        audio from ``.audio``; files and audio are displayed in the user
        bubble and stored in
        :attr:`~cortex_agents_client.models.thread.StoredMessage.attachments`
        for history replay.

        .. note::

            File and audio attachments are **not** forwarded to the agent.
            The Cortex Agents REST API currently only supports ``text``
            content items in user messages — there is no inline image,
            document, or audio content type. Only the typed text portion of
            the prompt reaches the agent. Multimodal support in Snowflake is
            provided through Cortex AI Functions (SQL, staged files) rather
            than through the chat API.

        Appends both the user message and the assembled assistant
        :class:`~cortex_agents_client.models.thread.StoredMessage` to session
        state.

        Args:
            raw: Either a ``str`` prompt or the ``UploadedFileRec`` object
                from an ``accept_file``/``accept_audio``-enabled
                ``st.chat_input``.
            thread: Active :class:`~cortex_agents_client.client.Thread`.
            append_message_fn: The ``append_message`` helper from session module.
        """
        import streamlit as st

        from cortex_agents_client.st.render import render_streaming_response

        # Unwrap plain string vs attach-enabled chat_input result
        if isinstance(raw, str):
            prompt_text = raw
            attachments: list[Any] = []
        else:
            prompt_text = getattr(raw, "text", "") or ""
            files = list(getattr(raw, "files", None) or [])
            audio = getattr(raw, "audio", None)
            attachments = files + ([audio] if audio is not None else [])

        logger.info("Processing prompt for agent %s (attachments: %d)", self._agent_path, len(attachments))

        with st.chat_message("user"):
            for att in attachments:
                att_type = getattr(att, "type", "") or ""
                if att_type.startswith("image/"):
                    st.image(att)
                elif att_type.startswith("audio/"):
                    st.audio(att)
                elif att_type:
                    st.write(f":material/attach_file: {att.name}")
            if prompt_text:
                st.markdown(prompt_text)

        append_message_fn(
            StoredMessage(role="user", text=prompt_text, attachments=attachments),
            key=self._messages_key,
        )
        with st.chat_message("assistant"):
            # NOTE: attachments are NOT forwarded to the agent.
            #
            # The Cortex Agents Run API (MessageContentItem schema) currently only
            # supports {"type": "text"} content in user messages. There is no
            # image/document/audio content type for user input — multimodal is
            # handled separately via Cortex AI Functions on Snowflake stages (SQL),
            # not inline in the chat API.
            #
            # Files captured via accept_file / accept_audio are displayed in the
            # user bubble and stored in StoredMessage.attachments for rerun replay,
            # but prompt_text (the typed text) is the only thing sent to the agent.
            #
            # When the API adds multimodal user-message support, wire attachments
            # through the extra_content parameter on thread.chat().
            stored = render_streaming_response(
                thread.chat(
                    self._agent_path,
                    prompt_text,
                    tool_executor=self._tool_executor,
                ),
                container=st,
                show_thinking=self._show_thinking,
                show_tool_status=self._show_tool_status,
            )
        if stored.pending_permission:
            # Permission was required — save state and rerun to show approval UI.
            # The partial assistant message is NOT appended to history; the full
            # response will be appended after the user confirms or denies.
            logger.info(
                "Permission required for tool %s; pausing conversation",
                stored.pending_permission.name,
            )
            st.session_state[self._pending_permission_key] = {
                "tool_use_event": stored.pending_permission,
                "original_message": prompt_text,
            }
            st.rerun()
            return
        if stored.error:
            logger.error("Agent returned error %s: %s", stored.error.code, stored.error.message)
        else:
            logger.info(
                "Response complete: status=%s message_id=%s",
                getattr(stored, 'status', None) or 'success',
                stored.message_id,
            )
        append_message_fn(stored, key=self._messages_key)

    def _render_permission_ui(self, thread, append_message_fn) -> None:
        """Shows the permission approval UI when a tool requires user consent.

        Replaces the chat input until the user confirms or denies. On
        confirmation, sends a follow-up run request with the
        ``permission_decision`` content item and appends the resulting
        assistant message to history.

        Args:
            thread: Active :class:`~cortex_agents_client.client.Thread`.
            append_message_fn: The ``append_message`` helper from session module.
        """
        import streamlit as st

        from cortex_agents_client.st.render import render_streaming_response

        perm_data = st.session_state[self._pending_permission_key]
        perm_event = perm_data["tool_use_event"]
        original_message = perm_data["original_message"]
        logger.debug("Rendering permission UI for tool %s", perm_event.name)

        st.warning(
            f"**{perm_event.name}** is requesting permission before executing.",
            icon=":material/security:",
        )
        decision = st.radio(
            "Grant permission?",
            perm_event.permission_options,
            key=f"{self._pending_permission_key}_radio",
            horizontal=True,
        )
        if st.button(
            "Confirm",
            key=f"{self._pending_permission_key}_confirm",
            type="primary",
            icon=":material/check:",
        ):
            logger.info("Permission decision '%s' confirmed for tool %s", decision, perm_event.name)
            del st.session_state[self._pending_permission_key]
            permission_item = {
                "type": "permission_decision",
                "permission_decision": {
                    "tool_use_id": perm_event.tool_use_id,
                    "decision": decision,
                },
            }
            with st.chat_message("assistant"):
                stored = render_streaming_response(
                    thread.chat(
                        self._agent_path,
                        original_message,
                        permission_decisions=[permission_item],
                        tool_executor=self._tool_executor,
                    ),
                    container=st,
                    show_thinking=self._show_thinking,
                    show_tool_status=self._show_tool_status,
                )
            append_message_fn(stored, key=self._messages_key)
            st.rerun()

    # ------------------------------------------------------------------
    # Full-page mode
    # ------------------------------------------------------------------

    def _render_fullpage(self) -> None:
        """Renders the full-page chatbot.

        Uses ``st.chat_input`` pinned to the page bottom. The "New
        conversation" button appears in the sidebar.
        """
        import streamlit as st

        thread, get_messages, append_message, reset_thread = self._init()

        if self._new_conversation_button:
            with st.sidebar:
                if st.button(
                    "New conversation",
                    icon=":material/add_comment:",
                    use_container_width=True,
                ):
                    st.session_state.pop(self._pending_permission_key, None)
                    logger.info("New conversation started (agent: %s)", self._agent_path)
                    reset_thread(
                        client_key=self._client_key,
                        thread_key=self._thread_key,
                        messages_key=self._messages_key,
                        origin_application=self._origin_application,
                    )
                    st.rerun()

        self._render_message_history(get_messages)

        if self._pending_permission_key in st.session_state:
            self._render_permission_ui(thread, append_message)
        elif prompt := st.chat_input(
            self._input_placeholder,
            accept_file=self._accept_file,
            accept_audio=self._accept_audio,
            file_type=self._file_type,
        ):
            self._process_prompt(prompt, thread, append_message)

    # ------------------------------------------------------------------
    # Embedded mode
    # ------------------------------------------------------------------

    def _render_embedded(self) -> None:
        """Renders the embedded chatbot inside the current container context.

        Uses a fixed-height scrollable message area (``st.container`` with
        ``autoscroll=True``) and an inline ``st.chat_input`` (Streamlit
        ≥ 1.59) so the chatbot stays within its container. The "New
        conversation" button appears inline above the message area (not in
        the sidebar).

        Call this inside the container where you want the chat to live::

            with col2:
                bot.render()

            # or inside a dialog:
            @st.dialog("Chat")
            def chat_dialog():
                bot.render()
        """
        import streamlit as st

        thread, get_messages, append_message, reset_thread = self._init()

        # Optional inline "New conversation" button (not sidebar).
        if self._new_conversation_button:
            if st.button(
                "New conversation",
                icon=":material/add_comment:",
                use_container_width=True,
            ):
                st.session_state.pop(self._pending_permission_key, None)
                logger.info("New conversation started (agent: %s)", self._agent_path)
                reset_thread(
                    client_key=self._client_key,
                    thread_key=self._thread_key,
                    messages_key=self._messages_key,
                    origin_application=self._origin_application,
                )
                st.rerun()

        # Scrollable message history area.
        chat_area = st.container(height=self._height, autoscroll=True)
        with chat_area:
            self._render_message_history(get_messages)

        # st.chat_input works inline in any container (Streamlit ≥ 1.59).
        # The explicit key keeps it stable across reruns when the widget
        # is rendered inside a container or dialog.
        if self._pending_permission_key in st.session_state:
            self._render_permission_ui(thread, append_message)
        elif prompt := st.chat_input(
            self._input_placeholder,
            key=self._input_key,
            accept_file=self._accept_file,
            accept_audio=self._accept_audio,
            file_type=self._file_type,
        ):
            # Append new messages directly into the scrollable chat area.
            with chat_area:
                self._process_prompt(prompt, thread, append_message)
