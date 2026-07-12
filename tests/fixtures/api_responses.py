"""Mock API response fixtures for integration tests."""
from __future__ import annotations

import json

AGENT_DESCRIBE_RESPONSE = {
    "name": "MY_AGENT",
    "database_name": "TEST_DB",
    "schema_name": "TEST_SCHEMA",
    "owner": "ACCOUNTADMIN",
    "comment": "Test agent",
    "created_on": "2024-06-01T12:00:00Z",
    "profile": {"display_name": "My Agent"},
    "agent_spec": json.dumps({
        "models": {"orchestration": "claude-4-sonnet"},
        "instructions": {
            "response": "Be concise.",
            "orchestration": "Use Analyst for revenue questions.",
        },
        "tools": [
            {"tool_spec": {"type": "cortex_analyst_text_to_sql", "name": "Analyst1"}}
        ],
        "tool_resources": {
            "Analyst1": {
                "semantic_view": "TEST_DB.TEST_SCHEMA.REVENUE_VIEW",
                "execution_environment": {"type": "warehouse", "warehouse": "MY_WH"},
            }
        },
    }),
}

AGENT_LIST_RESPONSE = [
    {
        "name": "AGENT_ONE",
        "database": "TEST_DB",
        "schema": "TEST_SCHEMA",
        "created_on": "2024-06-01T12:00:00Z",
        "owner": "ACCOUNTADMIN",
        "comment": "",
        "profile": {"display_name": "Agent One"},
    },
    {
        "name": "AGENT_TWO",
        "database": "TEST_DB",
        "schema": "TEST_SCHEMA",
        "created_on": "2024-06-02T08:30:00Z",
        "owner": "SYSADMIN",
        "comment": "second agent",
        "profile": {"display_name": "Agent Two"},
    },
]

THREAD_CREATE_RESPONSE = {
    "thread_id": 1234567890,
    "thread_name": "",
    "origin_application": "test_app",
    "created_on": 1717000000000,
    "updated_on": 1717000000000,
}

THREAD_DESCRIBE_RESPONSE = {
    "metadata": {
        "thread_id": 1234567890,
        "thread_name": "Test Thread",
        "origin_application": "test_app",
        "created_on": 1717000000000,
        "updated_on": 1717000100000,
    },
    "messages": [
        {
            "message_id": 2,
            "parent_id": 1,
            "created_on": 1717000001000,
            "role": "assistant",
            "message_payload": "The revenue was $4.2B.",
            "request_id": "req_002",
            "message_type": "conversation",
        },
        {
            "message_id": 1,
            "parent_id": None,
            "created_on": 1717000000000,
            "role": "user",
            "message_payload": "What is revenue?",
            "request_id": "req_001",
            "message_type": "conversation",
        },
    ],
}

NON_STREAMING_RUN_RESPONSE = {
    "role": "assistant",
    "content": [
        {"type": "text", "text": "The revenue was $4.2B."},
        {
            "type": "table",
            "table": {
                "tool_use_id": "toolu_01",
                "query_id": "qid_abc",
                "result_set": {
                    "statementHandle": "stmnt_abc",
                    "resultSetMetaData": {
                        "partition": 0,
                        "numRows": 1,
                        "format": "jsonv2",
                        "rowType": [
                            {"name": "REVENUE", "type": "FLOAT", "length": 0,
                             "precision": 15, "scale": 2, "nullable": True}
                        ],
                    },
                    "data": [["4200000000.00"]],
                },
                "title": "Revenue",
            },
        },
    ],
    "status": "completed",
    "error": None,
}
