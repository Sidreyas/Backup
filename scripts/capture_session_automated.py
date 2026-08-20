"""
Capture a Workday session by signing in automatically.

The shipped flow (`tools/meridian_capture.py`) opens a browser and waits for a
human to type the password, so Meridian never holds one. This script is the
automated alternative: it drives the login itself, which means the password
must exist somewhere.

It is a **testing** tool, deliberately kept out of the product path:

  - Credentials come from the environment, never from argv (visible in `ps`)
    and never from the database.
  - It writes the resulting session through the same `browser_sessions.capture`
    service the helper posts to, so what is stored and how it is encrypted are
    identical to the real flow.
  - It cannot work against a tenant with MFA. That is not a bug to fix — it is
    the reason the human-in-the-loop flow exists.

Usage:

    export WORKDAY_USERNAME=... WORKDAY_PASSWORD=...
    python scripts/capture_session_automated.py --connection cn-xxxx
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Run as `python scripts/capture_session_automated.py` from the repo root, so
# the repo itself is not on the path — only `scripts/` is. The other scripts
# here are standalone; this is the first to import the application.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.core.db import SessionLocal
from api.domain.models import Connection
from api.services import browser_sessions

#: Workday's login form, as it actually renders on the identity gateway.
#:
#: Probed against a live tenant rather than assumed: `/login.htmld` redirects
#: to a separate identity host (`<tenant>-identity.../wday/authgwy/...`), and
#: there the username field carries **no** `data-automation-id` — only the
#: password and submit do. Selecting `[data-automation-id='username']` matches
#: nothing and the script waits for the full timeout with an empty browser,
#: which reads as a hang rather than a bad selector.
#:
#: Ordered most- to least-specific; `.first` picks the winner.
USERNAME = (
    "[data-automation-id='username'] input, "
    "[data-automation-id='username'], "
    "input[type='text']"
)
PASSWORD = "[data-automation-id='password'] input, input[type='password']"
SUBMIT = "[data-automation-id='goButton'], button[type='submit']"


def _login_error(page) -> str:
    """Whatever the login page is complaining about.

    Tries the places Workday puts a message before falling back to body text.
    Returned as a string rather than raised on, because "no message found" is
    itself informative: it points at the submit never having been accepted rather
    than at the credentials being rejected.
    """
    for selector in (
        "[data-automation-id='errorMessage']",
        "[data-automation-id='alertMessage']",
        "[role='alert']",
        ".wd-Error",
        "[class*='error' i]",
    ):
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible():
                text = (locator.inner_text() or "").strip()
                if text:
                    return " | ".join(text.splitlines())[:300]
        except Exception:
            continue

    try:
        body = (page.inner_text("body") or "").strip()
    except Exception:
        return "(could not read the page)"

    # Keep only lines that look like a message, so the reader is not handed a
    # navigation menu and asked to spot the error in it.
    lines = [
        line.strip()
        for line in body.splitlines()
        if line.strip() and len(line.strip()) > 12
    ]
    return " | ".join(lines[:6])[:400] or "(no visible text)"


def sign_in(host: str, tenant: str, username: str, password: str, *, headless: bool):
    """Return Playwright storage state as JSON after a completed sign-in."""
    from playwright.sync_api import sync_playwright

    login_url = f"{host.rstrip('/')}/{tenant}/login.htmld"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1600, "height": 1200})
        page = context.new_page()
        # Generous: launching a browser cold on a Windows host with real-time
        # antivirus has been measured at 40s here before a single navigation.
        page.set_default_timeout(90_000)

        print(f"  opening {login_url}")
        page.goto(login_url, wait_until="domcontentloaded")
        # /login.htmld redirects to the identity gateway; wait for the form
        # itself rather than assuming the first paint is the login page.
        page.wait_for_selector(PASSWORD, timeout=90_000)
        print(f"  login form on {page.url}")

        page.locator(USERNAME).first.fill(username)
        page.locator(PASSWORD).first.fill(password)
        page.locator(SUBMIT).first.click()

        # Wait for the *password* field to go: the username selector falls back
        # to `input[type=text]`, which matches search boxes on the landing page
        # too, so waiting for it to detach can return immediately or never.
        #
        # The timeout is caught rather than allowed to propagate. Workday reports
        # a rejected sign-in by re-rendering the same form with a message beside
        # it — no HTTP error, no navigation — so the field simply never detaches
        # and the raw Playwright timeout says only that a selector stayed visible.
        # The reason is on the page, and it is the whole content of the answer:
        # a wrong password, a locked account, a rate limit and an unexpected MFA
        # prompt all produce this identical timeout and need four different fixes.
        try:
            page.wait_for_selector(PASSWORD, state="detached", timeout=60_000)
            page.wait_for_load_state("networkidle")
        except Exception:
            shot = Path("tmp_login_failure.png").resolve()
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:
                shot = None
            reason = _login_error(page)
            url = page.url
            context.close()
            browser.close()
            lines = [
                "Sign-in did not complete: the password field never went away.",
                f"  url    : {url}",
                f"  page   : {reason}",
            ]
            if shot:
                lines.append(f"  shot   : {shot}")
            lines.append(
                "  Re-run with --headed (or --watch-login via probe_wql.py) to "
                "watch the page if the message above is not enough."
            )
            raise SystemExit("\n".join(lines)) from None

        url = page.url
        print(f"  landed on {url}")

        # A failed sign-in re-renders the form rather than returning an HTTP
        # error, so success is judged by the form being gone — not by the URL.
        # The URL cannot be used: sign-in happens on an identity host whose
        # path contains "/login", so a URL test marks a *successful* login as
        # failed.
        if page.locator(PASSWORD).count():
            body = page.inner_text("body")[:400]
            context.close()
            browser.close()
            raise SystemExit(f"Sign-in did not complete. Page said:\n{body}")

        state = context.storage_state()
        context.close()
        browser.close()

    return json.dumps(state)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--connection", required=True)
    parser.add_argument("--headed", action="store_true", help="watch the login")
    args = parser.parse_args()

    username = os.environ.get("WORKDAY_USERNAME", "")
    password = os.environ.get("WORKDAY_PASSWORD", "")
    if not username or not password:
        print("Set WORKDAY_USERNAME and WORKDAY_PASSWORD in the environment.")
        return 2

    db = SessionLocal()
    connection = db.get(Connection, args.connection)
    if connection is None:
        print(f"No connection {args.connection}")
        return 2

    settings = connection.settings or {}
    host = str(settings.get("host") or "")
    tenant = str(settings.get("tenant") or "")
    if not host or not tenant:
        print("Connection has no host/tenant configured.")
        return 2

    print(f"Signing in to {tenant} as {username}")
    state_json = sign_in(
        host, tenant, username, password, headless=not args.headed
    )

    browser_sessions.capture(
        db,
        connection_id=connection.id,
        state_json=state_json,
        captured_by=f"{username} (automated)",
        workspace_id=connection.workspace_id or "ws-default",
    )
    db.commit()

    status = browser_sessions.status(db, connection.id)
    print(
        f"Session stored. present={status.present} "
        f"expires in {status.remaining_seconds // 60} min"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
