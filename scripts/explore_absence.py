"""
One-off exploration of the client's Workday demo tenant.

Phase 2 of the browser-discovery design — the "walk an operator to the screen
and record the path" step — with me as the operator. Produces a description of
what is actually on the two time off plan screens, which is what the absence
recipes get built from.

Read-only: navigate, screenshot, read the DOM. Nothing is clicked that could
commit a change.

Not part of the product. Kept in `scripts/` because the *findings* are what
matter and they get committed as fixtures; this file is how they were obtained.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

HOST = os.environ.get("WD_HOST", "https://wcpdev.wd101.myworkday.com")
TENANT = os.environ.get("WD_TENANT", "aia_wcpdev1")

# Read from the environment, never committed. These are a real person's
# credentials in the client's tenant; a password in a repo outlives every
# assumption anyone made about who could read it.
USER = os.environ.get("WD_USER", "")
PASSWORD = os.environ.get("WD_PASSWORD", "")

PLANS = {
    "hkg_annual_leave": f"{HOST}/{TENANT}/d/inst/1$1733/2039$14.htmld",
    "gbr_statutory_holiday": f"{HOST}/{TENANT}/d/inst/1$1733/2039$6.htmld",
}

OUT = Path(__file__).resolve().parent.parent / "tmp_absence_probe"
OUT.mkdir(exist_ok=True)


def log(*parts: object) -> None:
    print(*parts, flush=True)


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()


def login(page) -> bool:
    page.goto(f"{HOST}/{TENANT}/login.htmld", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    # Workday wraps its fields: `data-automation-id="password"` is a div with
    # the real <input> inside. Descendant-input selectors come first so the
    # wrapper is never the fill target.
    for user_sel in (
        "[data-automation-id='username'] input",
        "input[data-automation-id='username']",
        "input[name='username']",
        "#username",
    ):
        if page.locator(user_sel).count():
            page.fill(user_sel, USER)
            break
    else:
        log("!! no username input found")
        return False

    for pw_sel in (
        "[data-automation-id='password'] input",
        "input[data-automation-id='password']",
        "input[type='password']",
        "input[name='password']",
        "#password",
    ):
        if page.locator(pw_sel).count():
            page.fill(pw_sel, PASSWORD)
            break
    else:
        log("!! no password input found")
        return False

    for btn in (
        "[data-automation-id='goButton']",
        "button[type='submit']",
        "input[type='submit']",
    ):
        if page.locator(btn).count():
            page.click(btn)
            break
    else:
        page.keyboard.press("Enter")

    page.wait_for_timeout(6000)
    url = page.url
    log("after login url:", url)
    page.screenshot(path=str(OUT / "after_login.png"), full_page=True)

    if "login" in url.lower():
        body = page.inner_text("body")[:600]
        log("!! still on login page. Page said:\n", body)
        return False
    return True


def describe(page, key: str, url: str) -> dict:
    """Read one plan screen without changing anything."""
    log(f"\n=== {key} ===")
    page.goto(url, wait_until="domcontentloaded")
    # Workday's shell renders before its content. Waiting for the page title
    # element rather than a fixed delay is what makes this reliable; the sleep
    # is the fallback for screens that never set one.
    try:
        page.wait_for_selector(
            "[data-automation-id='pageHeaderTitleText'], h1, [role='tab']",
            timeout=45_000,
        )
    except PWTimeout:
        log("  (no page header appeared)")
    page.wait_for_timeout(4000)

    info: dict = {"key": key, "url": url, "finalUrl": page.url, "title": page.title()}

    try:
        info["heading"] = page.locator("h1, [data-automation-id='pageHeaderTitleText']").first.inner_text().strip()
    except Exception:
        info["heading"] = ""

    body = page.inner_text("body")
    info["bodyChars"] = len(body)
    info["bodyPreview"] = body[:3000]

    # Tabs, which is where absence configuration actually lives.
    tabs = []
    for sel in ("[role='tab']", "[data-automation-id='tabLabel']"):
        for t in page.locator(sel).all_inner_texts():
            t = t.strip()
            if t and t not in tabs:
                tabs.append(t)
    info["tabs"] = tabs

    # Workday lazy-loads tab panels: only the active one is in the DOM, so a
    # single capture sees Balance and nothing else. Each tab is visited and
    # read separately. Clicking a tab is navigation, not a mutation.
    info["tabContent"] = {}
    for tab in tabs:
        try:
            page.click(f"[role='tab']:has-text('{tab}')", timeout=15_000)
            page.wait_for_timeout(3500)
        except Exception as exc:  # noqa: BLE001 - a missing tab is data, not a crash
            info["tabContent"][tab] = {"error": str(exc)[:200]}
            continue

        info["tabContent"][tab] = {
            "text": page.inner_text("body")[:6000],
            "grids": page.evaluate(
                """
                () => Array.from(
                    document.querySelectorAll('table, [role="grid"]')
                ).map((g) => ({
                  headers: Array.from(g.querySelectorAll('th, [role="columnheader"]'))
                    .map((h) => (h.innerText || '').split('\\n')[0].trim()).filter(Boolean),
                  rows: Array.from(g.querySelectorAll('tr, [role="row"]')).slice(0, 20)
                    .map((r) => Array.from(r.querySelectorAll('td, [role="gridcell"], [role="cell"]'))
                      .map((c) => (c.innerText || '').trim()))
                    .filter((r) => r.length && r.some(Boolean)),
                })).slice(0, 10)
                """
            ),
        }
        page.screenshot(path=str(OUT / f"{key}__{_safe(tab)}.png"), full_page=True)
        log(f"  tab '{tab}': {len(info['tabContent'][tab].get('grids', []))} grid(s)")

    # Label/value pairs as rendered.
    info["fields"] = page.evaluate(
        """
        () => {
          const out = [];
          const seen = new Set();
          document.querySelectorAll('[data-automation-id]').forEach((el) => {
            const id = el.getAttribute('data-automation-id') || '';
            const label = (el.getAttribute('aria-label') || '').trim();
            const text = (el.innerText || '').trim();
            if (!text || text.length > 300) return;
            const key = id + '|' + label + '|' + text.slice(0, 60);
            if (seen.has(key)) return;
            seen.add(key);
            out.push({ automationId: id, label, text: text.slice(0, 300) });
          });
          return out.slice(0, 400);
        }
        """
    )

    # Grids — accrual and eligibility rules render as tables.
    info["grids"] = page.evaluate(
        """
        () => {
          const grids = [];
          document.querySelectorAll('table, [role="grid"], [data-automation-id*="grid" i]')
            .forEach((g) => {
              const headers = Array.from(g.querySelectorAll('th, [role="columnheader"]'))
                .map((h) => (h.innerText || '').trim()).filter(Boolean);
              const rows = Array.from(g.querySelectorAll('tr, [role="row"]'))
                .slice(0, 25)
                .map((r) => Array.from(r.querySelectorAll('td, [role="gridcell"], [role="cell"]'))
                  .map((c) => (c.innerText || '').trim()))
                .filter((r) => r.length && r.some(Boolean));
              if (headers.length || rows.length) grids.push({ headers, rowCount: rows.length, rows: rows.slice(0, 12) });
            });
          return grids.slice(0, 20);
        }
        """
    )

    log("heading:", info["heading"])
    log("title:", info["title"])
    log("tabs:", tabs)
    log("fields captured:", len(info["fields"]))
    log("grids captured:", len(info["grids"]))

    page.screenshot(path=str(OUT / f"{key}.png"), full_page=True)
    (OUT / f"{key}.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def main() -> int:
    if not USER or not PASSWORD:
        log(
            "Set WD_USER and WD_PASSWORD first, e.g.\n"
            '  $env:WD_USER="Lmcneil"; $env:WD_PASSWORD="..."\n'
            "then re-run. Credentials are deliberately not stored in this file."
        )
        return 2

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1200})
        page = context.new_page()
        page.set_default_timeout(45_000)

        try:
            if not login(page):
                return 1
            for key, url in PLANS.items():
                try:
                    describe(page, key, url)
                except PWTimeout:
                    log(f"!! timeout on {key}")
            (OUT / "session_state.json").write_text(
                json.dumps(context.storage_state()), encoding="utf-8"
            )
            log("\nsaved session state")
        finally:
            context.close()
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
