"""
Meridian session capture — the desktop helper.

Runs on the administrator's own machine, not on the Meridian server. That is
the entire reason it exists: a click in a web browser cannot open a login
window on someone's laptop, and a login window on the server has nobody sitting
at it.

What it does:

    1. Opens a real Chrome window at the customer's Workday login page.
    2. Waits while the administrator signs in — password, MFA, SSO, whatever
       their tenant enforces. Meridian is not involved and never sees any of it.
    3. Reads the resulting session state out of the browser it launched.
    4. Posts that session to Meridian over HTTPS.

What it deliberately does not do:

  - It never asks for, stores, or transmits a password. The only thing that
    leaves this machine is a session cookie set, which expires.
  - It never navigates anywhere except the login page. Discovery happens on
    the server, against recorded read-only recipes.
  - It never runs headless. The whole point is a human at a keyboard.

Usage:

    python meridian_capture.py \\
        --meridian https://meridian.internal \\
        --connection cn-abc123 \\
        --host https://wd2-impl-services1.workday.com \\
        --tenant acme_preview

Packaged for distribution with PyInstaller; run directly during development.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from urllib import error, request

#: Markers that mean Workday's authenticated shell has rendered. Waiting on any
#: of these rather than on navigation is what makes this tolerate MFA, SSO
#: redirects and whatever else sits between the login form and the home page —
#: however many hops there are, the wait ends when the person is actually in.
SIGNED_IN_MARKERS = (
    "[data-automation-id='globalSearchInput']",
    "[data-automation-id='navigationBar']",
    "[data-automation-id='workdayLogo']",
)


def log(message: str) -> None:
    print(message, flush=True)


def capture(host: str, tenant: str, timeout_seconds: int) -> str:
    """Open a browser, wait for sign-in, return the session state."""
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        log(
            "Playwright is not installed.\n"
            "  pip install playwright && playwright install chromium"
        )
        raise SystemExit(2) from None

    landing = f"{host.rstrip('/')}/{tenant}/login.htmld"
    log(f"Opening {landing}")
    log("Sign in as you normally would. This window will close by itself.")

    with sync_playwright() as pw:
        # Headed, always. A headless browser has nobody to satisfy the MFA
        # prompt, and a flag to disable this would only ever be used wrongly.
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(landing, wait_until="domcontentloaded")
            page.wait_for_selector(
                ", ".join(SIGNED_IN_MARKERS), timeout=timeout_seconds * 1000
            )
            state = context.storage_state()
        except PWTimeout:
            log(
                f"\nSign-in was not completed within {timeout_seconds}s. "
                "Nothing was captured."
            )
            raise SystemExit(1) from None
        finally:
            context.close()
            browser.close()

    log("Signed in. Session captured.")
    return json.dumps(state)


def post(
    meridian: str,
    connection_id: str,
    state_json: str,
    *,
    token: str,
    captured_by: str,
    ttl_minutes: int | None,
) -> dict:
    """Send the session to Meridian."""
    url = f"{meridian.rstrip('/')}/api/connections/{connection_id}/browser-session"
    payload = {
        "stateJson": state_json,
        "capturedBy": captured_by,
        "ttlMinutes": ttl_minutes,
    }
    body = json.dumps(payload).encode("utf-8")

    req = request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Actor-Email", captured_by)
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        log(f"\nMeridian rejected the session ({exc.code}): {detail}")
        raise SystemExit(1) from None
    except error.URLError as exc:
        log(f"\nCould not reach Meridian at {meridian}: {exc.reason}")
        raise SystemExit(1) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="meridian-capture",
        description="Capture a Workday browser session for Meridian.",
    )
    parser.add_argument("--meridian", required=True, help="Meridian base URL")
    parser.add_argument("--connection", required=True, help="Connection id")
    parser.add_argument("--host", required=True, help="Workday host URL")
    parser.add_argument("--tenant", required=True, help="Workday tenant name")
    parser.add_argument(
        "--captured-by",
        default="",
        help="Your email. Recorded so the extraction is attributable.",
    )
    parser.add_argument(
        "--ttl-minutes",
        type=int,
        default=None,
        help="Your tenant's session idle timeout, if you know it.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for sign-in (default 300).",
    )
    args = parser.parse_args(argv)

    captured_by = args.captured_by or getpass.getuser()

    # The API token is read from the environment or prompted for, never taken
    # as an argument: command lines end up in shell history and process lists.
    import os

    token = os.environ.get("MERIDIAN_TOKEN", "")

    log("")
    log("Meridian session capture")
    log("------------------------")
    log("Meridian never receives your password. It receives only the session")
    log("your browser creates after you sign in, and that session expires.")
    log("")

    state_json = capture(args.host, args.tenant, args.timeout)
    result = post(
        args.meridian,
        args.connection,
        state_json,
        token=token,
        captured_by=captured_by,
        ttl_minutes=args.ttl_minutes,
    )

    log("")
    log(f"Sent to Meridian. {result.get('message', '')}")
    if result.get("expiresAt"):
        log(f"Expires at: {result['expiresAt']}")
    log("Screen discovery can now run until then.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
