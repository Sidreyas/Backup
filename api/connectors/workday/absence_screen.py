"""
Parsing a Time Off Plan *screen* into a plan.

Written against a real tenant rather than from documentation, and several
things it does exist because the real screen does something a reasonable
person would not predict:

**Tab panels are cumulative, not isolated.** Clicking "Eligibility" leaves the
Balance, Accruals and Time Offs grids in the DOM as well, so the fifth tab
contains five grids and the first contains one. Reading "the grids on the
Eligibility tab" therefore returns mostly other tabs' data. Grids are
identified by their *headers* instead of by which tab they were captured on.

**Every value is effective-dated.** The first column of every grid is
"Effective-Dated Snapshot", and rows after the first in a group have it blank —
they are continuations of the same snapshot, not new records. Treating each row
as independent produces phantom configuration.

**The accrual amount is not on this screen.** The plan lists which accruals
*add to balance* by name ("GBR Statutory Holiday (Days) Accrual") but the
amount and frequency live on the accrual object itself, one navigation away.
This is the single most important finding for the summary: a plan screen alone
cannot say how much leave someone gets, and any summary claiming otherwise from
this source is inventing it.

**Eligibility is prose, not references.** The real criteria read "In Salaried
Compensation Plan / Worker's Company = UK as of PE Date / Worker Employee Type
is Regular or Fixed Term Contract as of PE Date" — newline-separated conditions
in Workday's own phrasing. Kept verbatim: they are already the layman statement
the client asked for, and re-deriving them from structure would be strictly
worse prose with a risk of being wrong.
"""

from __future__ import annotations

from typing import Any

from api.connectors.workday.absence import (
    AccrualRule,
    Calculation,
    ConditionalBranch,
    EligibilityRule,
    EntitlementBand,
    TimeOffPlan,
)

#: Workday appends its sort/filter affordance to header text.
_HEADER_NOISE = ("Sort and filter column", "Filter column")

#: Grids are recognised by a header only they have. Matching on tab position
#: would break the moment Workday reorders tabs, which it does between releases.
_BALANCE_MARKER = "Carryover Limit"
_ACCRUAL_FREQUENCY_MARKER = "Accrual Frequency Method"
_ADDS_TO_BALANCE_MARKER = "Adds to Balance"
_SUBTRACTS_MARKER = "Subtracts from Balance"
_ELIGIBILITY_MARKER = "Worker Eligibility"


def clean_header(header: str) -> str:
    text = str(header or "").replace("\n", " ")
    for noise in _HEADER_NOISE:
        text = text.replace(noise, "")
    return " ".join(text.split())


def _rows_as_dicts(grid: dict[str, Any]) -> list[dict[str, str]]:
    """Grid rows keyed by cleaned header.

    Rows shorter than the header list are normal — Workday omits trailing empty
    cells — so missing columns resolve to "" rather than raising.
    """
    headers = [clean_header(h) for h in grid.get("headers", [])]
    out: list[dict[str, str]] = []
    for row in grid.get("rows", []):
        if not any(str(c).strip() for c in row):
            continue
        out.append(
            {
                headers[i]: str(cell).strip()
                for i, cell in enumerate(row)
                if i < len(headers) and headers[i]
            }
        )
    return out


def _find_grid(grids: list[dict], marker: str) -> dict | None:
    """The grid carrying a distinguishing column, searched most-recent-first.

    Later tabs accumulate earlier tabs' grids, so the *last* occurrence is the
    most completely rendered one.
    """
    for grid in reversed(grids):
        headers = {clean_header(h) for h in grid.get("headers", [])}
        if marker in headers:
            return grid
    return None


def all_grids(capture: dict[str, Any]) -> list[dict]:
    """Every grid across every tab, deduplicated by header signature."""
    seen: set[tuple[str, ...]] = set()
    out: list[dict] = []
    for detail in (capture.get("tabs_detail") or {}).values():
        for grid in detail.get("grids", []):
            signature = tuple(clean_header(h) for h in grid.get("headers", []))
            if not signature or signature in seen:
                continue
            seen.add(signature)
            out.append(grid)
    return out


def parse_plan_screen(
    capture: dict[str, Any],
    *,
    plan_id: str,
    name: str,
    unit_of_time: str = "",
    balance_period: str = "",
) -> TimeOffPlan:
    """Build a plan from one captured `View Time Off Plan` screen.

    `plan_id`, `name` and the header fields are passed in rather than scraped:
    they render as label/value pairs outside any grid, and reading them from
    loose DOM text is far more fragile than reading a grid. The connector takes
    them from SOAP or the report, which is where they are reliable.
    """
    grids = all_grids(capture)

    plan = TimeOffPlan(
        plan_id=plan_id,
        name=name,
        unit_of_time=unit_of_time,
        balance_period=balance_period,
        via="screen",
    )

    balance = _find_grid(grids, _BALANCE_MARKER)
    if balance:
        rows = _rows_as_dicts(balance)
        if rows:
            row = rows[0]
            plan.carryover_limit = row.get("Carryover Limit", "")
            expiry_amount = row.get("Amount of Time Before Carryover Expiration", "")
            expiry_unit = row.get("Carryover Expires Unit of Time", "")
            plan.carryover_expiry = (
                f"{expiry_amount} {expiry_unit}".strip()
                if expiry_amount or expiry_unit
                else ""
            )

    limits = _find_grid(grids, _ACCRUAL_FREQUENCY_MARKER)
    frequency = ""
    if limits:
        rows = _rows_as_dicts(limits)
        if rows:
            row = rows[0]
            plan.maximum_balance = row.get("Time Off Plan Balance Upper Limit", "")
            plan.minimum_increment = row.get("Daily Quantity Default", "")
            recurs_every = row.get("Accrual Recurs Every", "")
            recurs_unit = row.get("Accrual Recurs Unit of Time", "")
            frequency = (
                f"{recurs_every} {recurs_unit}".strip()
                if recurs_every or recurs_unit
                else row.get("Accrual Frequency Method", "")
            )

    adds = _find_grid(grids, _ADDS_TO_BALANCE_MARKER)
    if adds:
        for row in _rows_as_dicts(adds):
            accrual_name = row.get("Adds to Balance", "")
            if not accrual_name:
                continue
            plan.accruals.append(
                AccrualRule(
                    name=accrual_name,
                    # Deliberately empty. The screen names the accrual but not
                    # its amount — that is on the accrual object itself. A
                    # value invented here would be a fabricated leave
                    # entitlement, which `summary_gaps` reports as unknown.
                    amount="",
                    unit=unit_of_time,
                    frequency=frequency,
                    # Workday flags these per accrual, and they are the reason
                    # a plan is complex: an override means this accrual does
                    # not follow the plan's own rules.
                    condition=_override_note(row),
                )
            )

    eligibility = _find_grid(grids, _ELIGIBILITY_MARKER)
    if eligibility:
        for row in _rows_as_dicts(eligibility):
            criteria = row.get("Worker Eligibility", "")
            if not criteria:
                continue
            worker_type = row.get("Enabled for Worker Type Plan Eligibility", "")
            country = row.get("Country / Country Region", "")
            plan.eligibility.append(
                EligibilityRule(
                    # Workday returns the conditions newline-separated; joined
                    # with a separator that survives being read aloud.
                    name=_first_line(criteria),
                    criteria=" and ".join(
                        line.strip() for line in criteria.splitlines() if line.strip()
                    ),
                    references=[v for v in (worker_type, country) if v],
                )
            )
            if country and not plan.country:
                plan.country = country

    return plan


def parse_accrual_screen(capture: dict[str, Any]) -> dict[str, str]:
    """Read one `View Accrual` screen.

    The hop the plan screen cannot make. Returns the calculation driving the
    amount and the schedule it runs on.

    A literal is distinguished from a calculated field here, and the
    distinction is not cosmetic: "0" in the Calculation column means the
    accrual grants nothing automatically (GBR Vacation Buy works this way —
    the balance comes from a purchase election, not an accrual), whereas a
    named calculation means the amount exists but lives one hop further on.
    Reporting both as "unknown" would hide a plan that genuinely grants zero.
    """
    grids = capture.get("grids") or []
    grid = _find_grid(grids, "Calculation")
    if not grid:
        return {}

    rows = _rows_as_dicts(grid)
    if not rows:
        return {}

    row = rows[0]
    calculation = row.get("Calculation", "").strip()

    # Scheduling is the last column and Workday omits trailing empty cells, so
    # a row can simply be too short to contain it — and the column's position
    # differs between plans (GBR carries a "Time Calculation Tags" column that
    # HKG does not). An absent schedule is therefore "not captured", never
    # "no schedule": the value may well exist on screen and just not be in
    # this row's cells. Reporting it as empty is the honest outcome; inventing
    # a default would state a frequency nobody configured.
    schedule = row.get("Scheduling", "").strip()

    # Later rows carry additional schedule variants with the other columns
    # blank — Workday's continuation-row pattern. Real examples: "Front-Loaded"
    # and "Worker Hired Mid-Period" on the GBR base accrual.
    variants = [
        r.get("Scheduling", "").strip()
        for r in rows[1:]
        if r.get("Scheduling", "").strip()
    ]

    return {
        "calculation": calculation,
        "isLiteral": _is_number(calculation),
        "schedule": schedule.removeprefix("Scheduling:").strip(),
        "scheduleVariants": variants,
        "priority": row.get("Priority", "").strip(),
        "frontLoaded": row.get("Front-Loaded", "").strip(),
        "allowInput": row.get("Allow Input", "").strip(),
        "rounding": row.get("Rounding", "").strip(),
    }


def parse_calculation(entry: dict[str, Any]) -> Calculation | None:
    """Resolve one calculated field from a `View …Calculation` capture.

    Handles both shapes the client's plans use. A lookup resolves to bands of
    threshold → value; a conditional resolves to ordered condition → result
    branches. Anything else keeps its name and reports itself unresolved,
    which is what stops the summary implying a rule was understood when only
    its title was read.
    """
    name = str(entry.get("calculation") or "").strip()
    if not name:
        return None

    kind = str(entry.get("calculationType") or "").strip()
    calculation = Calculation(
        name=name,
        kind=kind,
        table_name=str(entry.get("lookupTable") or "").strip(),
        criteria=str(entry.get("searchCriteria") or "").strip(),
    )

    for grid in entry.get("tableGrids") or []:
        rows = _rows_as_dicts(grid)
        headers = {clean_header(h) for h in grid.get("headers", [])}
        if "Search Value" not in headers:
            continue
        calculation.bands = [
            EntitlementBand(
                search=row.get("Search Value", ""), result=row.get("Return Value", "")
            )
            for row in rows
            if row.get("Search Value") and row.get("Return Value")
        ]

    for grid in entry.get("calculationGrids") or []:
        rows = _rows_as_dicts(grid)
        headers = {clean_header(h) for h in grid.get("headers", [])}
        if "Condition" not in headers or "Result" not in headers:
            continue
        calculation.branches = [
            ConditionalBranch(
                order=row.get("Order", ""),
                condition=row.get("Condition", ""),
                result=row.get("Result", ""),
            )
            for row in rows
            if row.get("Condition") or row.get("Result")
        ]

    return calculation


def attach_calculations(
    plan: TimeOffPlan, lookup_entries: list[dict[str, Any]]
) -> TimeOffPlan:
    """Fold resolved calculations onto a plan's accruals, matched by name."""
    by_accrual = {
        str(entry.get("accrual", "")).strip(): entry
        for entry in lookup_entries
        if entry.get("accrual")
    }

    for accrual in plan.accruals:
        entry = by_accrual.get(accrual.name)
        if not entry:
            continue
        resolved = parse_calculation(entry)
        if resolved is None:
            continue
        accrual.resolved = resolved
        # A literal was already promoted to `amount` by `attach_accrual_detail`.
        # Writing it back as a calculation would undo that and produce
        # "0 Days (from '0')" — the same fact stated twice, once as nonsense.
        if not accrual.calculation and resolved.name and not _is_number(resolved.name):
            accrual.calculation = resolved.name

    return plan


def attach_accrual_detail(
    plan: TimeOffPlan, accrual_captures: list[dict[str, Any]]
) -> TimeOffPlan:
    """Fold `View Accrual` reads back onto the plan's accruals.

    Matched by name, which is the only key both screens share — the plan lists
    "GBR Vacation Buy (Days)" and the accrual screen is titled the same. An
    unmatched capture is ignored rather than appended: a plan's accruals are
    defined by the plan, and inventing one from a stray capture would assert
    configuration that does not exist.
    """
    by_name = {
        str(capture.get("name", "")).strip(): capture
        for capture in accrual_captures
        if capture.get("name")
    }

    for accrual in plan.accruals:
        capture = by_name.get(accrual.name)
        if not capture:
            continue
        detail = parse_accrual_screen(capture)
        if not detail:
            continue

        if detail.get("isLiteral"):
            # A literal amount is the entitlement itself.
            accrual.amount = detail["calculation"]
            accrual.calculation = ""
        else:
            accrual.calculation = detail.get("calculation", "")

        # The accrual's own schedule *replaces* the plan-level frequency
        # method rather than filling in behind it. The plan grid's "Accrual
        # Frequency Method" is a coarse plan-wide setting ("Start of Period");
        # the accrual screen carries the actual schedule ("Annual - 1st Period
        # of Calendar Year (based on Period End Date) or Mid-Period Hire").
        # Preferring the plan-level value made every accrual read "Start of
        # Period", which is true of the plan and says nothing about when
        # anyone actually accrues.
        schedule = detail.get("schedule") or ""
        if schedule:
            accrual.frequency = schedule

    return plan


def _is_number(value: str) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _override_note(row: dict[str, str]) -> str:
    """Which of an accrual's overrides are active, as readable text.

    "Eligibility Override Exists = Yes" means this accrual applies to a
    different population than the plan does — exactly the kind of detail a
    summary must not omit, because it makes the plan's headline eligibility
    wrong for that accrual.
    """
    active = [
        label
        for column, label in (
            ("Accrual Frequency Override Exists", "a different accrual frequency"),
            ("Eligibility Override Exists", "different eligibility"),
            ("Upper Limit Override Exists", "a different balance cap"),
            ("Expiration Override Exists", "different expiry"),
        )
        if row.get(column, "").strip().lower() == "yes"
    ]
    if not active:
        return ""
    return "this accrual has " + " and ".join(active)


def _first_line(text: str) -> str:
    for line in str(text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""
