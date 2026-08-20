"""
The absence walk: a multi-hop browser extraction.

Single-screen recipes cannot express this. A leave entitlement lives at the end
of a chain that Workday only exposes by navigation:

    Time Off Plan → Accruals tab → Accrual → Calculation → Lookup Table

Every hop is a click, because Workday renders these references as JavaScript
handlers rather than links — there is no URL to collect and visit. So the walk
is a loop of "open the plan, click through, come back", which is slower and
more fragile than following hrefs and is what the application supports.

Everything here was learned from a real tenant, and several behaviours would
not be guessed:

  - **Tabs lazy-load and then accumulate.** A plan screen shows only the
    Balance tab until others are clicked, after which earlier tabs' grids stay
    in the DOM. So grids are matched by their headers, never by tab position.
  - **Accrual names are `promptOption` divs**, identified by having a matching
    "<name> effective as of ..." sibling. That pairing is what separates a
    navigable reference from a plain value like "Days".
  - **Column indexes are unreliable.** One plan's grid has an empty column
    where another's does not, so reading cell *n* finds the right value on one
    plan and nothing on the next — silently, as an empty result.
  - **Calculations come in types.** The page title names them: a Lookup
    Calculation resolves to a table of values, a Conditional Calculation to
    ordered branches. They are different answers to the same question.

**Read-only throughout.** The walk clicks tabs and reference links; it never
touches a control that commits. `browser.FORBIDDEN_TARGETS` covers the recipe
language, and this module's click targets are all discovered references and
Workday-delivered tab labels.

**Session expiry is expected, not exceptional.** A tenant with forty plans
takes longer than a session lives. `WalkResult.partial` reports that honestly
so a run stops, keeps what it has, and asks for a new capture — rather than
failing and discarding the work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from api.connectors.workday.browser import BrowserUnavailable, playwright_available

#: Workday-delivered tab on the time off plan screen.
ACCRUALS_TAB = "Accruals"

#: How long to wait for a Workday screen to render. Generous: these are heavy
#: pages and a false timeout costs a whole plan's extraction.
SCREEN_TIMEOUT_MS = 45_000

#: Settle time after a navigation. Workday renders its shell before its
#: content, so the DOM being ready is not the same as the data being present.
SETTLE_MS = 3_500

_GRIDS_JS = """
() => Array.from(document.querySelectorAll('table, [role="grid"]'))
  .map(g => ({
    headers: Array.from(g.querySelectorAll('th,[role="columnheader"]'))
      .map(x => (x.innerText || '')
        .replace(/\\n/g, ' ')
        .replace(/Sort and filter column/g, '')
        .replace(/Filter column/g, '')
        .trim())
      .filter(Boolean),
    rows: Array.from(g.querySelectorAll('tr,[role="row"]')).slice(0, 40)
      .map(r => Array.from(r.querySelectorAll('td,[role="gridcell"],[role="cell"]'))
        .map(c => (c.innerText || '').trim()))
      .filter(r => r.length && r.some(Boolean)),
  })).filter(g => g.headers.length)
"""

#: Names on the page that are navigable references to other objects.
#:
#: Identified by the "<name> effective as of ..." pairing rather than by tag,
#: because Workday renders them as divs. Reading anchors found nothing at all.
_REFERENCES_JS = """
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

#: Label/value pairs outside any grid.
_PAIRS_JS = """
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

#: The lookup table a Lookup Calculation reads.
#:
#: `_PAIRS_JS` cannot find it: that reads `aria-label`, and on the View Lookup
#: Calculation screen the field is labelled by an adjacent text node instead,
#: so the pair map comes back holding only chrome. Falling back to it left the
#: table name empty, the walk never clicked through, and a Lookup Calculation
#: resolved with zero bands — the entitlement itself missing while everything
#: around it looked extracted.
#:
#: Finds the "Lookup Table" label, then the nearest reference beside it.
_LOOKUP_TABLE_JS = """
() => {
  const nodes = Array.from(document.querySelectorAll('*'));
  const label = nodes.find(
    (e) => (e.innerText || '').trim() === 'Lookup Table'
            && e.children.length === 0);
  if (!label) return '';
  let el = label.parentElement;
  for (let i = 0; i < 6 && el; i++) {
    const option = el.querySelector("[data-automation-id='promptOption']");
    if (option) {
      const text = (option.innerText || '').trim();
      if (text && text !== 'Lookup Table') return text;
    }
    el = el.parentElement;
  }
  return '';
}
"""

#: The value a lookup table is keyed on. Without it the bands are bare pairs of
#: numbers, and "1 → 7" answers nothing.
_SEARCH_CRITERIA_JS = """
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

#: The calculation an accrual uses, read from its own grid column.
#:
#: Not from the reference heuristic: on an accrual page the calculation has no
#: "effective as of" sibling, so that heuristic reports every accrual as a
#: literal — which looked like a plan with no calculated fields at all.
_CALCULATION_JS = """
() => {
  const grids = Array.from(document.querySelectorAll('table, [role="grid"]'));
  for (const g of grids.reverse()) {
    const headers = Array.from(g.querySelectorAll('th,[role="columnheader"]'))
      .map(h => (h.innerText || '').split('\\n')[0].trim());
    const col = headers.indexOf('Calculation');
    if (col < 0) continue;
    for (const row of g.querySelectorAll('tr,[role="row"]')) {
      const cells = Array.from(
        row.querySelectorAll('td,[role="gridcell"],[role="cell"]'));
      const text = cells[col] && (cells[col].innerText || '').trim();
      if (text) return text;
    }
  }
  return '';
}
"""


@dataclass(slots=True)
class PlanCapture:
    """Everything one plan's walk produced."""

    plan_url: str
    plan_name: str = ""
    #: The name as the plan screen titles itself, when it could be read. Kept
    #: separate from `plan_name` so the caller can tell "the tenant calls it
    #: this" from "this is what I was asked to walk".
    screen_name: str = ""
    tabs: list[str] = field(default_factory=list)
    tabs_detail: dict[str, Any] = field(default_factory=dict)
    accruals: list[dict] = field(default_factory=list)
    lookups: list[dict] = field(default_factory=list)
    #: Hops that failed. Recorded rather than dropped: a plan extracted with
    #: three of four accruals is a different thing from one extracted whole,
    #: and only this distinguishes them.
    failures: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WalkResult:
    captures: list[PlanCapture] = field(default_factory=list)
    #: True when the walk stopped early. The caller keeps what was extracted
    #: and reports the run as partial rather than failing it — on a large
    #: tenant an expiry mid-walk is the normal case, not an error.
    partial: bool = False
    reason: str = ""


class SessionExpired(BrowserUnavailable):
    """The captured session stopped working mid-walk."""


def _looks_signed_out(page: Any) -> bool:
    """Whether Workday has bounced us to a login screen.

    Checked after every navigation. An expired session does not raise — it
    silently serves the login page, and a walk that did not notice would
    extract the login form's fields as though they were configuration.
    """
    url = (page.url or "").lower()
    if "login" in url or "signin" in url:
        return True
    return bool(page.locator("[data-automation-id='username']").count())


class AbsenceWalker:
    """Walks time off plans and everything they reference.

    Constructed with an open Playwright page so the caller owns the browser
    lifecycle — one browser for a whole run rather than one per plan, which on
    forty plans is the difference between minutes and hours.
    """

    def __init__(self, page: Any, *, settle_ms: int = SETTLE_MS) -> None:
        self.page = page
        self.settle_ms = settle_ms

    # --- primitives --------------------------------------------------------

    def _goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.wait_for_timeout(self.settle_ms)
        if _looks_signed_out(self.page):
            raise SessionExpired(
                "The Workday session has expired. Capture a new one to "
                "continue; everything extracted so far is kept."
            )

    def _click_reference(self, name: str) -> None:
        """Click a navigable reference by its visible name."""
        self.page.click(
            f"[data-automation-id='promptOption']:has-text('{name}')",
            timeout=SCREEN_TIMEOUT_MS,
        )
        self.page.wait_for_timeout(self.settle_ms + 1_000)
        if _looks_signed_out(self.page):
            raise SessionExpired("The Workday session expired during navigation.")

    def _grids(self) -> list[dict]:
        return self.page.evaluate(_GRIDS_JS)

    def _references(self) -> list[str]:
        return self.page.evaluate(_REFERENCES_JS)

    # --- the walk ----------------------------------------------------------

    def walk_plan(self, plan_url: str, *, plan_name: str = "") -> PlanCapture:
        """One plan, its accruals, their calculations and lookup tables."""
        capture = PlanCapture(plan_url=plan_url, plan_name=plan_name)

        self._goto(plan_url)

        # The plan's own name, from the page title ("View Time Off Plan - HKG
        # Annual Leave - Workday"). Read here rather than left to the caller
        # because a connection with no integration user has no name to pass —
        # it falls back to the configuration key, and the graph then labels a
        # plan `HKG_ANNUAL_LEAVE` where the tenant says `HKG Annual Leave`.
        #
        # The page *title* specifically, not loose DOM text: it is a single
        # structured string, unlike the label/value pairs elsewhere on this
        # screen which are genuinely fragile to scrape.
        title = (self.page.title() or "").replace(" - Workday", "").strip()
        if title.startswith("View Time Off Plan"):
            screen_name = title[len("View Time Off Plan") :].lstrip(" -").strip()
            if screen_name:
                capture.screen_name = screen_name

        try:
            self.page.wait_for_selector(
                f"text={ACCRUALS_TAB}", timeout=SCREEN_TIMEOUT_MS
            )
        except Exception:  # noqa: BLE001 - a plan without tabs is data
            capture.failures.append("plan screen did not render its tabs")
            return capture

        capture.tabs = [
            tab.strip()
            for tab in self.page.locator("[role='tab']").all_inner_texts()
            if tab.strip()
        ]

        # Visit each tab. They lazy-load, so an unvisited tab contributes
        # nothing, and they accumulate, so the last read holds the most.
        for tab in dict.fromkeys(capture.tabs):
            try:
                self.page.click(f"[role='tab']:has-text('{tab}')", timeout=20_000)
                self.page.wait_for_timeout(self.settle_ms)
                capture.tabs_detail[tab] = {"grids": self._grids()}
            except Exception:  # noqa: BLE001
                capture.failures.append(f"tab '{tab}' did not open")

        accrual_names = self._accrual_names()
        for name in accrual_names:
            try:
                capture.accruals.append(self._walk_accrual(plan_url, name))
            except SessionExpired:
                raise
            except Exception as exc:  # noqa: BLE001
                capture.failures.append(f"accrual '{name}': {str(exc)[:120]}")

        for accrual in capture.accruals:
            lookup = accrual.pop("_lookup", None)
            if lookup:
                capture.lookups.append(lookup)

        return capture

    def _accrual_names(self) -> list[str]:
        """Accruals on the currently open plan, via the Accruals tab."""
        try:
            self.page.click(
                f"[role='tab']:has-text('{ACCRUALS_TAB}')", timeout=20_000
            )
            self.page.wait_for_timeout(self.settle_ms)
        except Exception:  # noqa: BLE001
            return []
        return self._references()

    def _walk_accrual(self, plan_url: str, name: str) -> dict:
        """One accrual, its calculation, and any lookup table behind it.

        Returns to the plan first because the accrual name is not a URL — the
        only way back to a sibling accrual is through the plan screen.
        """
        self._goto(plan_url)
        self.page.wait_for_selector(f"text={ACCRUALS_TAB}", timeout=SCREEN_TIMEOUT_MS)
        self.page.click(f"[role='tab']:has-text('{ACCRUALS_TAB}')", timeout=20_000)
        self.page.wait_for_timeout(self.settle_ms)
        self._click_reference(name)

        entry: dict = {"name": name, "grids": self._grids()}

        calculation = self.page.evaluate(_CALCULATION_JS)
        entry["calculation"] = calculation
        if not calculation:
            return entry

        # A numeric calculation is the entitlement itself — there is nothing
        # further to open, and clicking would navigate somewhere unrelated.
        if calculation.replace(".", "", 1).isdigit():
            entry["note"] = f"literal amount: {calculation}"
            return entry

        self._click_reference(calculation)
        entry["calculationType"] = (
            (self.page.title() or "")
            .replace("View ", "")
            .replace(" - Workday", "")
            .strip()
        )
        entry["calculationGrids"] = self._grids()
        pairs = self.page.evaluate(_PAIRS_JS)

        # The calculation is handed on whether or not it has a lookup table.
        # Only Lookup Calculations have one; a Conditional Calculation keeps
        # its ordered branches in `calculationGrids` on the screen just read.
        # Returning early when there was no table meant every conditional
        # calculation — every statutory plan worth asking about — was captured
        # and then silently discarded, leaving a named calculation with no
        # contents and a summary that could not say what it decides.
        entry["_lookup"] = {
            "accrual": name,
            "calculation": calculation,
            "calculationType": entry.get("calculationType", ""),
            "calculationGrids": entry.get("calculationGrids") or [],
        }

        table = str(pairs.get("Lookup Table") or "").strip()
        if not table:
            table = str(self.page.evaluate(_LOOKUP_TABLE_JS) or "").strip()
        if not table:
            return entry

        entry["lookupTable"] = table
        self._click_reference(table)
        entry["_lookup"].update(
            {
                "lookupTable": table,
                "searchCriteria": self.page.evaluate(_SEARCH_CRITERIA_JS),
                "tableGrids": self._grids(),
            }
        )
        return entry


def walk(
    session_state_json: str,
    plans: list[dict],
    *,
    headless: bool = True,
) -> WalkResult:
    """Walk several plans in one browser.

    `plans` is a list of `{"url": ..., "name": ...}`. Plan URLs are
    tenant-specific instance ids, which is why they are supplied rather than
    discovered — a plan inventory comes from SOAP or a report, where it is
    reliable.
    """
    if not playwright_available():
        raise BrowserUnavailable(
            "Playwright is not installed on this host, so screen discovery "
            "cannot run."
        )

    from playwright.sync_api import sync_playwright

    result = WalkResult()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            storage_state=json.loads(session_state_json),
            viewport={"width": 1600, "height": 1400},
        )
        page = context.new_page()
        page.set_default_timeout(SCREEN_TIMEOUT_MS)
        walker = AbsenceWalker(page)

        try:
            for plan in plans:
                url = str(plan.get("url") or "").strip()
                if not url:
                    continue
                try:
                    result.captures.append(
                        walker.walk_plan(url, plan_name=str(plan.get("name") or ""))
                    )
                except SessionExpired as exc:
                    # Stop, keep what was extracted, say why. On a large tenant
                    # this is the expected ending, not a failure.
                    result.partial = True
                    result.reason = str(exc)
                    break
        finally:
            context.close()
            browser.close()

    return result
