"""Session state management for Streamlit applications.

Provides idempotent initialisation of the :class:`~cortex_agents_client.CortexAgentsClient`
and :class:`~cortex_agents_client.Thread` across Streamlit reruns, plus helpers for
reading and writing the conversation message list.

All session state keys are prefixed with ``_ca_`` by default to avoid
collisions with user-defined session state. Custom key prefixes can be
passed to override this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cortex_agents_client.client import CortexAgentsClient, Thread
    from cortex_agents_client.models.thread import StoredMessage

_DEFAULT_CLIENT_KEY = "_ca_client"
_DEFAULT_THREAD_KEY = "_ca_thread"
_DEFAULT_MESSAGES_KEY = "_ca_messages"


def init_session(
    account_url: str,
    auth: Any,
    *,
    origin_application: str | None = None,
    client_key: str = _DEFAULT_CLIENT_KEY,
    thread_key: str = _DEFAULT_THREAD_KEY,
    messages_key: str = _DEFAULT_MESSAGES_KEY,
    timeout: float = 120.0,
    default_database: str | None = None,
    default_schema: str | None = None,
) -> tuple[CortexAgentsClient, Thread]:
    """Idempotently initialises a client and thread in Streamlit session state.

    On the first call per session, creates a new
    :class:`~cortex_agents_client.CortexAgentsClient` and
    :class:`~cortex_agents_client.Thread` and stores them in ``st.session_state``.
    On every subsequent call (Streamlit rerun), returns the cached objects.

    Call this at the top of your Streamlit app script, before any UI code.

    Args:
        account_url: Snowflake account base URL including scheme
            (e.g. ``"https://myorg-myaccount.snowflakecomputing.com"``).
        auth: PAT token string or
            :class:`~cortex_agents_client.auth.AuthProvider` instance.
        origin_application: Label attached to the created thread for
            monitoring purposes. Limited to 16 bytes.
        client_key: ``st.session_state`` key for the client.
        thread_key: ``st.session_state`` key for the thread.
        messages_key: ``st.session_state`` key for the message list.
        timeout: HTTP request timeout in seconds.
        default_database: Default database for agent operations.
        default_schema: Default schema for agent operations.

    Returns:
        A tuple of ``(CortexAgentsClient, Thread)``.

    Raises:
        ImportError: If ``streamlit`` is not installed.

    Example::

        import streamlit as st
        from cortex_agents_client.st.session import init_session

        client, thread = init_session(
            account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
            auth=st.secrets["SNOWFLAKE_PAT"],
            origin_application="my_app",
        )
    """
    import streamlit as st

    from cortex_agents_client.client import CortexAgentsClient

    if client_key not in st.session_state:
        st.session_state[client_key] = CortexAgentsClient(
            account_url,
            auth,
            timeout=timeout,
            default_database=default_database,
            default_schema=default_schema,
            origin_application=origin_application,
        )

    client: CortexAgentsClient = st.session_state[client_key]

    if thread_key not in st.session_state:
        st.session_state[thread_key] = client.create_thread(
            origin_application=origin_application
        )

    if messages_key not in st.session_state:
        st.session_state[messages_key] = []

    return client, st.session_state[thread_key]


def reset_thread(
    *,
    client_key: str = _DEFAULT_CLIENT_KEY,
    thread_key: str = _DEFAULT_THREAD_KEY,
    messages_key: str = _DEFAULT_MESSAGES_KEY,
    origin_application: str | None = None,
) -> None:
    """Starts a fresh conversation by replacing the current thread.

    Creates a new thread using the existing client and clears the message
    history. The client is kept alive — only the thread and messages are
    replaced.

    Args:
        client_key: ``st.session_state`` key for the client.
        thread_key: ``st.session_state`` key for the thread.
        messages_key: ``st.session_state`` key for the message list.
        origin_application: Optional label for the new thread.

    Raises:
        KeyError: If ``client_key`` is not in session state (i.e.
            :func:`init_session` has not been called yet).
        ImportError: If ``streamlit`` is not installed.

    Example::

        if st.button("New conversation"):
            reset_thread()
            st.rerun()
    """
    import streamlit as st

    client = st.session_state[client_key]
    st.session_state[thread_key] = client.create_thread(
        origin_application=origin_application
    )
    st.session_state[messages_key] = []


def get_messages(key: str = _DEFAULT_MESSAGES_KEY) -> list[StoredMessage]:
    """Returns the current conversation message list from session state.

    Args:
        key: ``st.session_state`` key for the message list.

    Returns:
        List of :class:`~cortex_agents_client.models.thread.StoredMessage` objects,
        in chronological order. Returns an empty list if the key is not yet
        set.

    Raises:
        ImportError: If ``streamlit`` is not installed.
    """
    import streamlit as st

    return st.session_state.get(key, [])


def append_message(
    msg: StoredMessage, key: str = _DEFAULT_MESSAGES_KEY
) -> None:
    """Appends a message to the conversation history in session state.

    Args:
        msg: The :class:`~cortex_agents_client.models.thread.StoredMessage` to
            append.
        key: ``st.session_state`` key for the message list.

    Raises:
        ImportError: If ``streamlit`` is not installed.
    """
    import streamlit as st

    if key not in st.session_state:
        st.session_state[key] = []
    st.session_state[key].append(msg)


def sis_init_session(
    *,
    origin_application: str | None = None,
    client_key: str = _DEFAULT_CLIENT_KEY,
    thread_key: str = _DEFAULT_THREAD_KEY,
    messages_key: str = _DEFAULT_MESSAGES_KEY,
    default_database: str | None = None,
    default_schema: str | None = None,
    token_path: str = "/snowflake/session/token",
) -> tuple[CortexAgentsClient, Thread]:
    """Initialises a client and thread for Streamlit-in-Snowflake container runtime.

    A convenience wrapper around :func:`init_session` that automatically:

    - Reads the account URL from the ``SNOWFLAKE_HOST`` environment variable
      injected by Snowflake into the container.
    - Creates a :class:`~cortex_agents_client.auth.SiSContainerAuth` that reads the
      OAuth token file at ``/snowflake/session/token`` on every request,
      ensuring tokens are never stale.

    Call this at the top of your SiS app instead of :func:`init_session`.
    On every Streamlit rerun, the same cached client and thread are returned.

    Args:
        origin_application: Label attached to the created thread.
        client_key: ``st.session_state`` key for the client.
        thread_key: ``st.session_state`` key for the thread.
        messages_key: ``st.session_state`` key for the message list.
        default_database: Default database for agent operations.
        default_schema: Default schema for agent operations.
        token_path: Path to the Snowflake OAuth token file.
            Defaults to ``/snowflake/session/token``.

    Returns:
        A tuple of ``(CortexAgentsClient, Thread)``.

    Raises:
        EnvironmentError: If ``SNOWFLAKE_HOST`` is not set in the environment.
        FileNotFoundError: If the token file does not exist.
        ImportError: If ``streamlit`` is not installed.

    Example::

        import streamlit as st
        from cortex_agents_client.st.session import sis_init_session

        # In your SiS container app:
        client, thread = sis_init_session(origin_application="my_sis_app")
    """
    from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

    account_url = account_url_from_env()
    auth = SiSContainerAuth(token_path=token_path)

    return init_session(
        account_url,
        auth,
        origin_application=origin_application,
        client_key=client_key,
        thread_key=thread_key,
        messages_key=messages_key,
        default_database=default_database,
        default_schema=default_schema,
    )

