"""
Workday authentication.

Three methods, because Workday genuinely has three and a customer's security
team may only permit one of them:

  1. **OAuth 2.0 refresh-token grant** — the default. Verified as universally
     available: `Register API Client for Integrations` produces a non-expiring
     refresh token bound to an Integration System User, which is exchanged for
     short-lived access tokens.
  2. **OAuth 2.0 JWT bearer** — for customers who will not store a shared
     secret. The client signs an assertion with a private key whose x509 public
     half is registered in the tenant.
  3. **WS-Security username/password (ISU basic)** — the classic SOAP path, and
     still the only auth some older tenants have configured. Also the simplest
     path for RaaS.

Notably absent: `client_credentials`. Several third-party guides claim Workday
supports it for integrations, but no Workday-authored source shows it in the
`Register API Client for Integrations` grant dropdown, and no release note
announces it. Building on it would be an availability risk, so it is not
offered. If a tenant turns out to have it, `refresh_token` still works there.

The token endpoint is **never derived** from the tenant name. Workday displays
the exact endpoint per tenant in `View API Clients`, and hostnames vary by pod
(`wd2-impl-services1`, `wd5-services1`, `myworkday.com` vs `workday.com`).
Guessing it produces a confusing 404 against a host that does exist.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from api.connectors.base import ConnectorError, NotConfigured

# Access tokens are typically ~3600s. Refreshed early so a long extraction does
# not fail midway on a token that expired between two paginated calls.
_EXPIRY_SKEW_SECONDS = 120


class WorkdayAuthError(ConnectorError):
    """Authentication failed in a way the operator can act on."""


@dataclass(slots=True)
class WorkdayCredentials:
    """What a customer supplies. Nothing here is stored in the database.

    `host` is the full service host including scheme, exactly as it appears in
    the customer's tenant URL — not derived, because pod naming is not
    predictable from the tenant name.
    """

    host: str = ""
    tenant: str = ""

    method: str = "oauth_refresh_token"

    # --- oauth_refresh_token ---------------------------------------------
    token_endpoint: str = ""
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""

    # --- oauth_jwt --------------------------------------------------------
    private_key_pem: str = ""
    jwt_issuer: str = ""
    jwt_subject: str = ""

    # --- isu_basic --------------------------------------------------------
    # Workday expects `user@tenant` for WS-Security. Stored as typed and
    # qualified at use, so a customer who already included the suffix is not
    # silently given `user@tenant@tenant`.
    username: str = ""
    password: str = ""

    api_version: str = "v46.2"

    def normalised_host(self) -> str:
        host = self.host.strip().rstrip("/")
        if not host:
            raise NotConfigured("No Workday host configured.")
        if not host.startswith(("http://", "https://")):
            host = f"https://{host}"
        return host

    def qualified_username(self) -> str:
        user = self.username.strip()
        if not user:
            return ""
        return user if "@" in user else f"{user}@{self.tenant}"

    def missing(self) -> list[str]:
        """Which required fields are absent, named as the UI labels them.

        Returned as a list rather than raising on the first gap so the setup
        screen can mark every missing field at once instead of making the user
        submit repeatedly to discover them one at a time.
        """
        gaps: list[str] = []
        if not self.host.strip():
            gaps.append("Workday host")
        if not self.tenant.strip():
            gaps.append("Tenant name")

        if self.method == "oauth_refresh_token":
            if not self.token_endpoint.strip():
                gaps.append("Token endpoint")
            if not self.client_id.strip():
                gaps.append("Client ID")
            if not self.client_secret.strip():
                gaps.append("Client secret")
            if not self.refresh_token.strip():
                gaps.append("Refresh token")
        elif self.method == "oauth_jwt":
            if not self.token_endpoint.strip():
                gaps.append("Token endpoint")
            if not self.client_id.strip():
                gaps.append("Client ID")
            if not self.private_key_pem.strip():
                gaps.append("Private key")
            if not self.jwt_subject.strip():
                gaps.append("Integration System User")
        elif self.method == "isu_basic":
            if not self.username.strip():
                gaps.append("Integration System User")
            if not self.password.strip():
                gaps.append("Password")
        else:
            gaps.append(f"Unknown authentication method '{self.method}'")

        return gaps


@dataclass
class WorkdayAuth:
    """Issues credentials for outbound calls, refreshing as needed."""

    credentials: WorkdayCredentials
    _access_token: str = field(default="", init=False, repr=False)
    _expires_at: float = field(default=0.0, init=False, repr=False)

    @property
    def uses_oauth(self) -> bool:
        return self.credentials.method in {"oauth_refresh_token", "oauth_jwt"}

    def access_token(self, client: httpx.Client | None = None) -> str:
        """A valid bearer token, minting or refreshing one if required."""
        if not self.uses_oauth:
            raise WorkdayAuthError(
                "This connection uses username/password authentication and has no bearer token."
            )

        if self._access_token and time.time() < self._expires_at - _EXPIRY_SKEW_SECONDS:
            return self._access_token

        owns_client = client is None
        http_client = client or httpx.Client(timeout=30.0)
        try:
            payload = self._grant_payload()
            response = http_client.post(
                self.credentials.token_endpoint.strip(),
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                # Workday accepts the client secret either in the body or via
                # HTTP Basic. Basic is used because some tenant configurations
                # reject in-body secrets, and Basic works in both.
                auth=(self.credentials.client_id, self.credentials.client_secret)
                if self.credentials.method == "oauth_refresh_token"
                else None,
            )
        except httpx.HTTPError as exc:
            raise WorkdayAuthError(
                f"Could not reach the Workday token endpoint: {exc}"
            ) from exc
        finally:
            if owns_client:
                http_client.close()

        if response.status_code != 200:
            raise WorkdayAuthError(_explain_token_failure(response))

        body = response.json()
        token = body.get("access_token")
        if not token:
            raise WorkdayAuthError(
                "Workday returned a token response with no access_token."
            )

        self._access_token = token
        self._expires_at = time.time() + float(body.get("expires_in", 3600))
        return token

    def _grant_payload(self) -> dict[str, str]:
        if self.credentials.method == "oauth_refresh_token":
            return {
                "grant_type": "refresh_token",
                "refresh_token": self.credentials.refresh_token.strip(),
            }
        return {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": self._signed_assertion(),
            "client_id": self.credentials.client_id.strip(),
        }

    def _signed_assertion(self) -> str:
        """Build and sign the JWT bearer assertion.

        `PyJWT` is imported lazily: a deployment using only refresh-token or
        basic auth should not need a crypto dependency installed to boot.
        """
        try:
            import jwt  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise WorkdayAuthError(
                "JWT authentication needs PyJWT with cryptography installed "
                "(pip install 'pyjwt[crypto]')."
            ) from exc

        now = int(time.time())
        claims = {
            "iss": self.credentials.jwt_issuer.strip() or self.credentials.client_id.strip(),
            "sub": self.credentials.jwt_subject.strip(),
            "aud": self.credentials.token_endpoint.strip(),
            "exp": now + 300,
            "iat": now,
        }
        try:
            return jwt.encode(claims, self.credentials.private_key_pem, algorithm="RS256")
        except Exception as exc:  # noqa: BLE001 - surfaces as an operator-facing message
            raise WorkdayAuthError(
                f"The private key could not sign the assertion: {exc}"
            ) from exc

    def rest_headers(self, client: httpx.Client | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token(client)}",
            "Accept": "application/json",
        }

    def basic_auth(self) -> tuple[str, str] | None:
        """Credentials for RaaS, which accepts Basic as well as Bearer."""
        if self.credentials.method != "isu_basic":
            return None
        return (self.credentials.qualified_username(), self.credentials.password)

    def raas_auth_kwargs(self, client: httpx.Client | None = None) -> dict[str, Any]:
        """Whichever auth this connection can offer RaaS.

        RaaS is the one Workday surface that accepts both, which matters: it is
        also the surface that carries the configuration the APIs cannot reach,
        so it must work regardless of which method the customer chose.
        """
        if self.credentials.method == "isu_basic":
            return {"auth": self.basic_auth()}
        return {"headers": {"Authorization": f"Bearer {self.access_token(client)}"}}


def _explain_token_failure(response: httpx.Response) -> str:
    """Turn an OAuth error into something an admin can act on.

    Workday's OAuth errors are terse (`invalid_client`, `invalid_grant`) and
    each maps to a different, specific mistake during tenant setup. Passing the
    raw code through would leave the operator guessing at which of six setup
    steps went wrong.
    """
    try:
        body = response.json()
        code = body.get("error", "")
        description = body.get("error_description", "")
    except ValueError:
        code, description = "", response.text[:200]

    hints = {
        "invalid_client": (
            "Workday rejected the Client ID or secret. Check them against "
            "'View API Clients' in the tenant — the secret is shown only once "
            "when the API client is registered, so it may need regenerating."
        ),
        "invalid_grant": (
            "Workday rejected the refresh token. It may have been revoked, or "
            "generated for a different API client. Regenerate it with "
            "'Manage Refresh Tokens for Integrations'."
        ),
        "invalid_request": (
            "Workday rejected the request shape. The token endpoint is usually "
            "wrong — copy it exactly from 'View API Clients' rather than "
            "assembling it from the tenant name."
        ),
        "unauthorized_client": (
            "This API client is not permitted the grant it attempted. Confirm it "
            "was created with 'Register API Client for Integrations' and has "
            "'Non-Expiring Refresh Tokens' enabled."
        ),
    }

    hint = hints.get(code)
    if hint:
        return hint
    if response.status_code == 404:
        return (
            "The token endpoint returned 404. The host or tenant in the URL is "
            "likely wrong — copy the endpoint from 'View API Clients'."
        )
    return (
        f"Workday returned {response.status_code} from the token endpoint"
        f"{f': {code}' if code else ''}"
        f"{f' — {description}' if description else '.'}"
    )
