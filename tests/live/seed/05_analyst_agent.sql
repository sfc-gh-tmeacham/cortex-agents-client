-- Seed script 05: Cortex Analyst agent using the sales semantic view.
--
-- Run AFTER 04_semantic_view.sql — the semantic view must exist before
-- the agent can reference it in tool_resources.
--
-- Requires live_test_wh to exist (created by 02_search_service.sql).
-- Adjust names to match your test account.

CREATE AGENT IF NOT EXISTS live_test_db.live_test_schema.analyst_agent
  COMMENT = 'Cortex Analyst agent used by cortex-agents-client live integration tests.'
  FROM SPECIFICATION
  $$
  instructions:
    response: 'You are a data analyst. Use the SalesAnalyst tool to answer questions about sales revenue, quantity, and transactions. Always return a table of results.'

  tools:
    - tool_spec:
        type: cortex_analyst_text_to_sql
        name: SalesAnalyst
        description: 'Answers questions about product sales, revenue by region, quantities sold, and transaction counts.'

  tool_resources:
    SalesAnalyst:
      semantic_view: live_test_db.live_test_schema.sales_view
      execution_environment:
        type: warehouse
        warehouse: live_test_wh
  $$;

GRANT USAGE ON AGENT live_test_db.live_test_schema.analyst_agent
  TO ROLE app_owner_role;
