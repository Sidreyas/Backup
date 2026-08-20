"""
Probe a Workday tenant for Workday Query Language (WQL) access.

Answers one question the documentation cannot: **is WQL usable through the
browser, with a named account and no Integration System User?**

That matters because the WQL REST API is OAuth-only. If WQL is reachable only
over the API, it is blocked behind exactly the ISU nobody has issued, and is no
better off than SOAP or RaaS. If it is reachable as a *task in the tenant*, then
screen discovery can drive it today — and a query language over report data
sources reaches business process definitions and condition rules, which no API
returns at any permission level.

**Controls are the point.** Searching for a task and finding nothing proves two
different things: the tenant lacks it, or this account cannot see it. So a task
we know an implementation-tenant admin holds is probed alongside, and a term that
should match nothing is probed too. Without the first, absence is unreadable;
without the second, a search box that matches everything looks like success.

Read-only. It types in the global search box and reads what comes back. It does
not click into tasks that could submit anything, and it never runs a query with
side effects — WQL is read-only by design in any case.

Usage:

    export WORKDAY_USERNAME=... WORKDAY_PASSWORD=...
    python scripts/probe_wql.py --connection cn-xxxx --capture
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.core.db import SessionLocal
from api.domain.models import Connection
from api.services import browser_sessions

SEARCH_INPUT = "[data-automation-id='globalSearchInput']"

#: Read whatever tabular content the page is showing.
#:
#: Workday grids differ by report, so this takes rows wherever it finds them
#: rather than assuming one layout, and keeps the raw cell text. Interpreting the
#: columns is left to a human reading the output — a probe that guessed which
#: column was the WQL alias could report the wrong answer confidently.
_CATALOGUE_JS = """() => {
    const rows = [];
    for (const tr of document.querySelectorAll("tr")) {
        const cells = [...tr.querySelectorAll("td,th")]
            .map(td => (td.innerText || "").trim())
            .filter(t => t.length && t.length < 200);
        if (cells.length >= 2) rows.push(cells);
    }
    if (!rows.length) {
        for (const el of document.querySelectorAll("[role='row']")) {
            const cells = [...el.querySelectorAll("[role='gridcell'],[role='cell']")]
                .map(c => (c.innerText || "").trim())
                .filter(t => t.length && t.length < 200);
            if (cells.length >= 2) rows.push(cells);
        }
    }
    return rows.slice(0, 800);
}"""
RESULT_TIMEOUT_MS = 15_000


@dataclass(slots=True)
class Probe:
    """One search term and why it is being searched."""

    term: str
    purpose: str
    #: True for a term whose presence we already expect. If a control comes back
    #: absent, every other absence in the run is uninterpretable.
    control: bool = False
    #: True for a term that should match nothing. If a negative control comes
    #: back present, the search is matching loosely and presence means little.
    negative: bool = False


PROBES: list[Probe] = [
    # --- the question -------------------------------------------------------
    Probe("Workday Query Language", "Is WQL exposed as a task at all?"),
    Probe("Convert Report to WQL", "The documented route from a report to WQL."),
    Probe("WQL", "Bare acronym, in case the task is named differently."),
    # --- what WQL would have to reach --------------------------------------
    Probe("Business Process Definitions", "The data source no API returns."),
    Probe("Condition Rule", "The other thing only the reporting layer reaches."),
    Probe(
        "Data Sources",
        "The standard report that lists every data source and its WQL alias. "
        "This is the decisive one: it answers what WQL can reach, from the "
        "tenant itself rather than from documentation.",
    ),
    Probe("View Data Source", "Whether an individual data source is inspectable."),
    Probe(
        "WQL Alias",
        "Workday documents a 'WQL Alias' report field and a related-actions "
        "route to it. If either is reachable here, aliases — including those "
        "Workday assigns to calculated fields — can be enumerated from the UI "
        "with no API client at all.",
    ),
    # --- controls ----------------------------------------------------------
    Probe(
        "Create Custom Report",
        "Known admin task. If absent, this account is not an admin and every "
        "absence below is about the account rather than the tenant.",
        control=True,
    ),
    Probe(
        "Time Off Plan",
        "Known present — screen discovery already reads these.",
        control=True,
    ),
    Probe(
        "Zzqq Nonexistent Task Meridian",
        "Should match nothing. If it matches, search is loose and presence is weak evidence.",
        negative=True,
    ),
]


@dataclass
class Result:
    probe: Probe
    matches: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def present(self) -> bool:
        return bool(self.matches)


def _search(page, term: str) -> list[str]:
    """Type a term into global search and read the result titles."""
    page.fill(SEARCH_INPUT, "")
    page.fill(SEARCH_INPUT, term)
    page.keyboard.press("Enter")
    try:
        page.wait_for_selector("[data-automation-id='searchResult']", timeout=RESULT_TIMEOUT_MS)
    except Exception:
        # No result container is a legitimate outcome: nothing matched.
        pass
    page.wait_for_timeout(1200)

    titles = page.evaluate(
        """() => {
            const out = [];
            const seen = new Set();
            // Result rows vary by release, so several shapes are tried rather
            // than one brittle selector.
            const sels = [
              "[data-automation-id='searchResult']",
              "[data-automation-id='resultTitle']",
              "[data-automation-id='promptOption']",
              "a[data-automation-id]",
            ];
            for (const sel of sels) {
              for (const el of document.querySelectorAll(sel)) {
                const t = (el.innerText || "").trim().split("\\n")[0].trim();
                if (t && t.length < 120 && !seen.has(t)) { seen.add(t); out.push(t); }
              }
              if (out.length) break;
            }
            return out.slice(0, 12);
        }"""
    )
    return [t for t in titles if t]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", required=True)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--out", default="tmp_wql_probe.json")
    parser.add_argument(
        "--watch-login",
        action="store_true",
        help="Show the browser during sign-in, to see what the login page does.",
    )
    parser.add_argument(
        "--capture",
        action="store_true",
        help=(
            "Sign in first if no live session exists, using WORKDAY_USERNAME and "
            "WORKDAY_PASSWORD from the environment. Workday sessions last about "
            "45 minutes, so a probe run separated from its capture by any real "
            "interval finds the session already gone."
        ),
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        cn = db.get(Connection, args.connection)
        if cn is None:
            print(f"No connection {args.connection}")
            return 1

        status = browser_sessions.status(db, cn.id)
        print(f"session: {status.message}")

        # Capture inline when asked and the stored session is unusable. Credentials
        # come from the environment and are never read from argv or the database:
        # a password in a command line is visible in the process list and in shell
        # history, which is a worse exposure than the one it saves typing.
        if args.capture and not (status.present and status.remaining_seconds > 60):
            import os

            username = os.environ.get("WORKDAY_USERNAME", "")
            password = os.environ.get("WORKDAY_PASSWORD", "")
            if not username or not password:
                print("Set WORKDAY_USERNAME and WORKDAY_PASSWORD to use --capture.")
                return 2

            import capture_session_automated as capture_tool

            settings = cn.settings or {}
            print(f"signing in to {settings.get('tenant')} as {username}")
            state = capture_tool.sign_in(
                str(settings.get("host") or ""),
                str(settings.get("tenant") or ""),
                username,
                password,
                headless=not args.watch_login,
            )
            browser_sessions.capture(
                db,
                connection_id=cn.id,
                state_json=state,
                captured_by=f"{username} (automated)",
                workspace_id=cn.workspace_id or "ws-default",
            )
            db.commit()
            status = browser_sessions.status(db, cn.id)
            print(f"session: {status.message}")

        try:
            state_json = browser_sessions.state(db, cn.id)
        except Exception as exc:
            print(f"cannot read session: {exc}")
            return 1

        settings = cn.settings or {}
        host = str(settings.get("host") or "").rstrip("/")
        tenant = str(settings.get("tenant") or "")
        home = f"{host}/{tenant}/d/home.htmld"
    finally:
        db.close()

    from playwright.sync_api import sync_playwright

    results: list[Result] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        try:
            context = browser.new_context(storage_state=json.loads(state_json))
            page = context.new_page()
            print(f"opening {home}")
            page.goto(home, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            # An expired session lands on the identity gateway. Scraping that
            # would produce confident nonsense, so it is detected and refused.
            if "login" in page.url.lower() or "authgwy" in page.url.lower():
                print(f"session is not authenticated — landed on {page.url}")
                print("Re-run scripts/capture_session_automated.py first.")
                return 2
            print(f"landed on {page.url}")

            try:
                page.wait_for_selector(SEARCH_INPUT, timeout=RESULT_TIMEOUT_MS)
            except Exception:
                print("global search box not found; cannot probe")
                return 2

            for probe in PROBES:
                result = Result(probe=probe)
                try:
                    result.matches = _search(page, probe.term)
                except Exception as exc:
                    result.error = f"{type(exc).__name__}: {exc}"
                results.append(result)
                mark = "FOUND" if result.present else "absent"
                tag = " [control]" if probe.control else (" [neg]" if probe.negative else "")
                print(f"  {mark:6} {probe.term!r}{tag}")
                for m in result.matches[:5]:
                    print(f"           - {m}")
                if result.error:
                    print(f"           ! {result.error}")
            # --- phase two ------------------------------------------------
            #
            # Searching only proves a report is listed. What matters is what is
            # inside it: the data source catalogue, with the WQL alias for each.
            # A data source with no alias is not WQL-queryable, so the alias
            # column is the answer to "can WQL reach business processes" — and it
            # comes from this tenant rather than from a vendor blog.
            if any(r.probe.term == "Data Sources" and r.present for r in results):
                print()
                print("opening the Data Sources report")
                try:
                    page.fill(SEARCH_INPUT, "")
                    page.fill(SEARCH_INPUT, "Data Sources")
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1500)
                    page.click("text=Data Sources")
                    page.wait_for_timeout(4000)
                    print(f"  on {page.url}")
                    catalogue = page.evaluate(_CATALOGUE_JS)
                    print(f"  rows read: {len(catalogue)}")
                    interesting = [
                        row
                        for row in catalogue
                        if any(
                            word in " ".join(str(v) for v in row).lower()
                            for word in (
                                "business process",
                                "condition",
                                "security group",
                                "calculated",
                                "time off",
                                "accrual",
                            )
                        )
                    ]
                    print(f"  rows mentioning what we need: {len(interesting)}")
                    for row in interesting[:25]:
                        print(f"    {row}")
                    Path("tmp_wql_datasources.json").write_text(
                        json.dumps(catalogue, indent=2), encoding="utf-8"
                    )
                    print("  written: tmp_wql_datasources.json")
                except Exception as exc:
                    print(f"  could not read the catalogue: {type(exc).__name__}: {exc}")
        finally:
            browser.close()

    Path(args.out).write_text(
        json.dumps(
            [
                {
                    "term": r.probe.term,
                    "purpose": r.probe.purpose,
                    "control": r.probe.control,
                    "negative": r.probe.negative,
                    "present": r.present,
                    "matches": r.matches,
                    "error": r.error,
                }
                for r in results
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    controls = [r for r in results if r.probe.control]
    negatives = [r for r in results if r.probe.negative]
    print()
    if controls and not all(c.present for c in controls):
        print("CONTROL FAILED — a task this account should hold was not found.")
        print("Absences in this run say nothing about the tenant. Do not conclude "
              "WQL is unavailable.")
    elif any(n.present for n in negatives):
        print("NEGATIVE CONTROL FAILED — a term that should match nothing matched.")
        print("Search is matching loosely; treat 'FOUND' as weak evidence.")
    else:
        print("Controls passed: absences in this run are about the tenant, not the account.")

    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
