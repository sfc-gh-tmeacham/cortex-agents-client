-- Seed script 01: minimal LLM-only agent for smoke tests.
--
-- This agent has no tools. It responds to any input with a short plain-text
-- acknowledgement, making responses fast and deterministic enough for CI.
--
-- Run as a role that has CREATE AGENT privilege on the target schema.
-- Adjust the database / schema to match your test account.

CREATE DATABASE IF NOT EXISTS live_test_db;
CREATE SCHEMA  IF NOT EXISTS live_test_db.live_test_schema;

CREATE AGENT IF NOT EXISTS live_test_db.live_test_schema.minimal_agent
  COMMENT = 'Minimal LLM-only agent used by cortex-agents-client live integration tests.'
  FROM SPECIFICATION
  $$
  instructions:
    response: 'You are a concise test assistant. Respond to any input with a single sentence of 10 words or fewer.'
  $$;

GRANT USAGE ON AGENT live_test_db.live_test_schema.minimal_agent
  TO ROLE app_owner_role;
