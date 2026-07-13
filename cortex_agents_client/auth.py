"""Authentication providers for the Cortex Agents REST API.

Supports four methods:
- PAT (Programmatic Access Token): simplest, recommended for external apps.
- JWT (key-pair): requires ``pip install "cortex-agents-client[jwt]"``.
- OAuth: standard Bearer token with a static token string.
- SiSContainerAuth: for Streamlit-in-Snowflake container runtime, reads the
  Snowflake-injected token file on every request so tokens are always fresh.

Example::

    from cortex_agents_client.auth import PATAuth, JWTAuth, SiSContainerAuth

    auth = PATAuth("v2:my_token")
    auth = JWTAuth(account="myorg-myaccount", user="MYUSER",
                   private_key_path="/path/to/rsa_key.p8")
    auth = SiSContainerAuth()  # auto-detects token path and env vars
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

__all__ = ["AuthProvider", "PATAuth", "JWTAuth", "OAuthAuth", "SiSContainerAuth"]

_JWT_LIFETIME_SECONDS = 3600  # Max JWT validity per Snowflake docs


class AuthProvider(ABC):
    """Abstract base class for authentication providers.

    Subclasses must implement :meth:`headers` to return the HTTP headers
    required to authenticate a request.
    """

    @abstractmethod
    def headers(self) -> dict[str, str]:
        """Returns the HTTP headers required to authenticate a request.

        Returns:
            A dict mapping header names to values.
        """


class PATAuth(AuthProvider):
    """Authenticates using a Snowflake Programmatic Access Token (PAT).

    This is the simplest authentication method and requires no additional
    dependencies. Suitable for most Streamlit applications.

    Args:
        token: The PAT token string (typically starts with ``v2:``).

    Example::

        auth = PATAuth("v2:my_pat_token_here")
    """

    def __init__(self, token: str) -> None:
        """Initialises PAT authentication.

        Args:
            token: The PAT token string.
        """
        self._token = token

    def headers(self) -> dict[str, str]:
        """Returns PAT authentication headers.

        Returns:
            Dict with ``Authorization`` and
            ``X-Snowflake-Authorization-Token-Type`` headers.
        """
        return {
            "Authorization": f"Bearer {self._token}",
            "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
        }


class JWTAuth(AuthProvider):
    """Authenticates using RSA key-pair (JWT) authentication.

    Generates a fresh JWT on every :meth:`headers` call. The token is valid
    for up to one hour, which is the maximum allowed by Snowflake.

    Requires ``pip install "cortex-agents-client[jwt]"`` (installs ``cryptography``
    and ``PyJWT``).

    Args:
        account: Snowflake account identifier (e.g. ``myorg-myaccount``).
            Must match the account used to generate the key pair.
        user: Snowflake username. Will be uppercased automatically.
        private_key_path: Path to the PEM-encoded RSA private key file
            (typically ``rsa_key.p8``).
        passphrase: Optional passphrase for encrypted private key files,
            as bytes (e.g. ``b"my_passphrase"``).

    Raises:
        ImportError: If ``cryptography`` or ``PyJWT`` is not installed.

    Example::

        auth = JWTAuth(
            account="myorg-myaccount",
            user="MYUSER",
            private_key_path="/path/to/rsa_key.p8",
        )
    """

    def __init__(
        self,
        account: str,
        user: str,
        private_key_path: str | Path,
        passphrase: bytes | None = None,
    ) -> None:
        """Initialises JWT authentication.

        Args:
            account: Snowflake account identifier.
            user: Snowflake username.
            private_key_path: Path to PEM-encoded RSA private key.
            passphrase: Optional passphrase for encrypted key files.
        """
        self._account = account.upper()
        self._user = user.upper()
        self._private_key_path = Path(private_key_path)
        self._passphrase = passphrase
        self._private_key = self._load_private_key()
        self._public_key_fingerprint = self._compute_fingerprint()

    def _load_private_key(self):
        """Loads the RSA private key from disk.

        Returns:
            The loaded private key object.

        Raises:
            ImportError: If ``cryptography`` is not installed.
            FileNotFoundError: If the key file does not exist.
        """
        try:
            from cryptography.hazmat.primitives import serialization
        except ImportError as exc:
            raise ImportError(
                "JWT authentication requires 'cryptography'. "
                "Install with: pip install "cortex-agents-client[jwt]""
            ) from exc

        key_data = self._private_key_path.read_bytes()
        return serialization.load_pem_private_key(key_data, password=self._passphrase)

    def _compute_fingerprint(self) -> str:
        """Computes the SHA-256 fingerprint of the public key.

        Returns:
            Fingerprint string prefixed with ``SHA256:``.
        """
        import base64
        import hashlib

        from cryptography.hazmat.primitives import serialization

        pub_key_der = self._private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        digest = hashlib.sha256(pub_key_der).digest()
        fingerprint = base64.b64encode(digest).decode("utf-8")
        return f"SHA256:{fingerprint}"

    def _generate_jwt(self) -> str:
        """Generates a fresh JWT token.

        Returns:
            Signed JWT token string.

        Raises:
            ImportError: If ``PyJWT`` is not installed.
        """
        try:
            import jwt
        except ImportError as exc:
            raise ImportError(
                "JWT authentication requires 'PyJWT'. "
                "Install with: pip install "cortex-agents-client[jwt]""
            ) from exc

        now = int(time.time())
        qualified_name = f"{self._account}.{self._user}"
        payload = {
            "iss": f"{qualified_name}.{self._public_key_fingerprint}",
            "sub": qualified_name,
            "iat": now,
            "exp": now + _JWT_LIFETIME_SECONDS,
        }
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    def headers(self) -> dict[str, str]:
        """Returns JWT authentication headers with a freshly generated token.

        Returns:
            Dict with ``Authorization`` and optional token-type headers.
        """
        return {
            "Authorization": f"Bearer {self._generate_jwt()}",
            "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
        }


class OAuthAuth(AuthProvider):
    """Authenticates using an OAuth Bearer token.

    Args:
        token: The OAuth access token string.

    Example::

        auth = OAuthAuth("my_oauth_access_token")
    """

    def __init__(self, token: str) -> None:
        """Initialises OAuth authentication.

        Args:
            token: The OAuth access token.
        """
        self._token = token

    def headers(self) -> dict[str, str]:
        """Returns OAuth authentication headers.

        Returns:
            Dict with the ``Authorization`` header only.
            Snowflake determines the token type automatically.
        """
        return {"Authorization": f"Bearer {self._token}"}


# ---------------------------------------------------------------------------
# Snowflake SiS container runtime helpers
# ---------------------------------------------------------------------------

#: Default path to the Snowflake OAuth token file injected into containers.
_SIS_TOKEN_PATH = "/snowflake/session/token"

#: Environment variable injected by Snowflake into container runtime apps.
_SNOWFLAKE_HOST_ENV = "SNOWFLAKE_HOST"


class SiSContainerAuth(AuthProvider):
    """Authentication for Streamlit-in-Snowflake (SiS) container runtime.

    Snowflake injects a short-lived OAuth token into the container at
    ``/snowflake/session/token`` and refreshes it automatically. This class
    reads the token file on **every** :meth:`headers` call so requests always
    carry a valid, current token — unlike :class:`OAuthAuth` which holds a
    single static string that would expire.

    Use :func:`account_url_from_env` to build the base URL from the
    ``SNOWFLAKE_HOST`` environment variable that Snowflake also injects.

    Args:
        token_path: Path to the Snowflake token file. Defaults to
            ``/snowflake/session/token``, which is the standard location
            in all Snowflake container runtime environments.

    Raises:
        FileNotFoundError: At construction time if ``token_path`` does not
            exist, so misconfiguration is caught early.

    Example::

        import os
        from cortex_agents_client import CortexAgentsClient
        from cortex_agents_client.auth import SiSContainerAuth, account_url_from_env

        client = CortexAgentsClient(
            account_url=account_url_from_env(),
            auth=SiSContainerAuth(),
        )
    """

    def __init__(self, token_path: str | Path = _SIS_TOKEN_PATH) -> None:
        """Initialises SiS container authentication.

        Args:
            token_path: Path to the Snowflake OAuth token file.

        Raises:
            FileNotFoundError: If the token file does not exist at the
                specified path.
        """
        self._token_path = Path(token_path)
        if not self._token_path.exists():
            raise FileNotFoundError(
                f"Snowflake token file not found at '{self._token_path}'. "
                "SiSContainerAuth is only valid inside a Snowflake container "
                "runtime environment. For external apps, use PATAuth instead."
            )

    def headers(self) -> dict[str, str]:
        """Returns OAuth headers with the current token read from disk.

        The token file is re-read on every call so that refreshed tokens
        are used automatically without restarting the application.

        Returns:
            Dict with ``Authorization`` header only. Snowflake determines
            the token type from the token value.

        Raises:
            FileNotFoundError: If the token file was removed after init.
        """
        token = self._token_path.read_text().strip()
        return {"Authorization": f"Bearer {token}"}


def account_url_from_env(host_env: str = _SNOWFLAKE_HOST_ENV) -> str:
    """Builds the Snowflake account base URL from an environment variable.

    In SiS container runtime, Snowflake injects the ``SNOWFLAKE_HOST``
    environment variable (e.g. ``myorg-myaccount.snowflakecomputing.com``).
    This helper wraps it with ``https://`` to produce the full base URL
    expected by :class:`~cortex_agents_client.CortexAgentsClient`.

    Args:
        host_env: Name of the environment variable containing the Snowflake
            host. Defaults to ``"SNOWFLAKE_HOST"``.

    Returns:
        Full base URL string (e.g.
        ``"https://myorg-myaccount.snowflakecomputing.com"``).

    Raises:
        EnvironmentError: If the environment variable is not set.

    Example::

        from cortex_agents_client.auth import account_url_from_env

        url = account_url_from_env()
        # → "https://myorg-myaccount.snowflakecomputing.com"
    """
    import os

    host = os.environ.get(host_env)
    if not host:
        raise EnvironmentError(
            f"Environment variable '{host_env}' is not set. "
            "This variable is injected automatically by Snowflake container "
            "runtime. If running locally, set it manually or pass account_url "
            "directly to CortexAgentsClient."
        )
    return f"https://{host}"

