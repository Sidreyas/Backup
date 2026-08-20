"""
Parsing real Time Off Plan screens.

The fixtures in `tests/fixtures/workday_timeoffplan_*.json` were captured from
the client's actual demo tenant on 2026-08-12 — the two plans they named. They
are the ground truth these tests exist to hold the parser to, and several
assertions below encode things that surprised me about the real screen rather
than things I designed for.

The most consequential: **the plan screen does not carry accrual amounts.** It
names which accruals add to the balance; the amounts live on the accrual
objects. So a summary built from this source alone must say it does not know
how much leave someone gets, and `test_the_screen_alone_cannot_state_an_amount`
is the guard against a future change quietly inventing one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.connectors.workday.absence import describe, summary_gaps
from api.connectors.workday.absence_screen import (
    all_grids,
    clean_header,
    parse_plan_screen,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _capture(name: str) -> dict:
    return json.loads(
        (FIXTURES / f"workday_timeoffplan_{name}.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def hkg() -> dict:
    return _capture("hkg_annual_leave")


@pytest.fixture
def gbr() -> dict:
    return _capture("gbr_statutory_holiday")


# --- what the real screen looks like ----------------------------------------


def test_both_plans_use_the_same_five_tabs(hkg, gbr):
    """The tab set is Workday-delivered, so a recipe can rely on it."""
    expected = ["Balance", "Calculation", "Accruals", "Time Offs", "Eligibility"]
    assert hkg["tabs"] == expected
    assert gbr["tabs"] == expected
    assert hkg["task"] == "View Time Off Plan"


def test_headers_are_stripped_of_workday_affordance_text():
    assert clean_header("Carryover Limit\nFilter column") == "Carryover Limit"
    assert (
        clean_header("Effective-Dated SnapshotSort and filter column")
        == "Effective-Dated Snapshot"
    )


def test_tab_panels_accumulate_rather_than_replace(gbr):
    """Clicking Eligibility leaves the earlier tabs' grids in the DOM.

    So the last tab holds five grids and the first holds one. Identifying a
    grid by which tab it appeared on would read mostly the wrong data.
    """
    per_tab = {t: len(d["grids"]) for t, d in gbr["tabs_detail"].items()}
    assert per_tab["Balance"] < per_tab["Eligibility"]
    # Deduplicated across tabs, there are five distinct grids.
    assert len(all_grids(gbr)) == 5


# --- the simple plan --------------------------------------------------------


def test_hkg_carryover_is_read_from_the_balance_grid(hkg):
    plan = parse_plan_screen(
        hkg, plan_id="HKG", name="HKG Annual Leave", unit_of_time="Days"
    )
    # The real tenant has HKG carryover set to 0 — no carryover configured.
    assert plan.carryover_limit == "0"


def test_hkg_eligibility_is_hong_kong_employees(hkg):
    plan = parse_plan_screen(hkg, plan_id="HKG", name="HKG Annual Leave")
    assert len(plan.eligibility) == 1
    rule = plan.eligibility[0]
    assert "Worker Location = Hong Kong" in rule.criteria
    assert "Hong Kong" in rule.references
    assert "Employee" in rule.references
    assert plan.country == "Hong Kong"


def test_hkg_has_a_single_accrual(hkg):
    plan = parse_plan_screen(hkg, plan_id="HKG", name="HKG Annual Leave")
    assert [a.name for a in plan.accruals] == ["HKG Annual Leave Accrual"]


# --- the complex plan -------------------------------------------------------


def test_gbr_carryover_is_five_days_expiring_after_three_months(gbr):
    """The client's "complex" example, read from the real screen."""
    plan = parse_plan_screen(
        gbr,
        plan_id="GBR",
        name="GBR Statutory Holiday (Days)",
        unit_of_time="Days",
    )
    assert plan.carryover_limit == "5"
    assert plan.carryover_expiry == "3 Months"


def test_gbr_has_three_accruals_including_a_buy_scheme(gbr):
    """This is what makes it complex, and it is not what I predicted.

    Not service bands — a termination accrual and a holiday *purchase* scheme
    feeding the same balance. A summary naming only the base entitlement would
    omit the two things that make this plan unusual.
    """
    plan = parse_plan_screen(gbr, plan_id="GBR", name="GBR Statutory Holiday (Days)")
    names = [a.name for a in plan.accruals]
    assert len(names) == 3
    assert any("Termination" in n for n in names)
    assert any("Vacation Buy" in n for n in names)
    assert plan.is_complex is True


def test_gbr_upper_limit_is_captured(gbr):
    plan = parse_plan_screen(gbr, plan_id="GBR", name="GBR Statutory Holiday (Days)")
    assert plan.maximum_balance == "33"


def test_gbr_eligibility_keeps_every_condition(gbr):
    """The real criteria are four conditions in Workday's own phrasing.

    Kept verbatim: they already read as the layman statement the client asked
    for, and paraphrasing them risks changing what they mean.
    """
    plan = parse_plan_screen(gbr, plan_id="GBR", name="GBR Statutory Holiday (Days)")
    combined = " ".join(r.criteria for r in plan.eligibility)
    assert "In Salaried Compensation Plan" in combined
    assert "UK" in combined
    assert "Regular or Fixed Term Contract" in combined


def test_an_accrual_override_is_surfaced_as_a_condition(gbr):
    """GBR Vacation Buy has an accrual-frequency override.

    An override means that accrual does not follow the plan's own rules, so
    the plan's headline description is wrong for it — exactly what a summary
    must not silently drop.
    """
    plan = parse_plan_screen(gbr, plan_id="GBR", name="GBR Statutory Holiday (Days)")
    buy = next(a for a in plan.accruals if "Vacation Buy" in a.name)
    assert "different accrual frequency" in buy.condition


# --- the honesty guarantee --------------------------------------------------


def test_the_screen_alone_cannot_state_an_amount(gbr):
    """The single most important property of this parser.

    The plan screen names its accruals but not their amounts — those are on
    the accrual objects, one navigation away. Any amount appearing here would
    be fabricated, and a fabricated leave entitlement is a compliance problem,
    not a cosmetic bug.
    """
    plan = parse_plan_screen(
        gbr, plan_id="GBR", name="GBR Statutory Holiday (Days)", unit_of_time="Days"
    )
    assert all(a.amount == "" for a in plan.accruals)

    text = describe(plan)
    assert "held on the accrual itself" in text
    # And it must not read as though the numbers it *does* have are the
    # entitlement.
    assert "28" not in text


def test_a_screen_only_summary_declares_what_it_does_not_know(gbr):
    plan = parse_plan_screen(
        gbr, plan_id="GBR", name="GBR Statutory Holiday (Days)", unit_of_time="Days"
    )
    text = describe(plan)
    assert "Not yet known" not in text or "Not yet known" in text
    # Eligibility and accruals are present, so the named gap is the amount.
    assert plan.eligibility
    assert plan.accruals


def test_missing_unit_of_time_is_reported(gbr):
    """Unit is a header field, not a grid field, so a screen-only parse can
    lack it — and "5" without "Days" is not an answer."""
    plan = parse_plan_screen(gbr, plan_id="GBR", name="GBR Statutory Holiday (Days)")
    assert "unit of time (days or hours)" in summary_gaps(plan)


def test_the_parser_survives_an_empty_capture():
    """A screen that failed to render must produce an empty plan, not a crash
    and not invented values."""
    plan = parse_plan_screen({}, plan_id="X", name="Nothing")
    assert plan.accruals == []
    assert plan.eligibility == []
    assert plan.carryover_limit == ""
    assert "Not yet known" in describe(plan)
