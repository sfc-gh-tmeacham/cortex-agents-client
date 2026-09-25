-- Seed script 02: small fixed-corpus table and Cortex Search service.
--
-- The corpus contains 10 short documents about fictional products.
-- A fixed, known corpus means full-agent tests can assert that
-- ToolUseEvent / ToolResultEvent / TextAnnotationEvent are emitted
-- without depending on response text content.
--
-- Requires:
--   - A warehouse (default: cac_live_wh) with USAGE granted to app_owner_role
--   - CREATE CORTEX SEARCH SERVICE privilege on the target schema
--   - SNOWFLAKE.CORTEX_USER or SNOWFLAKE.CORTEX_EMBED_USER database role
--     granted to the role creating the service (required for embedding functions)
--
-- Adjust names to match your test account.

CREATE DATABASE  IF NOT EXISTS cac_live_db;
CREATE SCHEMA    IF NOT EXISTS cac_live_db.cac_live_schema;
CREATE WAREHOUSE IF NOT EXISTS cac_live_wh
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND   = 60
  AUTO_RESUME    = TRUE
  COMMENT = 'Warehouse used by streamlit-cortex-agents live integration tests.';

GRANT USAGE ON WAREHOUSE cac_live_wh TO ROLE app_owner_role;

-- Fixed corpus table
CREATE TABLE IF NOT EXISTS cac_live_db.cac_live_schema.test_docs (
    doc_id   INT     NOT NULL COMMENT 'Unique document identifier',
    title    VARCHAR NOT NULL COMMENT 'Document title used as a citation label',
    body     VARCHAR NOT NULL COMMENT 'Document body text indexed by Cortex Search'
)
COMMENT = 'Fixed test corpus for streamlit-cortex-agents live integration tests.';

-- Truncate and repopulate so the script is idempotent
TRUNCATE TABLE IF EXISTS cac_live_db.cac_live_schema.test_docs;

INSERT INTO cac_live_db.cac_live_schema.test_docs (doc_id, title, body) VALUES
  (1,  'Widget Alpha overview',   'Widget Alpha is our flagship product. It features a durable aluminium casing and a 2-year warranty.'),
  (2,  'Widget Beta overview',    'Widget Beta is a compact version of Widget Alpha. It is 30 percent lighter and ships in 3 colours.'),
  (3,  'Gadget Pro overview',     'Gadget Pro targets enterprise customers. It includes 24/7 support and a 99.9 percent uptime SLA.'),
  (4,  'Gadget Lite overview',    'Gadget Lite is the entry-level tier. It supports up to 5 users and has basic reporting features.'),
  (5,  'Pricing guide',           'Widget Alpha costs 99 USD per unit. Gadget Pro is priced at 499 USD per seat per year.'),
  (6,  'Shipping policy',         'Orders ship within 2 business days. Express shipping is available for an additional 15 USD.'),
  (7,  'Return policy',           'Returns are accepted within 30 days of purchase. Items must be in original packaging.'),
  (8,  'Support contact',         'Contact support at support@example.com or call 1-800-555-0199 Monday to Friday, 9 AM to 5 PM EST.'),
  (9,  'Compatibility matrix',    'Widget Alpha requires firmware 3.x or later. Gadget Pro is compatible with Windows 10+ and macOS 12+.'),
  (10, 'Release notes v2.0',      'Version 2.0 introduced dark mode, improved search, and a new REST API. Released January 2025.');

-- Cortex Search service over the corpus
CREATE CORTEX SEARCH SERVICE IF NOT EXISTS cac_live_db.cac_live_schema.doc_search
  ON body
  ATTRIBUTES title
  WAREHOUSE  = cac_live_wh
  TARGET_LAG = '1 minute'
  AS SELECT doc_id, title, body
     FROM cac_live_db.cac_live_schema.test_docs;

GRANT USAGE ON CORTEX SEARCH SERVICE cac_live_db.cac_live_schema.doc_search
  TO ROLE app_owner_role;
