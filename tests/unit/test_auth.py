"""Unit tests for authentication providers."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from cortex_agents_client.auth import OAuthAuth, PATAuth, SiSContainerAuth, account_url_from_env
from cortex_agents_client.client import _coerce_auth


def test_pat_auth_authorization_header(pat_token):
    """PATAuth returns correct Authorization header."""
    auth = PATAuth(pat_token)
    headers = auth.headers()
    assert headers["Authorization"] == f"Bearer {pat_token}"


def test_pat_auth_token_type_header(pat_token):
    """PATAuth includes the PROGRAMMATIC_ACCESS_TOKEN type header."""
    auth = PATAuth(pat_token)
    headers = auth.headers()
    assert headers["X-Snowflake-Authorization-Token-Type"] == "PROGRAMMATIC_ACCESS_TOKEN"


def test_string_coercion_wraps_as_pat(pat_token):
    """Passing a plain string to _coerce_auth wraps it as PATAuth."""
    auth = _coerce_auth(pat_token)
    assert isinstance(auth, PATAuth)
    headers = auth.headers()
    assert f"Bearer {pat_token}" in headers["Authorization"]


def test_auth_provider_passthrough():
    """Passing an AuthProvider instance to _coerce_auth returns it unchanged."""
    original = PATAuth("my_token")
    result = _coerce_auth(original)
    assert result is original


def test_oauth_auth_authorization_header():
    """OAuthAuth returns correct Authorization header."""
    token = "oauth_token_xyz"
    auth = OAuthAuth(token)
    headers = auth.headers()
    assert headers["Authorization"] == f"Bearer {token}"


def test_oauth_auth_no_type_header():
    """OAuthAuth does not include X-Snowflake-Authorization-Token-Type."""
    auth = OAuthAuth("some_token")
    headers = auth.headers()
    assert "X-Snowflake-Authorization-Token-Type" not in headers


def test_jwt_auth_raises_without_cryptography():
    """JWTAuth raises ImportError when cryptography is not importable."""
    import sys
    import importlib

    # Mock a missing cryptography package only if not installed
    try:
        import cryptography  # noqa: F401
        # Package exists; skip this test
        pytest.skip("cryptography is installed; cannot test missing-package path")
    except ImportError:
        pass

    from cortex_agents_client.auth import JWTAuth

    with pytest.raises(ImportError, match="cryptography"):
        JWTAuth(
            account="myorg-myaccount",
            user="MYUSER",
            private_key_path="/nonexistent/key.p8",
        )


class TestSiSContainerAuth:
    """Tests for SiSContainerAuth."""

    def test_reads_token_from_file(self, tmp_path):
        """headers() returns token read from the token file."""
        token_file = tmp_path / "token"
        token_file.write_text("my_oauth_token_12345")

        auth = SiSContainerAuth(token_path=token_file)
        headers = auth.headers()
        assert headers["Authorization"] == "Bearer my_oauth_token_12345"

    def test_strips_whitespace_from_token(self, tmp_path):
        """Token file with trailing newline is stripped correctly."""
        token_file = tmp_path / "token"
        token_file.write_text("my_token\n")

        auth = SiSContainerAuth(token_path=token_file)
        assert auth.headers()["Authorization"] == "Bearer my_token"

    def test_re_reads_token_on_each_call(self, tmp_path):
        """Each headers() call reads the current file contents."""
        token_file = tmp_path / "token"
        token_file.write_text("token_v1")

        auth = SiSContainerAuth(token_path=token_file)
        assert "token_v1" in auth.headers()["Authorization"]

        # Simulate Snowflake refreshing the token
        token_file.write_text("token_v2")
        assert "token_v2" in auth.headers()["Authorization"]

    def test_raises_if_token_file_missing(self, tmp_path):
        """FileNotFoundError is raised at construction if file is absent."""
        with pytest.raises(FileNotFoundError, match="token file not found"):
            SiSContainerAuth(token_path=tmp_path / "nonexistent_token")

    def test_no_token_type_header(self, tmp_path):
        """SiSContainerAuth does not add X-Snowflake-Authorization-Token-Type."""
        token_file = tmp_path / "token"
        token_file.write_text("tok")
        auth = SiSContainerAuth(token_path=token_file)
        assert "X-Snowflake-Authorization-Token-Type" not in auth.headers()


class TestAccountUrlFromEnv:
    """Tests for account_url_from_env()."""

    def test_returns_https_url(self, monkeypatch):
        """Constructs full https URL from SNOWFLAKE_HOST env var."""
        monkeypatch.setenv("SNOWFLAKE_HOST", "myorg-myaccount.snowflakecomputing.com")
        url = account_url_from_env()
        assert url == "https://myorg-myaccount.snowflakecomputing.com"

    def test_raises_if_env_var_missing(self, monkeypatch):
        """EnvironmentError raised if SNOWFLAKE_HOST is not set."""
        monkeypatch.delenv("SNOWFLAKE_HOST", raising=False)
        with pytest.raises(EnvironmentError, match="SNOWFLAKE_HOST"):
            account_url_from_env()

    def test_custom_env_var_name(self, monkeypatch):
        """Custom env var name is respected."""
        monkeypatch.setenv("MY_CUSTOM_HOST", "custom.snowflakecomputing.com")
        url = account_url_from_env(host_env="MY_CUSTOM_HOST")
        assert url == "https://custom.snowflakecomputing.com"
