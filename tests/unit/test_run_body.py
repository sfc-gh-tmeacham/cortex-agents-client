"""Unit tests for agent:run request body construction.

Covers the ``models`` / deprecated ``model`` resolution, the lite-run
``orchestration`` budget, and the ``background`` flag. These assert on the
exact request body because a wrong field name still returns HTTP 200 from a
mocked transport — only the body shape reveals the defect.
"""
from __future__ import annotations

import pytest

from cortex_agents_client.auth import PATAuth
from cortex_agents_client.http import HttpClient
from cortex_agents_client.resources.runs import RunsResource

MESSAGES = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]


@pytest.fixture
def runs() -> RunsResource:
    http = HttpClient(
        base_url="https://testorg.snowflakecomputing.com",
        auth=PATAuth("v2:test_token"),
        timeout=5.0,
    )
    return RunsResource(http, "TEST_DB", "TEST_SCHEMA")


class TestModelConfig:
    """The request must carry a `models` object, not a bare `model` string."""

    def test_models_dict_sent_verbatim(self, runs):
        body = runs._build_body(MESSAGES, models={"orchestration": "claude-4-sonnet"})
        assert body["models"] == {"orchestration": "claude-4-sonnet"}
        assert "model" not in body

    def test_deprecated_model_maps_into_models(self, runs):
        with pytest.warns(DeprecationWarning, match="'model' argument is deprecated"):
            body = runs._build_body(MESSAGES, model="claude-4-sonnet")
        # The legacy bare `model` string must not reach the wire.
        assert "model" not in body
        assert body["models"] == {"orchestration": "claude-4-sonnet"}

    def test_models_wins_over_model(self, runs):
        with pytest.warns(DeprecationWarning, match="'model' is ignored"):
            body = runs._build_body(
                MESSAGES,
                models={"orchestration": "claude-4-sonnet"},
                model="llama3.1-70b",
            )
        assert body["models"] == {"orchestration": "claude-4-sonnet"}

    def test_no_models_key_when_neither_given(self, runs):
        body = runs._build_body(MESSAGES)
        assert "models" not in body
        assert "model" not in body

    def test_no_warning_when_only_models_given(self, runs):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            runs._build_body(MESSAGES, models={"orchestration": "claude-4-sonnet"})


class TestOrchestrationBudget:
    """Lite runs can constrain orchestration time and tokens."""

    def test_orchestration_sent(self, runs):
        budget = {"budget": {"seconds": 30, "tokens": 16000}}
        body = runs._build_body(MESSAGES, orchestration=budget)
        assert body["orchestration"] == budget

    def test_orchestration_omitted_when_none(self, runs):
        assert "orchestration" not in runs._build_body(MESSAGES)


class TestBackgroundFlag:
    """`background` is only emitted when explicitly enabled."""

    def test_background_true_sent(self, runs):
        body = runs._build_body(MESSAGES, thread_id=1, background=True)
        assert body["background"] is True

    def test_background_false_omitted(self, runs):
        body = runs._build_body(MESSAGES, thread_id=1, background=False)
        assert "background" not in body

    def test_background_default_omitted(self, runs):
        assert "background" not in runs._build_body(MESSAGES, thread_id=1)


class TestExistingFields:
    """Guards the fields that already worked, to catch collateral damage."""

    def test_stream_flag_always_present(self, runs):
        assert runs._build_body(MESSAGES, stream=True)["stream"] is True
        assert runs._build_body(MESSAGES, stream=False)["stream"] is False

    def test_thread_id_pairs_with_parent_message_id(self, runs):
        body = runs._build_body(MESSAGES, thread_id=42, parent_message_id=7)
        assert body["thread_id"] == 42
        assert body["parent_message_id"] == 7

    def test_parent_message_id_omitted_without_thread(self, runs):
        body = runs._build_body(MESSAGES)
        assert "thread_id" not in body
        assert "parent_message_id" not in body
