"""
Browser session lifecycle.

A captured session carries a real administrator's permissions in a customer's
tenant, which makes it the most powerful thing Meridian holds for a connection.
Most of what is tested here is therefore about *containment*: that it is
encrypted, that it is never returned, that it supersedes rather than
accumulates, and that an expired one is distinguishable from an absent one.

The last distinction matters more than it looks. "Expired" and "never captured"
have different fixes — sign in again, versus set this up for the first time —
and a UI that conflates them sends people to the wrong place.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from api.core import secrets
from api.core.ids import new_id, utcnow
from api.domain.models import BrowserSessionRecord, Connection
from api.services import browser_sessions

VALID_STATE = json.dumps(
    {
        "cookies": [
            {"name": "wd-browser-id", "value": "abc", "domain": ".workday.com"}
        ],
        "origins": [],
    }
)


@pytest.fixture
def connection(db) -> Connection:
    cn = Connection(
        id=new_id("cn"),
        connector_id="cx-workday",
        label="Implementation Tenant",
        workspace_id="ws-sess",
    )
    db.add(cn)
    db.flush()
    return cn


def _capture(db, connection, **kw) -> BrowserSessionRecord:
    return browser_sessions.capture(
        db,
        connection_id=connection.id,
        state_json=kw.pop("state_json", VALID_STATE),
        captured_by=kw.pop("captured_by", "admin@acme.example"),
        workspace_id=connection.workspace_id,
        **kw,
    )


# --- storage ----------------------------------------------------------------


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_the_session_is_encrypted_at_rest(db, connection):
    """The cookies *are* the administrator until they expire.

    A database dump containing a readable session would be a credential leak
    with extra steps.
    """
    record = _capture(db, connection)
    assert VALID_STATE not in record.state_encrypted
    assert "wd-browser-id" not in record.state_encrypted
    assert browser_sessions.state(db, connection.id) == VALID_STATE


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_capturing_supersedes_rather_than_accumulates(db, connection):
    """Several live sessions would mean several answers to "whose access read
    this", which is the question an auditor actually asks."""
    first = _capture(db, connection, captured_by="one@acme.example")
    second = _capture(db, connection, captured_by="two@acme.example")

    assert first.revoked_at is not None
    assert "superseded" in (first.revoked_reason or "")
    assert browser_sessions.live_session(db, connection.id).id == second.id


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_a_superseded_session_is_kept_not_deleted(db, connection):
    """Configuration extracted with a session is attributed to that capture.

    Deleting the row would orphan the provenance.
    """
    _capture(db, connection)
    _capture(db, connection)
    rows = (
        db.query(BrowserSessionRecord)
        .filter(BrowserSessionRecord.connection_id == connection.id)
        .all()
    )
    assert len(rows) == 2


# --- what is rejected --------------------------------------------------------


def test_a_payload_that_is_not_json_is_refused(db, connection):
    with pytest.raises(browser_sessions.SessionUnavailable, match="does not look like"):
        _capture(db, connection, state_json="not json at all")


def test_a_session_with_no_cookies_is_refused(db, connection):
    """An incomplete sign-in produces a storage state with nothing in it.

    Storing it would mean discovery failing later with a confusing error rather
    than the admin being told now that they did not finish signing in.
    """
    with pytest.raises(browser_sessions.SessionUnavailable, match="not an\\s+authenticated"):
        _capture(db, connection, state_json=json.dumps({"cookies": [], "origins": []}))


# --- status reporting --------------------------------------------------------


def test_no_session_is_reported_as_absent_not_expired(db, connection):
    status = browser_sessions.status(db, connection.id)
    assert status.present is False
    assert status.expired is False
    assert "No session captured" in status.message


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_a_live_session_reports_who_captured_it(db, connection):
    _capture(db, connection, captured_by="priya@acme.example")
    status = browser_sessions.status(db, connection.id)

    assert status.present is True
    assert status.expired is False
    assert status.captured_by == "priya@acme.example"
    assert status.remaining_seconds > 0


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_an_expired_session_is_present_but_expired(db, connection):
    """The two states have different fixes and must not be conflated."""
    record = _capture(db, connection)
    record.expires_at = utcnow() - timedelta(minutes=5)
    db.flush()

    status = browser_sessions.status(db, connection.id)
    assert status.present is True
    assert status.expired is True
    assert "expired" in status.message.lower()


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_a_session_about_to_expire_warns_before_a_long_run(db, connection):
    """Warning early costs a re-capture; warning late costs a failed run."""
    record = _capture(db, connection)
    record.expires_at = utcnow() + timedelta(minutes=4)
    db.flush()

    status = browser_sessions.status(db, connection.id)
    assert status.expiring_soon is True
    assert status.expired is False


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_status_never_carries_the_session(db, connection):
    _capture(db, connection)
    status = browser_sessions.status(db, connection.id)
    serialised = json.dumps(status.__getstate__() if hasattr(status, "__getstate__") else {
        k: getattr(status, k) for k in status.__slots__
    })
    assert "wd-browser-id" not in serialised
    assert "cookies" not in serialised


# --- use and revocation ------------------------------------------------------


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_use_is_recorded_so_captured_and_working_are_distinguishable(db, connection):
    _capture(db, connection)
    assert browser_sessions.status(db, connection.id).last_used_at == ""

    browser_sessions.mark_used(db, connection.id)
    db.flush()
    assert browser_sessions.status(db, connection.id).last_used_at != ""


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_revoking_ends_the_session_without_losing_the_record(db, connection):
    _capture(db, connection)
    assert browser_sessions.revoke(db, connection.id, reason="test") is True

    assert browser_sessions.live_session(db, connection.id) is None
    assert browser_sessions.status(db, connection.id).present is False
    assert (
        db.query(BrowserSessionRecord)
        .filter(BrowserSessionRecord.connection_id == connection.id)
        .count()
        == 1
    )


def test_revoking_nothing_is_not_an_error(db, connection):
    assert browser_sessions.revoke(db, connection.id) is False


def test_reading_a_session_that_does_not_exist_explains_the_fix(db, connection):
    with pytest.raises(
        browser_sessions.SessionUnavailable, match="administrator must sign in"
    ):
        browser_sessions.state(db, connection.id)


# --- the generated launcher --------------------------------------------------


def _launcher(connection, *, windows: bool) -> str:
    """Render a launcher the way the endpoint does.

    The template substitution is what these tests are about; going through
    FastAPI would test the routing instead.
    """
    from api.routers.sessions import _POSIX_LAUNCHER, _WINDOWS_LAUNCHER

    template = _WINDOWS_LAUNCHER if windows else _POSIX_LAUNCHER
    return template.format(
        api_base="https://meridian.example/api",
        server_root="https://meridian.example",
        connection_id=connection.id,
        host="https://wd2-impl-services1.workday.com",
        tenant="acme_preview",
        label=connection.label,
    )


def test_the_launcher_carries_every_value_a_person_would_mistype(connection):
    """The whole reason the server generates this.

    A hand-assembled command with the wrong tenant sends someone to a different
    customer's login page.
    """
    script = _launcher(connection, windows=False)
    assert connection.id in script
    assert "acme_preview" in script
    assert "wd2-impl-services1.workday.com" in script


def test_the_tool_download_and_the_api_root_are_different_urls(connection):
    """`--meridian` takes the server root because the tool appends /api itself;
    the download needs the prefix spelled out.

    Using one value for both produced a 404 on the download — silently, since
    the launcher only fails once someone runs it.
    """
    script = _launcher(connection, windows=False)
    assert 'curl -fsSL "https://meridian.example/api/capture-tool"' in script
    assert '--meridian "https://meridian.example"' in script


def test_the_launcher_never_contains_a_credential(connection):
    """It is emailed, saved to Downloads, and pasted into chat.

    Nothing in it may be secret — it names a connection and a tenant, both of
    which are already visible in the UI.
    """
    for windows in (True, False):
        script = _launcher(connection, windows=windows)
        # Comment lines legitimately mention "password" — they are the
        # assurance that Meridian never receives one. Only executable lines
        # could actually carry a secret.
        executable = "\n".join(
            line
            for line in script.splitlines()
            if line.strip()
            and not line.strip().startswith(("#", "REM", "rem", "echo", "@echo"))
        )
        for marker in ("password", "secret", "token", "cookie", "apikey"):
            assert marker not in executable.lower()


def test_the_windows_launcher_uses_windows_conventions(connection):
    script = _launcher(connection, windows=True)
    assert script.startswith("@echo off")
    assert "%TEMP%" in script
    assert "^" in script  # line continuation
    assert "\\\n" not in script  # not the POSIX one


def test_the_posix_launcher_fails_loudly_without_python(connection):
    """A missing interpreter must say so, not produce a stack trace."""
    script = _launcher(connection, windows=False)
    assert "Python 3 is required" in script
    assert "set -euo pipefail" in script


# --- reaching the connector -------------------------------------------------
#
# The session was stored correctly and never arrived. `config_for` built the
# connector from settings and credentials, the session lived in its own table,
# and nothing joined the two — so screen discovery worked from a script that
# passed the session explicitly and quietly did nothing through the product's own
# sync path. Nothing failed: the connector reported "no session captured", which
# was true of the config it was handed and false of the database.


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_a_captured_session_reaches_the_connector(db, connection):
    """The join that was missing."""
    from api.services import connections

    _capture(db, connection)

    config = connections.config_for(connection, db)

    assert config["browser_session_state"], "the session must reach the connector"
    assert config["browser_session_captured_by"] == "admin@acme.example"

    connector = connections.build_from_connection(connection, db)
    assert connector.browser_session is not None
    assert connector.browser_session.is_present()


def test_without_a_session_the_connector_says_so_rather_than_pretending(db, connection):
    from api.services import connections

    connector = connections.build_from_connection(connection, db)

    assert connector.browser_session is None


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_an_expired_session_still_reaches_the_connector(db, connection):
    """Withholding it would collapse two different problems into one.

    "Expired, re-capture" and "never captured" have different fixes, and the
    connector is the thing that can tell them apart — but only if it is given the
    expired session rather than nothing.
    """
    from api.services import connections

    record = _capture(db, connection)
    record.expires_at = utcnow() - timedelta(hours=2)
    db.flush()

    config = connections.config_for(connection, db)

    assert config["browser_session_state"]
    assert config["browser_session_expires_at"]


@pytest.mark.skipif(not secrets.available(), reason="no encryption key configured")
def test_a_revoked_session_does_not_reach_the_connector(db, connection):
    """Revocation is the one case where withholding is the point."""
    from api.services import connections

    _capture(db, connection)
    browser_sessions.revoke(db, connection.id, reason="rotated")

    config = connections.config_for(connection, db)

    assert "browser_session_state" not in config


def test_the_session_is_not_included_when_no_db_is_passed(db, connection):
    """Callers that only need credentials must not silently trigger a lookup."""
    from api.services import connections

    config = connections.config_for(connection)

    assert "browser_session_state" not in config
