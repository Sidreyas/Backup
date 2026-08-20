"""
Credential encryption.

The property that matters: a database dump must not be a credential leak. These
tests check that the stored form reveals nothing, that tampering is detected
rather than silently decrypted into garbage, and that the module refuses to
operate rather than falling back to plaintext.
"""

from __future__ import annotations

import pytest

from api.core import secrets

KEY = "test-key-not-used-anywhere-real"


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("MERIDIAN_SECRET_KEY", KEY)
    yield


def test_roundtrip(with_key):
    payload = {"client_secret": "s3cr3t", "refresh_token": "rt-abc-123"}
    assert secrets.decrypt(secrets.encrypt(payload)) == payload


def test_ciphertext_reveals_nothing(with_key):
    """A leaked backup should not yield the token by inspection."""
    blob = secrets.encrypt({"refresh_token": "correct-horse-battery-staple"})
    assert "correct-horse" not in blob
    assert "refresh_token" not in blob


def test_same_plaintext_encrypts_differently(with_key):
    """A fresh nonce per write. Deterministic ciphertext would let someone
    compare two rows and learn that two connections share a secret."""
    payload = {"password": "same"}
    assert secrets.encrypt(payload) != secrets.encrypt(payload)


def test_tampering_is_detected(with_key):
    blob = secrets.encrypt({"password": "original"})
    # Flip a character in the ciphertext body.
    body = list(blob)
    body[-5] = "A" if body[-5] != "A" else "B"
    tampered = "".join(body)

    with pytest.raises(ValueError, match="integrity check"):
        secrets.decrypt(tampered)


def test_a_different_key_cannot_decrypt(with_key, monkeypatch):
    blob = secrets.encrypt({"password": "original"})
    monkeypatch.setenv("MERIDIAN_SECRET_KEY", "a-completely-different-key")

    # Reported as an integrity failure rather than returning garbage, so the
    # operator learns the key changed instead of debugging a corrupt password.
    with pytest.raises(ValueError):
        secrets.decrypt(blob)


def test_no_key_refuses_rather_than_storing_plaintext(monkeypatch):
    """Storing credentials unencrypted 'for now' is how plaintext credentials
    reach production. The failure is loud instead.

    Both sources must be cleared: the key is read from the environment *and*
    from `.env` via settings, so unsetting only the environment variable
    leaves a developer's local key still in force.
    """
    from api.core.config import settings

    monkeypatch.delenv("MERIDIAN_SECRET_KEY", raising=False)
    monkeypatch.setattr(settings, "meridian_secret_key", "")

    assert not secrets.available()
    with pytest.raises(secrets.SecretsUnavailable):
        secrets.encrypt({"password": "x"})


def test_redaction_marks_presence_not_absence():
    """The UI must distinguish 'a secret is stored' from 'no secret set', or a
    user will regenerate a Workday token they did not need to."""
    out = secrets.redact({"client_id": "public", "client_secret": "hidden"})
    assert out["client_id"] == "public"
    assert out["client_secret"] == "••••••••"
    assert "hidden" not in str(out)


def test_redaction_omits_empty_secrets():
    out = secrets.redact({"client_secret": ""})
    assert "client_secret" not in out


def test_every_declared_password_field_is_also_redacted():
    """Encryption follows `kind='password'`; redaction follows SENSITIVE_FIELDS.

    Two lists that must agree, which is exactly the kind of pair that drifts
    when a connector is added. A secret encrypted at rest but echoed back by an
    endpoint that forgot to strip it is still a leaked secret.
    """
    from api.connectors import registry

    declared = {
        field.id
        for entry in registry.REGISTRY.values()
        for field in entry.credential_fields
        if field.kind == "password"
    }
    missing = declared - secrets.SENSITIVE_FIELDS
    assert not missing, f"password fields absent from SENSITIVE_FIELDS: {sorted(missing)}"


def test_settings_column_never_receives_a_secret():
    """The split that keeps a database dump from being a credential leak."""
    from api.services import connections as service

    secret_values, settings_values = service.split_credentials(
        "cx-azure-devops",
        {"organization": "contoso", "pat": "REAL-TOKEN", "projects": "Payroll"},
    )
    assert secret_values == {"pat": "REAL-TOKEN"}
    assert "pat" not in settings_values
    assert "REAL-TOKEN" not in str(settings_values)
