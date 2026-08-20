"""
Absence: time off plans, accruals, eligibility and the rules behind them.

Why this is its own module rather than more rows in `reports.py`. A business
process is a *sequence* — the interesting question is what happens third. A
time off plan is a *calculation*: how much someone accrues, when they become
eligible, what carries over and for how long. Those need different extraction
and produce a different shape of answer, and mixing them would give both the
worst of the other's structure.

The immediate driver is a client asking for time off plan configuration in
language a business user can read:

    HKG Annual Leave — Full-time Hong Kong employees accrue 1.25 days per
    month, up to 15 days a year. Unused balance carries into the next year but
    expires after 3 months.

Producing that sentence needs five separate things: the plan, its accrual, its
eligibility rule, its carryover limit, and the units everything is expressed
in. They live in different places in Workday, and a summary that silently drops
any one of them is worse than no summary — "accrues 1.25 days per month" with
the eligibility rule missing reads as though it applies to everyone.

**Configuration only, and that boundary is enforced rather than intended.**
Absence is the most PII-dense area in Workday: balances, leave dates, and
absence types that imply medical detail. This module extracts *plans* and never
*balances*. `FORBIDDEN_BALANCE_FIELDS` exists so a future report whose columns
drift into worker data fails loudly instead of quietly ingesting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Column names that mean the report is returning per-worker data rather than
#: configuration. Their presence is a setup error, not something to filter out
#: silently — a report built on the wrong data source needs rebuilding, and
#: dropping the columns would hide that while still having transmitted them.
FORBIDDEN_BALANCE_FIELDS = frozenset(
    {
        "worker",
        "employee_id",
        "employee",
        "balance",
        "current_balance",
        "as_of_date_balance",
        "absence_date",
        "first_day_of_absence",
        "last_day_of_absence",
        "leave_date",
        "requested_days",
    }
)


class AbsencePiiError(ValueError):
    """A report returned worker data where configuration was expected."""


def assert_no_worker_data(columns: list[str], *, report: str) -> None:
    """Refuse a report whose columns carry per-worker absence data.

    Called before any row is read. Absence balances and leave dates are among
    the most sensitive fields in an HR system, and the cost of getting this
    wrong is not a bug report — it is having ingested medical-adjacent data
    nobody consented to share.
    """
    normalised = {c.strip().lower().replace(" ", "_") for c in columns}
    offending = sorted(normalised & FORBIDDEN_BALANCE_FIELDS)
    if offending:
        raise AbsencePiiError(
            f"The report '{report}' returns per-worker absence data "
            f"({', '.join(offending)}). Meridian reads time off *configuration* "
            "only. Rebuild the report on a plan-level data source, without "
            "worker or balance columns."
        )


# --- the pieces of a plan ---------------------------------------------------


@dataclass(slots=True)
class AccrualRule:
    """How entitlement is earned.

    `amount` and `frequency` are kept as the source states them rather than
    converted to a canonical per-year figure. A plan that grants "1.25 days per
    month" and one that grants "15 days per year" are not the same plan even
    when the totals match — the first accrues progressively and a leaver takes
    a pro-rated balance with them.
    """

    name: str
    amount: str = ""
    unit: str = ""
    frequency: str = ""
    #: Condition rule gating this accrual, e.g. service-band-dependent grants.
    condition: str = ""
    #: Calculated field driving the amount, when it is not a constant. This is
    #: what makes UK statutory leave hard: the amount *is* a calculation.
    calculation: str = ""
    effective_date: str = ""
    #: The calculation resolved to its values, when the walk reached them.
    #: `calculation` alone is only a name — this is what makes the difference
    #: between "calculated by 'HKG Annual Leave Days Entitlement'" and
    #: "7 days rising to 14 days, by years of service".
    resolved: Calculation | None = None

    @property
    def is_calculated(self) -> bool:
        return bool(self.calculation)


@dataclass(slots=True)
class EntitlementBand:
    """One row of a lookup table: a threshold and what it grants.

    `search` is whatever the table is keyed on — years of service, FTE
    percentage — and is meaningless without `criteria` on the owning
    calculation naming it. "1 → 7" says nothing; "1 year of service → 7 days"
    is an answer.
    """

    search: str
    result: str


@dataclass(slots=True)
class ConditionalBranch:
    """One branch of a conditional calculation: a test and its outcome."""

    order: str
    condition: str
    result: str


@dataclass(slots=True)
class Calculation:
    """A calculated field, resolved as far as configuration allows.

    Workday has several calculated-field types and they resolve differently,
    which is the whole reason this is modelled rather than kept as a name:

      - **Lookup Calculation** → a table of thresholds and values. Fully
        resolvable; the numbers are right there.
      - **Conditional Calculation** → ordered condition/result branches, where
        each result may itself be another calculated field. Resolvable one
        level, and honest about the rest.
      - Anything else → the name, and a statement that it was not resolved.

    Both of the client's plans are represented: HKG is a lookup, GBR is
    conditional. A model that only handled one would have looked correct on
    whichever plan was tried first.
    """

    name: str
    kind: str = ""
    #: What a lookup table is keyed on, verbatim from Workday.
    criteria: str = ""
    bands: list[EntitlementBand] = field(default_factory=list)
    branches: list[ConditionalBranch] = field(default_factory=list)
    table_name: str = ""

    @property
    def is_resolved(self) -> bool:
        """Whether this reached actual values rather than another name."""
        return bool(self.bands or self.branches)

    def describe(self, unit: str = "") -> str:
        """The calculation in plain language.

        Returns a phrase, not a sentence — the caller composes it into the
        plan summary.
        """
        suffix = f" {unit}" if unit else ""
        if self.bands:
            subject = self.criteria or "a lookup"
            first, last = self.bands[0], self.bands[-1]
            return (
                f"{first.result}{suffix} rising to {last.result}{suffix}, "
                f"by {subject.lower()}"
                if first.result != last.result
                else f"{first.result}{suffix}, by {subject.lower()}"
            )
        if self.branches:
            return "; ".join(
                f"{b.result} when {b.condition}" for b in self.branches
            )
        return f"calculated by '{self.name}'"


@dataclass(slots=True)
class EligibilityRule:
    """Who the plan applies to."""

    name: str
    criteria: str = ""
    #: Eligibility often keys off worker type, location or job family. Kept as
    #: separate references so the graph can link a plan to the organisation it
    #: governs rather than only holding prose.
    references: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TimeOffPlan:
    """One time off plan, with everything needed to describe it.

    Deliberately a flat record rather than a graph fragment. The connector turns
    this into nodes and relations; keeping extraction shape separate from graph
    shape means a change to the ontology does not require reworking parsing.
    """

    plan_id: str
    name: str
    plan_type: str = ""
    unit_of_time: str = ""
    #: "Days" and "Hours" plans cannot be compared or summed, and a summary
    #: that omits the unit is not merely incomplete — it is wrong.
    balance_period: str = ""
    accruals: list[AccrualRule] = field(default_factory=list)
    eligibility: list[EligibilityRule] = field(default_factory=list)
    carryover_limit: str = ""
    carryover_expiry: str = ""
    maximum_balance: str = ""
    minimum_increment: str = ""
    allows_negative_balance: str = ""
    position_management: str = ""
    country: str = ""
    inactive: bool = False
    #: Where this came from — report, SOAP or screen. Absence configuration is
    #: reachable by more than one route and they do not always agree, so the
    #: route is recorded with the data rather than inferred later.
    via: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def natural_key(self) -> str:
        return f"workday:timeoffplan:{self.plan_id}"

    @property
    def is_complex(self) -> bool:
        """Whether this plan needs more than one sentence to describe honestly.

        Used to decide how much detail a summary must carry. A plan with
        conditional accrual or several eligibility rules cannot be reduced to
        "you get N days" without losing the part that matters.
        """
        return (
            len(self.accruals) > 1
            or len(self.eligibility) > 1
            or any(a.condition or a.is_calculated for a in self.accruals)
        )


# --- what has to be true for a summary to be safe ---------------------------

#: A layman summary is generated from these. Anything missing is stated as
#: unknown rather than omitted: a sentence that silently drops the eligibility
#: rule reads as though the plan applies to everybody, which for a
#: country-specific statutory plan is a materially wrong statement to put in
#: front of a business user.
SUMMARY_REQUIRED = ("name", "unit_of_time", "accruals", "eligibility")


def summary_gaps(plan: TimeOffPlan) -> list[str]:
    """What is missing before this plan can be described honestly."""
    gaps: list[str] = []
    if not plan.name:
        gaps.append("plan name")
    if not plan.unit_of_time:
        gaps.append("unit of time (days or hours)")
    if not plan.accruals:
        gaps.append("how entitlement is earned")
    if not plan.eligibility:
        gaps.append("who the plan applies to")
    for accrual in plan.accruals:
        if not accrual.is_calculated or accrual.amount:
            continue
        if accrual.resolved and accrual.resolved.is_resolved:
            # Resolved to real values, so not a gap. A conditional calculation
            # whose branches point at *further* calculated fields is still
            # partially unresolved, and that is reported per branch rather
            # than as a blanket unknown — the reader can see which branch.
            unresolved = [
                b.result
                for b in accrual.resolved.branches
                if b.result and not _looks_numeric(b.result)
            ]
            gaps.extend(
                f"what '{result}' evaluates to"
                for result in unresolved
                if "prorated" not in result.lower()
            )
            continue
        gaps.append(f"the value of the calculated field '{accrual.calculation}'")
    return gaps


def _looks_numeric(value: str) -> bool:
    """Whether a branch result is already a number rather than another rule."""
    try:
        float(str(value).split()[0])
    except (TypeError, ValueError, IndexError):
        return False
    return True


def describe(plan: TimeOffPlan) -> str:
    """A plain-language description of a plan, with its gaps stated.

    Deliberately templated rather than model-generated. A hallucinated leave
    policy is a compliance problem, and the input here is a handful of known
    fields — there is nothing for a language model to add except risk. The
    generation layer's job is to make this *read* better, from a base that is
    already true.

    Every unknown is named. "Eligibility not extracted" is useful; silence is
    a claim that the plan applies to everyone.
    """
    parts: list[str] = []
    unit = plan.unit_of_time or "units"

    if not plan.eligibility:
        parts.append(f"{plan.name}. Eligibility not extracted.")
    elif len(plan.eligibility) == 1:
        parts.append(
            f"{plan.name} applies to: "
            f"{plan.eligibility[0].criteria or plan.eligibility[0].name}."
        )
    else:
        # Several rules are alternatives, not one long conjunction. Running
        # them together with "and" describes a population nobody is in — the
        # GBR plan has a mid-period-termination variant and a normal one, and
        # no worker satisfies both.
        parts.append(f"{plan.name} applies to workers meeting any of:")
        for index, rule in enumerate(plan.eligibility, start=1):
            parts.append(f"({index}) {rule.criteria or rule.name}.")

    if plan.accruals:
        for accrual in plan.accruals:
            # Name the accrual. A plan with three of them produced three
            # identical sentences without this, which reads as a rendering bug
            # rather than as three distinct rules.
            subject = accrual.name or "Accrues"
            if accrual.resolved and accrual.resolved.is_resolved:
                # The walk reached actual values. This is the difference
                # between naming a rule and answering the question.
                earned = accrual.resolved.describe(unit)
            elif accrual.is_calculated and accrual.calculation != accrual.amount:
                earned = (
                    f"an amount calculated by '{accrual.calculation}'"
                    if not accrual.amount
                    else f"{accrual.amount} {unit} (from '{accrual.calculation}')"
                )
            elif accrual.amount:
                earned = f"{accrual.amount} {unit}"
            else:
                # Say where the number is, not just that it is missing.
                # "An unspecified amount" invites the reader to assume it was
                # unset in Workday; it was simply not on this screen.
                earned = "an amount held on the accrual itself"
            when = f", {accrual.frequency}" if accrual.frequency else ""
            gate = f" ({accrual.condition})" if accrual.condition else ""
            parts.append(f"{subject}: {earned}{when}{gate}.")
    else:
        parts.append("How entitlement is earned was not extracted.")

    if plan.carryover_limit:
        # A limit of zero is a real, deliberate setting and must be stated —
        # "use it or lose it" is exactly the thing a business user needs to
        # know — but "Up to 0 Days carry over" reads as a rendering fault.
        if plan.carryover_limit.strip() in {"0", "0.0", "0.00"}:
            parts.append("Unused balance does not carry over.")
        else:
            expiry = (
                f", expiring after {plan.carryover_expiry}"
                if plan.carryover_expiry
                else ""
            )
            parts.append(f"Up to {plan.carryover_limit} {unit} carry over{expiry}.")
    if plan.maximum_balance:
        parts.append(f"Balance is capped at {plan.maximum_balance} {unit}.")

    gaps = summary_gaps(plan)
    if gaps:
        parts.append("Not yet known: " + ", ".join(dict.fromkeys(gaps)) + ".")

    return " ".join(parts)


# --- parsing ----------------------------------------------------------------


def parse_plan_rows(
    rows: list[dict[str, Any]], *, via: str = "report"
) -> list[TimeOffPlan]:
    """Turn report rows into plans.

    One row per plan/accrual combination is the usual shape, so rows are
    grouped by plan and accruals accumulated — the same one-row-per-child
    problem the runtime BP report has.
    """
    from api.connectors.workday.raas import field_value

    if rows:
        assert_no_worker_data(list(rows[0].keys()), report="time off plans")

    plans: dict[str, TimeOffPlan] = {}
    for row in rows:
        plan_id = field_value(
            row, "Time_Off_Plan_ID", "Plan_ID", "Absence_Plan_ID", "planId"
        )
        name = field_value(
            row, "Time_Off_Plan", "Plan_Name", "Absence_Plan", "planName"
        )
        if not plan_id and not name:
            continue
        plan_id = plan_id or _slug(name)

        plan = plans.get(plan_id)
        if plan is None:
            plan = TimeOffPlan(
                plan_id=plan_id,
                name=name or plan_id,
                plan_type=field_value(row, "Plan_Type", "Time_Off_Type", "Absence_Type"),
                unit_of_time=field_value(
                    row, "Unit_of_Time", "Units", "Unit", "unitOfTime"
                ),
                balance_period=field_value(row, "Balance_Period", "Period"),
                carryover_limit=field_value(
                    row, "Carryover_Limit", "Carry_Over_Limit", "Maximum_Carryover"
                ),
                carryover_expiry=field_value(
                    row, "Carryover_Expiration", "Carry_Over_Expiration"
                ),
                maximum_balance=field_value(row, "Maximum_Balance", "Balance_Limit"),
                minimum_increment=field_value(row, "Minimum_Increment", "Increment"),
                allows_negative_balance=field_value(
                    row, "Allows_Negative_Balance", "Negative_Balance"
                ),
                country=field_value(row, "Country", "Location_Context"),
                inactive=_truthy(field_value(row, "Inactive", "Is_Inactive")),
                via=via,
                raw=dict(row),
            )
            plans[plan_id] = plan

        accrual_name = field_value(row, "Accrual", "Accrual_Name", "Accrual_Rule")
        if accrual_name:
            plan.accruals.append(
                AccrualRule(
                    name=accrual_name,
                    amount=field_value(row, "Accrual_Amount", "Amount", "Rate"),
                    unit=plan.unit_of_time,
                    frequency=field_value(
                        row, "Accrual_Frequency", "Frequency", "Accrual_Period"
                    ),
                    # Deliberately does NOT fall back to `Eligibility_Rule`.
                    # Eligibility says *who is in the plan*; an accrual
                    # condition says *when this particular accrual applies to
                    # someone already in it*. Conflating them made every plan
                    # with an eligibility rule read as conditionally gated,
                    # which flipped `is_complex` on for the simplest plans and
                    # would have put "accrues 1.25 days, when Full-time Hong
                    # Kong employees" into a business user's summary.
                    condition=field_value(row, "Accrual_Condition", "Condition_Rule"),
                    calculation=field_value(
                        row, "Calculated_Field", "Accrual_Calculation", "Calculation"
                    ),
                    effective_date=field_value(row, "Effective_Date"),
                )
            )

        eligibility_name = field_value(
            row, "Eligibility_Rule", "Eligibility", "Eligibility_Criteria"
        )
        if eligibility_name and not any(
            e.name == eligibility_name for e in plan.eligibility
        ):
            plan.eligibility.append(
                EligibilityRule(
                    name=eligibility_name,
                    criteria=field_value(
                        row, "Eligibility_Criteria", "Criteria", "Eligibility_Rule"
                    ),
                    references=[
                        v
                        for v in (
                            field_value(row, "Worker_Type", "Employee_Type"),
                            field_value(row, "Location", "Country"),
                            field_value(row, "Job_Family"),
                        )
                        if v
                    ],
                )
            )

    return list(plans.values())


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _slug(value: str) -> str:
    """Re-exported from the connector so both produce identical keys.

    Defining a second slug here was a live bug waiting to happen: this module
    builds plan ids and the connector builds the relation targets that point at
    them, and a hyphen-versus-underscore difference between the two would have
    left every `DEPENDS_ON` edge dangling with nothing failing.
    """
    from api.connectors.workday.connector import _slug as connector_slug

    return connector_slug(value)
