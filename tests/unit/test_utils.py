"""Unit tests for utility functions (agent path parsing, DataFrame conversion)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cortex_agents_client.resources.runs import RunsResource
from cortex_agents_client.http import HttpClient
from cortex_agents_client.auth import PATAuth


def make_runs_resource(default_db=None, default_schema=None):
    """Creates a RunsResource with a dummy HTTP client for path resolution tests."""
    http = HttpClient("https://test.snowflakecomputing.com", PATAuth("tok"))
    return RunsResource(http, default_database=default_db, default_schema=default_schema)


class TestAgentPathResolution:
    """Tests for agent_path parsing in RunsResource._resolve_path."""

    def test_three_part_path(self):
        """'DB.SCHEMA.AGENT' resolves all three parts correctly."""
        runs = make_runs_resource()
        path = runs._resolve_path(agent_path="MY_DB.MY_SCHEMA.MY_AGENT")
        assert "/databases/MY_DB/schemas/MY_SCHEMA/agents/MY_AGENT:run" in path

    def test_two_part_path_uses_default_database(self):
        """'SCHEMA.AGENT' with default_database resolves correctly."""
        runs = make_runs_resource(default_db="DEFAULT_DB")
        path = runs._resolve_path(agent_path="MY_SCHEMA.MY_AGENT")
        assert "/databases/DEFAULT_DB/schemas/MY_SCHEMA/agents/MY_AGENT:run" in path

    def test_one_part_path_uses_both_defaults(self):
        """'AGENT' with defaults for both database and schema resolves correctly."""
        runs = make_runs_resource(default_db="DEFAULT_DB", default_schema="DEFAULT_SCHEMA")
        path = runs._resolve_path(agent_path="MY_AGENT")
        assert "/databases/DEFAULT_DB/schemas/DEFAULT_SCHEMA/agents/MY_AGENT:run" in path

    def test_three_part_path_overrides_defaults(self):
        """Three-part path overrides defaults completely."""
        runs = make_runs_resource(default_db="OTHER_DB", default_schema="OTHER_SCHEMA")
        path = runs._resolve_path(agent_path="EXPLICIT_DB.EXPLICIT_SCHEMA.MY_AGENT")
        assert "EXPLICIT_DB" in path
        assert "EXPLICIT_SCHEMA" in path
        assert "OTHER_DB" not in path

    def test_two_part_path_missing_default_database_raises(self):
        """Two-part path without default_database raises ValueError."""
        runs = make_runs_resource()  # No defaults
        with pytest.raises(ValueError, match="database"):
            runs._resolve_path(agent_path="SCHEMA.AGENT")

    def test_one_part_path_missing_defaults_raises(self):
        """One-part path without defaults raises ValueError."""
        runs = make_runs_resource()
        with pytest.raises(ValueError):
            runs._resolve_path(agent_path="AGENT")

    def test_none_agent_path_returns_none(self):
        """No agent_path specified returns None (lite run)."""
        runs = make_runs_resource()
        result = runs._resolve_path()
        assert result is None

    def test_agent_name_with_database_schema(self):
        """agent= kwarg with explicit database and schema resolves correctly."""
        runs = make_runs_resource()
        path = runs._resolve_path(agent="MY_AGENT", database="DB", schema="SC")
        assert "/databases/DB/schemas/SC/agents/MY_AGENT:run" in path


class TestResultSetToDataframe:
    """Tests for result_set_to_dataframe type casting."""

    @pytest.fixture
    def table_event_factory(self):
        """Returns a factory for creating TableEvent instances."""
        from cortex_agents_client.models.events import TableEvent

        def _make(row_types, data):
            payload = {
                "content_index": 0,
                "tool_use_id": "t1",
                "query_id": "q1",
                "result_set": {
                    "statementHandle": "s1",
                    "resultSetMetaData": {
                        "partition": 0,
                        "numRows": len(data),
                        "format": "jsonv2",
                        "rowType": row_types,
                    },
                    "data": data,
                },
                "title": None,
            }
            return TableEvent._from_payload(payload)

        return _make

    def test_column_names_match_row_types(self, table_event_factory):
        """DataFrame columns match rowType names."""
        import pandas as pd
        from cortex_agents_client.st.render import result_set_to_dataframe

        event = table_event_factory(
            [
                {"name": "YEAR", "type": "INTEGER", "length": 0, "precision": 10, "scale": 0, "nullable": False},
                {"name": "REVENUE", "type": "FLOAT", "length": 0, "precision": 15, "scale": 2, "nullable": True},
            ],
            [["2025", "4200000000.00"]],
        )
        df = result_set_to_dataframe(event)
        assert list(df.columns) == ["YEAR", "REVENUE"]

    def test_integer_type_casting(self, table_event_factory):
        """INTEGER rowType → Int64 dtype."""
        from cortex_agents_client.st.render import result_set_to_dataframe

        event = table_event_factory(
            [{"name": "COUNT", "type": "INTEGER", "length": 0, "precision": 10, "scale": 0, "nullable": False}],
            [["42"]],
        )
        df = result_set_to_dataframe(event)
        assert df["COUNT"].dtype.name == "Int64"

    def test_float_type_casting(self, table_event_factory):
        """FLOAT rowType → float64 dtype."""
        from cortex_agents_client.st.render import result_set_to_dataframe

        event = table_event_factory(
            [{"name": "AMOUNT", "type": "FLOAT", "length": 0, "precision": 15, "scale": 2, "nullable": True}],
            [["3.14"]],
        )
        df = result_set_to_dataframe(event)
        assert df["AMOUNT"].dtype.name == "float64"

    def test_varchar_type_stays_as_string(self, table_event_factory):
        """VARCHAR rowType → object dtype (string)."""
        from cortex_agents_client.st.render import result_set_to_dataframe

        event = table_event_factory(
            [{"name": "NAME", "type": "VARCHAR", "length": 255, "precision": 0, "scale": 0, "nullable": True}],
            [["Alice"], ["Bob"]],
        )
        df = result_set_to_dataframe(event)
        assert df["NAME"].dtype.name in ("object", "str")  # 'object' pre-pandas 3, 'str' from pandas 3+

    def test_empty_result_set_returns_empty_dataframe(self, table_event_factory):
        """Empty result set returns DataFrame with correct columns but no rows."""
        from cortex_agents_client.st.render import result_set_to_dataframe

        event = table_event_factory(
            [{"name": "ID", "type": "INTEGER", "length": 0, "precision": 10, "scale": 0, "nullable": False}],
            [],
        )
        df = result_set_to_dataframe(event)
        assert len(df) == 0
        assert "ID" in df.columns

    def test_empty_row_types_returns_empty_dataframe(self, table_event_factory):
        """No rowType metadata → empty DataFrame."""
        from cortex_agents_client.models.events import TableEvent
        from cortex_agents_client.st.render import result_set_to_dataframe

        payload = {
            "content_index": 0,
            "tool_use_id": "t1",
            "query_id": "q1",
            "result_set": {
                "statementHandle": "s1",
                "resultSetMetaData": {"partition": 0, "numRows": 0, "format": "jsonv2", "rowType": []},
                "data": [],
            },
            "title": None,
        }
        event = TableEvent._from_payload(payload)
        df = result_set_to_dataframe(event)
        assert len(df) == 0


class TestToolExecutor:
    """Tests for Thread.chat() tool_executor callback (Gap 3 — client-side tools)."""

    def _make_thread(self):
        """Creates a Thread with a mocked HTTP client."""
        from cortex_agents_client.client import CortexAgentsClient, Thread

        client = MagicMock(spec=CortexAgentsClient)
        client.runs = MagicMock()
        thread = Thread(client, thread_id=1, parent_message_id=0)
        return thread, client

    def test_tool_executor_called_for_client_side_tool(self):
        """tool_executor is called when ToolUseEvent has client_side_execute=True."""
        from cortex_agents_client.models.events import (
            MetadataEvent,
            TextEvent,
            ToolResultEvent,
            ToolUseEvent,
        )

        thread, client = self._make_thread()
        executor = MagicMock(return_value=[{"type": "json", "json": {"result": 42}}])

        client_tool_event = ToolUseEvent._from_payload({
            "content_index": 0,
            "tool_use_id": "toolu_client",
            "type": "generic",
            "name": "MyUDF",
            "input": {"x": 1},
            "client_side_execute": True,
            "permission": {"options": []},
        })
        meta = MetadataEvent._from_payload(
            {"metadata": {"role": "assistant", "message_id": 99, "run_id": "r1"}}
        )
        text = TextEvent._from_payload({"content_index": 0, "text": "Done."})

        # First stream: client-side tool event only
        # Second stream (follow-up): text + metadata
        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return iter([client_tool_event])
            return iter([text, meta])

        client.runs.stream.side_effect = side_effect

        events = list(thread.chat("DB.SC.AGENT", "Hello", tool_executor=executor))

        executor.assert_called_once_with(client_tool_event)
        assert client.runs.stream.call_count == 2

        # ToolUseEvent and synthetic ToolResultEvent yielded from first stream
        event_types = [type(e).__name__ for e in events]
        assert "ToolUseEvent" in event_types
        assert "ToolResultEvent" in event_types
        assert "TextEvent" in event_types

    def test_tool_executor_exception_yields_error_result(self):
        """If tool_executor raises, a 'error' status ToolResultEvent is yielded."""
        from cortex_agents_client.models.events import (
            MetadataEvent,
            TextEvent,
            ToolResultEvent,
            ToolUseEvent,
        )

        thread, client = self._make_thread()
        executor = MagicMock(side_effect=RuntimeError("Tool failed"))

        client_tool_event = ToolUseEvent._from_payload({
            "content_index": 0,
            "tool_use_id": "toolu_err",
            "type": "generic",
            "name": "BrokenUDF",
            "input": {},
            "client_side_execute": True,
            "permission": {"options": []},
        })
        meta = MetadataEvent._from_payload(
            {"metadata": {"role": "assistant", "message_id": 10, "run_id": "r1"}}
        )

        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return iter([client_tool_event])
            return iter([meta])

        client.runs.stream.side_effect = side_effect

        events = list(thread.chat("DB.SC.AGENT", "Hello", tool_executor=executor))

        # Synthetic ToolResultEvent should have status="error"
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
        assert len(tool_results) == 1
        assert tool_results[0].status == "error"
        assert tool_results[0].tool_use_id == "toolu_err"

    def test_no_tool_executor_client_side_event_yields_normally(self):
        """client_side_execute=True without tool_executor → event yielded unchanged."""
        from cortex_agents_client.models.events import MetadataEvent, ToolUseEvent

        thread, client = self._make_thread()

        client_tool_event = ToolUseEvent._from_payload({
            "content_index": 0,
            "tool_use_id": "toolu_pass",
            "type": "generic",
            "name": "MyUDF",
            "input": {},
            "client_side_execute": True,
            "permission": {"options": []},
        })
        meta = MetadataEvent._from_payload(
            {"metadata": {"role": "assistant", "message_id": 5, "run_id": "r1"}}
        )

        client.runs.stream.return_value = iter([client_tool_event, meta])

        events = list(thread.chat("DB.SC.AGENT", "Hello"))  # No tool_executor

        # Event should pass through unmodified (no follow-up request)
        assert client.runs.stream.call_count == 1
        assert any(isinstance(e, ToolUseEvent) for e in events)


class TestRecursionGuard:
    """Tests for the _MAX_TOOL_ITERATIONS safety limit in Thread.chat()."""

    def _make_thread(self):
        from cortex_agents_client.client import CortexAgentsClient, Thread

        client = MagicMock(spec=CortexAgentsClient)
        client.runs = MagicMock()
        thread = Thread(client, thread_id=1, parent_message_id=0)
        return thread, client

    def test_raises_runtime_error_after_max_iterations(self):
        """Thread.chat() raises RuntimeError after _MAX_TOOL_ITERATIONS."""
        from cortex_agents_client.client import Thread
        from cortex_agents_client.models.events import ToolUseEvent

        thread, client = self._make_thread()

        # Every stream returns a client-side tool event, creating an infinite loop
        client_tool_event = ToolUseEvent._from_payload({
            "content_index": 0,
            "tool_use_id": "toolu_loop",
            "type": "generic",
            "name": "InfiniteTool",
            "input": {},
            "client_side_execute": True,
            "permission": {"options": []},
        })
        client.runs.stream.return_value = iter([client_tool_event])
        # Make stream return a fresh iterator each call
        client.runs.stream.side_effect = lambda *a, **kw: iter([client_tool_event])

        executor = MagicMock(return_value=[{"type": "json", "json": {}}])

        with pytest.raises(RuntimeError, match="exceeded.*iterations"):
            list(thread.chat("DB.SC.AGENT", "loop", tool_executor=executor))

        assert executor.call_count == Thread._MAX_TOOL_ITERATIONS


class TestContextManager:
    """Tests for CortexAgentsClient context manager support."""

    def test_context_manager_calls_close(self):
        from cortex_agents_client.client import CortexAgentsClient

        with patch.object(CortexAgentsClient, "close") as mock_close:
            client = CortexAgentsClient("https://test.snowflakecomputing.com", "v2:tok")
            with client:
                pass
            mock_close.assert_called_once()

    def test_context_manager_calls_close_on_exception(self):
        from cortex_agents_client.client import CortexAgentsClient

        with patch.object(CortexAgentsClient, "close") as mock_close:
            client = CortexAgentsClient("https://test.snowflakecomputing.com", "v2:tok")
            with pytest.raises(ValueError):
                with client:
                    raise ValueError("test error")
            mock_close.assert_called_once()


class TestURLEncoding:
    """Tests that special characters in identifiers are URL-encoded."""

    def test_resolve_path_encodes_spaces(self):
        from cortex_agents_client.resources.runs import RunsResource
        from cortex_agents_client.http import HttpClient
        from cortex_agents_client.auth import PATAuth

        http = HttpClient("https://test.snowflakecomputing.com", PATAuth("v2:tok"))
        runs = RunsResource(http)
        path = runs._resolve_path(agent_path="MY DB.MY SCHEMA.MY AGENT")
        assert "MY%20DB" in path
        assert "MY%20SCHEMA" in path
        assert "MY%20AGENT" in path
        http.close()

    def test_resolve_path_encodes_slashes(self):
        from cortex_agents_client.resources.runs import RunsResource
        from cortex_agents_client.http import HttpClient
        from cortex_agents_client.auth import PATAuth

        http = HttpClient("https://test.snowflakecomputing.com", PATAuth("v2:tok"))
        runs = RunsResource(http)
        path = runs._resolve_path(agent_path="DB.SC.agent/name")
        assert "agent%2Fname" in path
        http.close()

    def test_agents_path_encodes_special_chars(self):
        from cortex_agents_client.resources.agents import AgentsResource
        from cortex_agents_client.http import HttpClient
        from cortex_agents_client.auth import PATAuth

        http = HttpClient("https://test.snowflakecomputing.com", PATAuth("v2:tok"))
        agents = AgentsResource(http)
        path = agents._path("MY DB", "MY SCHEMA", "MY AGENT")
        assert "MY%20DB" in path
        assert "MY%20SCHEMA" in path
        assert "MY%20AGENT" in path
        http.close()
