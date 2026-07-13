-- Seed script 01: minimal LLM-only agent for smoke tests.
--
-- This agent has no tools. It responds to any input with a short plain-text
-- acknowledgement, making responses fast and deterministic enough for CI.
--
-- Run as a role that has CREATE CORTEX AGENT privilege on the target schema.
-- Adjust the database / schema / warehouse to match your test account.
--
-- Usage:
--   snow sql -f tests/live/seed/01_minimal_agent.sql \
--     -D db=live_test_db -D schema=live_test_schema

CREATE DATABASE IF NOT EXISTS live_test_db;
CREATE SCHEMA  IF NOT EXISTS live_test_db.live_test_schema;

CREATE CORTEX AGENT IF NOT EXISTS live_test_db.live_test_schema.minimal_agent
  COMMENT = 'Minimal LLM-only agent used by cortex-agents-client live integration tests.'
  INSTRUCTIONS = (
    SYSTEM = 'You are a concise test assistant. Respond to any input with a single sentence of 10 words or fewer.'
  );

GRANT USAGE ON CORTEX AGENT live_test_db.live_test_schema.minimal_agent
  TO ROLE app_owner_role;
