"""
Browser session endpoints.

Two consumers, deliberately different in what they may do:

  - The **desktop capture helper** posts a session it obtained from a browser
    the administrator signed into on their own machine. It is the only thing
    that writes here.
  - The **UI** reads status and can revoke. It never sees a session, because
    displaying one would put a live credential on a screen and in a browser's
    memory for no benefit.

The capture flow exists because Workday has no OAuth for its UI. Where a
platform offers one, Meridian uses it — this is the fallback for configuration
that lives only on screens, and it is deliberately the most restricted surface
in the product.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.core.db import get_db
from api.domain.models import Connection
from api.routers.deps import Actor, current_actor, current_workspace
from api.services import browser_sessions

router = APIRouter(tags=["sessions"])


class CaptureInput(BaseModel):
    #: Playwright storage state as JSON. Never logged, never echoed.
    stateJson: str = Field(min_length=2, max_length=2_000_000)
    #: Who signed in. Sent by the helper rather than taken from the request
    #: actor because the person at the browser and the person holding the API
    #: token need not be the same, and the session carries the former's
    #: permissions.
    capturedBy: str = ""
    #: Tenant idle timeout in minutes, when the helper could determine it.
    ttlMinutes: int | None = None


class SessionStatusOut(BaseModel):
    present: bool
    capturedBy: str = ""
    capturedAt: str = ""
    expiresAt: str = ""
    lastUsedAt: str = ""
    remainingSeconds: int = 0
    expired: bool = False
    expiringSoon: bool = False
    message: str = ""


def _out(status: browser_sessions.SessionStatus) -> SessionStatusOut:
    return SessionStatusOut(
        present=status.present,
        capturedBy=status.captured_by,
        capturedAt=status.captured_at,
        expiresAt=status.expires_at,
        lastUsedAt=status.last_used_at,
        remainingSeconds=status.remaining_seconds,
        expired=status.expired,
        expiringSoon=status.expiring_soon,
        message=status.message,
    )


def _connection(db: Session, connection_id: str) -> Connection:
    connection = db.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


@router.get(
    "/connections/{connection_id}/browser-session",
    response_model=SessionStatusOut,
)
def get_session(
    connection_id: str, db: Session = Depends(get_db)
) -> SessionStatusOut:
    """Whether a session exists, who captured it, and how long it has left.

    Never the session itself.
    """
    _connection(db, connection_id)
    return _out(browser_sessions.status(db, connection_id))


@router.post(
    "/connections/{connection_id}/browser-session",
    response_model=SessionStatusOut,
    status_code=201,
)
def post_session(
    connection_id: str,
    body: CaptureInput,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> SessionStatusOut:
    """Store a session captured on an administrator's machine."""
    connection = _connection(db, connection_id)

    from datetime import timedelta

    ttl = (
        timedelta(minutes=body.ttlMinutes)
        if body.ttlMinutes and body.ttlMinutes > 0
        else browser_sessions.DEFAULT_TTL
    )

    try:
        browser_sessions.capture(
            db,
            connection_id=connection.id,
            state_json=body.stateJson,
            captured_by=body.capturedBy or actor.email,
            workspace_id=connection.workspace_id or workspace_id,
            ttl=ttl,
        )
    except browser_sessions.SessionUnavailable as exc:
        # 422 rather than 500: every failure here is something the caller can
        # fix — an unconfigured key, a payload that is not a session, a login
        # that was not completed.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.commit()
    return _out(browser_sessions.status(db, connection_id))


@router.get("/capture-tool")
def get_capture_tool() -> Response:
    """The capture tool's source, fetched by the launcher.

    Served from this server rather than bundled into the launcher so the two
    cannot drift: a launcher saved months ago downloads whatever the current
    Meridian expects, and there is one copy of the tool rather than one per
    download.
    """
    source = Path(__file__).resolve().parents[2] / "tools" / "meridian_capture.py"
    if not source.exists():
        raise HTTPException(
            status_code=500,
            detail="The capture tool is missing from this Meridian install.",
        )
    return Response(
        content=source.read_text(encoding="utf-8"),
        media_type="text/x-python",
    )


@router.get("/connections/{connection_id}/browser-session/launcher")
def get_launcher(
    connection_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """A pre-configured launcher script for this connection.

    Meridian generates it rather than asking an administrator to assemble a
    command. The connection id, tenant host and API address are all things the
    server already knows and a person would otherwise copy by hand — and a
    mistyped tenant produces a login page for the wrong customer, which is a
    bad failure to hand someone.

    Windows gets `.cmd`, everything else `.sh`, chosen from the User-Agent.
    Guessing wrong costs a rename; asking would put an operating-system
    question in front of someone trying to sign in.
    """
    connection = _connection(db, connection_id)
    settings_blob = connection.settings or {}
    host = str(settings_blob.get("host") or "")
    tenant = str(settings_blob.get("tenant") or "")

    # The server's address as this request reached it, so the launcher points
    # back at whatever served it rather than at a build-time constant that is
    # wrong in every deployment but one.
    #
    # `base_url` is the *root* — it excludes the router's /api prefix — so the
    # two URLs are built separately. `--meridian` takes the root because the
    # capture tool appends /api itself; the tool download needs the prefix
    # spelled out. Using one value for both produced a 404 on the download.
    server_root = str(request.base_url).rstrip("/")
    api_base = f"{server_root}/api"

    windows = "windows" in (request.headers.get("user-agent") or "").lower()
    body = (
        _WINDOWS_LAUNCHER if windows else _POSIX_LAUNCHER
    ).format(
        api_base=api_base,
        server_root=server_root,
        connection_id=connection.id,
        host=host,
        tenant=tenant,
        label=connection.label,
    )
    suffix = "cmd" if windows else "sh"
    filename = f"meridian-capture-{connection.id}.{suffix}"

    return Response(
        content=body,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


#: Launchers are generated per connection rather than shipped as a static file
#: because the values that make them work — which Meridian, which connection,
#: which tenant — differ per connection and are exactly what a person would
#: mistype.
#: Both launchers fetch the capture tool from the Meridian that served them.
#:
#: The alternative — assuming `meridian_capture` is installed — fails on a
#: machine that has never run this, which is every machine the first time. A
#: self-contained script that downloads what it needs is the difference between
#: "run this" and "run this after installing four things".
_POSIX_LAUNCHER = """#!/usr/bin/env bash
# Meridian session capture — {label}
#
# Opens a browser so you can sign in to Workday. Meridian never receives your
# password; it receives only the session your browser creates, and that session
# expires.
set -euo pipefail

echo "Meridian session capture — {label}"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required but was not found. Install it from python.org."
  exit 1
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "Preparing (first run takes a minute)..."
python3 -m pip install --quiet --upgrade playwright
python3 -m playwright install chromium

curl -fsSL "{api_base}/capture-tool" -o "$WORKDIR/meridian_capture.py"

python3 "$WORKDIR/meridian_capture.py" \\
  --meridian "{server_root}" \\
  --connection "{connection_id}" \\
  --host "{host}" \\
  --tenant "{tenant}"
"""

_WINDOWS_LAUNCHER = """@echo off
setlocal
REM Meridian session capture — {label}
REM
REM Opens a browser so you can sign in to Workday. Meridian never receives your
REM password; it receives only the session your browser creates, and that
REM session expires.

echo Meridian session capture - {label}
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo Python 3 is required but was not found. Install it from python.org.
  pause
  exit /b 1
)

echo Preparing ^(first run takes a minute^)...
python -m pip install --quiet --upgrade playwright
python -m playwright install chromium

curl -fsSL "{api_base}/capture-tool" -o "%TEMP%\\meridian_capture.py"

python "%TEMP%\\meridian_capture.py" ^
  --meridian "{server_root}" ^
  --connection "{connection_id}" ^
  --host "{host}" ^
  --tenant "{tenant}"

if errorlevel 1 pause
"""


@router.delete(
    "/connections/{connection_id}/browser-session",
    response_model=SessionStatusOut,
)
def delete_session(
    connection_id: str,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> SessionStatusOut:
    """Revoke the current session.

    The row is kept and marked revoked rather than deleted: configuration
    extracted using it is attributed to that capture, and removing the record
    would orphan the provenance.
    """
    _connection(db, connection_id)
    browser_sessions.revoke(db, connection_id, reason=f"revoked by {actor.email}")
    db.commit()
    return _out(browser_sessions.status(db, connection_id))
