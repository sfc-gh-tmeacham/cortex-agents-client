-- Teardown script: drops all objects created by the cac_live seed scripts.
--
-- Executed automatically by the pytest session fixture after live tests complete.
-- Can also be run manually if a test session was interrupted:
--
--   SNOWFLAKE_ACCOUNT_URL="https://..." SNOWFLAKE_PAT="v2:..." \
--     uv run python tests/live/seed/teardown.py

-- Agents (drop before dependent resources)
DROP AGENT IF EXISTS cac_live_db.cac_live_schema.cac_live_web_agent;
DROP AGENT IF EXISTS cac_live_db.cac_live_schema.cac_live_analyst_agent;
DROP AGENT IF EXISTS cac_live_db.cac_live_schema.cac_live_full_agent;
DROP AGENT IF EXISTS cac_live_db.cac_live_schema.cac_live_minimal_agent;

-- Disposable agents created by test_agents.py. Those tests drop their own
-- agent in a fixture finally block; this is only a backstop for a run that
-- was killed hard. Names are cac_live_crud_<uuid8>, so they cannot be listed
-- statically -- see cleanup_leaked_agents.py to sweep them by prefix.

-- Cortex Search service
DROP CORTEX SEARCH SERVICE IF EXISTS cac_live_db.cac_live_schema.cac_live_doc_search;

-- Semantic view
DROP SEMANTIC VIEW IF EXISTS cac_live_db.cac_live_schema.cac_live_sales_view;

-- Tables
DROP TABLE IF EXISTS cac_live_db.cac_live_schema.cac_live_docs;
DROP TABLE IF EXISTS cac_live_db.cac_live_schema.cac_live_sales;

-- Schema, database, warehouse (dropped last)
DROP SCHEMA    IF EXISTS cac_live_db.cac_live_schema;
DROP DATABASE  IF EXISTS cac_live_db;
DROP WAREHOUSE IF EXISTS cac_live_wh;
