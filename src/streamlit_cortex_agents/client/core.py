"""Top-level client facade and Thread convenience class.

This module provides the two primary entry points for the library:

- :class:`CortexAgentsClient`: the main client, constructed with
  authentication credentials and optional defaults.
- :class:`Thread`: a stateful wrapper around a thread ID that tracks
  ``parent_message_id`` automatically, making multi-turn conversations
  easy to implement correctly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from streamlit_cortex_agents.client.auth import AuthProvider, PATAuth
from streamlit_cortex_agents.client.http import HttpClient
from streamlit_cortex_agents.client.models.events import (
    MetadataEvent,
    RunMetadata,
    SSEEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from streamlit_cortex_agents.client.models.thread import ThreadMessage
from streamlit_cortex_agents.client.resources.agents import AgentsResource
from streamlit_cortex_agents.client.resources.runs import RunResult, RunsResource
from streamlit_cortex_agents.client.resources.threads import ThreadsResource

logger = logging.getLogger(__name__)

__all__ = ["CortexAgentsClient", "Thread"]


def _coerce_auth(auth: AuthProvider | str) -> AuthProvider:
    """Wraps a plain string token as a PATAuth provider.

    Args:
        auth: Either an :class:`~streamlit_cortex_agents.client.auth.AuthProvider` instance
            or a string PAT token.

    Returns:
        An :class:`~streamlit_cortex_agents.client.auth.AuthProvider` instance.
    """
    if isinstance(auth, str):
        return PATAuth(auth)
    return auth


class Thread:
    """A stateful conversation thread with automatic message ID tracking.

    Wraps a thread ID and keeps track of the ``parent_message_id`` so that
    callers never need to manage it manually. Each call to :meth:`chat`
    uses the current ``parent_message_id`` and advances it to the new
    assistant message ID after the response is complete.

    Threads are typically created via
    :meth:`CortexAgentsClient.create_thread` or resumed via
    :meth:`CortexAgentsClient.get_thread`.

    Key methods:
    - :meth:`chat` — stream events for a new user message.
    - :meth:`list_messages` — full paginated message history.
    - :meth:`latest_context` — compaction-aware context for long threads.
    - :meth:`fork` — branch from a specific assistant message.
    - :meth:`delete` — delete the thread.

    Args:
        client: The parent :class:`CortexAgentsClient` instance.
        thread_id: The integer thread ID.
        parent_message_id: Starting parent message ID. Use ``0`` (default)
            for a brand-new thread, or the last assistant message ID when
            resuming a previous conversation.

    Example::

        thread = client.create_thread()
        for event in thread.chat("DB.SCHEMA.MY_AGENT", "Hello!"):
            if isinstance(event, TextDeltaEvent):
                print(event.text, end="")
        # Next turn uses the correct parent_message_id automatically
        for event in thread.chat("DB.SCHEMA.MY_AGENT", "What about 2024?"):
            ...
    """

    def __init__(
        self,
        client: CortexAgentsClient,
        thread_id: int,
        parent_message_id: int = 0,
    ) -> None:
        """Initialises the thread.

        Args:
            client: The parent CortexAgentsClient.
            thread_id: Integer thread identifier.
            parent_message_id: Starting parent message ID.
        """
        self._client = client
        self._thread_id = thread_id
        self._parent_message_id = parent_message_id

    @property
    def thread_id(self) -> int:
        """The integer thread ID.

        Returns:
            Thread ID.
        """
        return self._thread_id

    @property
    def parent_message_id(self) -> int:
        """The current parent message ID.

        This is the assistant message ID from the most recent completed turn,
        or ``0`` if no turns have been completed yet.

        Returns:
            Current parent message ID.
        """
        return self._parent_message_id

    def __repr__(self) -> str:
        return (
            f"Thread(thread_id={self._thread_id!r}, "
            f"parent_message_id={self._parent_message_id!r})"
        )

    _MAX_TOOL_ITERATIONS = 20

    def chat(
        self,
        agent_path: str,
        message: str,
        *,
        tool_choice: dict[str, Any] | None = None,
        permission_decisions: list[dict[str, Any]] | None = None,
        extra_content: list[dict[str, Any]] | None = None,
        background: bool = False,
        tool_executor: Callable[[ToolUseEvent], list[dict[str, Any]]] | None = None,
        variables: Mapping[str, Any] | None = None,
    ) -> Iterator[SSEEvent]:
        """Streams a conversation turn, auto-advancing ``parent_message_id``.

        Constructs the user message, streams the response from the agent,
        and captures ``metadata`` events to advance ``parent_message_id``
        for the next turn. All events are yielded to the caller.

        If the assistant metadata event is missing (rare server-side
        failure), a warning is logged and ``parent_message_id`` is left
        unchanged so the conversation can be retried.

        Client-side tool execution loops are capped at
        :attr:`_MAX_TOOL_ITERATIONS` to prevent stack overflow from
        misbehaving agents.

        Args:
            agent_path: Dot-separated agent identifier
                (e.g. ``"DB.SCHEMA.MY_AGENT"``).
            message: The user's message text.
            tool_choice: Optional tool selection constraint dict.
            permission_decisions: Optional list of permission decision
                content items to include alongside the user message.
                Use this when the previous turn emitted a
                :class:`~streamlit_cortex_agents.client.models.events.ToolUseEvent` with
                ``permission_options`` populated.
            extra_content: Additional content items to append to the user
                message content array.
            background: Run asynchronously with a 6-hour timeout instead of
                the default 15-minute one. The run survives a client
                disconnect; resume it with
                :meth:`CortexAgentsClient.stream_run` using the ``run_id``
                from any :class:`~streamlit_cortex_agents.client.models.events.MetadataEvent`.
            tool_executor: Optional callable invoked when the agent emits a
                :class:`~streamlit_cortex_agents.client.models.events.ToolUseEvent` with
                ``client_side_execute=True``. Receives the event and must
                return a list of result content
                dicts (e.g. ``[{"type": "json", "json": {...}}]``).
                The library executes the tool, yields a synthetic
                :class:`~streamlit_cortex_agents.client.models.events.ToolResultEvent` so
                renderers can close any status spinners, then automatically
                sends a follow-up request with the result.
            variables: Optional session attributes for multi-tenancy (see
                :meth:`~streamlit_cortex_agents.client.resources.RunsResource.stream`).
                Sent on every request of the turn, including client-side
                tool-loop follow-ups.

        Yields:
            All :class:`~streamlit_cortex_agents.client.models.events.SSEEvent` subclass
            instances received from the agent, in order.

        Raises:
            streamlit_cortex_agents.client.exceptions.RunError: If the agent emits a fatal
                error event.
            streamlit_cortex_agents.client.exceptions.AuthError: On authentication failure.
            streamlit_cortex_agents.client.exceptions.CortexAgentError: On other errors.
            RuntimeError: If client-side tool iterations exceed
                :attr:`_MAX_TOOL_ITERATIONS`.

        Example::

            for event in thread.chat("DB.SCHEMA.MY_AGENT", "What is revenue?"):
                if isinstance(event, TextDeltaEvent):
                    print(event.text, end="", flush=True)
        """
        # The first request carries the user's text, permission decisions,
        # and attachments. Tool-loop follow-ups carry only the tool_result so
        # the user's question is not re-sent as a new turn.
        content: list[dict[str, Any]] = [{"type": "text", "text": message}]
        if permission_decisions:
            content.extend(permission_decisions)
        if extra_content:
            content.extend(extra_content)

        for _ in range(self._MAX_TOOL_ITERATIONS):

            messages = [{"role": "user", "content": content}]
            new_assistant_message_id: int | None = None
            client_tool_result: dict[str, Any] | None = None

            event_stream = self._client.runs.stream(
                messages,
                agent_path=agent_path,
                thread_id=self._thread_id,
                parent_message_id=self._parent_message_id,
                tool_choice=tool_choice,
                background=background,
                variables=variables,
            )

            for event in event_stream:
                if isinstance(event, MetadataEvent) and event.role == "assistant":
                    new_assistant_message_id = event.message_id

                if (
                    isinstance(event, ToolUseEvent)
                    and event.client_side_execute
                    and tool_executor is not None
                    and client_tool_result is None
                ):
                    yield event
                    try:
                        result_content = tool_executor(event)
                        status = "success"
                    except Exception as exc:
                        logger.warning(
                            "tool_executor raised for tool '%s': %s", event.name, exc
                        )
                        result_content = [{"type": "text", "text": str(exc)}]
                        status = "error"
                    yield ToolResultEvent._from_payload({
                        "content_index": event.content_index,
                        "tool_use_id": event.tool_use_id,
                        "type": event.type,
                        "name": event.name,
                        "content": result_content,
                        "status": status,
                    })
                    client_tool_result = {
                        "type": "tool_result",
                        "tool_result": {
                            "tool_use_id": event.tool_use_id,
                            "type": event.type,
                            "name": event.name,
                            "content": result_content,
                            "status": status,
                        },
                    }
                    # Keep reading so the assistant metadata event (which
                    # carries the parent_message_id for the follow-up) arrives.
                    continue

                yield event

            if client_tool_result is None:
                # No more tool calls — conversation turn is complete.
                if new_assistant_message_id is not None:
                    self._parent_message_id = new_assistant_message_id
                else:
                    logger.warning(
                        "No assistant metadata event received for thread %d. "
                        "parent_message_id unchanged (%d).",
                        self._thread_id,
                        self._parent_message_id,
                    )
                return

            # Advance parent_message_id if the server issued one for this
            # intermediate response, so the next tool-loop iteration sends
            # the correct context pointer.
            if new_assistant_message_id is not None:
                self._parent_message_id = new_assistant_message_id

            # Send only the tool result on the next iteration.
            content = [client_tool_result]

        raise RuntimeError(
            f"Client-side tool execution exceeded {self._MAX_TOOL_ITERATIONS} "
            f"iterations. The agent may be in an infinite tool-call loop."
        )

    def fork(self, at_message_id: int) -> Thread:
        """Creates a new Thread branched from a specific assistant message.

        The forked thread shares the same ``thread_id`` but starts from
        a different branch point. This allows exploring alternate
        conversation paths without losing the original.

        Args:
            at_message_id: The assistant message ID to fork from. Must be
                an assistant message ID (not a user message ID) per API
                requirements.

        Returns:
            A new :class:`Thread` instance with the given
            ``parent_message_id``.

        Example::

            fork = thread.fork(at_message_id=456)
            for event in fork.chat("DB.SCHEMA.MY_AGENT", "What about costs?"):
                ...
        """
        return Thread(self._client, self._thread_id, parent_message_id=at_message_id)

    def list_messages(self) -> list[ThreadMessage]:
        """Returns all conversation messages in chronological order.

        Delegates to
        :meth:`~streamlit_cortex_agents.client.resources.ThreadsResource.list_messages`.

        Returns:
            Chronologically ordered list of
            :class:`~streamlit_cortex_agents.client.models.thread.ThreadMessage` objects.
        """
        return self._client.threads.list_messages(self._thread_id)

    def latest_context(self) -> list[ThreadMessage]:
        """Returns the latest compaction summary and all subsequent messages.

        Delegates to
        :meth:`~streamlit_cortex_agents.client.resources.ThreadsResource.latest_context`.
        Useful for seeding multi-turn context without replaying the entire
        history.

        Returns:
            List of :class:`~streamlit_cortex_agents.client.models.thread.ThreadMessage`
            objects in chronological order: the newest compaction summary
            (if any) followed by all subsequent conversation messages.
        """
        return self._client.threads.latest_context(self._thread_id)

    def get_history(self) -> list[ThreadMessage]:
        """Deprecated: use :meth:`list_messages` instead."""
        import warnings
        warnings.warn(
            "Thread.get_history() is deprecated; use Thread.list_messages() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.list_messages()

    def delete(self) -> None:
        """Deletes this thread and all its messages.

        After calling this method, the thread object is no longer usable.

        Raises:
            streamlit_cortex_agents.client.exceptions.ThreadNotFoundError: If the thread
                does not exist.
        """
        self._client.threads.delete(self._thread_id)


class CortexAgentsClient:
    """Top-level client for the Snowflake Cortex Agents REST API.

    Provides access to agent management, thread management, and run
    operations via the :attr:`agents`, :attr:`threads`, and :attr:`runs`
    resource objects. Also exposes convenience methods for common workflows:
    :meth:`create_thread`, :meth:`get_thread`, :meth:`stream`, and
    :meth:`run`.

    Passing a plain string as ``auth`` wraps it automatically as
    :class:`~streamlit_cortex_agents.client.auth.PATAuth`.

    Args:
        account_url: Full base URL of the Snowflake account, including
            scheme (e.g. ``"https://myorg-myaccount.snowflakecomputing.com"``).
        auth: Authentication provider or plain PAT token string.
        timeout: Read timeout in seconds. Defaults to 120 (2 minutes).
            Controls the maximum silence allowed between data chunks in an
            SSE stream. Increase for agents with very long processing times.
        default_database: Default database for agent operations. Can be
            overridden per-call.
        default_schema: Default schema for agent operations.
        origin_application: Default ``origin_application`` label used when
            creating threads. Identifies this client in monitoring.
        role: Optional Snowflake role sent as the ``X-Snowflake-Role`` header
            on every request. Note that Cortex Agents derives tool
            permissions from the user's default role regardless of this
            header; it affects the role the request itself runs under.

    Example::

        from streamlit_cortex_agents import CortexAgentsClient

        client = CortexAgentsClient(
            account_url="https://myorg-myaccount.snowflakecomputing.com",
            auth="v2:my_pat_token",
            default_database="MY_DB",
            default_schema="MY_SCHEMA",
        )

        # Create a thread and start chatting
        thread = client.create_thread()
        for event in thread.chat("MY_AGENT", "What is 2025 revenue?"):
            print(event)
    """

    def __init__(
        self,
        account_url: str,
        auth: AuthProvider | str,
        *,
        timeout: float = 120.0,
        default_database: str | None = None,
        default_schema: str | None = None,
        origin_application: str | None = None,
        role: str | None = None,
    ) -> None:
        """Initialises the client.

        Args:
            account_url: Snowflake account base URL.
            auth: Auth provider or PAT token string.
            timeout: Read timeout in seconds.
            default_database: Default database.
            default_schema: Default schema.
            origin_application: Default origin application label for threads.
            role: Optional Snowflake role for the ``X-Snowflake-Role`` header.
        """
        self._account_url = account_url
        self._http = HttpClient(
            base_url=account_url,
            auth=_coerce_auth(auth),
            timeout=timeout,
            role=role,
        )
        self._origin_application = origin_application
        self.agents = AgentsResource(self._http, default_database, default_schema)
        self.threads = ThreadsResource(self._http)
        self.runs = RunsResource(self._http, default_database, default_schema)

    def __repr__(self) -> str:
        return f"CortexAgentsClient(account_url={self._account_url!r})"

    def close(self) -> None:
        """Closes the underlying HTTP connection pool.

        Should be called when the client is no longer needed to release
        connections. Alternatively, use the client as a context manager.
        """
        self._http.close()

    def __enter__(self) -> CortexAgentsClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def create_thread(
        self, *, origin_application: str | None = None
    ) -> Thread:
        """Creates a new conversation thread and returns a Thread wrapper.

        Args:
            origin_application: Application label for this thread. Falls
                back to the client-level ``origin_application`` if not set.

        Returns:
            A :class:`Thread` wrapping the new thread ID, ready for
            conversation.

        Raises:
            streamlit_cortex_agents.client.exceptions.AuthError: On authentication failure.
            streamlit_cortex_agents.client.exceptions.CortexAgentError: On other API errors.
        """
        app = origin_application or self._origin_application
        metadata = self.threads.create(origin_application=app)
        return Thread(self, metadata.thread_id)

    def get_thread(self, thread_id: int, *, parent_message_id: int = 0) -> Thread:
        """Returns a :class:`Thread` wrapper for a previously created thread.

        Use this to resume a conversation whose ``thread_id`` was persisted
        (e.g. in a database or URL parameter).

        Args:
            thread_id: The integer thread identifier to resume.
            parent_message_id: The parent message ID to start from. Defaults
                to ``0`` (beginning of thread). Pass the last known assistant
                message ID to resume mid-conversation.

        Returns:
            A :class:`Thread` ready for :meth:`~Thread.chat` calls.
        """
        return Thread(self, thread_id, parent_message_id=parent_message_id)

    def stream(
        self,
        agent_path: str,
        message: str,
        *,
        thread: Thread | None = None,
        tool_choice: dict[str, Any] | None = None,
        variables: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Iterator[SSEEvent]:
        """Convenience method for streaming a single message to an agent.

        For multi-turn conversations, prefer creating a :class:`Thread`
        with :meth:`create_thread` and calling :meth:`Thread.chat` directly,
        as that handles ``parent_message_id`` tracking automatically.

        Args:
            agent_path: Dot-separated agent identifier.
            message: User message text.
            thread: Optional :class:`Thread` to use for context persistence.
                If provided, ``parent_message_id`` is managed automatically.
            tool_choice: Optional tool selection constraint.
            variables: Optional session attributes for multi-tenancy (see
                :meth:`~streamlit_cortex_agents.client.resources.RunsResource.stream`).
                Forwarded on both the thread and the one-shot path.
            **kwargs: Additional keyword arguments passed to
                :meth:`~streamlit_cortex_agents.client.resources.RunsResource.stream`.

        Yields:
            :class:`~streamlit_cortex_agents.client.models.events.SSEEvent` subclass instances.

        Raises:
            streamlit_cortex_agents.client.exceptions.RunError: On fatal agent error.
            streamlit_cortex_agents.client.exceptions.AuthError: On authentication failure.
        """
        if thread is not None:
            yield from thread.chat(
                agent_path, message, tool_choice=tool_choice, variables=variables
            )
            return

        messages = [{"role": "user", "content": [{"type": "text", "text": message}]}]
        yield from self.runs.stream(
            messages,
            agent_path=agent_path,
            tool_choice=tool_choice,
            variables=variables,
            **kwargs,
        )

    def run(
        self,
        agent_path: str,
        message: str,
        *,
        thread: Thread | None = None,
        tool_choice: dict[str, Any] | None = None,
        variables: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> RunResult:
        """Convenience method for a non-streaming single-message run.

        Args:
            agent_path: Dot-separated agent identifier.
            message: User message text.
            thread: Optional :class:`Thread` for context persistence.
                Note: non-streaming mode does not advance
                ``parent_message_id`` automatically. Use
                :meth:`Thread.chat` for tracked multi-turn conversations.
            tool_choice: Optional tool selection constraint.
            variables: Optional session attributes for multi-tenancy (see
                :meth:`~streamlit_cortex_agents.client.resources.RunsResource.stream`).
            **kwargs: Additional keyword arguments passed to
                :meth:`~streamlit_cortex_agents.client.resources.RunsResource.run`.

        Returns:
            Assembled :class:`~streamlit_cortex_agents.client.resources.RunResult`.

        Raises:
            streamlit_cortex_agents.client.exceptions.RunError: On fatal agent error.
        """
        messages = [{"role": "user", "content": [{"type": "text", "text": message}]}]
        thread_id = thread.thread_id if thread else None
        parent_id = thread.parent_message_id if thread else 0
        return self.runs.run(
            messages,
            agent_path=agent_path,
            thread_id=thread_id,
            parent_message_id=parent_id,
            tool_choice=tool_choice,
            variables=variables,
            **kwargs,
        )

    def stream_run(
        self,
        run_id: str,
        *,
        starting_after: int | None = None,
    ) -> Iterator[SSEEvent]:
        """Reconnects to an existing agent run and streams its output.

        Delegates to
        :meth:`~streamlit_cortex_agents.client.resources.runs.RunsResource.stream_run`.
        Use this to resume a background run or recover from a dropped
        connection.

        Args:
            run_id: Run identifier, in ``{thread_id}-{user_message_id}`` form.
            starting_after: Sequence number to resume from, exclusive.

        Yields:
            :class:`~streamlit_cortex_agents.client.models.events.SSEEvent` subclass instances.

        Raises:
            streamlit_cortex_agents.client.exceptions.RunNotActiveError: If the run
                finished more than 5 minutes ago.
        """
        yield from self.runs.stream_run(run_id, starting_after=starting_after)

    def cancel_run(self, run_id: str) -> RunMetadata:
        """Cancels an actively running agent run.

        Delegates to
        :meth:`~streamlit_cortex_agents.client.resources.runs.RunsResource.cancel_run`.

        Args:
            run_id: Run identifier, in ``{thread_id}-{user_message_id}`` form.

        Returns:
            :class:`~streamlit_cortex_agents.client.models.events.RunMetadata` for the
            cancelled run.

        Raises:
            streamlit_cortex_agents.client.exceptions.RunNotActiveError: If the run has
                already completed or been cancelled.
        """
        return self.runs.cancel_run(run_id)
