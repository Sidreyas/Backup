"""
Credential storage.

Connector credentials have to be persisted — a refresh token the user pastes
once must survive a restart, or the connector is unusable. But a database dump
must not be a credential leak, so secrets are encrypted at rest with a key held
outside the database.

This is deliberately modest about what it provides. Envelope encryption with a
locally-held key protects against a leaked database backup, a stolen disk, or a
read-only SQL injection. It does not protect against an attacker who has the
application process, because that process must be able to decrypt. Real
deployments should point `MERIDIAN_SECRET_KEY` at a KMS-managed key or replace
this module with a secrets manager — the interface is two functions.

If no key is configured, secrets are **not** stored. Storing them in plaintext
"for now" is how plaintext credentials reach production, so the failure is loud
and immediate instead.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets as _secrets
from typing import Any

_KEY_ENV = "MERIDIAN_SECRET_KEY"


def _configured_key() -> str:
    """The key, from the environment or from `.env`.

    Read through the settings object as well as `os.environ` because the app is
    normally started with a `.env` file and an operator who set the key there
    would otherwise be told, wrongly, that no key is configured. The
    environment still wins, so a container-injected secret overrides the file.
    """
    from_env = os.environ.get(_KEY_ENV, "").strip()
    if from_env:
        return from_env

    from api.core.config import settings

    return (settings.meridian_secret_key or "").strip()


# Fields never returned to a client, whatever the caller asks for. Belt and
# braces alongside the encryption: a serialisation bug should not be able to
# leak a secret through an endpoint that merely forgot to strip it.
SENSITIVE_FIELDS = frozenset(
    {
        "client_secret",
        "refresh_token",
        "password",
        "private_key_pem",
        "api_token",
        "token",
        "secret",
        # Per-connector secret field ids. Encryption already follows the
        # declared kind="password", so these are the second line: if a
        # connector ever declares one of these as plain text by mistake, it
        # still never reaches a client.
        "pat",
        "entra_token",
        "access_token",
        # A captured browser session is a bearer credential: whoever holds the
        # cookies *is* the signed-in administrator until they expire. It is not
        # a password, which makes it easy to file as harmless state — it is
        # not, and it grants strictly more than any ISU credential here.
        "browser_session_state",
    }
)


class SecretsUnavailable(RuntimeError):
    """No encryption key is configured, so credentials cannot be stored."""


def _key() -> bytes:
    raw = _configured_key()
    if not raw:
        raise SecretsUnavailable(
            f"{_KEY_ENV} is not set, so connector credentials cannot be stored "
            "safely. Generate one with: python -c \"import secrets; "
            "print(secrets.token_urlsafe(32))\" and set it in your environment."
        )
    # Derived rather than used directly so any sufficiently long string works
    # as a key without the caller having to produce exactly 32 bytes.
    return hashlib.sha256(raw.encode("utf-8")).digest()


def available() -> bool:
    return bool(_configured_key())


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """Counter-mode keystream from HMAC-SHA256.

    Uses only the standard library. `cryptography` would give AES-GCM and is
    the better choice for a real deployment, but adding a compiled dependency
    to store one refresh token is a poor trade — and a construction that is
    obviously HMAC-CTR + HMAC is easier to audit than a hand-rolled cipher.
    """
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt(payload: dict[str, Any]) -> str:
    """Encrypt a credential blob. Returns an opaque, storable string.

    Encrypt-then-MAC: the tag covers the nonce and the ciphertext, so tampering
    is detected before anything is decrypted.
    """
    key = _key()
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    nonce = _secrets.token_bytes(16)

    enc_key = hashlib.sha256(b"enc" + key).digest()
    mac_key = hashlib.sha256(b"mac" + key).digest()

    ciphertext = bytes(
        a ^ b for a, b in zip(plaintext, _keystream(enc_key, nonce, len(plaintext)))
    )
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()

    return "v1." + base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")


def decrypt(blob: str) -> dict[str, Any]:
    """Decrypt a credential blob, rejecting anything tampered with."""
    if not blob:
        return {}
    if not blob.startswith("v1."):
        raise ValueError("Unrecognised credential format.")

    key = _key()
    raw = base64.urlsafe_b64decode(blob[3:].encode("ascii"))
    nonce, tag, ciphertext = raw[:16], raw[16:48], raw[48:]

    mac_key = hashlib.sha256(b"mac" + key).digest()
    expected = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    # Constant-time: a timing-variable comparison here leaks the tag one byte
    # at a time to anyone who can submit blobs.
    if not hmac.compare_digest(tag, expected):
        raise ValueError(
            "Stored credentials failed their integrity check. They were either "
            "tampered with or encrypted under a different key."
        )

    enc_key = hashlib.sha256(b"enc" + key).digest()
    plaintext = bytes(
        a ^ b for a, b in zip(ciphertext, _keystream(enc_key, nonce, len(ciphertext)))
    )
    return json.loads(plaintext.decode("utf-8"))


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """A copy safe to return over the API.

    Secret fields become a presence marker rather than disappearing: the UI
    needs to show "client secret is set" so a user editing a connection knows
    not to re-enter it, and an absent key is indistinguishable from an unset
    one.
    """
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in SENSITIVE_FIELDS and value:
            out[key] = "••••••••"
        elif key not in SENSITIVE_FIELDS:
            out[key] = value
    return out
