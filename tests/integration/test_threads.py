"""Integration tests for ThreadsResource using pytest-httpx."""
from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from cortex_agents_client.exceptions import ThreadNotFoundError
from tests.fixtures.api_responses import THREAD_CREATE_RESPONSE, THREAD_DESCRIBE_RESPONSE


class TestCreateThread:
    """Tests for threads.create()."""

    def test_create_returns_metadata(self, ca_client, httpx_mock: HTTPXMock):
        """create() returns ThreadMetadata with correct thread_id."""
        httpx_mock.add_response(method="POST", json=THREAD_CREATE_RESPONSE)
        meta = ca_client.threads.create(origin_application="test_app")
        assert meta.thread_id == 1234567890
        assert meta.origin_application == "test_app"

    def test_create_with_origin_application_in_body(self, ca_client, httpx_mock: HTTPXMock):
        """origin_application is included in the request body."""
        captured: dict = {}

        def responder(request):
            import json, httpx
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=THREAD_CREATE_RESPONSE)

        httpx_mock.add_callback(responder)
        ca_client.threads.create(origin_application="my_app")
        assert captured["body"].get("origin_application") == "my_app"

    def test_create_without_origin_application(self, ca_client, httpx_mock: HTTPXMock):
        """create() without origin_application sends empty body."""
        httpx_mock.add_response(method="POST", json=THREAD_CREATE_RESPONSE)
        meta = ca_client.threads.create()
        assert meta.thread_id == 1234567890


class TestGetThread:
    """Tests for threads.get()."""

    def test_get_returns_thread_detail(self, ca_client, httpx_mock: HTTPXMock):
        """get() returns ThreadDetail with metadata and messages."""
        httpx_mock.add_response(json=THREAD_DESCRIBE_RESPONSE)
        detail = ca_client.threads.get(1234567890)
        assert detail.metadata.thread_id == 1234567890
        assert len(detail.messages) == 2
        assert detail.messages[0].role == "assistant"

    def test_get_404_raises_thread_not_found(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 404 raises ThreadNotFoundError."""
        httpx_mock.add_response(status_code=404, json={"message": "Thread not found"})
        with pytest.raises(ThreadNotFoundError):
            ca_client.threads.get(9999)

    def test_get_with_message_type_filter(self, ca_client, httpx_mock: HTTPXMock):
        """message_type='compaction' is sent as query param."""
        captured: list[str] = []

        def responder(request):
            captured.append(str(request.url))
            return httpx.Response(200, json=THREAD_DESCRIBE_RESPONSE)

        httpx_mock.add_callback(responder)
        ca_client.threads.get(1234567890, message_type="compaction")
        assert "message_type=compaction" in captured[0]


class TestListMessages:
    """Tests for threads.list_messages()."""

    def test_list_messages_paginates(self, ca_client, httpx_mock: HTTPXMock):
        """list_messages() pages through results using last_message_id cursor."""
        # First page: 2 messages (equals page_size=2 → triggers next page)
        page1 = {
            "metadata": THREAD_DESCRIBE_RESPONSE["metadata"],
            "messages": [
                {"message_id": 4, "parent_id": 3, "created_on": 4000, "role": "assistant",
                 "message_payload": "reply2", "request_id": "r4", "message_type": "conversation"},
                {"message_id": 3, "parent_id": 2, "created_on": 3000, "role": "user",
                 "message_payload": "msg2", "request_id": "r3", "message_type": "conversation"},
            ],
        }
        # Second page: 1 message (< page_size → last page)
        page2 = {
            "metadata": THREAD_DESCRIBE_RESPONSE["metadata"],
            "messages": [
                {"message_id": 2, "parent_id": 1, "created_on": 2000, "role": "assistant",
                 "message_payload": "reply1", "request_id": "r2", "message_type": "conversation"},
            ],
        }
        httpx_mock.add_response(json=page1)
        httpx_mock.add_response(json=page2)

        messages = ca_client.threads.list_messages(1234567890, page_size=2)
        # Should be chronological (oldest first) after reversal
        assert len(messages) == 3
        assert messages[0].message_id == 2   # oldest
        assert messages[-1].message_id == 4  # newest


class TestLatestContext:
    """Tests for threads.latest_context()."""

    def test_latest_context_no_compaction(self, ca_client, httpx_mock: HTTPXMock):
        """When no compaction exists, returns all conversation messages."""
        # Compaction page: empty
        httpx_mock.add_response(
            json={"metadata": THREAD_DESCRIBE_RESPONSE["metadata"], "messages": []}
        )
        # Conversation page
        httpx_mock.add_response(json=THREAD_DESCRIBE_RESPONSE)

        context = ca_client.threads.latest_context(1234567890)
        # 0 summaries + 2 conversation messages, chronological
        assert len(context) == 2
        assert context[0].message_id == 1  # oldest

    def test_latest_context_with_compaction(self, ca_client, httpx_mock: HTTPXMock):
        """When compaction exists, returns summary + messages after anchor."""
        summary = {
            "metadata": THREAD_DESCRIBE_RESPONSE["metadata"],
            "messages": [
                {"message_id": 10, "parent_id": 9, "created_on": 10000, "role": "assistant",
                 "message_payload": "Summary", "request_id": "r10", "message_type": "compaction"},
            ],
        }
        # Conversation messages: ids 11 and 12 (after anchor 10), id 9 (before anchor)
        conversations = {
            "metadata": THREAD_DESCRIBE_RESPONSE["metadata"],
            "messages": [
                {"message_id": 12, "parent_id": 11, "created_on": 12000, "role": "assistant",
                 "message_payload": "a2", "request_id": "r12", "message_type": "conversation"},
                {"message_id": 11, "parent_id": 10, "created_on": 11000, "role": "user",
                 "message_payload": "q2", "request_id": "r11", "message_type": "conversation"},
                {"message_id": 9, "parent_id": 8, "created_on": 9000, "role": "user",
                 "message_payload": "old", "request_id": "r9", "message_type": "conversation"},
            ],
        }
        httpx_mock.add_response(json=summary)
        httpx_mock.add_response(json=conversations)

        context = ca_client.threads.latest_context(1234567890)
        # Summary (id=10) + messages 11, 12 (after anchor 10), not 9
        assert len(context) == 3
        assert context[0].message_id == 10  # summary
        assert context[1].message_id == 11
        assert context[2].message_id == 12


class TestDeleteThread:
    """Tests for threads.delete()."""

    def test_delete_happy_path(self, ca_client, httpx_mock: HTTPXMock):
        """Successful delete returns without error."""
        httpx_mock.add_response(method="DELETE", json={"success": True})
        ca_client.threads.delete(1234567890)

    def test_delete_404_raises_thread_not_found(self, ca_client, httpx_mock: HTTPXMock):
        """HTTP 404 raises ThreadNotFoundError."""
        httpx_mock.add_response(status_code=404, json={"message": "not found"})
        with pytest.raises(ThreadNotFoundError):
            ca_client.threads.delete(9999)
