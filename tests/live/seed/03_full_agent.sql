-- Seed script 03: full agent with Cortex Search tool.
--
-- Run AFTER 02_search_service.sql — the search service must exist before
-- the agent is created (it is referenced in tool_resources).
--
-- Adjust names to match your test account.

CREATE AGENT IF NOT EXISTS live_test_db.live_test_schema.full_agent
  COMMENT = 'Search-enabled agent used by cortex-agents-client full live integration tests.'
  FROM SPECIFICATION
  $$
  instructions:
    response: 'You are a helpful assistant. Use the DocSearch tool to answer questions about products, pricing, and policies. Always cite your sources.'

  tools:
    - tool_spec:
        type: cortex_search
        name: DocSearch
        description: 'Search product documentation, pricing guides, and policies.'

  tool_resources:
    DocSearch:
      name: live_test_db.live_test_schema.doc_search
      title_column: title
      id_column: doc_id
      max_results: '3'
  $$;

GRANT USAGE ON AGENT live_test_db.live_test_schema.full_agent
  TO ROLE app_owner_role;
