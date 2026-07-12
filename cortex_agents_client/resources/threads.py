"""Resource class for thread CRUD and message retrieval.

Provides create, describe, update, list, delete, and message-listing
operations against the ``/api/v2/cortex/threads`` endpoint family.

Includes the compaction-aware ``latest_context`` method that fetches the
most recent thread summary (if any) plus all subsequent conversation messages.
"""

from __future__ import annotations

from typing import Any

from cortex_agents_client.http import HttpClient
from cortex_agents_client.models.thread import (
    ThreadDetail,
    ThreadMessage,
    ThreadMetadata,
)

_THREADS_BASE = "/api/v2/cortex/threads"


class ThreadsResource:
    """Manages Cortex Agent conversation threads.

    Threads persist conversation context across turns so that client
    applications do not have to resend history with each request.

    Args:
        http: Authenticated HTTP client.

    Example::

        thread = client.threads.create(origin_application="my_app")
        print(thread.thread_id)
    """

    def __init__(self, http: HttpClient) -> None:
        """Initialises the threads resource.

        Args:
            http: Authenticated HTTP client.
        """
        self._http = http

    def create(self, *, origin_application: str | None = None) -> ThreadMetadata:
        """Creates a new conversation thread.

        Args:
            origin_application: Optional name of the application creating
                the thread. Used to group threads by application in the
                Snowsight monitoring UI. Limited to 16 bytes by the API.

        Returns:
            :class:`~cortex_agents_client.models.thread.ThreadMetadata` with the
            new ``thread_id``.

        Raises:
            cortex_agents_client.exceptions.AuthError: On authentication failure.
            cortex_agents_client.exceptions.CortexAgentError: On other API errors.

        Example::

            thread = client.threads.create(origin_application="streamlit_app")
            print(thread.thread_id)  # e.g. 1234567890
        """
        body: dict[str, Any] = {}
        if origin_application:
            body["origin_application"] = origin_application

        data = self._http.request("POST", _THREADS_BASE, json=body or None, resource="thread")
        return ThreadMetadata.from_dict(data)

    def get(
        self,
        thread_id: int,
        *,
        message_type: str | None = None,
        page_size: int = 20,
        last_message_id: int | None = None,
    ) -> ThreadDetail:
        """Describes a thread and returns a page of messages.

        Messages are returned in **descending** order (newest first).
        Use ``last_message_id`` as a cursor to page through older messages.

        Args:
            thread_id: Unique thread identifier.
            message_type: Filter messages by type. ``"conversation"`` for
                normal messages, ``"compaction"`` for summary messages.
                ``None`` returns all types.
            page_size: Number of messages per page. Default 20, max 100.
            last_message_id: Return messages older than this ID. Leave
                ``None`` for the first page.

        Returns:
            :class:`~cortex_agents_client.models.thread.ThreadDetail` with metadata
            and a page of messages.

        Raises:
            cortex_agents_client.exceptions.ThreadNotFoundError: If the thread does
                not exist or belongs to a different user.
        """
        params: dict[str, Any] = {"page_size": page_size}
        if message_type:
            params["message_type"] = message_type
        if last_message_id is not None:
            params["last_message_id"] = last_message_id

        data = self._http.request(
            "GET", f"{_THREADS_BASE}/{thread_id}", params=params, resource="thread"
        )
        return ThreadDetail.from_dict(data)

    def update(self, thread_id: int, *, thread_name: str) -> None:
        """Renames a thread.

        Args:
            thread_id: Unique thread identifier.
            thread_name: New name for the thread.

        Raises:
            cortex_agents_client.exceptions.ThreadNotFoundError: If the thread does
                not exist.
        """
        self._http.request(
            "POST",
            f"{_THREADS_BASE}/{thread_id}",
            json={"thread_name": thread_name},
            resource="thread",
        )

    def list(self, *, origin_application: str | None = None) -> list[ThreadMetadata]:
        """Lists all threads belonging to the current user.

        Args:
            origin_application: Optional filter to return only threads
                created by a specific application.

        Returns:
            List of :class:`~cortex_agents_client.models.thread.ThreadMetadata`
            objects.
        """
        params: dict[str, Any] = {}
        if origin_application:
            params["origin_application"] = origin_application

        data = self._http.request(
            "GET", _THREADS_BASE, params=params or None, resource="thread"
        )
        if isinstance(data, list):
            return [ThreadMetadata.from_dict(item) for item in data]
        return []

    def delete(self, thread_id: int) -> None:
        """Deletes a thread and all its messages.

        Args:
            thread_id: Unique thread identifier.

        Raises:
            cortex_agents_client.exceptions.ThreadNotFoundError: If the thread does
                not exist.
        """
        self._http.request(
            "DELETE", f"{_THREADS_BASE}/{thread_id}", resource="thread"
        )

    def list_messages(
        self,
        thread_id: int,
        *,
        message_type: str = "conversation",
        page_size: int = 50,
    ) -> list[ThreadMessage]:
        """Returns all messages of the specified type in chronological order.

        Paginates automatically using the ``last_message_id`` cursor until
        all messages are fetched. The returned list is ordered oldest-first.

        Args:
            thread_id: Unique thread identifier.
            message_type: ``"conversation"`` (default) or ``"compaction"``.
            page_size: Messages per page, max 100.

        Returns:
            Chronologically ordered list of
            :class:`~cortex_agents_client.models.thread.ThreadMessage` objects.
        """
        all_messages: list[ThreadMessage] = []
        last_message_id: int | None = None

        while True:
            detail = self.get(
                thread_id,
                message_type=message_type,
                page_size=page_size,
                last_message_id=last_message_id,
            )
            page = detail.messages
            if not page:
                break

            all_messages.extend(page)

            if len(page) < page_size:
                # Last page.
                break

            # Messages are returned newest-first; the last item on the page
            # is the oldest and becomes the next cursor.
            last_message_id = page[-1].message_id

        # Reverse to chronological order (oldest first).
        all_messages.reverse()
        return all_messages

    def latest_context(self, thread_id: int) -> list[ThreadMessage]:
        """Returns the latest compaction summary plus all subsequent messages.

        When a thread grows long, Cortex Agents periodically compacts older
        turns into a summary (``compaction`` message). This method returns
        the most recent summary followed by all conversation messages created
        after it — which is the minimal context needed for the next turn.

        If no compaction has occurred, all conversation messages are returned.
        Messages are ordered oldest-first.

        Args:
            thread_id: Unique thread identifier.

        Returns:
            List starting with the latest compaction message (if any),
            followed by conversation messages in chronological order.

        Example::

            context = client.threads.latest_context(thread_id)
            # context[0] is the summary (if compacted), rest are recent turns
        """
        # Step 1: fetch the newest compaction summary.
        summary_detail = self.get(
            thread_id, message_type="compaction", page_size=1
        )
        summaries = summary_detail.messages
        anchor_id = summaries[0].message_id if summaries else -1

        # Step 2: walk backward through conversation messages, collecting
        # those created after the anchor.
        collected: list[ThreadMessage] = []
        last_message_id: int | None = None
        page_size = 50

        while True:
            detail = self.get(
                thread_id,
                message_type="conversation",
                page_size=page_size,
                last_message_id=last_message_id,
            )
            page = detail.messages
            if not page:
                break

            new_messages = [m for m in page if m.message_id > anchor_id]
            collected.extend(new_messages)

            # Stop if we've crossed the anchor or reached the end.
            if len(new_messages) < len(page) or len(page) < page_size:
                break

            last_message_id = page[-1].message_id

        # Reverse to chronological order.
        collected.reverse()
        return summaries + collected
