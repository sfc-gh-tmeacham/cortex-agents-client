"""Shared test fixtures."""
import pytest


@pytest.fixture
def pat_token() -> str:
    """Returns a fake PAT token for testing."""
    return "v2:test_pat_token_abc123"


@pytest.fixture
def account_url() -> str:
    """Returns a fake Snowflake account URL."""
    return "https://testorg-testaccount.snowflakecomputing.com"
