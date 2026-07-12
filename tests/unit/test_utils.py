"""Unit tests for utility functions (agent path parsing, DataFrame conversion)."""
from __future__ import annotations

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
        assert df["NAME"].dtype.name == "object"

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
