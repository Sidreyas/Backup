"""
Walk the last two hops: accrual → calculated field → lookup table.

This is where the numbers finally are. The full chain a leave entitlement
travels in Workday:

    Time Off Plan → Accrual → Lookup Calculation → Lookup Table → values

HKG's table is `Annual Leave Accrual (Hong Kong)`, keyed on "Worker Years of
Service (based on Hire Date) as of Period Start Date", returning days: 1 year →
7 days, rising to 9 years → 14 days.

Read-only. Credentials come from the environment.
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

GRIDS_JS = """
() => Array.from(document.querySelectorAll('table, [role="grid"]'))
  .map(g => ({
    headers: Array.from(g.querySelectorAll('th,[role="columnheader"]'))
      .map(x => (x.innerText || '').split('\\n')[0].trim()).filter(Boolean),
    rows: Array.from(g.querySelectorAll('tr,[role="row"]')).slice(0, 40)
      .map(r => Array.from(r.querySelectorAll('td,[role="gridcell"],[role="cell"]'))
        .map(c => (c.innerText || '').trim()))
      .filter(r => r.length && r.some(Boolean)),
  })).filter(g => g.headers.length)
"""

#: Label/value pairs outside any grid — where the lookup's search criteria and
#: effective date live.
PAIRS_JS = """
() => {
  const out = {};
  document.querySelectorAll('[data-automation-id]').forEach((el) => {
    const label = (el.getAttribute('aria-label') || '').trim();
    const text = (el.innerText || '').trim();
    if (label && text && text.length < 200 && label !== text) out[label] = text;
  });
  return out;
}
"""


def log(*parts: object) -> None:
    print(*parts, flush=True)


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()[:55]


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


def _linked_options(page) -> list[str]:
    """Names on the page that are links to other objects.

    A linked object has a matching "<name> effective as of ..." sibling —
    that pairing is what separates a navigable reference from a plain value
    like "Days". Lookup tables have no such sibling, so the caller passes the
    expected name instead where that applies.
    """
    return page.evaluate(
        """
        () => {
          const texts = Array.from(
            document.querySelectorAll("[data-automation-id='promptOption']")
          ).map(e => (e.innerText || '').trim()).filter(Boolean);
          const out = [];
          texts.forEach(t => {
            if (t.includes('effective as of')) return;
            if (texts.some(o => o.startsWith(t + ' effective as of')) && !out.includes(t)) {
              out.push(t);
            }
          });
          return out;
        }
        """
    )


def walk_plan(page, key: str, url: str) -> list[dict]:
    """Plan → each accrual → its calculation → its lookup table."""
    results: list[dict] = []

    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector("text=Accruals", timeout=60_000)
    page.wait_for_timeout(4000)
    page.click("[role='tab']:has-text('Accruals')")
    page.wait_for_timeout(4000)
    accruals = _linked_options(page)
    log(f"  accruals: {accruals}")

    for accrual in accruals:
        entry: dict = {"accrual": accrual}
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector("text=Accruals", timeout=60_000)
            page.wait_for_timeout(3000)
            page.click("[role='tab']:has-text('Accruals')")
            page.wait_for_timeout(3500)
            page.click(
                f"[data-automation-id='promptOption']:has-text('{accrual}')",
                timeout=30_000,
            )
            page.wait_for_timeout(5000)
        except PWTimeout:
            entry["error"] = "could not open accrual"
            results.append(entry)
            continue

        # The calculation is read from the accrual's own grid, not from the
        # linked-option heuristic: on an accrual page the calculation has no
        # "<name> effective as of" sibling, so that heuristic finds nothing and
        # every accrual looks like a literal. The Calculation column is where
        # it actually lives.
        calculation = page.evaluate(
            """
            () => {
              const grids = Array.from(
                document.querySelectorAll('table, [role="grid"]')
              );
              for (const g of grids.reverse()) {
                const headers = Array.from(
                  g.querySelectorAll('th,[role="columnheader"]')
                ).map(h => (h.innerText || '').split('\\n')[0].trim());
                const col = headers.indexOf('Calculation');
                if (col < 0) continue;
                for (const row of g.querySelectorAll('tr,[role="row"]')) {
                  const cells = Array.from(row.querySelectorAll(
                    'td,[role="gridcell"],[role="cell"]'));
                  const text = cells[col] && (cells[col].innerText || '').trim();
                  if (text) return text;
                }
              }
              return '';
            }
            """
        )
        entry["calculation"] = calculation
        if not calculation:
            entry["note"] = "no Calculation column value found"
            results.append(entry)
            continue
        if calculation.replace(".", "", 1).isdigit():
            entry["note"] = f"literal amount: {calculation}"
            results.append(entry)
            continue
        try:
            page.click(
                f"[data-automation-id='promptOption']:has-text('{calculation}')",
                timeout=30_000,
            )
            page.wait_for_timeout(5500)
        except PWTimeout:
            entry["error"] = "could not open calculation"
            results.append(entry)
            continue

        entry["calculationPage"] = page.title()
        entry["calculationPairs"] = page.evaluate(PAIRS_JS)
        # Workday has several calculated-field types and the page title is what
        # names them: "View Lookup Calculation" resolves to a table of values,
        # "View Conditional Calculation" is branching arithmetic with no table
        # to read. Recording the type is what lets the summary say which kind
        # of rule it could not resolve, instead of a flat "unknown".
        entry["calculationType"] = (
            page.title().replace("View ", "").replace(" - Workday", "").strip()
        )
        entry["calculationText"] = page.inner_text("body")[:4000]
        entry["calculationGrids"] = page.evaluate(GRIDS_JS)
        page.screenshot(
            path=str(OUT / f"calc__{_safe(calculation)}.png"), full_page=True
        )

        # A Lookup Calculation renders a "Lookup Table" label/value pair;
        # other calculation types do not, and there is nothing further to
        # follow for those.
        table = entry["calculationPairs"].get("Lookup Table", "").strip()
        if not table:
            table = page.evaluate(
                """
                () => {
                  const nodes = Array.from(document.querySelectorAll('*'));
                  const label = nodes.find(
                    (e) => (e.innerText || '').trim() === 'Lookup Table'
                            && e.children.length === 0);
                  if (!label) return '';
                  // The value sits in the next cell of the label/value pair.
                  let el = label.parentElement;
                  for (let i = 0; i < 4 && el; i++) {
                    const opt = el.querySelector("[data-automation-id='promptOption']");
                    if (opt) return (opt.innerText || '').trim();
                    el = el.parentElement;
                  }
                  return '';
                }
                """
            )
        entry["lookupTable"] = table
        if not table:
            entry["note"] = "calculation is not a lookup — no table to read"
            results.append(entry)
            continue
        try:
            page.click(
                f"[data-automation-id='promptOption']:has-text('{table}')",
                timeout=30_000,
            )
            page.wait_for_timeout(6000)
        except PWTimeout:
            entry["error"] = "could not open lookup table"
            results.append(entry)
            continue

        entry["tablePage"] = page.title()
        entry["tableText"] = page.inner_text("body")[:4000]
        entry["tableGrids"] = page.evaluate(GRIDS_JS)
        # What the table is keyed on — "Worker Years of Service (based on Hire
        # Date) as of Period Start Date". Without it the bands are bare pairs
        # of numbers: "1 -> 7" is not an answer to anything.
        entry["searchCriteria"] = page.evaluate(
            """
            () => {
              const nodes = Array.from(document.querySelectorAll('*'));
              const label = nodes.find(
                (e) => (e.innerText || '').trim() === 'Numeric Search Criteria'
                        && e.children.length === 0);
              if (!label) return '';
              let el = label.parentElement;
              for (let i = 0; i < 5 && el; i++) {
                const link = el.querySelector('a, [data-automation-id="promptOption"]');
                if (link) return (link.innerText || '').trim();
                el = el.parentElement;
              }
              return '';
            }
            """
        )
        page.screenshot(path=str(OUT / f"lookup__{_safe(table)}.png"), full_page=True)
        log(f"    {accrual} -> {calculation} -> {table}")
        results.append(entry)

    return results


def main() -> int:
    if not USER or not PASSWORD:
        log("Set WD_USER and WD_PASSWORD first.")
        return 2

    out: dict[str, list[dict]] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1600})
        page = context.new_page()
        page.set_default_timeout(60_000)
        try:
            if not login(page):
                log("!! login failed")
                return 1
            for key, url in PLANS.items():
                log(f"\n=== {key} ===")
                out[key] = walk_plan(page, key, url)
        finally:
            context.close()
            browser.close()

    (OUT / "lookups.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    log("\nwrote tmp_absence_probe/lookups.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
