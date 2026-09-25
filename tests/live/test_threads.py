"""Live tests: thread lifecycle — create, list, get, delete, fork, latest_context."""
from __future__ import annotations

import pytest

from streamlit_cortex_agents import CortexAgentsClient
from streamlit_cortex_agents.client.core import Thread
from streamlit_cortex_agents.client.exceptions import ThreadNotFoundError
from streamlit_cortex_agents.client.models.thread import ThreadMetadata

from tests.live.conftest import LIVE_ORIGIN_APP


@pytest.mark.live
class TestThreadCreate:
    """Thread creation."""

    def test_create_returns_metadata_with_thread_id(
        self,
        live_client: CortexAgentsClient,
    ) -> None:
        """create() returns a ThreadMetadata with a non-zero thread_id."""
        meta = live_client.threads.create(origin_application=LIVE_ORIGIN_APP)
        assert isinstance(meta, ThreadMetadata)
        assert meta.thread_id > 0
        # cleanup
        live_client.threads.delete(meta.thread_id)


@pytest.mark.live
class TestThreadGet:
    """Thread retrieval."""

    def test_get_thread_returns_correct_id(
        self,
        live_client: CortexAgentsClient,
        live_thread: Thread,
    ) -> None:
        """get() returns the same thread_id that was created."""
        detail = live_client.threads.get(live_thread.thread_id)
        assert detail.metadata.thread_id == live_thread.thread_id

    def test_get_nonexistent_thread_raises_not_found(
        self,
        live_client: CortexAgentsClient,
    ) -> None:
        """get() on a thread that doesn't exist raises ThreadNotFoundError."""
        with pytest.raises(ThreadNotFoundError):
            live_client.threads.get(999_999_999_999)


@pytest.mark.live
class TestThreadList:
    """Thread listing."""

    def test_list_with_origin_filter_returns_own_threads(
        self,
        live_client: CortexAgentsClient,
        live_thread: Thread,
    ) -> None:
        """Listing with origin_application='cac_live' includes the test thread."""
        threads = live_client.threads.list(origin_application=LIVE_ORIGIN_APP)
        thread_ids = [t.thread_id for t in threads]
        assert live_thread.thread_id in thread_ids


@pytest.mark.live
class TestThreadDelete:
    """Thread deletion."""

    def test_delete_removes_thread(
        self,
        live_client: CortexAgentsClient,
    ) -> None:
        """delete() removes the thread so a subsequent get() raises ThreadNotFoundError."""
        meta = live_client.threads.create(origin_application=LIVE_ORIGIN_APP)
        thread_id = meta.thread_id
        live_client.threads.delete(thread_id)
        with pytest.raises(ThreadNotFoundError):
            live_client.threads.get(thread_id)


@pytest.mark.live
class TestThreadFork:
    """Thread forking."""

    def test_fork_creates_new_thread(
        self,
        live_thread: Thread,
        agent_path_minimal: str,
    ) -> None:
        """fork() returns a Thread branched at the given message_id.

        Thread.fork() does NOT create a new API thread — it returns a Thread
        wrapper with the same thread_id but with parent_message_id set to the
        fork point.  Subsequent chat() calls on the fork branch from that point.
        """
        # Need at least one message so we have a message_id to fork from
        events = list(live_thread.chat(agent_path_minimal, "hello"))
        from streamlit_cortex_agents.client.models.events import MetadataEvent
        meta_event = next((e for e in events if isinstance(e, MetadataEvent) and e.role == "assistant"), None)
        if meta_event is None:
            pytest.skip("No MetadataEvent received — cannot determine message_id to fork from")

        fork = live_thread.fork(at_message_id=meta_event.message_id)
        # fork() branches within the same API thread, so thread_id is identical
        assert fork.thread_id == live_thread.thread_id
        # but the fork starts from the specified message_id
        assert fork.parent_message_id == meta_event.message_id
        # the fixture teardown handles deleting the shared thread — no separate cleanup needed


@pytest.mark.live
class TestLatestContext:
    """Thread latest_context."""

    def test_latest_context_returns_list(
        self,
        live_thread: Thread,
    ) -> None:
        """latest_context() returns a list (may be empty for a fresh thread)."""
        context = live_thread.latest_context()
        assert isinstance(context, list)

    def test_latest_context_after_chat_contains_messages(
        self,
        live_thread: Thread,
        agent_path_minimal: str,
    ) -> None:
        """latest_context() returns at least 2 messages after one chat turn."""
        list(live_thread.chat(agent_path_minimal, "hello"))
        context = live_thread.latest_context()
        assert len(context) >= 2  # at least user + assistant
