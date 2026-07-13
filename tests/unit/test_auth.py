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


def test_oauth_auth_includes_type_header():
    """OAuthAuth now includes X-Snowflake-Authorization-Token-Type: OAUTH."""
    auth = OAuthAuth("some_token")
    headers = auth.headers()
    assert headers.get("X-Snowflake-Authorization-Token-Type") == "OAUTH"


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

    def test_includes_oauth_type_header(self, tmp_path):
        """SiSContainerAuth includes X-Snowflake-Authorization-Token-Type: OAUTH."""
        token_file = tmp_path / "token"
        token_file.write_text("tok")
        auth = SiSContainerAuth(token_path=token_file)
        assert auth.headers().get("X-Snowflake-Authorization-Token-Type") == "OAUTH"


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


# ---------------------------------------------------------------------------
# JWTAuth — tests skipped when cryptography / PyJWT are not installed
# ---------------------------------------------------------------------------

cryptography = pytest.importorskip("cryptography", reason="cryptography not installed")
jwt_lib = pytest.importorskip("jwt", reason="PyJWT not installed")


@pytest.fixture
def rsa_key_file(tmp_path):
    """Generate a fresh 2048-bit RSA private key and write it to a temp PEM file."""
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    key_file = tmp_path / "key.p8"
    key_file.write_bytes(pem)
    return key_file


class TestJWTAuth:
    """Tests for JWTAuth (requires cryptography + PyJWT)."""

    def _make_auth(self, rsa_key_file, account="myorg-myaccount", user="myuser"):
        from cortex_agents_client.auth import JWTAuth
        return JWTAuth(account=account, user=user, private_key_path=rsa_key_file)

    def _decode(self, token, rsa_key_file):
        """Decode JWT without verifying expiry for claim inspection."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
        from cryptography.hazmat.backends import default_backend

        # Load the private key to derive the public key for verification
        private_key = serialization.load_pem_private_key(
            rsa_key_file.read_bytes(), password=None, backend=default_backend()
        )
        pub_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return jwt_lib.decode(token, pub_pem, algorithms=["RS256"], options={"verify_exp": False})

    def test_headers_include_authorization_and_keypair_jwt_type(self, rsa_key_file):
        """headers() returns Authorization bearer token and KEYPAIR_JWT type header."""
        auth = self._make_auth(rsa_key_file)
        headers = auth.headers()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")
        assert headers["X-Snowflake-Authorization-Token-Type"] == "KEYPAIR_JWT"

    def test_jwt_claims_iss_format(self, rsa_key_file):
        """iss claim is ACCOUNT.USER.SHA256:<fingerprint>."""
        auth = self._make_auth(rsa_key_file, account="myorg-myaccount", user="myuser")
        token = auth.headers()["Authorization"].split(" ", 1)[1]
        claims = self._decode(token, rsa_key_file)
        iss = claims["iss"]
        # Format: ACCOUNT.USER.SHA256:<fingerprint>
        assert iss.startswith("MYORG-MYACCOUNT.MYUSER.SHA256:")
        assert len(iss.split(".")) >= 3

    def test_jwt_claims_sub_format(self, rsa_key_file):
        """sub claim is ACCOUNT.USER."""
        auth = self._make_auth(rsa_key_file, account="myorg-myaccount", user="myuser")
        token = auth.headers()["Authorization"].split(" ", 1)[1]
        claims = self._decode(token, rsa_key_file)
        assert claims["sub"] == "MYORG-MYACCOUNT.MYUSER"

    def test_jwt_exp_within_one_hour(self, rsa_key_file):
        """JWT expiry is at most 3600 seconds after issue time."""
        auth = self._make_auth(rsa_key_file)
        token = auth.headers()["Authorization"].split(" ", 1)[1]
        claims = self._decode(token, rsa_key_file)
        assert claims["exp"] - claims["iat"] <= 3600

    def test_account_and_user_uppercased_in_claims(self, rsa_key_file):
        """Lowercase account and user are uppercased in JWT claims."""
        auth = self._make_auth(rsa_key_file, account="lowercase-org", user="lowercase_user")
        token = auth.headers()["Authorization"].split(" ", 1)[1]
        claims = self._decode(token, rsa_key_file)
        assert "lowercase" not in claims["iss"]
        assert "lowercase" not in claims["sub"]
        assert "LOWERCASE-ORG.LOWERCASE_USER" in claims["sub"]
