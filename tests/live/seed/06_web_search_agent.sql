-- Seed script 06: web search agent.
--
-- Requires web search to be enabled at the account level by an ACCOUNTADMIN
-- via Snowsight: AI & ML → Agents → Settings → Web search toggle.
--
-- No additional resources are needed — web_search is a built-in tool.
-- Adjust names to match your test account.

CREATE AGENT IF NOT EXISTS cac_live_db.cac_live_schema.web_agent
  COMMENT = 'Web search agent used by cortex-agents-client live integration tests.'
  FROM SPECIFICATION
  $$
  instructions:
    response: 'You are a helpful assistant. Use the WebSearch tool to look up current information and answer questions about recent events.'

  tools:
    - tool_spec:
        type: web_search
        name: WebSearch
        description: 'Searches the web for current information, news, and real-time data.'
  $$;

GRANT USAGE ON AGENT cac_live_db.cac_live_schema.web_agent
  TO ROLE app_owner_role;
