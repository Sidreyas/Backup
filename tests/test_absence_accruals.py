"""
The accrual hop: `View Time Off Plan` → `View Accrual`.

The plan screen names its accruals but not what they grant. This is the
navigation that reaches the amounts, captured from the client's real tenant on
2026-08-12.

What the hop actually found, and none of it was predictable from the plan
screen alone:

  - **HKG** accrues via `HKG Annual Leave Days Entitlement`, scheduled
    annually in the first period of the calendar year, with mid-period hire
    handling.
  - **GBR base** accrues via `GBR Statutory Holiday Annual Accrual Calculation`.
  - **GBR termination** has its own calculation for mid-year leavers.
  - **GBR Vacation Buy** has calculation `0` — a literal, not a calculated
    field. It grants nothing automatically; the balance comes from a purchase
    election. Reporting that as "amount unknown" would be wrong in a way that
    matters: the plan genuinely grants zero here.

Even after this hop the *number* is still not reached — a named calculated
field is one further hop. The tests below hold the summary to saying so rather
than implying the calculation's name is the entitlement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.connectors.workday.absence import describe, summary_gaps
from api.connectors.workday.absence_screen import (
    attach_accrual_detail,
    parse_accrual_screen,
    parse_plan_screen,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _accruals() -> dict:
    return json.loads(
        (FIXTURES / "workday_accruals.json").read_text(encoding="utf-8")
    )


def _plan_capture(name: str) -> dict:
    return json.loads(
        (FIXTURES / f"workday_timeoffplan_{name}.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def gbr_plan():
    plan = parse_plan_screen(
        _plan_capture("gbr_statutory_holiday"),
        plan_id="GBR",
        name="GBR Statutory Holiday (Days)",
        unit_of_time="Days",
    )
    return attach_accrual_detail(plan, _accruals()["gbr_statutory_holiday"])


@pytest.fixture
def hkg_plan():
    plan = parse_plan_screen(
        _plan_capture("hkg_annual_leave"),
        plan_id="HKG",
        name="HKG Annual Leave",
        unit_of_time="Days",
    )
    return attach_accrual_detail(plan, _accruals()["hkg_annual_leave"])


# --- reading one accrual screen ---------------------------------------------


def test_the_accrual_screen_yields_its_calculation():
    capture = _accruals()["hkg_annual_leave"][0]
    detail = parse_accrual_screen(capture)
    assert detail["calculation"] == "HKG Annual Leave Days Entitlement"
    assert detail["isLiteral"] is False


def test_the_schedule_is_read_and_stripped_of_its_label():
    capture = _accruals()["hkg_annual_leave"][0]
    detail = parse_accrual_screen(capture)
    assert detail["schedule"].startswith("Annual - 1st Period")
    assert "Scheduling:" not in detail["schedule"]


def test_a_literal_amount_is_distinguished_from_a_calculated_one():
    """GBR Vacation Buy has calculation "0".

    That is a real entitlement of zero — the balance comes from a purchase
    election, not an accrual — and reporting it as "amount unknown" would
    describe a different plan.
    """
    buy = next(
        a for a in _accruals()["gbr_statutory_holiday"] if "Vacation Buy" in a["name"]
    )
    detail = parse_accrual_screen(buy)
    assert detail["calculation"] == "0"
    assert detail["isLiteral"] is True


def test_an_empty_capture_yields_nothing_rather_than_raising():
    assert parse_accrual_screen({}) == {}
    assert parse_accrual_screen({"grids": []}) == {}


# --- folding detail back onto the plan --------------------------------------


def test_hkg_accrual_gains_its_calculation(hkg_plan):
    accrual = hkg_plan.accruals[0]
    assert accrual.calculation == "HKG Annual Leave Days Entitlement"
    assert accrual.is_calculated is True


def test_all_three_gbr_accruals_are_matched_by_name(gbr_plan):
    by_name = {a.name: a for a in gbr_plan.accruals}
    assert len(by_name) == 3
    assert (
        by_name["GBR Statutory Holiday (Days) Accrual"].calculation
        == "GBR Statutory Holiday Annual Accrual Calculation"
    )
    assert "Mid Year Termination" in (
        by_name["GBR Statutory Holiday (Days) Termination Accrual"].calculation
    )


def test_the_literal_becomes_an_amount_not_a_calculation(gbr_plan):
    buy = next(a for a in gbr_plan.accruals if "Vacation Buy" in a.name)
    assert buy.amount == "0"
    assert buy.calculation == ""
    assert buy.is_calculated is False


def test_an_unmatched_capture_does_not_invent_an_accrual(gbr_plan):
    """A plan's accruals are defined by the plan.

    Appending a stray capture would assert configuration the tenant does not
    have.
    """
    before = len(gbr_plan.accruals)
    attach_accrual_detail(gbr_plan, [{"name": "Not On This Plan", "grids": []}])
    assert len(gbr_plan.accruals) == before


# --- what the summary can now say -------------------------------------------


def test_the_summary_names_the_calculation_behind_each_accrual(gbr_plan):
    text = describe(gbr_plan)
    assert "GBR Statutory Holiday Annual Accrual Calculation" in text
    assert "Mid Year Termination" in text


def test_the_summary_still_does_not_invent_a_number(gbr_plan):
    """The hop reaches the calculation's *name*, not its value.

    Naming a calculated field is honest; printing a number nobody extracted
    would be a fabricated leave entitlement.
    """
    text = describe(gbr_plan)
    assert "calculated by" in text
    gaps = summary_gaps(gbr_plan)
    assert any("GBR Statutory Holiday Annual Accrual Calculation" in g for g in gaps)


def test_the_zero_accrual_reads_as_zero_not_as_unknown(gbr_plan):
    text = describe(gbr_plan)
    assert "0 Days" in text


def test_hkg_summary_after_the_hop(hkg_plan):
    """The client's simple case, as far as configuration alone can take it."""
    text = describe(hkg_plan)
    assert "HKG Annual Leave" in text
    assert "Worker Location = Hong Kong" in text
    assert "HKG Annual Leave Days Entitlement" in text
    assert "does not carry over" in text
