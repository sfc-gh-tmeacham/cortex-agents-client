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
from collections.abc import Callable, Iterator
from typing import Any

from cortex_agents_client.auth import AuthProvider, PATAuth
from cortex_agents_client.exceptions import CortexAgentError
from cortex_agents_client.http import HttpClient
from cortex_agents_client.models.events import MetadataEvent, SSEEvent, ToolResultEvent, ToolUseEvent
from cortex_agents_client.models.thread import StoredMessage, ThreadMessage, ThreadMetadata
from cortex_agents_client.resources.agents import AgentsResource
from cortex_agents_client.resources.runs import RunResult, RunsResource
from cortex_agents_client.resources.threads import ThreadsResource

logger = logging.getLogger(__name__)

__all__ = ["CortexAgentsClient", "Thread"]


def _coerce_auth(auth: AuthProvider | str) -> AuthProvider:
    """Wraps a plain string token as a PATAuth provider.

    Args:
        auth: Either an :class:`~cortex_agents_client.auth.AuthProvider` instance
            or a string PAT token.

    Returns:
        An :class:`~cortex_agents_client.auth.AuthProvider` instance.
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
    :meth:`CortexAgentsClient.create_thread` or retrieved by constructing
    ``Thread(client, thread_id)`` with a previously stored thread ID.

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
                print(event.delta, end="")
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

    def chat(
        self,
        agent_path: str,
        message: str,
        *,
        tool_choice: dict[str, Any] | None = None,
        permission_decisions: list[dict[str, Any]] | None = None,
        extra_content: list[dict[str, Any]] | None = None,
        tool_executor: Callable[[ToolUseEvent], list[dict[str, Any]]] | None = None,
    ) -> Iterator[SSEEvent]:
        """Streams a conversation turn, auto-advancing ``parent_message_id``.

        Constructs the user message, streams the response from the agent,
        and captures ``metadata`` events to advance ``parent_message_id``
        for the next turn. All events are yielded to the caller.

        If the assistant metadata event is missing (rare server-side
        failure), a warning is logged and ``parent_message_id`` is left
        unchanged so the conversation can be retried.

        Args:
            agent_path: Dot-separated agent identifier
                (e.g. ``"DB.SCHEMA.MY_AGENT"``).
            message: The user's message text.
            tool_choice: Optional tool selection constraint dict.
            permission_decisions: Optional list of permission decision
                content items to include alongside the user message.
                Use this when the previous turn emitted a
                :class:`~cortex_agents_client.models.events.ToolUseEvent` with
                ``permission_options`` populated.
            extra_content: Additional content items to append to the user
                message content array.
            tool_executor: Optional callable invoked when the agent emits a
                :class:`~cortex_agents_client.models.events.ToolUseEvent` with
                ``client_side_execute=True``. Receives the event and must
                return a list of result content
                dicts (e.g. ``[{"type": "json", "json": {...}}]``).
                The library executes the tool, yields a synthetic
                :class:`~cortex_agents_client.models.events.ToolResultEvent` so
                renderers can close any status spinners, then automatically
                sends a follow-up request with the result.

        Yields:
            All :class:`~cortex_agents_client.models.events.SSEEvent` subclass
            instances received from the agent, in order.

        Raises:
            cortex_agents_client.exceptions.RunError: If the agent emits a fatal
                error event.
            cortex_agents_client.exceptions.AuthError: On authentication failure.
            cortex_agents_client.exceptions.CortexAgentError: On other errors.

        Example::

            for event in thread.chat("DB.SCHEMA.MY_AGENT", "What is revenue?"):
                if isinstance(event, TextDeltaEvent):
                    print(event.delta, end="", flush=True)
        """
        content: list[dict[str, Any]] = [{"type": "text", "text": message}]
        if permission_decisions:
            content.extend(permission_decisions)
        if extra_content:
            content.extend(extra_content)

        messages = [{"role": "user", "content": content}]
        new_assistant_message_id: int | None = None
        client_tool_result: dict[str, Any] | None = None

        event_stream = self._client.runs.stream(
            messages,
            agent_path=agent_path,
            thread_id=self._thread_id,
            parent_message_id=self._parent_message_id,
            tool_choice=tool_choice,
        )

        for event in event_stream:
            if isinstance(event, MetadataEvent) and event.role == "assistant":
                new_assistant_message_id = event.message_id

            if (
                isinstance(event, ToolUseEvent)
                and event.client_side_execute
                and tool_executor is not None
            ):
                yield event
                # Execute the tool client-side.
                try:
                    result_content = tool_executor(event)
                    status = "success"
                except Exception as exc:
                    logger.warning(
                        "tool_executor raised for tool '%s': %s", event.name, exc
                    )
                    result_content = [{"type": "text", "text": str(exc)}]
                    status = "error"
                # Yield a synthetic ToolResultEvent so renderers close spinners.
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
                        "content": result_content,
                        "status": status,
                    },
                }
                break  # Stream ends; restart with the tool result.

            yield event

        if client_tool_result is not None:
            # Restart the run with the tool result embedded in the user message.
            # Recursion handles any further client-side tools in the same turn.
            merged_extra = list(extra_content) if extra_content else []
            merged_extra.append(client_tool_result)
            yield from self.chat(
                agent_path,
                message,
                tool_choice=tool_choice,
                extra_content=merged_extra,
                tool_executor=tool_executor,
            )
            return  # parent_message_id is updated by the recursive call.

        if new_assistant_message_id is not None:
            self._parent_message_id = new_assistant_message_id
        else:
            logger.warning(
                "No assistant metadata event received for thread %d. "
                "parent_message_id unchanged (%d).",
                self._thread_id,
                self._parent_message_id,
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
        :meth:`~cortex_agents_client.resources.ThreadsResource.list_messages`.

        Returns:
            Chronologically ordered list of
            :class:`~cortex_agents_client.models.thread.ThreadMessage` objects.
        """
        return self._client.threads.list_messages(self._thread_id)

    def latest_context(self) -> list[ThreadMessage]:
        """Returns the latest compaction summary and all subsequent messages.

        Delegates to
        :meth:`~cortex_agents_client.resources.ThreadsResource.latest_context`.
        Useful for seeding multi-turn context without replaying the entire
        history.

        Returns:
            List of :class:`~cortex_agents_client.models.thread.ThreadMessage`
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
            cortex_agents_client.exceptions.ThreadNotFoundError: If the thread
                does not exist.
        """
        self._client.threads.delete(self._thread_id)


class CortexAgentsClient:
    """Top-level client for the Snowflake Cortex Agents REST API.

    Provides access to agent management, thread management, and run
    operations via the :attr:`agents`, :attr:`threads`, and :attr:`runs`
    resource objects. Also exposes convenience methods for common workflows.

    Passing a plain string as ``auth`` wraps it automatically as
    :class:`~cortex_agents_client.auth.PATAuth`.

    Args:
        account_url: Full base URL of the Snowflake account, including
            scheme (e.g. ``"https://myorg-myaccount.snowflakecomputing.com"``).
        auth: Authentication provider or plain PAT token string.
        timeout: HTTP request timeout in seconds. Defaults to 900 (15
            minutes), matching the API's maximum allowed duration.
        default_database: Default database for agent operations. Can be
            overridden per-call.
        default_schema: Default schema for agent operations.
        origin_application: Default ``origin_application`` label used when
            creating threads. Identifies this client in monitoring.

    Example::

        from cortex_agents_client import CortexAgentsClient

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
        timeout: float = 900.0,
        default_database: str | None = None,
        default_schema: str | None = None,
        origin_application: str | None = None,
    ) -> None:
        """Initialises the client.

        Args:
            account_url: Snowflake account base URL.
            auth: Auth provider or PAT token string.
            timeout: Request timeout in seconds.
            default_database: Default database.
            default_schema: Default schema.
            origin_application: Default origin application label for threads.
        """
        self._account_url = account_url
        self._http = HttpClient(
            base_url=account_url,
            auth=_coerce_auth(auth),
            timeout=timeout,
        )
        self._origin_application = origin_application
        self.agents = AgentsResource(self._http, default_database, default_schema)
        self.threads = ThreadsResource(self._http)
        self.runs = RunsResource(self._http, default_database, default_schema)

    def __repr__(self) -> str:
        return f"CortexAgentsClient(account_url={self._account_url!r})"

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
            cortex_agents_client.exceptions.AuthError: On authentication failure.
            cortex_agents_client.exceptions.CortexAgentError: On other API errors.
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
            **kwargs: Additional keyword arguments passed to
                :meth:`~cortex_agents_client.resources.RunsResource.stream`.

        Yields:
            :class:`~cortex_agents_client.models.events.SSEEvent` subclass instances.

        Raises:
            cortex_agents_client.exceptions.RunError: On fatal agent error.
            cortex_agents_client.exceptions.AuthError: On authentication failure.
        """
        if thread is not None:
            yield from thread.chat(agent_path, message, tool_choice=tool_choice)
            return

        messages = [{"role": "user", "content": [{"type": "text", "text": message}]}]
        yield from self.runs.stream(
            messages, agent_path=agent_path, tool_choice=tool_choice, **kwargs
        )

    def run(
        self,
        agent_path: str,
        message: str,
        *,
        thread: Thread | None = None,
        tool_choice: dict[str, Any] | None = None,
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
            **kwargs: Additional keyword arguments passed to
                :meth:`~cortex_agents_client.resources.RunsResource.run`.

        Returns:
            Assembled :class:`~cortex_agents_client.resources.RunResult`.

        Raises:
            cortex_agents_client.exceptions.RunError: On fatal agent error.
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
            **kwargs,
        )
