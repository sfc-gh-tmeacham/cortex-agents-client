-- Seed script 07: multi-tenancy probe objects (row access policy on session attribute).
--
-- Used by tests/live/test_runs_multitenancy.py. Creates a NEW table and
-- attaches the policy to that table only — never to an existing table.
--
-- Run AFTER 02_search_service.sql (needs cac_live_wh). Independent of the
-- other agents. Dropped by teardown.sql.
--
-- Export the agent path to enable the tests:
--   LIVE_AGENT_MULTITENANCY=cac_live_db.cac_live_schema.cac_mt_agent

CREATE DATABASE IF NOT EXISTS cac_live_db;
CREATE SCHEMA  IF NOT EXISTS cac_live_db.cac_live_schema;

-- Fixed dataset: North totals 300, South 700, one row each for East and West.
CREATE OR REPLACE TABLE cac_live_db.cac_live_schema.cac_mt_sales (
    sale_id INT           NOT NULL COMMENT 'Unique sale identifier',
    region  VARCHAR       NOT NULL COMMENT 'Sales region (tenant key)',
    revenue NUMBER(10, 2) NOT NULL COMMENT 'Revenue in USD'
)
COMMENT = 'Multi-tenancy live test table for streamlit-cortex-agents.';

INSERT INTO cac_live_db.cac_live_schema.cac_mt_sales (sale_id, region, revenue) VALUES
  (1, 'North', 100.00), (2, 'North', 200.00),
  (3, 'South', 300.00), (4, 'South', 400.00),
  (5, 'East',  500.00), (6, 'West',  600.00);

-- The policy reads the session attribute the client sends in `variables`.
-- With no attribute set, SYS_CONTEXT returns NULL and no rows match, so a
-- request that omits its tenant sees nothing rather than everything.
CREATE OR REPLACE ROW ACCESS POLICY cac_live_db.cac_live_schema.cac_mt_region_rap
  AS (region_col VARCHAR) RETURNS BOOLEAN ->
    region_col = SYS_CONTEXT('SNOWFLAKE$SESSION_ATTRIBUTES', 'region');

ALTER TABLE cac_live_db.cac_live_schema.cac_mt_sales
  ADD ROW ACCESS POLICY cac_live_db.cac_live_schema.cac_mt_region_rap ON (region);

CREATE OR REPLACE SEMANTIC VIEW cac_live_db.cac_live_schema.cac_mt_sales_view
  TABLES (
    sales AS cac_live_db.cac_live_schema.cac_mt_sales
      PRIMARY KEY (sale_id)
      COMMENT = 'Sales transactions'
  )
  DIMENSIONS (
    sales.region AS region
      COMMENT = 'Sales region'
      SAMPLE_VALUES ('North', 'South', 'East', 'West')
      IS_ENUM
  )
  METRICS (
    sales.total_revenue AS SUM(revenue) COMMENT = 'Total revenue in USD'
  )
  COMMENT = 'Multi-tenancy live test view for streamlit-cortex-agents.';

CREATE OR REPLACE AGENT cac_live_db.cac_live_schema.cac_mt_agent
  COMMENT = 'Multi-tenancy live test agent for streamlit-cortex-agents.'
  FROM SPECIFICATION
  $$
  instructions:
    response: 'Use the SalesAnalyst tool. Always return a table with one row per region and its total revenue. Do not add regions that are not in the query result.'
  tools:
    - tool_spec:
        type: cortex_analyst_text_to_sql
        name: SalesAnalyst
        description: 'Answers questions about revenue by region.'
  tool_resources:
    SalesAnalyst:
      semantic_view: CAC_LIVE_DB.CAC_LIVE_SCHEMA.CAC_MT_SALES_VIEW
      execution_environment:
        type: warehouse
        warehouse: CAC_LIVE_WH
  $$;

GRANT REFERENCES, SELECT ON SEMANTIC VIEW cac_live_db.cac_live_schema.cac_mt_sales_view
  TO ROLE app_owner_role;
GRANT USAGE ON AGENT cac_live_db.cac_live_schema.cac_mt_agent
  TO ROLE app_owner_role;

-- Sanity check the policy on its own: expect 0 rows, because no session
-- attribute is set in this worksheet session.
SELECT * FROM cac_live_db.cac_live_schema.cac_mt_sales;
