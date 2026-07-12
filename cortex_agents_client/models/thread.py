"""Data models for threads and conversation history.

Represents thread metadata, individual messages, and the ``StoredMessage``
dataclass used by the Streamlit integration to persist rendered content
across reruns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cortex_agents_client.models.events import (
        ChartEvent,
        ErrorEvent,
        TableEvent,
        TextAnnotationEvent,
        ToolResultEvent,
        ToolUseEvent,
        WarningEvent,
    )


@dataclass
class ThreadMetadata:
    """Metadata returned when creating or listing threads.

    Attributes:
        thread_id: Unique integer identifier for the thread.
        thread_name: Optional human-readable name.
        origin_application: Application that created the thread.
            Limited to 16 bytes by the API.
        created_on: Unix timestamp in milliseconds when the thread was created.
        updated_on: Unix timestamp in milliseconds when the thread was last
            updated (any new message counts as an update).
    """

    thread_id: int = 0
    thread_name: str = ""
    origin_application: str = ""
    created_on: int = 0
    updated_on: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThreadMetadata:
        """Creates a ThreadMetadata from an API response dict.

        Args:
            data: Dict from the create/list thread API response.

        Returns:
            A populated ThreadMetadata instance.
        """
        return cls(
            thread_id=int(data.get("thread_id", 0)),
            thread_name=data.get("thread_name", ""),
            origin_application=data.get("origin_application", ""),
            created_on=int(data.get("created_on", 0)),
            updated_on=int(data.get("updated_on", 0)),
        )


@dataclass
class ThreadMessage:
    """A single message stored in a thread.

    Messages are returned in **descending** order (newest first) by the
    describe thread endpoint.

    Attributes:
        message_id: Unique integer identifier for this message.
        parent_id: ID of the parent message, or ``None`` for root messages.
        created_on: Unix timestamp in milliseconds.
        role: ``"user"`` or ``"assistant"``.
        message_payload: The message content as a string.
        request_id: Snowflake request ID associated with this message.
        message_type: ``"conversation"`` for normal messages,
            ``"compaction"`` for thread summary messages.
    """

    message_id: int = 0
    parent_id: int | None = None
    created_on: int = 0
    role: str = ""
    message_payload: str = ""
    request_id: str = ""
    message_type: str = "conversation"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThreadMessage:
        """Creates a ThreadMessage from an API response dict.

        Args:
            data: Dict from the describe thread messages array.

        Returns:
            A populated ThreadMessage instance.
        """
        parent_raw = data.get("parent_id")
        return cls(
            message_id=int(data.get("message_id", 0)),
            parent_id=int(parent_raw) if parent_raw is not None else None,
            created_on=int(data.get("created_on", 0)),
            role=data.get("role", ""),
            message_payload=str(data.get("message_payload", "")),
            request_id=data.get("request_id", ""),
            message_type=data.get("message_type", "conversation"),
        )


@dataclass
class ThreadDetail:
    """A thread with its messages, as returned by the describe endpoint.

    Attributes:
        metadata: Thread metadata.
        messages: List of messages in the thread, newest first.
    """

    metadata: ThreadMetadata = field(default_factory=ThreadMetadata)
    messages: list[ThreadMessage] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThreadDetail:
        """Creates a ThreadDetail from an API response dict.

        Args:
            data: Dict with ``metadata`` and ``messages`` keys.

        Returns:
            A populated ThreadDetail instance.
        """
        meta_raw = data.get("metadata") or {}
        messages_raw = data.get("messages") or []
        return cls(
            metadata=ThreadMetadata.from_dict(meta_raw),
            messages=[ThreadMessage.from_dict(m) for m in messages_raw],
        )


@dataclass
class StoredMessage:
    """A complete conversation turn stored in Streamlit session state.

    This is the canonical representation used by the Streamlit integration
    for both streaming new messages and replaying history on reruns.
    Every field is designed so that :func:`cortex_agents_client.st.render.render_stored_message`
    can produce identical output to the original streaming render.

    Attributes:
        role: ``"user"`` or ``"assistant"``.
        text: Final assembled text from all ``response.text`` events.
            May contain ``[^N]`` citation markers.
        thinking: Agent reasoning text from ``response.thinking`` events.
            ``None`` if the model did not emit thinking.
        is_elicitation: ``True`` if the agent is asking the user for more
            information rather than providing an answer. Use this flag to
            render the message with a distinct visual treatment so the user
            understands a response is required.
        tables: Ordered list of table events from ``response.table`` events.
        charts: Ordered list of chart events from ``response.chart`` events.
        annotations: Citation annotations from ``response.text.annotation``
            events, used to render a citations section below the text.
        tool_executions: Pairs of ``(ToolUseEvent, ToolResultEvent | None)``
            for each tool invocation in this turn.
        warnings: Warning events emitted during this turn.
        error: Fatal error event if the run terminated with an error.
        analyst_sql: Maps ``tool_use_id`` to SQL string from
            ``response.tool_result.analyst.delta`` events.
            Useful for displaying generated SQL.
        message_id: Thread message ID from the ``metadata`` event for the
            assistant message. ``None`` for user messages or if the server
            did not persist the message.
        attachments: Uploaded file or audio objects attached to a user message
            via ``st.chat_input(accept_file=True)`` or ``accept_audio=True``.
            Stored as-is; Streamlit ``UploadedFile`` objects survive
            ``st.session_state`` reruns so history replay can display them.
    """

    role: str
    text: str = ""
    thinking: str | None = None
    is_elicitation: bool = False
    tables: list[TableEvent] = field(default_factory=list)
    charts: list[ChartEvent] = field(default_factory=list)
    annotations: list[TextAnnotationEvent] = field(default_factory=list)
    tool_executions: list[tuple[ToolUseEvent, ToolResultEvent | None]] = field(
        default_factory=list
    )
    warnings: list[WarningEvent] = field(default_factory=list)
    error: ErrorEvent | None = None
    analyst_sql: dict[str, str] = field(default_factory=dict)
    message_id: int | None = None
    attachments: list[Any] = field(default_factory=list)
    tool_result_text: dict[str, str] = field(default_factory=dict)
    """Maps tool_use_id to concatenated text from ToolResultContent.text items.

    Populated when a ToolResultEvent contains content items with type "text"
    (e.g. results from generic or web_search tools). Used by render_stored_message
    to replay text results on Streamlit reruns.
    """
    pending_permission: ToolUseEvent | None = None
    """Set when the stream was interrupted by a tool requiring user permission.

    Contains the ToolUseEvent with non-empty permission_options. The Streamlit
    chatbot component uses this to show an approval UI on the next rerun, then
    clears it once the user submits a decision.
    """
