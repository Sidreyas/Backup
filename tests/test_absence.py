"""
Absence: time off plans and the layman summary.

Driven by a real client request — read a tenant's time off plan configuration
and describe it in language a business user understands. The two plans the
client named are the fixtures here: one simple (HKG Annual Leave) and one
deliberately complex (GBR Statutory Holiday), because a system that only
handles the simple case fails on exactly the plans people ask about.

Two properties matter more than parsing:

  - **A summary must never overstate.** Missing eligibility has to read as
    "not extracted", never as silence — silence about who a plan covers is a
    claim that it covers everyone, which for a country-specific statutory plan
    is materially wrong.
  - **Worker absence data must be refused, not filtered.** Balances and leave
    dates are medical-adjacent, and a connector that quietly drops the columns
    has still received them.
"""

from __future__ import annotations

import pytest

from api.connectors.workday.absence import (
    AbsencePiiError,
    AccrualRule,
    EligibilityRule,
    TimeOffPlan,
    assert_no_worker_data,
    describe,
    parse_plan_rows,
    summary_gaps,
)

# --- fixtures modelled on the client's two plans ----------------------------

SIMPLE_ROWS = [
    {
        "Time_Off_Plan_ID": "HKG_ANNUAL_LEAVE",
        "Time_Off_Plan": "HKG Annual Leave",
        "Unit_of_Time": "Days",
        "Plan_Type": "Annual Leave",
        "Balance_Period": "Calendar Year",
        "Carryover_Limit": "5",
        "Carryover_Expiration": "3 months",
        "Country": "Hong Kong",
        "Accrual": "Monthly accrual",
        "Accrual_Amount": "1.25",
        "Accrual_Frequency": "month",
        "Eligibility_Rule": "Full-time Hong Kong employees",
        "Worker_Type": "Full-time",
    }
]

# The complex case: two accrual bands, one driven by a calculated field, plus a
# separate eligibility rule. This is the shape UK statutory leave takes.
COMPLEX_ROWS = [
    {
        "Time_Off_Plan_ID": "GBR_STAT_HOLIDAY",
        "Time_Off_Plan": "GBR Statutory Holiday (Days)",
        "Unit_of_Time": "Days",
        "Balance_Period": "Calendar Year",
        "Country": "United Kingdom",
        "Accrual": "Base statutory entitlement",
        "Accrual_Amount": "28",
        "Accrual_Frequency": "year",
        "Eligibility_Rule": "UK employees",
    },
    {
        "Time_Off_Plan_ID": "GBR_STAT_HOLIDAY",
        "Time_Off_Plan": "GBR Statutory Holiday (Days)",
        "Unit_of_Time": "Days",
        "Accrual": "Part-time pro-rata",
        "Calculated_Field": "CF_UK_Prorata_Entitlement",
        "Accrual_Frequency": "year",
        "Accrual_Condition": "worker is part-time",
    },
]


def _plan(rows) -> TimeOffPlan:
    return parse_plan_rows(rows)[0]


# --- parsing ----------------------------------------------------------------


def test_a_simple_plan_parses_into_one_accrual_and_one_rule():
    plan = _plan(SIMPLE_ROWS)
    assert plan.name == "HKG Annual Leave"
    assert plan.unit_of_time == "Days"
    assert len(plan.accruals) == 1
    assert plan.accruals[0].amount == "1.25"
    assert plan.accruals[0].frequency == "month"
    assert len(plan.eligibility) == 1


def test_rows_group_by_plan_rather_than_producing_one_plan_per_row():
    """Workday returns one row per plan/accrual pair."""
    plans = parse_plan_rows(COMPLEX_ROWS)
    assert len(plans) == 1
    assert len(plans[0].accruals) == 2


def test_a_calculated_accrual_is_marked_as_such():
    """The amount *is* a calculation, and reporting a blank amount as zero
    would understate someone's leave entitlement."""
    plan = _plan(COMPLEX_ROWS)
    calculated = [a for a in plan.accruals if a.is_calculated]
    assert len(calculated) == 1
    assert calculated[0].calculation == "CF_UK_Prorata_Entitlement"
    assert calculated[0].amount == ""


def test_complexity_is_detected_not_assumed():
    """Which plans need more than one sentence to describe honestly."""
    assert _plan(SIMPLE_ROWS).is_complex is False
    assert _plan(COMPLEX_ROWS).is_complex is True


def test_duplicate_eligibility_rules_are_not_repeated():
    rows = [*SIMPLE_ROWS, dict(SIMPLE_ROWS[0], Accrual="Second accrual")]
    plan = parse_plan_rows(rows)[0]
    assert len(plan.eligibility) == 1
    assert len(plan.accruals) == 2


# --- the PII boundary -------------------------------------------------------


def test_worker_absence_data_is_refused_not_filtered():
    """Absence is the most PII-dense area in Workday.

    Filtering the columns out would mean the data had already been received;
    refusing the report is what makes the boundary real.
    """
    with pytest.raises(AbsencePiiError, match="per-worker absence data"):
        assert_no_worker_data(
            ["Time_Off_Plan", "Worker", "Balance"], report="time off plans"
        )


def test_the_refusal_names_the_offending_columns_and_the_fix():
    try:
        assert_no_worker_data(["Employee_ID", "Absence_Date"], report="plans")
    except AbsencePiiError as exc:
        message = str(exc)
    assert "employee_id" in message
    assert "absence_date" in message
    assert "Rebuild the report" in message


def test_parsing_refuses_rows_carrying_worker_data():
    """The guard runs before any row is read, not after."""
    rows = [{**SIMPLE_ROWS[0], "Worker": "Alice Tan", "Balance": "12"}]
    with pytest.raises(AbsencePiiError):
        parse_plan_rows(rows)


def test_configuration_columns_are_not_mistaken_for_worker_data():
    """The guard must not reject a legitimate plan report."""
    assert_no_worker_data(list(SIMPLE_ROWS[0].keys()), report="plans")


# --- the summary ------------------------------------------------------------


def test_a_simple_plan_reads_as_a_business_user_would_expect():
    text = describe(_plan(SIMPLE_ROWS))
    assert "HKG Annual Leave" in text
    assert "Full-time Hong Kong employees" in text
    assert "1.25" in text
    assert "month" in text
    assert "5 Days carry over" in text
    assert "expiring after 3 months" in text


def test_a_complete_summary_says_nothing_about_gaps():
    assert "Not yet known" not in describe(_plan(SIMPLE_ROWS))


def test_missing_eligibility_is_stated_rather_than_omitted():
    """Silence about who a plan covers reads as "everyone"."""
    plan = TimeOffPlan(
        plan_id="X",
        name="Some Plan",
        unit_of_time="Days",
        accruals=[AccrualRule(name="a", amount="10", frequency="year")],
    )
    text = describe(plan)
    assert "Eligibility not extracted" in text
    assert "Not yet known" in text
    assert "who the plan applies to" in text


def test_a_calculated_accrual_is_described_as_calculated_not_as_zero():
    text = describe(_plan(COMPLEX_ROWS))
    assert "CF_UK_Prorata_Entitlement" in text
    assert "calculated by" in text
    # And the condition gating it must survive into the sentence.
    assert "worker is part-time" in text


def test_the_unit_appears_wherever_a_number_does():
    """"You get 28" is not an answer. Days and hours plans cannot be
    compared, and a number without its unit is worse than no number."""
    text = describe(_plan(COMPLEX_ROWS))
    assert "28 Days" in text


def test_gaps_name_the_unresolved_calculated_field():
    gaps = summary_gaps(_plan(COMPLEX_ROWS))
    assert any("CF_UK_Prorata_Entitlement" in g for g in gaps)


def test_a_plan_with_no_unit_is_reported_as_incomplete():
    plan = TimeOffPlan(
        plan_id="X",
        name="Some Plan",
        accruals=[AccrualRule(name="a", amount="10")],
        eligibility=[EligibilityRule(name="everyone")],
    )
    assert "unit of time (days or hours)" in summary_gaps(plan)


# --- connector wiring -------------------------------------------------------


def _connector(**extra):
    from api.connectors.workday.connector import WorkdayConnector

    return WorkdayConnector(
        {
            "host": "https://wcpdev.wd101.myworkday.com",
            "tenant": "aia_wcpdev1",
            "method": "isu_basic",
            "username": "isu",
            "password": "pw",
            **extra,
        }
    )


def test_a_plan_becomes_a_node_with_its_summary_attached():
    """The summary is stored, not recomputed at read time — it is a claim
    about the configuration as extracted."""
    connector = _connector(granted_scopes=["read.absence"])
    records = list(connector._records_for_plan(_plan(SIMPLE_ROWS)))

    plan_record = records[0]
    assert plan_record.natural_key == "workday:timeoffplan:HKG_ANNUAL_LEAVE"
    assert "1.25" in plan_record.payload["summary"]
    assert plan_record.payload["summaryComplete"] is True
    assert plan_record.payload["unitOfTime"] == "Days"


def test_accruals_are_ordered_within_their_plan():
    """An initial award followed by monthly accrual is not the same plan with
    the order reversed — the first year's entitlement differs."""
    connector = _connector(granted_scopes=["read.absence"])
    records = list(connector._records_for_plan(_plan(COMPLEX_ROWS)))

    accruals = [r for r in records if ":accrual:" in r.natural_key]
    assert len(accruals) == 2
    positions = [
        order.sequence
        for record in accruals
        for order in record.ordering.values()
    ]
    assert sorted(positions) == [1, 2]


def test_a_calculated_accrual_links_to_the_field_it_depends_on():
    """Without this edge, changing the calculated field shows no impact on the
    leave policy it drives."""
    connector = _connector(granted_scopes=["read.absence"])
    records = list(connector._records_for_plan(_plan(COMPLEX_ROWS)))

    targets = {t for r in records for p, t in r.relations if p == "DEPENDS_ON"}
    assert "workday:field:cf-uk-prorata-entitlement" in targets


def test_absence_capability_appears_only_when_granted():
    assert "workday.absence" not in {
        c.id for c in _connector(granted_scopes=["read.organisation"]).discover_capabilities()
    }
    assert "workday.absence" in {
        c.id for c in _connector(granted_scopes=["read.absence"]).discover_capabilities()
    }


def test_absence_reports_are_in_the_pack_with_a_pii_warning():
    from api.connectors.workday.reports import REPORTS_BY_ID

    spec = REPORTS_BY_ID["time_off_plans"]
    assert "Unit_of_Time" in {f.name for f in spec.fields if f.required}
    assert any("per-worker" in n for n in spec.notes)


def test_absence_recipes_are_valid():
    from api.connectors.workday.recipes import RECIPES_BY_ID, validate_pack

    validate_pack()
    assert "time_off_plan_screen" in RECIPES_BY_ID
    assert "eligibility_rule_screen" in RECIPES_BY_ID
