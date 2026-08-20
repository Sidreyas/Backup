"""
The starter recipe pack.

These are the paths phase 2 (discovery) would produce, written out directly
because the screens they target are Workday-delivered and identical in every
tenant — there is nothing to discover about where "Edit Business Process
Definition" lives. Tenant-specific screens still need recording, and
`Recipe.from_dict` exists for exactly that.

Every recipe targets configuration that no API returns *and no report reaches
either*. That is the bar for belonging here. If RaaS can get it, RaaS should:
a report is stable across releases, and a screen is not.

What is left after that bar is applied is small and specific:

  - **Condition rule expressions as displayed.** The condition rules report
    gives the rule's name and return type; the actual expression is rendered on
    screen. "Approve when comp change > 10%" versus the name "Comp_Threshold"
    is the difference between an auditable rule and a label.
  - **Field-level validation and conditional visibility.** Never exposed
    anywhere else, and the most common cause of "the integration worked in
    sandbox and failed in production".
  - **Security policy displays.** The report gives group membership; the screen
    gives which domains a group can actually act in.

Each recipe carries `workday_release` because these are the fragile ones and
dating a failure is the first thing anyone will need.
"""

from __future__ import annotations

from api.connectors.workday.browser import Recipe, Step

#: Recorded against this Workday release. Bump when re-recorded; a mismatch
#: with the customer's tenant is the first thing to suspect on failure.
RECORDED_RELEASE = "2026R1"


RECIPE_PACK: list[Recipe] = [
    Recipe(
        id="bp_definition_screen",
        title="Edit Business Process Definition",
        unlocks=(
            "Step-level configuration as Workday renders it, including the "
            "condition expressions and step types the report cannot express."
        ),
        produces_kind="config_object",
        workday_release=RECORDED_RELEASE,
        steps=[
            Step(action="search_task", target="Edit Business Process Definition"),
            Step(
                action="capture",
                name="Definition",
                selector="[data-automation-id='pageContent']",
            ),
            Step(
                action="capture_grid",
                name="Steps",
                selector="[data-automation-id='gridContainer']",
            ),
        ],
    ),
    Recipe(
        id="condition_rule_expressions",
        title="View Condition Rule",
        unlocks=(
            "The rule expression as displayed. The report gives the rule's name "
            "and return type; only this screen shows what it actually tests."
        ),
        produces_kind="config_object",
        workday_release=RECORDED_RELEASE,
        steps=[
            Step(action="search_task", target="View Condition Rule"),
            Step(
                action="capture",
                name="Condition",
                selector="[data-automation-id='pageContent']",
            ),
            Step(
                action="capture_grid",
                name="Expression",
                selector="[data-automation-id='gridContainer']",
                optional=True,
            ),
        ],
    ),
    Recipe(
        id="domain_security_policy",
        title="View Domain Security Policy",
        unlocks=(
            "Which security groups may view versus modify each domain — the "
            "distinction the security groups report flattens away."
        ),
        produces_kind="config_object",
        workday_release=RECORDED_RELEASE,
        steps=[
            Step(action="search_task", target="View Domain Security Policy"),
            Step(
                action="capture_grid",
                name="Permissions",
                selector="[data-automation-id='gridContainer']",
            ),
        ],
    ),
    Recipe(
        id="custom_object_fields",
        title="View Custom Object",
        unlocks=(
            "Field-level validation messages and conditional visibility rules, "
            "which exist on no API and in no report."
        ),
        produces_kind="data_entity",
        workday_release=RECORDED_RELEASE,
        steps=[
            Step(action="search_task", target="View Custom Object"),
            Step(
                action="capture",
                name="Fields",
                selector="[data-automation-id='pageContent']",
            ),
        ],
    ),
]

#: Absence screens.
#:
#: Separate from the pack above because these are the ones a customer is most
#: likely to need *first* — a leave policy is the configuration business users
#: ask about, and unlike business processes it is largely invisible in the API.
#:
#: `View Time Off Plan` is where the accrual and carryover rules render. The
#: reports reach most of it, but conditional accrual bands and the resolved
#: value of a calculated field appear only here, which is exactly what makes a
#: statutory plan hard to describe from configuration alone.
ABSENCE_RECIPES: list[Recipe] = [
    Recipe(
        id="time_off_plan_screen",
        title="View Time Off Plan",
        unlocks=(
            "Accrual bands, carryover rules and the resolved values of "
            "calculated fields, as Workday renders them."
        ),
        produces_kind="config_object",
        workday_release=RECORDED_RELEASE,
        steps=[
            Step(action="search_task", target="View Time Off Plan"),
            Step(
                action="capture",
                name="Plan",
                selector="[data-automation-id='pageContent']",
            ),
            Step(
                action="capture_grid",
                name="Accruals",
                selector="[data-automation-id='gridContainer']",
                optional=True,
            ),
        ],
    ),
    Recipe(
        id="eligibility_rule_screen",
        title="View Eligibility Rule",
        unlocks=(
            "The criteria deciding who a plan applies to. A summary that omits "
            "this reads as though the plan covers everyone."
        ),
        produces_kind="config_object",
        workday_release=RECORDED_RELEASE,
        steps=[
            Step(action="search_task", target="View Eligibility Rule"),
            Step(
                action="capture",
                name="Eligibility",
                selector="[data-automation-id='pageContent']",
            ),
        ],
    ),
]

RECIPE_PACK.extend(ABSENCE_RECIPES)

RECIPES_BY_ID: dict[str, Recipe] = {r.id: r for r in RECIPE_PACK}


def validate_pack() -> None:
    """Fail fast if a shipped recipe is malformed.

    Called at import time in tests rather than at module import, so a bad
    recipe surfaces as a test failure with a name rather than as an API that
    will not boot.
    """
    for recipe in RECIPE_PACK:
        recipe.validate()
