-- Seed script 04: sales table and semantic view for Cortex Analyst tests.
--
-- Creates a small fixed sales dataset and a semantic view over it so the
-- analyst agent (05_analyst_agent.sql) can answer simple aggregation questions.
--
-- Requires:
--   - CREATE SEMANTIC VIEW privilege on the target schema
--   - USAGE on the database and schema
--   - SELECT on the tables used in the semantic view
--
-- Run BEFORE 05_analyst_agent.sql.

CREATE DATABASE IF NOT EXISTS cac_live_db;
CREATE SCHEMA  IF NOT EXISTS cac_live_db.cac_live_schema;

-- Fixed sales fact table
CREATE TABLE IF NOT EXISTS cac_live_db.cac_live_schema.sales (
    sale_id     INT           NOT NULL  COMMENT 'Unique sale identifier',
    product     VARCHAR       NOT NULL  COMMENT 'Product name',
    region      VARCHAR       NOT NULL  COMMENT 'Sales region',
    sale_date   DATE          NOT NULL  COMMENT 'Date of sale',
    quantity    INT           NOT NULL  COMMENT 'Units sold',
    revenue     NUMBER(10, 2) NOT NULL  COMMENT 'Revenue in USD'
)
COMMENT = 'Fixed sales test dataset for cortex-agents-client live integration tests.';

TRUNCATE TABLE IF EXISTS cac_live_db.cac_live_schema.sales;

INSERT INTO cac_live_db.cac_live_schema.sales
    (sale_id, product, region, sale_date, quantity, revenue)
VALUES
  (1,  'Widget Alpha', 'North', '2024-01-15', 10, 990.00),
  (2,  'Widget Alpha', 'South', '2024-01-20',  5, 495.00),
  (3,  'Widget Beta',  'North', '2024-02-03', 20, 800.00),
  (4,  'Widget Beta',  'East',  '2024-02-10',  8, 320.00),
  (5,  'Gadget Pro',   'West',  '2024-03-05',  3, 1497.00),
  (6,  'Widget Alpha', 'East',  '2024-03-12', 12, 1188.00),
  (7,  'Gadget Lite',  'South', '2024-04-01', 25, 1225.00),
  (8,  'Gadget Pro',   'North', '2024-04-18',  2, 998.00),
  (9,  'Widget Beta',  'West',  '2024-05-07', 15, 600.00),
  (10, 'Gadget Lite',  'East',  '2024-05-22', 30, 1470.00),
  (11, 'Widget Alpha', 'West',  '2024-06-14',  7, 693.00),
  (12, 'Gadget Pro',   'South', '2024-06-30',  4, 1996.00);

-- Semantic view over the sales table
CREATE SEMANTIC VIEW IF NOT EXISTS cac_live_db.cac_live_schema.sales_view

  TABLES (
    sales AS cac_live_db.cac_live_schema.sales
      PRIMARY KEY (sale_id)
      COMMENT = 'Sales transactions'
  )

  DIMENSIONS (
    sales.product   AS product
      COMMENT = 'Product name'
      SAMPLE_VALUES ('Widget Alpha', 'Widget Beta', 'Gadget Pro', 'Gadget Lite')
      IS_ENUM,
    sales.region    AS region
      COMMENT = 'Sales region'
      SAMPLE_VALUES ('North', 'South', 'East', 'West')
      IS_ENUM,
    sales.sale_date AS sale_date
      COMMENT = 'Date of sale',
    sales.sale_year AS YEAR(sale_date)
      COMMENT = 'Year of sale'
  )

  METRICS (
    sales.total_revenue AS SUM(revenue)
      COMMENT = 'Total revenue in USD',
    sales.total_quantity AS SUM(quantity)
      COMMENT = 'Total units sold',
    sales.transaction_count AS COUNT(sale_id)
      COMMENT = 'Number of sales transactions'
  )

  COMMENT = 'Sales semantic view for cortex-agents-client live integration tests.'

  AI_VERIFIED_QUERIES (
    revenue_by_product AS (
      QUESTION 'What is the total revenue by product?'
      VERIFIED_AT 1752451200
      VERIFIED_BY '(STEWARD = live_test_seed)'
      SQL 'SELECT product, SUM(revenue) AS total_revenue FROM __sales GROUP BY product ORDER BY total_revenue DESC'
    ),
    quantity_by_region AS (
      QUESTION 'What is the total quantity sold by region?'
      VERIFIED_AT 1752451200
      VERIFIED_BY '(STEWARD = live_test_seed)'
      SQL 'SELECT region, SUM(quantity) AS total_quantity FROM __sales GROUP BY region ORDER BY total_quantity DESC'
    )
  );

-- The agent's role needs REFERENCES and SELECT to use this view in Cortex Analyst
GRANT REFERENCES, SELECT ON SEMANTIC VIEW cac_live_db.cac_live_schema.sales_view
  TO ROLE app_owner_role;
