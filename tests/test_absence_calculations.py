"""
The last hop: calculated fields resolved to actual values.

The complete chain a leave entitlement travels in Workday:

    Time Off Plan → Accrual → Calculated Field → (Lookup Table) → values

Walking it against the client's tenant showed the two plans resolve through
*different calculated-field types*, which is the substantive finding here:

  - **HKG** uses a **Lookup Calculation** → table `Annual Leave Accrual (Hong
    Kong)`, keyed on "Worker Years of Service (based on Hire Date) as of Period
    Start Date": 1 year → 7 days, rising to 9 years → 14 days.
  - **GBR** uses a **Conditional Calculation** → ordered branches: hired before
    the calendar year starts → "UK Statutory 28 days prorated based on FTE%";
    hired mid-year → a further calculation.

A model handling only one type would have looked completely correct on
whichever plan happened to be tried first. That is why both are fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.connectors.workday.absence import describe, summary_gaps
from api.connectors.workday.absence_screen import (
    attach_accrual_detail,
    attach_calculations,
    parse_calculation,
    parse_plan_screen,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _plan(key: str, plan_id: str, name: str):
    plan = parse_plan_screen(
        _load(f"workday_timeoffplan_{key}.json"),
        plan_id=plan_id,
        name=name,
        unit_of_time="Days",
    )
    plan = attach_accrual_detail(plan, _load("workday_accruals.json")[key])
    return attach_calculations(plan, _load("workday_lookups.json")[key])


@pytest.fixture
def hkg():
    return _plan("hkg_annual_leave", "HKG", "HKG Annual Leave")


@pytest.fixture
def gbr():
    return _plan("gbr_statutory_holiday", "GBR", "GBR Statutory Holiday (Days)")


# --- the two calculation types ----------------------------------------------


def test_a_lookup_calculation_resolves_to_bands():
    entry = _load("workday_lookups.json")["hkg_annual_leave"][0]
    calc = parse_calculation(entry)

    assert calc.kind == "Lookup Calculation"
    assert calc.table_name == "Annual Leave Accrual (Hong Kong)"
    assert calc.is_resolved is True
    assert len(calc.bands) == 8
    assert (calc.bands[0].search, calc.bands[0].result) == ("1", "7")
    assert (calc.bands[-1].search, calc.bands[-1].result) == ("9", "14")


def test_the_lookup_records_what_it_is_keyed_on():
    """"1 → 7" is not an answer to anything without this."""
    calc = parse_calculation(_load("workday_lookups.json")["hkg_annual_leave"][0])
    assert "Years of Service" in calc.criteria


def test_a_conditional_calculation_resolves_to_ordered_branches():
    entry = _load("workday_lookups.json")["gbr_statutory_holiday"][0]
    calc = parse_calculation(entry)

    assert calc.kind == "Conditional Calculation"
    assert calc.is_resolved is True
    assert len(calc.branches) == 2
    assert calc.branches[0].order == "a"
    assert "28 days prorated" in calc.branches[0].result
    assert "FTE" in calc.branches[0].result


def test_a_literal_accrual_has_no_calculation_to_resolve():
    """GBR Vacation Buy's calculation is "0" — the walk correctly stops."""
    entry = next(
        e
        for e in _load("workday_lookups.json")["gbr_statutory_holiday"]
        if "Vacation Buy" in e["accrual"]
    )
    calc = parse_calculation(entry)
    assert calc is None or calc.is_resolved is False


def test_an_empty_entry_resolves_to_nothing_rather_than_raising():
    assert parse_calculation({}) is None
    assert parse_calculation({"calculation": ""}) is None


# --- what the summary can finally say ----------------------------------------


def test_hkg_states_the_actual_entitlement_range(hkg):
    """The client's question — "how much leave do HK staff get" — answered."""
    text = describe(hkg)
    assert "7" in text
    assert "14" in text
    assert "years of service" in text.lower()
    # And it must no longer hide behind the calculated field's name.
    assert "calculated by 'HKG Annual Leave Days Entitlement'" not in text


def test_hkg_has_no_remaining_gaps(hkg):
    """A fully resolved lookup leaves nothing unknown."""
    assert summary_gaps(hkg) == []
    assert "Not yet known" not in describe(hkg)


def test_gbr_states_its_branches_in_business_language(gbr):
    text = describe(gbr)
    assert "28 days prorated based on FTE%" in text
    assert "when" in text


def test_gbr_reports_the_branch_it_could_not_resolve(gbr):
    """One GBR branch points at a further calculated field.

    Naming which branch is unresolved is far more useful than a blanket
    "unknown" — the reader can see that the standard case is answered and only
    the mid-year-hire path is not.
    """
    gaps = summary_gaps(gbr)
    assert any("Mid Year Hire" in g for g in gaps)
    # The prorated branch is a real answer and must not be reported as a gap.
    assert not any("prorated" in g.lower() for g in gaps)


def test_the_zero_accrual_still_reads_as_zero(gbr):
    assert "0 Days" in describe(gbr)


def test_resolution_does_not_invent_values_for_unwalked_accruals(gbr):
    """An accrual with no lookup entry keeps its unresolved wording."""
    plan = parse_plan_screen(
        _load("workday_timeoffplan_gbr_statutory_holiday.json"),
        plan_id="GBR",
        name="GBR Statutory Holiday (Days)",
        unit_of_time="Days",
    )
    plan = attach_accrual_detail(
        plan, _load("workday_accruals.json")["gbr_statutory_holiday"]
    )
    # No calculations attached at all.
    text = describe(plan)
    assert "calculated by" in text
    assert "28 days prorated" not in text


def test_unmatched_lookup_entries_are_ignored(hkg):
    before = describe(hkg)
    attach_calculations(hkg, [{"accrual": "Not A Real Accrual", "calculation": "X"}])
    assert describe(hkg) == before
