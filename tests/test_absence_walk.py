"""
The absence walk.

Multi-hop browser extraction: plan → accrual → calculation → lookup table. No
browser is launched here — what is worth testing is the *decision logic* around
the navigation, not whether Playwright can click.

Three behaviours carry the weight:

  - **Session expiry stops the walk and keeps what it has.** On a tenant with
    forty plans, an expiry mid-walk is the normal ending, not an error. Losing
    the completed plans because the forty-first failed would make large tenants
    permanently un-extractable.
  - **An expired session is detected, not inferred from an exception.** Workday
    does not error when a session lapses — it serves the login page. A walk
    that did not notice would extract the login form's fields as configuration.
  - **A failed hop degrades to a recorded failure**, so a plan extracted with
    three of four accruals is distinguishable from one extracted whole.
"""

from __future__ import annotations

import pytest

from api.connectors.workday import absence_walk
from api.connectors.workday.absence_walk import (
    AbsenceWalker,
    PlanCapture,
    SessionExpired,
    WalkResult,
    _looks_signed_out,
)


class FakePage:
    """A Playwright page, reduced to what the walker touches.

    Hand-written rather than mocked: the walker's contract with the page is
    six methods, and a fake makes the *sequence* of calls visible in a way
    assert_called_with does not.
    """

    def __init__(
        self,
        *,
        url: str = "https://wd.example/tenant/d/inst/1$1/2$3.htmld",
        signed_out_after: int | None = None,
        references: list[str] | None = None,
        title: str = "View Accrual - Workday",
        grids: list[dict] | None = None,
        evaluations: dict[str, object] | None = None,
    ) -> None:
        self.url = url
        self._signed_out_after = signed_out_after
        self._navigations = 0
        self._references = references or []
        self._title = title
        self._grids = grids or []
        self._evaluations = evaluations or {}
        self.clicks: list[str] = []

    # --- navigation --------------------------------------------------------

    def goto(self, url: str, **_: object) -> None:
        self._navigations += 1
        if (
            self._signed_out_after is not None
            and self._navigations > self._signed_out_after
        ):
            self.url = "https://wd.example/tenant/login.htmld"
        else:
            self.url = url

    def click(self, selector: str, **_: object) -> None:
        self.clicks.append(selector)

    def wait_for_timeout(self, _ms: int) -> None:
        return None

    def wait_for_selector(self, _selector: str, **_: object) -> None:
        return None

    def set_default_timeout(self, _ms: int) -> None:
        return None

    def title(self) -> str:
        return self._title

    # --- reading -----------------------------------------------------------

    def evaluate(self, script: str) -> object:
        if "promptOption" in script and "effective as of" in script:
            return self._references
        if "columnheader" in script and "Calculation" in script:
            return self._evaluations.get("calculation", "")
        if "Numeric Search Criteria" in script:
            return self._evaluations.get("criteria", "")
        # The label-based fallback, used when the screen carries no aria-label
        # for the field — which is how the real View Lookup Calculation screen
        # renders it.
        if "'Lookup Table'" in script:
            return self._evaluations.get("lookupTableByLabel", "")
        if "aria-label" in script:
            return self._evaluations.get("pairs", {})
        if "columnheader" in script:
            return self._grids
        return self._evaluations.get("default", [])

    def locator(self, selector: str):
        page = self

        class _Locator:
            def count(self) -> int:
                if "username" in selector:
                    return 1 if "login" in page.url.lower() else 0
                return 0

            def all_inner_texts(self) -> list[str]:
                return page._evaluations.get("tabs", [])  # type: ignore[return-value]

        return _Locator()


# --- expiry detection --------------------------------------------------------


def test_a_login_url_reads_as_signed_out():
    """Workday serves the login page rather than erroring.

    A walk that did not check would extract the login form as configuration.
    """
    assert _looks_signed_out(FakePage(url="https://wd.example/t/login.htmld"))
    assert _looks_signed_out(FakePage(url="https://wd.example/t/signin"))


def test_a_plan_url_reads_as_signed_in():
    assert not _looks_signed_out(
        FakePage(url="https://wd.example/t/d/inst/1$1733/2039$14.htmld")
    )


def test_navigating_into_an_expired_session_raises(monkeypatch):
    page = FakePage(signed_out_after=0)
    walker = AbsenceWalker(page, settle_ms=0)

    with pytest.raises(SessionExpired, match="expired"):
        walker._goto("https://wd.example/t/d/inst/1$1/2$3.htmld")


def test_the_expiry_message_says_work_is_kept():
    """An admin reading "session expired" needs to know whether to start over."""
    page = FakePage(signed_out_after=0)
    walker = AbsenceWalker(page, settle_ms=0)
    try:
        walker._goto("https://wd.example/x")
    except SessionExpired as exc:
        assert "kept" in str(exc)


# --- partial runs ------------------------------------------------------------


def test_a_walk_cut_short_keeps_its_captures(monkeypatch):
    """The decision that makes large tenants extractable at all."""
    captures = [
        PlanCapture(plan_url="u1", plan_name="Plan one"),
        PlanCapture(plan_url="u2", plan_name="Plan two"),
    ]
    calls = {"n": 0}

    def fake_walk_plan(self, url, *, plan_name=""):
        calls["n"] += 1
        if calls["n"] > 2:
            raise SessionExpired("The Workday session has expired.")
        return captures[calls["n"] - 1]

    monkeypatch.setattr(AbsenceWalker, "walk_plan", fake_walk_plan)
    monkeypatch.setattr(absence_walk, "playwright_available", lambda: True)

    class _Ctx:
        def new_page(self):
            return FakePage()

        def close(self):
            return None

    class _Browser:
        def new_context(self, **_):
            return _Ctx()

        def close(self):
            return None

    class _PW:
        chromium = type("C", (), {"launch": staticmethod(lambda **_: _Browser())})()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(absence_walk, "sync_playwright", lambda: _PW(), raising=False)
    monkeypatch.setitem(
        __import__("sys").modules,
        "playwright.sync_api",
        type("M", (), {"sync_playwright": lambda: _PW()}),
    )

    result = absence_walk.walk(
        '{"cookies":[{"name":"x"}]}',
        [{"url": "u1"}, {"url": "u2"}, {"url": "u3"}],
    )

    assert result.partial is True
    assert len(result.captures) == 2
    assert "expired" in result.reason.lower()


def test_a_complete_walk_is_not_marked_partial():
    result = WalkResult(captures=[PlanCapture(plan_url="u1")])
    assert result.partial is False
    assert result.reason == ""


# --- per-plan failure handling -----------------------------------------------


def test_a_plan_whose_tabs_never_render_records_the_failure():
    """Silence would make a broken plan look like a plan with no accruals."""
    page = FakePage()

    def boom(*_args, **_kw):
        raise RuntimeError("no tabs")

    page.wait_for_selector = boom  # type: ignore[assignment]
    walker = AbsenceWalker(page, settle_ms=0)

    capture = walker.walk_plan("https://wd.example/t/d/inst/1$1/2$3.htmld")
    assert capture.accruals == []
    assert any("did not render" in f for f in capture.failures)


def test_a_literal_calculation_stops_the_walk_there():
    """"0" is the entitlement, not a link.

    Clicking it would navigate somewhere unrelated — the walk has to know when
    it has arrived.
    """
    page = FakePage(evaluations={"calculation": "0", "tabs": []})
    walker = AbsenceWalker(page, settle_ms=0)

    entry = walker._walk_accrual("https://wd.example/plan", "GBR Vacation Buy (Days)")
    assert entry["calculation"] == "0"
    assert "literal amount" in entry.get("note", "")
    assert "_lookup" not in entry


def test_an_accrual_with_no_calculation_yields_no_further_hops():
    page = FakePage(evaluations={"calculation": "", "tabs": []})
    walker = AbsenceWalker(page, settle_ms=0)

    entry = walker._walk_accrual("https://wd.example/plan", "Some Accrual")
    assert entry["calculation"] == ""
    assert "calculationType" not in entry


def test_a_calculation_with_no_lookup_table_is_still_handed_on():
    """A Conditional Calculation resolves to branches, not a table.

    Two separate things, and an earlier version conflated them: *not hunting
    for a table that does not exist* is right, but the calculation must still
    reach `capture.lookups`, because that is the only channel
    `attach_calculations` reads.

    Returning early when there was no table meant every conditional
    calculation — every statutory plan worth asking about — was walked,
    captured, and then silently dropped. The plan kept the calculation's
    *name*, so the summary said "an amount calculated by X" and never what X
    decides, while nothing failed and no gap was reported.
    """
    page = FakePage(
        title="View Conditional Calculation - Workday",
        evaluations={
            "calculation": "GBR Statutory Holiday Annual Accrual Calculation",
            "pairs": {},
            "tabs": [],
        },
    )
    walker = AbsenceWalker(page, settle_ms=0)

    entry = walker._walk_accrual("https://wd.example/plan", "GBR Accrual")
    assert entry["calculationType"] == "Conditional Calculation"
    # No table was found, so none is claimed.
    assert "lookupTable" not in entry
    # But the calculation itself is passed on, carrying the branch grids.
    assert entry["_lookup"]["calculation"] == (
        "GBR Statutory Holiday Annual Accrual Calculation"
    )
    assert entry["_lookup"]["calculationType"] == "Conditional Calculation"
    assert "calculationGrids" in entry["_lookup"]


def test_a_lookup_table_is_found_when_the_screen_has_no_aria_label():
    """The real View Lookup Calculation screen labels the field with an
    adjacent text node, not `aria-label`.

    So the pair map — which reads `aria-label` — comes back holding only page
    chrome, the table name resolves empty, and the walk returns before
    clicking through. The calculation then resolves with **zero bands**: the
    entitlement itself missing, while the plan, the accrual and the
    calculation's name were all extracted and nothing reported a failure.

    Observed against a live tenant; the HKG plan's bands (1 year → 7 days,
    rising to 9 → 14) were unreachable until this fallback existed.
    """
    page = FakePage(
        title="View Lookup Calculation - Workday",
        evaluations={
            "calculation": "HKG Annual Leave Days Entitlement",
            "pairs": {},  # no aria-label on this screen
            "lookupTableByLabel": "Annual Leave Accrual (Hong Kong)",
            "tabs": [],
        },
    )
    walker = AbsenceWalker(page, settle_ms=0)

    entry = walker._walk_accrual("https://wd.example/plan", "HKG Accrual")
    assert entry["lookupTable"] == "Annual Leave Accrual (Hong Kong)"
    assert entry["_lookup"]["lookupTable"] == "Annual Leave Accrual (Hong Kong)"
    # It clicked through to the table rather than stopping at the calculation.
    assert any("Annual Leave Accrual (Hong Kong)" in click for click in page.clicks)


def test_a_lookup_calculation_walks_through_to_the_table():
    page = FakePage(
        title="View Lookup Calculation - Workday",
        evaluations={
            "calculation": "HKG Annual Leave Days Entitlement",
            "pairs": {"Lookup Table": "Annual Leave Accrual (Hong Kong)"},
            "criteria": "Worker Years of Service (based on Hire Date)",
            "tabs": [],
        },
        grids=[{"headers": ["Search Value", "Return Value"], "rows": [["1", "7"]]}],
    )
    walker = AbsenceWalker(page, settle_ms=0)

    entry = walker._walk_accrual("https://wd.example/plan", "HKG Annual Leave Accrual")
    lookup = entry["_lookup"]
    assert lookup["lookupTable"] == "Annual Leave Accrual (Hong Kong)"
    assert "Years of Service" in lookup["searchCriteria"]
    assert lookup["tableGrids"][0]["rows"] == [["1", "7"]]


def test_the_walk_needs_playwright(monkeypatch):
    monkeypatch.setattr(absence_walk, "playwright_available", lambda: False)
    with pytest.raises(absence_walk.BrowserUnavailable, match="not installed"):
        absence_walk.walk("{}", [{"url": "u1"}])
