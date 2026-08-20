"""
Creating and running connections.

The one place that knows how to turn a stored `Connection` row back into a live
connector: decrypt its credentials, merge its settings, and hand the result to
the registry. Everything else — routers, the ingestion pipeline, the scheduler
— goes through `build_from_connection` so credential handling exists once.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from api.connectors import registry
from api.connectors.base import EnterpriseConnector
from api.core import secrets
from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.models import Connection, KnowledgeSource
from api.services import browser_sessions


class CredentialsRequired(Exception):
    """The connector needs values the caller did not supply.

    Carries the field labels rather than ids so the message can be shown
    directly: "Still needed: Token endpoint, Client ID" is actionable in a way
    that a list of snake_case keys is not.
    """

    def __init__(self, missing: list[str]) -> None:
        super().__init__("Missing: " + ", ".join(missing))
        self.missing = missing


def split_credentials(
    connector_id: str, values: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate secret values from ordinary settings.

    Driven by the connector's declared credential fields rather than by a
    hardcoded list, so a new connector cannot accidentally have a secret
    treated as a plain setting.
    """
    entry = registry.get(connector_id)
    secret_ids = {
        f.id
        for f in (entry.credential_fields if entry else [])
        if f.kind == "password" or f.id in secrets.SENSITIVE_FIELDS
    }

    secret_values = {k: v for k, v in values.items() if k in secret_ids and v not in (None, "")}
    settings = {k: v for k, v in values.items() if k not in secret_ids}
    return secret_values, settings


def validate_required(connector_id: str, values: dict[str, Any]) -> list[str]:
    """Which required fields are still empty, by their UI labels."""
    entry = registry.get(connector_id)
    if entry is None or not entry.credential_fields:
        return []

    method = str(values.get("method", "")).strip()

    missing: list[str] = []
    for field in entry.credential_fields:
        if not field.required:
            continue

        if field.auth_methods:
            # A method-scoped field is only required once a method is chosen.
            # Without this guard, an empty form demands every field from all
            # three Workday auth methods at once — including two different
            # fields both labelled "Integration System User", which is worse
            # than no guidance at all.
            if not method or method not in field.auth_methods:
                continue

        if not str(values.get(field.id, "")).strip():
            missing.append(field.label)

    # De-duplicated: two auth methods can legitimately share a label, and the
    # same requirement listed twice reads as a bug.
    return list(dict.fromkeys(missing))


def config_for(
    connection: Connection, db: Session | None = None
) -> dict[str, Any]:
    """Rebuild the connector config from a stored connection.

    `db` is optional because two of the three callers only need credentials. Pass
    it when the connector may need a captured browser session: sessions live in
    their own table rather than in `settings`, so without a session lookup a
    connector is built believing none exists.

    That was a real defect rather than a hypothetical. Screen discovery ran
    correctly from a script that handed the session over explicitly, and silently
    did nothing through the product's own sync path — the connector read
    `browser_session_state` from its config, and nothing ever put it there. The
    failure was invisible because a missing session is a legitimate state: the
    connector reported "no session captured", which was true of the config it had
    been given and false of the database.
    """
    config: dict[str, Any] = dict(connection.settings or {})

    if connection.credentials_encrypted:
        config.update(secrets.decrypt(connection.credentials_encrypted))

    config["granted_scopes"] = list(connection.granted_scopes or [])

    if db is not None:
        record = browser_sessions.live_session(db, connection.id)
        if record is not None:
            # Expired sessions are passed through deliberately. The connector
            # distinguishes "expired, re-capture" from "never captured", and
            # withholding an expired session here would collapse the two into
            # the less actionable one.
            config["browser_session_state"] = browser_sessions.state(
                db, connection.id
            )
            config["browser_session_captured_by"] = record.captured_by
            config["browser_session_captured_at"] = (
                record.captured_at.isoformat() if record.captured_at else ""
            )
            config["browser_session_expires_at"] = (
                record.expires_at.isoformat() if record.expires_at else ""
            )

    return config


def build_from_connection(
    connection: Connection, db: Session | None = None
) -> EnterpriseConnector:
    """Instantiate the connector this connection points at."""
    return registry.build(connection.connector_id, config_for(connection, db))


def create(
    db: Session,
    *,
    connector_id: str,
    label: str,
    auth_method: str,
    granted_scopes: list[str],
    cadence: str,
    owner: str,
    values: dict[str, Any],
    connected_by: str,
    workspace_id: str | None,
) -> Connection:
    """Register a new connection and its knowledge source."""
    entry = registry.get(connector_id)
    if entry is None:
        raise KeyError(f"Unknown connector: {connector_id}")
    if not entry.implemented:
        raise NotImplementedError(
            f"The {entry.name} connector is declared but not yet implemented."
        )

    missing = validate_required(connector_id, values)
    if missing:
        raise CredentialsRequired(missing)

    secret_values, settings = split_credentials(connector_id, values)

    encrypted: str | None = None
    if secret_values:
        # Refuses rather than falling back to plaintext. Storing credentials
        # unencrypted "for now" is how plaintext credentials reach production.
        encrypted = secrets.encrypt(secret_values)

    required = [s.id for s in entry.scopes if s.required]

    source = KnowledgeSource(
        id=new_id("src"),
        workspace_id=workspace_id,
        name=label.strip() or entry.name,
        kind=entry.kind,
        provider=entry.name,
        # Indexing, not connected: claiming readiness before the first sync
        # would be a lie the very next screen exposes.
        status=enums.IngestStatus.INDEXING,
        owner=owner,
    )
    db.add(source)
    db.flush()

    connection = Connection(
        id=new_id("cn"),
        connector_id=connector_id,
        label=label.strip() or entry.name,
        status=enums.IngestStatus.INDEXING,
        auth_method=auth_method,
        granted_scopes=sorted({*required, *granted_scopes}),
        cadence=cadence,
        owner=owner,
        connected_by=connected_by,
        connected_at=utcnow(),
        record_count=0,
        source_id=source.id,
        workspace_id=workspace_id,
        credentials_encrypted=encrypted,
        settings=settings,
    )
    db.add(connection)
    db.flush()
    return connection


def update_credentials(
    db: Session, connection: Connection, values: dict[str, Any]
) -> Connection:
    """Merge new credential values into an existing connection.

    Merged rather than replaced: the UI shows secrets as `••••••••` and sends
    back only what the user actually retyped. Replacing wholesale would wipe
    every secret the user did not touch.
    """
    secret_values, settings = split_credentials(connection.connector_id, values)

    if secret_values:
        existing = (
            secrets.decrypt(connection.credentials_encrypted)
            if connection.credentials_encrypted
            else {}
        )
        existing.update(secret_values)
        connection.credentials_encrypted = secrets.encrypt(existing)

    if settings:
        connection.settings = {**(connection.settings or {}), **settings}

    db.flush()
    return connection


def redacted_settings(connection: Connection) -> dict[str, Any]:
    """Connection settings plus presence markers for stored secrets.

    The markers matter: a user editing a connection needs to see that a client
    secret is already stored, or they will assume it was lost and go
    regenerate one in Workday for no reason.
    """
    out = dict(connection.settings or {})
    if connection.credentials_encrypted:
        try:
            stored = secrets.decrypt(connection.credentials_encrypted)
        except (ValueError, secrets.SecretsUnavailable):
            # An unreadable blob is reported as such rather than as absent —
            # "no credentials" and "credentials encrypted under a key this
            # process does not have" need different fixes.
            return {**out, "_credentialsUnreadable": True}
        out.update(secrets.redact(stored))
    return out
