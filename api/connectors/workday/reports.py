"""
The Workday Discovery Report Pack.

Workday exposes no API for business process definitions, condition rules,
security policies or custom field definitions. Its reporting layer does. So the
deep configuration this product needs arrives through custom reports the
customer builds in their own tenant — which means the product has to be
extremely precise about *which* reports, built on *which* data source, with
*which* fields.

This module is that specification, held as data rather than prose so three
things can be driven from one definition:

  - the setup checklist the UI renders,
  - the capability probe that reports which reports exist yet,
  - the extractor that reads each one.

Every report here is **optional**. A tenant with none of them still yields a
useful graph from SOAP — organisations, job profiles, locations, integration
systems. Each report that appears adds a layer the APIs cannot reach. Making
them mandatory would mean a customer cannot connect Workday at all until an
analyst has spent a day in the report builder, and a connector that cannot be
tried is a connector that does not get adopted.

Field names are what the pack asks the customer to name their columns. The
extractor accepts several spellings per field (see `raas.field_value`), because
report authors rename things and a rigid match would fail on a report that is
otherwise correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ReportField:
    name: str
    description: str
    required: bool = True


@dataclass(slots=True)
class ReportSpec:
    """One report in the pack."""

    id: str
    #: Default report name. The customer may rename it; the connection config
    #: carries the actual name.
    report_name: str
    title: str
    #: What this unlocks, in the product's terms rather than Workday's.
    unlocks: str
    #: The Workday data source the report must be built on. Getting this wrong
    #: is the single most common setup failure, so it is stated exactly.
    data_source: str
    #: Business object the data source returns, where it clarifies the choice.
    business_object: str
    fields: list[ReportField]
    #: What Meridian creates in the graph from each row.
    produces: str
    #: Why this cannot come from an API — shown in the UI so the customer
    #: understands the work is necessary rather than arbitrary.
    why_report: str
    #: Ordering for the setup checklist; lower is more valuable.
    priority: int = 50
    notes: list[str] = field(default_factory=list)


#: Every report in the pack, most valuable first.
REPORT_PACK: list[ReportSpec] = [
    ReportSpec(
        id="bp_definitions",
        report_name="CFG_BP_Definitions",
        title="Business process definitions",
        unlocks="Which processes exist, and which organisations each one governs.",
        data_source="Business Process Definitions (or 'All Business Processes')",
        business_object="Business Process Definition",
        priority=10,
        fields=[
            ReportField("Business_Process_Type", "The process type, e.g. 'Change Job'."),
            ReportField(
                "Business_Process_Definition",
                "The specific definition, e.g. 'Change Job — Malaysia Employees'.",
            ),
            ReportField(
                "Definition_ID", "Reference ID, used to link steps to this definition."
            ),
            ReportField("Effective_Date", "When this version took effect.", required=False),
            ReportField(
                "Organization",
                "The organisation this definition is scoped to, if any.",
                required=False,
            ),
            ReportField("Status", "Active or inactive.", required=False),
        ],
        produces="A business_process node per definition.",
        why_report=(
            "No Workday API returns business process definitions. All eight "
            "Business_Process SOAP operations act on running instances — approve, "
            "deny, cancel — and none reads the configuration."
        ),
        notes=[
            "Without this report Meridian can see that processes ran, but not what "
            "they were configured to do.",
        ],
    ),
    ReportSpec(
        id="bp_steps",
        report_name="CFG_BP_Steps",
        title="Business process steps",
        unlocks=(
            "The approval chain: step order, step type, who approves, and the "
            "conditions that route work."
        ),
        data_source="Business Process Steps (filtered to your in-scope definitions)",
        business_object="Business Process Step",
        priority=20,
        fields=[
            ReportField("Definition_ID", "Links the step to its definition."),
            ReportField("Step_Order", "Position in the sequence."),
            ReportField("Step_Type", "Approval, Action, Review, To Do, Integration…"),
            ReportField("Step_Name", "Label shown in Workday.", required=False),
            ReportField(
                "Group", "Security group or role that performs the step.", required=False
            ),
            ReportField(
                "Condition_Rule",
                "The rule that decides whether this step runs.",
                required=False,
            ),
            ReportField("Optional", "Whether the step can be skipped.", required=False),
            ReportField(
                "Subprocess", "Named subprocess this step invokes.", required=False
            ),
        ],
        produces=(
            "A config_object node per step, HAS_STEP from its definition, plus "
            "NEXT_STEP edges in order and APPROVED_BY to the security group."
        ),
        why_report=(
            "Step configuration is the highest-value data in a Workday tenant for "
            "change analysis, and it exists nowhere in the API surface."
        ),
        notes=[
            "Filter to the processes you actually govern. An unfiltered export "
            "across every delivered process is large and mostly noise.",
        ],
    ),
    ReportSpec(
        id="condition_rules",
        report_name="CFG_Condition_Rules",
        title="Condition rules",
        unlocks="The logic behind conditional routing, as testable expressions.",
        data_source="Condition Rules",
        business_object="Condition Rule",
        priority=30,
        fields=[
            ReportField("Condition_Rule", "Rule name."),
            ReportField("Rule_ID", "Reference ID.", required=False),
            ReportField("Description", "What the rule decides.", required=False),
            ReportField(
                "Expression", "The condition itself, if exposed.", required=False
            ),
            ReportField("Business_Object", "What it evaluates against.", required=False),
        ],
        produces="A policy node per rule, CONTROLLED_BY_RULE from the steps using it.",
        why_report="There is no Get_Condition_Rules operation in any Workday service.",
    ),
    ReportSpec(
        id="custom_fields",
        report_name="CFG_Custom_Fields",
        title="Custom and calculated fields",
        unlocks=(
            "Which fields are bespoke to this tenant, and what they are derived "
            "from — the usual blast radius of a data change."
        ),
        data_source="Custom Fields / Calculated Fields",
        business_object="Custom Field",
        priority=40,
        fields=[
            ReportField("Field_Name", "The field as it appears in Workday."),
            ReportField("Field_ID", "Reference ID.", required=False),
            ReportField("Business_Object", "The object it hangs off."),
            ReportField("Field_Type", "Data type.", required=False),
            ReportField(
                "Source_Fields",
                "Fields a calculated field derives from.",
                required=False,
            ),
            ReportField("Description", "What it is for.", required=False),
        ],
        produces=(
            "A data_entity node per field, HAS_FIELD from its business object, and "
            "DERIVED_FROM_FIELD for calculated fields."
        ),
        why_report="No API returns custom or calculated field definitions.",
    ),
    ReportSpec(
        id="security_groups",
        report_name="CFG_Security_Groups",
        title="Security groups and domain access",
        unlocks="Who can see and change what — the segregation-of-duties picture.",
        data_source="Security Groups (or Domain Security Policies)",
        business_object="Security Group",
        priority=50,
        fields=[
            ReportField("Security_Group", "Group name."),
            ReportField("Group_Type", "Role-based, user-based, and so on.", required=False),
            ReportField("Domain", "Security domain it grants against.", required=False),
            ReportField("Access_Level", "View, modify, or both.", required=False),
            ReportField("Members", "Assigned users or roles.", required=False),
        ],
        produces="A policy node per group, SECURED_BY from the objects it governs.",
        why_report=(
            "Group membership is partly reachable through SOAP, but the domain "
            "policy grants — the part that answers 'who can change this' — are not."
        ),
    ),
    ReportSpec(
        id="custom_reports",
        report_name="CFG_Custom_Report_Inventory",
        title="Custom report inventory",
        unlocks=(
            "Which reports exist and what they read, so a field change can be "
            "traced to the reporting it silently breaks."
        ),
        data_source="Custom Reports",
        business_object="Custom Report",
        priority=60,
        fields=[
            ReportField("Report_Name", "Report name."),
            ReportField("Report_Type", "Advanced, Simple, Matrix…", required=False),
            ReportField("Data_Source", "What it reads.", required=False),
            ReportField("Owner", "Who maintains it.", required=False),
            ReportField(
                "Web_Service_Enabled",
                "Whether it is exposed as RaaS — these are integration surface.",
                required=False,
            ),
        ],
        produces="A report node per report, READS_OBJECT to its data source.",
        why_report=(
            "Reports are the most commonly forgotten dependency in a Workday "
            "change, and no API enumerates them."
        ),
    ),
    ReportSpec(
        id="bp_runtime",
        report_name="CFG_BP_Runtime_Events",
        title="Business process run history",
        unlocks=(
            "What processes actually did, so configured routing can be compared "
            "with observed routing and undocumented steps surface."
        ),
        data_source="Business Process Transaction Log (or 'Business Process Events')",
        business_object="Business Process Transaction",
        priority=70,
        fields=[
            ReportField(
                "Business_Process_Instance_ID",
                "Groups the rows of one process run together.",
            ),
            ReportField("Business_Process_Type", "Which process ran, e.g. 'Change Job'."),
            ReportField("Step_Order", "Position of this step within the run."),
            ReportField("Step_Name", "The step as it executed."),
            ReportField("Step_Status", "Completed, denied, sent back…", required=False),
            ReportField("Overall_Status", "Status of the whole run.", required=False),
            ReportField(
                "Initiated_DateTime", "When the run started.", required=False
            ),
            ReportField(
                "Completed_DateTime", "When the step completed.", required=False
            ),
            ReportField("Due_Date", "SLA due date, where set.", required=False),
            ReportField(
                "Completed_By",
                "Who actioned the step. Pseudonymised on ingest by default — "
                "Meridian records that the same person acted, never who.",
                required=False,
            ),
        ],
        produces=(
            "A business_process_run node per instance, with ordered "
            "HAS_OBSERVED_STEP edges and a drift flag on steps that appear in "
            "no definition."
        ),
        why_report=(
            "Workday's runtime APIs act on a single named instance, so there is "
            "no way to ask 'what ran last month'. The transaction log is the only "
            "surface that answers it in bulk."
        ),
        notes=[
            "Filter to a recent window — 30 to 90 days is usually enough to show "
            "drift, and an unbounded log is very large.",
            "This report carries worker names. Meridian pseudonymises them on "
            "ingest, but restrict the report to the processes you actually "
            "govern rather than exporting everything.",
        ],
    ),
    ReportSpec(
        id="time_off_plans",
        report_name="CFG_Time_Off_Plans",
        title="Time off plan configuration",
        unlocks=(
            "How much leave each plan grants, who it applies to, and what "
            "carries over — the configuration behind every leave policy."
        ),
        data_source="Time Off Plans (or 'Absence Plans')",
        business_object="Time Off Plan",
        priority=30,
        fields=[
            ReportField("Time_Off_Plan_ID", "Reference ID, used to link accruals."),
            ReportField("Time_Off_Plan", "Plan name, e.g. 'HKG Annual Leave'."),
            ReportField(
                "Unit_of_Time",
                "Days or Hours. A plan's numbers mean nothing without it.",
            ),
            ReportField("Plan_Type", "Time off type this plan belongs to.", required=False),
            ReportField(
                "Balance_Period", "Calendar year, hire date anniversary…", required=False
            ),
            ReportField(
                "Carryover_Limit", "How much unused balance carries.", required=False
            ),
            ReportField(
                "Carryover_Expiration",
                "How long carried balance survives.",
                required=False,
            ),
            ReportField("Maximum_Balance", "Cap on total balance.", required=False),
            ReportField("Country", "Where the plan applies.", required=False),
            ReportField("Inactive", "Whether the plan is retired.", required=False),
        ],
        produces="A config_object node per plan, with its accruals and eligibility.",
        why_report=(
            "The Absence_Management SOAP service returns plan *names* but not the "
            "accrual amounts, carryover limits or eligibility criteria behind "
            "them. Those are only reachable by report or on screen."
        ),
        notes=[
            "Configuration only. Do not add Worker, Balance or absence date "
            "columns — Meridian refuses reports carrying per-worker absence "
            "data, which is medical-adjacent and out of scope.",
        ],
    ),
    ReportSpec(
        id="time_off_accruals",
        report_name="CFG_Time_Off_Accruals",
        title="Time off accruals and eligibility",
        unlocks=(
            "The rate leave is earned at, the conditions that change it, and "
            "the rule deciding who qualifies."
        ),
        data_source="Accruals (filtered to your in-scope plans)",
        business_object="Accrual",
        priority=35,
        fields=[
            ReportField("Time_Off_Plan_ID", "Links the accrual to its plan."),
            ReportField("Accrual", "Accrual rule name."),
            ReportField(
                "Accrual_Amount",
                "How much is earned. Blank when a calculated field decides it.",
                required=False,
            ),
            ReportField(
                "Accrual_Frequency", "Monthly, annually, per period…", required=False
            ),
            ReportField(
                "Calculated_Field",
                "The calculation driving the amount, where there is one. This is "
                "what makes statutory plans complex.",
                required=False,
            ),
            ReportField(
                "Accrual_Condition",
                "Condition rule gating this accrual — service bands, for example.",
                required=False,
            ),
            ReportField(
                "Eligibility_Rule", "Who qualifies for the plan.", required=False
            ),
            ReportField(
                "Worker_Type", "Employee type the rule keys off.", required=False
            ),
            ReportField("Effective_Date", "When this version took effect.", required=False),
        ],
        produces=(
            "Accrual and eligibility detail attached to each plan, plus "
            "GOVERNED_BY edges to the condition rules and calculated fields."
        ),
        why_report=(
            "Accrual amounts and eligibility criteria are configuration, and no "
            "Workday API returns them."
        ),
        notes=[
            "A plan with several accruals produces several rows; Meridian groups "
            "them by plan.",
        ],
    ),
]

REPORTS_BY_ID: dict[str, ReportSpec] = {spec.id: spec for spec in REPORT_PACK}


#: How to build any of these reports, in Workday.
#:
#: Identical for all six, so it is stated once rather than repeated per report.
#: This exists because the column list alone assumes the reader is already
#: sitting in the report builder and knows how they got there — someone with no
#: Workday background needs the task name, the report type, and the two
#: settings whose absence produces a failure that looks like a Meridian bug.
#:
#: Each entry names the symptom of skipping it. "Enable As Web Service" is the
#: sharpest: without it the report works perfectly inside Workday and is simply
#: invisible over RaaS, so there is nothing to notice until extraction runs.
REPORT_BUILD_STEPS: list[dict] = [
    {
        "id": "create",
        "task": "Create Custom Report",
        "title": "Start a new custom report",
        "detail": (
            "Search this task in Workday. Give the report the name shown below "
            "for whichever report you are building."
        ),
        "symptom": None,
    },
    {
        "id": "advanced",
        "task": None,
        "title": "Set Report Type to Advanced",
        "detail": (
            "Not Simple. Only Advanced reports can be exposed as a web service, "
            "and the type cannot be changed after the report is created."
        ),
        "symptom": (
            "A Simple report offers no 'Enable As Web Service' option later, and "
            "has to be rebuilt from scratch."
        ),
    },
    {
        "id": "web_service",
        "task": None,
        "title": "Tick 'Enable As Web Service'",
        "detail": (
            "On the report's Advanced tab. This is what makes the report "
            "readable over RaaS, which is how Meridian reads it."
        ),
        "symptom": (
            "Without it the report works perfectly inside Workday and is "
            "invisible to Meridian — the most commonly missed setting here."
        ),
        "critical": True,
    },
    {
        "id": "share",
        "task": "Share",
        "title": "Share it with the integration security group",
        "detail": (
            "On the report's Share tab, share with the security group created in "
            "step 2 — not with individual users."
        ),
        "symptom": (
            "An unshared report returns a permission error rather than empty "
            "data, which reads as bad credentials."
        ),
    },
]


def setup_checklist() -> list[dict]:
    """The report pack as the UI renders it."""
    return [
        {
            "id": spec.id,
            "reportName": spec.report_name,
            "title": spec.title,
            "unlocks": spec.unlocks,
            "dataSource": spec.data_source,
            "businessObject": spec.business_object,
            "whyReport": spec.why_report,
            "produces": spec.produces,
            "priority": spec.priority,
            "notes": spec.notes,
            "fields": [
                {
                    "name": f.name,
                    "description": f.description,
                    "required": f.required,
                }
                for f in spec.fields
            ],
        }
        for spec in sorted(REPORT_PACK, key=lambda s: s.priority)
    ]


#: Tenant setup steps, in the order an administrator performs them.
#:
#: Task names are exactly as they appear in Workday's search box. A guide that
#: paraphrases them ("create an integration user") forces the admin to guess
#: which of several similar tasks was meant, and guessing wrong here creates an
#: account that looks right and cannot authenticate.
TENANT_SETUP_STEPS: list[dict] = [
    {
        "id": "isu",
        "short": "Account",
        "task": "Create Integration System User",
        "title": "Create the integration account",
        "detail": (
            "Set Session Timeout to 0 so the session never expires mid-extraction, "
            "and tick 'Do Not Allow UI Sessions'. Exempt it from password expiry — "
            "an expired password on an integration account fails silently at 2am."
        ),
        "why": "Meridian acts as this user. Everything it reads is bounded by what this account can see.",
    },
    {
        "id": "group",
        "short": "Group",
        "task": "Create Security Group",
        "title": "Create an unconstrained integration security group",
        "detail": (
            "Type: Integration System Security Group (Unconstrained). Add the ISU "
            "as a member. Constrained groups limit visibility by organisation, "
            "which produces a partial graph that looks complete."
        ),
        "why": "Permissions are granted to the group, not to the user.",
    },
    {
        "id": "domains",
        "short": "Domains",
        "task": "Maintain Permissions for Security Group",
        "title": "Grant read-only domain access",
        "detail": (
            "Grant Get/View — never Put or Modify. Meridian never writes to "
            "Workday. Suggested domains: Business Process Administration, "
            "Integration Build, Integration Event, Organization Information, "
            "Job Information, Worker Data: Public Worker Reports, "
            "Custom Report Creation, and Absence (Time Off / Leave of "
            "Absence) if leave configuration is in scope."
        ),
        "why": "A read-only connector that holds write access is an audit finding waiting to happen.",
    },
    {
        "id": "activate",
        "short": "Activate",
        "task": "Activate Pending Security Policy Changes",
        "title": "Activate the permission changes",
        "detail": (
            "Permissions do nothing until this is run. It is the most commonly "
            "missed step and produces 403 errors that look like wrong credentials."
        ),
        "why": "Workday stages security changes; they take effect only on activation.",
        "critical": True,
    },
    {
        "id": "apiclient",
        "short": "API client",
        "task": "Register API Client for Integrations",
        "title": "Register the API client",
        "detail": (
            "Use 'for Integrations', not plain 'Register API Client' — they are "
            "different tasks and only this one supports non-expiring refresh "
            "tokens. Tick 'Non-Expiring Refresh Tokens'. Include the Integration "
            "functional area in scope. Copy the Client ID and Client Secret now; "
            "the secret is shown once."
        ),
        "why": "This is what lets Meridian authenticate without storing a password.",
    },
    {
        "id": "refresh",
        "short": "Token",
        "task": "Manage Refresh Tokens for Integrations",
        "title": "Generate a refresh token for the ISU",
        "detail": (
            "Select the Integration System User created in step 1 and generate the "
            "token. It is displayed once."
        ),
        "why": "The refresh token binds the API client to the integration user.",
    },
    {
        "id": "endpoint",
        "short": "Endpoint",
        "task": "View API Clients",
        "title": "Copy the token endpoint",
        "detail": (
            "Copy the Token Endpoint exactly as shown. Do not assemble it from the "
            "tenant name — Workday hosts differ by pod (wd2-impl-services1, "
            "wd5-services1, workday.com vs myworkday.com) and a constructed URL "
            "usually resolves to a real host that rejects the request."
        ),
        "why": "Meridian needs the exact endpoint; there is no reliable way to derive it.",
    },
    {
        "id": "reports",
        "short": "Reports",
        "task": "Create Custom Report",
        "title": "Build the discovery reports (optional, high value)",
        # Deliberately brief. The 'Discovery reports' section directly below
        # gives the build procedure as numbered steps and the exact columns per
        # report; repeating it here as prose makes the reader parse the same
        # requirements twice and get them from neither.
        "detail": (
            "These custom reports reach the business process configuration that "
            "no Workday API returns. See 'Discovery reports' below for how to "
            "build them and exactly which columns each one needs. You can "
            "connect without them and add them later."
        ),
        "why": (
            "Without these, Meridian sees organisational structure and integrations "
            "but not the approval logic — which is usually the thing a change "
            "actually touches."
        ),
        "optional": True,
    },
    {
        "id": "browser_session",
        "short": "Screens",
        "task": None,
        "title": "Capture a browser session (optional)",
        "detail": (
            "Some configuration exists only on Workday screens: field validation "
            "messages, conditional visibility, and the picklist values a field "
            "actually offers. To read those, an administrator signs in to "
            "Workday once in a browser Meridian opens, and Meridian keeps the "
            "resulting session."
        ),
        "why": (
            "Meridian never receives the password and never signs in on its own, "
            "so multi-factor authentication is satisfied by the person rather "
            "than worked around. The session expires like any other, at which "
            "point discovery stops until someone repeats this — deliberately, "
            "so it never becomes a standing unattended grant to your tenant. "
            "Replay can only navigate and read; it cannot submit, approve or "
            "save anything."
        ),
        "optional": True,
    },
]
