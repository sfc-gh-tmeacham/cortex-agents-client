-- Seed script 03: full agent with Cortex Search tool.
--
-- Run AFTER 02_search_service.sql — the search service must exist before
-- the agent is created (it is referenced in TOOL_RESOURCES).
--
-- Adjust names to match your test account.

CREATE CORTEX AGENT IF NOT EXISTS live_test_db.live_test_schema.full_agent
  COMMENT = 'Search-enabled agent used by cortex-agents-client full live integration tests.'
  INSTRUCTIONS = (
    SYSTEM = 'You are a helpful assistant. Use the DocSearch tool to answer questions about products, pricing, and policies. Always cite your sources.'
  )
  TOOLS = (
    {
      'tool_spec': {
        'type': 'cortex_search',
        'name': 'DocSearch'
      }
    }
  )
  TOOL_RESOURCES = {
    'DocSearch': {
      'search_service': 'live_test_db.live_test_schema.doc_search',
      'title_column':   'title',
      'id_column':      'doc_id',
      'max_results':    3
    }
  };

GRANT USAGE ON CORTEX AGENT live_test_db.live_test_schema.full_agent
  TO ROLE app_owner_role;
