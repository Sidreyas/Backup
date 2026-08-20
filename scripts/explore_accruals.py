"""
Follow a time off plan's accrual links and read the amounts.

The plan screen names its accruals but not what they grant — that lives on the
accrual object, one navigation away. This walks that hop for both of the
client's plans, which is what turns

    "GBR Statutory Holiday (Days) Accrual: an amount held on the accrual itself"

into an actual entitlement.

Read-only. Follows links, screenshots, reads the DOM; clicks nothing that
commits. Credentials come from the environment and are never written here.
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
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()[:60]


def login(page) -> bool:
    page.goto(f"{HOST}/{TENANT}/login.htmld", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    for sel in ("[data-automation-id='username'] input", "input[name='username']"):
        if page.locator(sel).count():
            page.fill(sel, USER)
            break
    for sel in ("[data-automation-id='password'] input", "input[type='password']"):
        if page.locator(sel).count():
            page.fill(sel, PASSWORD)
            break
    for sel in ("[data-automation-id='goButton']", "button[type='submit']"):
        if page.locator(sel).count():
            page.click(sel)
            break
    page.wait_for_timeout(6000)
    return "login" not in page.url.lower()


def accrual_names(page) -> list[str]:
    """Accrual names on the Accruals tab.

    Names, not URLs — Workday does not render these as anchors. They are
    `<div data-automation-id="promptOption">` wired to a JS handler, so there
    is no href to collect and the walk has to click each one and navigate back.
    That is slower and more fragile than following links, and it is the only
    option the application offers.
    """
    page.click("[role='tab']:has-text('Accruals')", timeout=20_000)
    page.wait_for_timeout(3500)

    # Read the accrual names from the `promptOption` elements directly rather
    # than by grid column index.
    #
    # Column-index reading broke on GBR: its grid declares 8 headers but the
    # second is empty, so "Adds to Balance" sits at index 2 while its cells
    # sit at a different offset — the lookup found nothing and an empty result
    # was indistinguishable from "this plan has no accruals". HKG, with no
    # empty header, worked fine, which is what made the bug look like a timing
    # problem.
    #
    # Every accrual name is paired with an "<name> effective as of ..."
    # snapshot entry, which points at the same object and is filtered out.
    return page.evaluate(
        """
        () => {
          const texts = Array.from(
            document.querySelectorAll("[data-automation-id='promptOption']")
          ).map((e) => (e.innerText || '').trim()).filter(Boolean);

          // An accrual is any option that has a matching "effective as of"
          // sibling — that pairing is what distinguishes a linked object from
          // a plain value like "Days" or "Monthly".
          const out = [];
          texts.forEach((t) => {
            if (t.includes('effective as of')) return;
            const hasSnapshot = texts.some(
              (o) => o.startsWith(t + ' effective as of')
            );
            if (hasSnapshot && !out.includes(t)) out.push(t);
          });
          return out;
        }
        """
    )


def read_accrual(page, name: str, plan_url: str) -> dict:
    """Open one accrual from the plan screen and read it.

    Navigates back to the plan and re-clicks each time rather than holding a
    URL, because the accrual name is not a link. Slower, but it is what the
    application supports.
    """
    page.goto(plan_url, wait_until="domcontentloaded")
    try:
        page.wait_for_selector("text=Accruals", timeout=45_000)
    except PWTimeout:
        return {"name": name, "error": "plan screen did not render"}
    page.wait_for_timeout(3000)
    page.click("[role='tab']:has-text('Accruals')")
    page.wait_for_timeout(3500)

    try:
        page.click(
            f"[data-automation-id='promptOption']:has-text('{name}')", timeout=30_000
        )
    except PWTimeout:
        return {"name": name, "error": "accrual link not clickable"}
    page.wait_for_timeout(4500)

    info = {
        "name": name,
        "url": page.url,
        "heading": page.title(),
        "text": page.inner_text("body")[:8000],
        "tabs": [t.strip() for t in page.locator("[role='tab']").all_inner_texts()],
        "grids": page.evaluate(
            """
            () => Array.from(document.querySelectorAll('table, [role="grid"]'))
              .map((g) => ({
                headers: Array.from(g.querySelectorAll('th, [role="columnheader"]'))
                  .map((h) => (h.innerText || '').split('\\n')[0].trim()).filter(Boolean),
                rows: Array.from(g.querySelectorAll('tr, [role="row"]')).slice(0, 15)
                  .map((r) => Array.from(r.querySelectorAll('td, [role="gridcell"], [role="cell"]'))
                    .map((c) => (c.innerText || '').trim()))
                  .filter((r) => r.length && r.some(Boolean)),
              })).slice(0, 12)
            """
        ),
    }
    page.screenshot(path=str(OUT / f"accrual__{_safe(name)}.png"), full_page=True)
    log(f"    read '{name}': {len(info['grids'])} grid(s), tabs={info['tabs']}")
    return info


def main() -> int:
    if not USER or not PASSWORD:
        log("Set WD_USER and WD_PASSWORD first.")
        return 2

    results: dict[str, list[dict]] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1200})
        page = context.new_page()
        page.set_default_timeout(45_000)
        try:
            if not login(page):
                log("!! login failed")
                return 1

            for key, url in PLANS.items():
                log(f"\n=== {key} ===")
                page.goto(url, wait_until="domcontentloaded")
                # Workday's tab <li>s report as not-visible to Playwright even
                # once rendered, so waiting on the role alone hangs. Waiting on
                # the tab's *text* is what actually signals the panel is up.
                try:
                    page.wait_for_selector("text=Accruals", timeout=45_000)
                except PWTimeout:
                    log("  !! Accruals tab never appeared")
                    continue
                page.wait_for_timeout(3500)

                # The grid sometimes has not populated by the time the tab
                # click returns, and an empty read is indistinguishable from a
                # plan with no accruals. Retrying separates the two.
                names: list[str] = []
                for attempt in range(3):
                    names = accrual_names(page)
                    if names:
                        break
                    log(f"  (attempt {attempt + 1}: grid empty, retrying)")
                    page.wait_for_timeout(4000)
                log(f"  {len(names)} accrual(s): {names}")

                results[key] = [read_accrual(page, name, url) for name in names]
        finally:
            context.close()
            browser.close()

    (OUT / "accruals.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    log("\nwrote tmp_absence_probe/accruals.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
