"""
The connector registry.

Two kinds of entry live here, and the difference is visible to the user rather
than hidden:

  - **Implemented** connectors have a class and can actually extract.
  - **Planned** connectors are declarations only, marked `coming_soon`. They
    appear in the catalogue because a customer evaluating the product needs to
    know what is on the roadmap, and they are flagged because listing an
    unimplemented connector as available would be a lie the first sync exposes.

The transcript lists something like a hundred systems. Shipping a hundred
stub classes that raise `NotImplementedError` would be worse than useless — it
would make the product look finished while every connection failed. So the ones
that exist are real and the rest are honest declarations.

Adding a connector means writing a class against `EnterpriseConnector` and
registering it here. Nothing else in the system needs to change: the ingestion
pipeline, the evidence store and the normaliser all work against the contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from api.connectors.apispec import ApiSpecConnector
from api.connectors.azure_devops import AzureDevOpsConnector
from api.connectors.base import ConnectorScope, EnterpriseConnector
from api.connectors.github import GitHubConnector
from api.connectors.jira import JiraConnector
from api.connectors.workday import WorkdayConnector
from api.connectors.workday.reports import (
    REPORT_BUILD_STEPS,
    TENANT_SETUP_STEPS,
    setup_checklist,
)


@dataclass(slots=True)
class CredentialField:
    """One value the customer must supply to connect.

    Declared as data rather than hardcoded in the UI so the connection form is
    generated from the connector's own requirements. A connector that needs a
    token endpoint and one that needs a base URL should not require a frontend
    change each — and more importantly, the help text belongs next to the code
    that knows why the field exists.
    """

    id: str
    label: str
    #: Where to find this value, in the source system's own terms.
    help: str
    #: 'text' | 'password' | 'textarea' | 'select'
    kind: str = "text"
    required: bool = True
    placeholder: str = ""
    #: For 'select', the allowed values as (id, label, description).
    options: list[tuple[str, str, str]] = field(default_factory=list)
    #: Only collected when the chosen auth method matches one of these.
    auth_methods: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConnectorEntry:
    id: str
    name: str
    vendor: str
    category: str
    kind: str
    description: str
    auth_methods: list[str]
    provides: list[str]
    scopes: list[ConnectorScope] = field(default_factory=list)
    implementation: type[EnterpriseConnector] | None = None
    coming_soon: bool = False
    #: What the connection form must collect. Empty means the connector reads
    #: its credentials from environment variables instead.
    credential_fields: list[CredentialField] = field(default_factory=list)
    #: Work the customer must do in their own system before connecting.
    setup_steps: list[dict] = field(default_factory=list)
    #: Artefacts the customer must build (Workday's report pack).
    required_artifacts: list[dict] = field(default_factory=list)
    #: How to build one of those artefacts, in the source system. Shared by
    #: every artefact, so it is declared once rather than per artefact.
    artifact_build_steps: list[dict] = field(default_factory=list)
    #: Stated plainly on the connector card, because a customer choosing a
    #: connector deserves to know its limits before they invest a day in setup.
    limitations: list[str] = field(default_factory=list)

    @property
    def implemented(self) -> bool:
        return self.implementation is not None


def _from_class(cls: type[EnterpriseConnector], **extra) -> ConnectorEntry:
    return ConnectorEntry(
        id=cls.id,
        name=cls.name,
        vendor=cls.vendor,
        category=cls.category,
        kind=cls.kind,
        description=cls.description,
        auth_methods=list(cls.auth_methods),
        provides=list(cls.provides),
        scopes=list(cls.scopes),
        implementation=cls,
        **extra,
    )


# Workday's connection form. Ordered as the admin gathers the values: identify
# the tenant, choose how to authenticate, then paste what that method needs.
WORKDAY_FIELDS: list[CredentialField] = [
    CredentialField(
        id="host",
        label="Workday host",
        help=(
            "The host from your Workday URL, including https://. Pods differ — "
            "wd2-impl-services1.workday.com for an implementation tenant, "
            "wd5-services1.myworkday.com for production. Copy it; it cannot be "
            "derived from the tenant name."
        ),
        placeholder="https://wd2-impl-services1.workday.com",
    ),
    CredentialField(
        id="tenant",
        label="Tenant name",
        help="The tenant identifier in your Workday URL, e.g. acme_preview.",
        placeholder="acme_preview",
    ),
    CredentialField(
        id="method",
        label="Authentication method",
        kind="select",
        help="Which method your security team has approved.",
        options=[
            (
                "oauth_refresh_token",
                "OAuth 2.0 — refresh token (recommended)",
                "Register API Client for Integrations with 'Non-Expiring Refresh "
                "Tokens'. Available in every tenant.",
            ),
            (
                "oauth_jwt",
                "OAuth 2.0 — JWT bearer",
                "Signs a certificate-based assertion. Use when your security team "
                "will not permit storing a shared secret.",
            ),
            (
                "isu_basic",
                "Integration System User credentials",
                "Username and password over WS-Security. Simplest, and the only "
                "option in some older tenants.",
            ),
        ],
    ),
    CredentialField(
        id="token_endpoint",
        label="Token endpoint",
        help=(
            "Copy exactly from the 'View API Clients' report in Workday. Do not "
            "assemble it from the tenant name — a constructed URL usually resolves "
            "to a real host that rejects the request."
        ),
        placeholder="https://wd2-impl-services1.workday.com/ccx/oauth2/acme_preview/token",
        auth_methods=["oauth_refresh_token", "oauth_jwt"],
    ),
    CredentialField(
        id="client_id",
        label="Client ID",
        help="From 'Register API Client for Integrations'.",
        auth_methods=["oauth_refresh_token", "oauth_jwt"],
    ),
    CredentialField(
        id="client_secret",
        label="Client secret",
        kind="password",
        help=(
            "Shown once when the API client is registered. If it was not captured, "
            "regenerate it — it cannot be read back."
        ),
        auth_methods=["oauth_refresh_token"],
    ),
    CredentialField(
        id="refresh_token",
        label="Refresh token",
        kind="password",
        help=(
            "From 'Manage Refresh Tokens for Integrations', generated against your "
            "Integration System User. Also shown once."
        ),
        auth_methods=["oauth_refresh_token"],
    ),
    CredentialField(
        id="private_key_pem",
        label="Private key (PEM)",
        kind="textarea",
        help=(
            "The private half of the x509 key pair whose public half you registered "
            "with 'Create x509 Public Key'."
        ),
        auth_methods=["oauth_jwt"],
    ),
    CredentialField(
        id="jwt_subject",
        label="Integration System User",
        help="The ISU the assertion acts as.",
        auth_methods=["oauth_jwt"],
    ),
    CredentialField(
        id="username",
        label="Integration System User",
        help=(
            "The ISU account name. Meridian appends @tenant automatically if you "
            "leave it off."
        ),
        placeholder="meridian_isu",
        auth_methods=["isu_basic"],
    ),
    CredentialField(
        id="password",
        label="Password",
        kind="password",
        help="The ISU's password. Exempt the account from password expiry.",
        auth_methods=["isu_basic"],
    ),
    CredentialField(
        id="report_owner",
        label="Report owner",
        required=False,
        help=(
            "The Workday account that owns the discovery reports — usually the ISU. "
            "Leave blank if you have not built the reports yet; everything else "
            "still works."
        ),
        placeholder="meridian_isu",
    ),
    CredentialField(
        id="api_version",
        label="API version",
        required=False,
        help="Pin a Workday web services version. Defaults to v46.2 (2026R1).",
        placeholder="v46.2",
    ),
]

WORKDAY_LIMITATIONS = [
    "Business process definitions and steps are not available through any Workday "
    "API. They require custom reports built in your tenant — Meridian tells you "
    "exactly which ones and what fields each needs.",
    "Condition rules, custom field definitions and domain security policies have "
    "the same limitation and are covered by the same report pack.",
    "Workday publishes no webhook for configuration changes, so drift is detected "
    "by re-extracting and comparing rather than in real time.",
    "The REST and Graph APIs need OAuth. A connection using Integration System "
    "User credentials still reads everything that matters — those two surfaces "
    "describe which objects Workday exposes, not how your tenant is configured.",
    "The Graph API is not enabled in every tenant. Where it is missing Meridian "
    "skips it; nothing else is affected.",
    "Run history shows what processes actually did, which is how undocumented "
    "steps are found. Worker names in it are replaced with a stable pseudonym "
    "before anything is stored, so the graph can show that the same person acted "
    "repeatedly without recording who they are.",
    "Screen discovery reads configuration that exists on no API — validation "
    "messages, conditional visibility, picklist values. It needs an administrator "
    "to sign in to Workday once in a browser; Meridian keeps the resulting "
    "session, never the password, and can only navigate and read.",
]


# Jira's connection form. Atlassian Cloud supports basic auth with an API
# token for server-to-server access; the token acts as the user, so what
# Meridian can read is bounded by that user's Jira permissions rather than by
# any scope selection.
JIRA_FIELDS: list[CredentialField] = [
    CredentialField(
        id="base_url",
        label="Jira site URL",
        help=(
            "Your Atlassian site, including https://. The host from your Jira "
            "URL, without a trailing path."
        ),
        placeholder="https://acme.atlassian.net",
    ),
    CredentialField(
        id="email",
        label="Account email",
        help=(
            "The Atlassian account the token belongs to. Basic auth sends this "
            "with the token, and it must be the same account that created it."
        ),
        placeholder="integrations@acme.com",
    ),
    CredentialField(
        id="api_token",
        label="API token",
        kind="password",
        help=(
            "Created at id.atlassian.com/manage-profile/security/api-tokens. "
            "Shown once — copy it before closing the dialog."
        ),
    ),
    CredentialField(
        id="jql",
        label="Issue filter (JQL)",
        required=False,
        help=(
            "Limits which issues are read. Leave empty to read every issue the "
            "account can see, newest first."
        ),
        placeholder="project = HCM ORDER BY updated DESC",
    ),
]


#: Jira setup. Short, because Atlassian exposes what Meridian needs by API —
#: but step 2 is a genuine decision rather than a formality, so it is stated
#: rather than buried.
JIRA_SETUP_STEPS: list[dict] = [
    {
        "id": "token",
        "short": "API token",
        "task": "Account settings › Security › Create and manage API tokens",
        "title": "Create an API token",
        "detail": (
            "At id.atlassian.com/manage-profile/security/api-tokens. Give it a "
            "name identifying Meridian so it can be revoked without guessing."
        ),
        "why": (
            "Meridian acts as this account. Everything it reads is bounded by "
            "what this account can already see in Jira."
        ),
    },
    {
        "id": "expiry",
        "short": "Expiry",
        "task": None,
        "title": "Note the expiry date",
        "detail": (
            "Atlassian caps API tokens at one year and no longer issues "
            "non-expiring ones. Set a reminder to reissue before it lapses."
        ),
        "why": (
            "An expired token fails every sync silently until someone looks at "
            "the connection. There is no way to opt out of expiry."
        ),
        "critical": True,
    },
    {
        "id": "permissions",
        "short": "Permissions",
        "task": None,
        "title": "Decide how much configuration to expose",
        "detail": (
            "Reading workflows requires the account to hold the 'Administer "
            "Jira' global permission. Without it Meridian still reads projects, "
            "fields, statuses and issue history — it simply cannot see the "
            "workflow rules that govern them."
        ),
        "why": (
            "Jira has no read-only administrator role, so this is a real "
            "trade-off. The connection test reports which of the two you got."
        ),
    },
]


JIRA_LIMITATIONS = [
    "Reading workflow configuration requires the 'Administer Jira' global "
    "permission. Jira offers no read-only administrator role, so a least-"
    "privilege account can read projects, fields, statuses and issues but not "
    "the workflows that govern them.",
    "Workflow conditions, validators and post-functions — the logic attached "
    "to a transition — are not readable. Atlassian restricts that API to "
    "Connect and Forge apps, and even then an app sees only rules it created "
    "itself. Meridian extracts workflow structure, not the rules inside it.",
    "Atlassian caps API tokens at one year and no longer issues non-expiring "
    "ones, so every Jira connection needs reissuing at least annually.",
    "Jira's issue search no longer returns a total count, so a sync reports "
    "progress as issues arrive rather than as a percentage of a known total.",
]


# GitHub's connection form. Fine-grained tokens are the default because a
# classic `repo` scope cannot express read-only access to a private
# repository — it is read *and write*, all or nothing.
GITHUB_FIELDS: list[CredentialField] = [
    CredentialField(
        id="token",
        label="Access token",
        kind="password",
        help=(
            "A fine-grained personal access token. Shown once when created — "
            "copy it before leaving the page."
        ),
    ),
    CredentialField(
        id="org",
        label="Organisation",
        required=False,
        help=(
            "Read every repository in this organisation that the token can "
            "see. Leave empty if you are naming repositories below."
        ),
        placeholder="acme-corp",
    ),
    CredentialField(
        id="repos",
        label="Repositories",
        required=False,
        help=(
            "Comma-separated owner/name pairs. More precise than an "
            "organisation, and the better choice on a large account."
        ),
        placeholder="acme-corp/payroll-api, acme-corp/hcm-web",
    ),
    CredentialField(
        id="api_url",
        label="API URL",
        required=False,
        help=(
            "Only for GitHub Enterprise Server. Leave empty for github.com."
        ),
        placeholder="https://api.github.com",
    ),
]


#: GitHub setup. The permission step is the one that goes wrong: reading a
#: workflow's YAML needs *two* permissions, and granting only the obvious one
#: yields a pipeline with a name and no contents.
GITHUB_SETUP_STEPS: list[dict] = [
    {
        "id": "token",
        "short": "Token",
        "task": "Settings › Developer settings › Personal access tokens › Fine-grained tokens",
        "title": "Create a fine-grained personal access token",
        "detail": (
            "Choose 'Fine-grained tokens', not 'Tokens (classic)'. Set the "
            "resource owner to the organisation that owns the repositories."
        ),
        "why": (
            "A classic token's 'repo' scope is read and write together, with no "
            "read-only variant for private repositories. Only a fine-grained "
            "token can express what Meridian actually needs."
        ),
        "critical": True,
    },
    {
        "id": "repos",
        "short": "Repositories",
        "task": None,
        "title": "Select the repositories",
        "detail": (
            "Either 'All repositories' or a named selection. A fine-grained "
            "token only reaches repositories chosen here."
        ),
        "why": (
            "A workflow that reuses one from another repository will not "
            "resolve unless that repository is selected too."
        ),
    },
    {
        "id": "permissions",
        "short": "Permissions",
        "task": None,
        "title": "Grant four read-only repository permissions",
        "detail": (
            "Metadata: Read-only, Contents: Read-only, Pull requests: "
            "Read-only, Actions: Read-only. Grant nothing with write access."
        ),
        "why": (
            "Actions alone lists a workflow's name and path; reading the YAML "
            "itself needs Contents. Granting only Actions produces pipelines "
            "with no visible steps."
        ),
        "critical": True,
    },
]


GITHUB_LIMITATIONS = [
    "A workflow that calls a reusable workflow or composite action in another "
    "repository is extracted as written. Resolving the reference needs that "
    "repository selected on the same token, so a step defined elsewhere may "
    "not be visible.",
    "Classic personal access tokens cannot express read-only access to a "
    "private repository — the 'repo' scope is read and write together. "
    "Meridian asks for a fine-grained token so read-only stays true.",
    "Fine-grained tokens do not advertise their permissions on API responses, "
    "so Meridian reports what it could actually read rather than listing the "
    "permissions you granted.",
    "Organisation-level rulesets and branch protection need organisation "
    "permissions beyond repository access and are not extracted.",
]


AZURE_DEVOPS_FIELDS: list[CredentialField] = [
    CredentialField(
        id="organization",
        label="Organisation name",
        help=(
            "Just the name, not the full URL. In "
            "https://dev.azure.com/contoso the organisation is 'contoso'."
        ),
        placeholder="contoso",
    ),
    CredentialField(
        id="method",
        label="Authentication method",
        kind="select",
        help="Which method your team has approved.",
        options=[
            (
                "pat",
                "Personal access token (recommended)",
                "Created from User settings › Personal access tokens. The simplest "
                "option and available to everyone.",
            ),
            (
                "entra",
                "Microsoft Entra ID",
                "For organisations that do not permit personal access tokens. "
                "Requires an app registration; paste its token below.",
            ),
        ],
    ),
    CredentialField(
        id="pat",
        label="Personal access token",
        kind="password",
        help=(
            "Shown once when created — copy it then. Give it read-only scopes; "
            "the next screen lists exactly which."
        ),
        auth_methods=["pat"],
    ),
    CredentialField(
        id="entra_token",
        label="Access token",
        kind="password",
        help="A Microsoft Entra ID access token for the Azure DevOps resource.",
        auth_methods=["entra"],
    ),
    CredentialField(
        id="projects",
        label="Projects",
        required=False,
        help=(
            "Comma-separated project names to read. Leave empty to read every "
            "project the token can see — fine for a small organisation, slow for "
            "a large one."
        ),
        placeholder="Payroll Platform, HR Integrations",
    ),
    CredentialField(
        id="base_url",
        label="Server URL",
        required=False,
        help=(
            "Only for Azure DevOps Server (on-premises). Leave empty for the "
            "cloud service at dev.azure.com."
        ),
        placeholder="https://dev.azure.com",
    ),
]


#: What an admin does in Azure DevOps before connecting.
#:
#: Far shorter than Workday's, because most of what Meridian needs is exposed
#: by API rather than requiring artefacts to be built first. The one genuinely
#: error-prone step is scope selection: the PAT screen offers read/write pairs
#: and picking the wrong half of one is silent until extraction fails.
AZURE_DEVOPS_SETUP_STEPS: list[dict] = [
    {
        "id": "pat",
        "short": "Create token",
        "task": "User settings › Personal access tokens › New Token",
        "title": "Create a personal access token",
        "detail": (
            "Set the organisation to the one you are connecting, and an expiry "
            "your team is willing to rotate. The token is shown once — copy it "
            "before closing the dialog."
        ),
        "why": (
            "Meridian acts as this token. Everything it reads is bounded by the "
            "scopes you grant it here."
        ),
    },
    {
        "id": "scopes",
        "short": "Scopes",
        "task": None,
        "title": "Grant read-only scopes",
        "detail": (
            "Tick the Read variant of: Project and team, Build, Release, "
            "Service endpoints, and Variable groups. Never tick a write or "
            "manage box — Meridian never writes to Azure DevOps."
        ),
        "why": (
            "Each scope maps to one thing Meridian can see. A missing scope "
            "produces a partial graph, not an error, so the connection test "
            "reports which surfaces are readable."
        ),
        "critical": True,
    },
    {
        "id": "environments",
        "short": "Environments",
        "task": None,
        "title": "Decide on the Environment scope",
        "detail": (
            "Azure DevOps publishes no read-only scope for environments — the "
            "only option is 'Environment (read and manage)'. Grant it to see "
            "environments, approval gates and deployment history; skip it and "
            "everything else still works."
        ),
        "why": (
            "This is Microsoft's design, not Meridian's requirement. Your "
            "security team should make this call knowingly rather than find a "
            "manage scope on an integration token later."
        ),
    },
    {
        "id": "projects",
        "short": "Projects",
        "task": None,
        "title": "Note which projects to read",
        "detail": (
            "Meridian can read every project the token can see, or a named "
            "list. On a large organisation, naming them keeps the first "
            "extraction quick."
        ),
        "why": "You can change this later without recreating the token.",
        "optional": True,
    },
]


AZURE_DEVOPS_LIMITATIONS = [
    "Azure DevOps publishes no webhook for pipeline definition changes. Every "
    "pipeline event fires on a run, never on someone editing a definition, so "
    "configuration drift is found by polling each definition's revision number "
    "rather than in real time.",
    "A pipeline that extends a YAML template in another repository cannot be "
    "fully resolved read-only — the only supported expansion queues a dry run, "
    "which Meridian will not do. The definition is extracted as stored, so a "
    "step that lives in a shared template is not visible.",
    "Approvals and checks on YAML environments come from a preview API whose "
    "response shape Microsoft has not published. Meridian reads it on a "
    "best-effort basis and reports when it cannot, rather than showing an "
    "environment as having no approvals when it may simply be unreadable.",
    "Reading environments requires the 'Environment (read and manage)' scope. "
    "Microsoft publishes no read-only equivalent, so this one grant is broader "
    "than Meridian's use of it.",
]


# Scopes reused by the planned platform connectors. Declared once so the
# catalogue stays consistent about what read-only access means.
_PLATFORM_SCOPES = [
    ConnectorScope(
        id="read.metadata",
        label="Read configuration metadata",
        description="Object definitions, field-level configuration and business rules.",
        required=True,
    ),
    ConnectorScope(
        id="read.records",
        label="Read transactional records",
        description="Sampled records used to build baselines for comparison testing.",
        required=False,
    ),
]


_PLANNED: list[ConnectorEntry] = [
    ConnectorEntry(
        id="cx-sap",
        name="SAP S/4HANA",
        vendor="SAP SE",
        category="erp",
        kind="platform",
        description=(
            "Reads CDS views, OData services, customizing configuration and "
            "flexible workflows."
        ),
        auth_methods=["oauth2", "basic", "service_account"],
        provides=["Configuration baseline", "Data model", "Workflow definitions"],
        scopes=_PLATFORM_SCOPES,
        coming_soon=True,
    ),
    ConnectorEntry(
        id="cx-dynamics",
        name="Dynamics 365",
        vendor="Microsoft",
        category="erp",
        kind="platform",
        description=(
            "Reads Dataverse tables, columns, business rules, business process "
            "flows and security roles."
        ),
        auth_methods=["oauth2", "service_account"],
        provides=["Data model", "Business rules", "Process flows"],
        scopes=_PLATFORM_SCOPES,
        coming_soon=True,
    ),
    # Azure DevOps moved to _IMPLEMENTED above.
    ConnectorEntry(
        id="cx-confluence",
        name="Confluence",
        vendor="Atlassian",
        category="docs",
        kind="wiki",
        description="Reads spaces, pages, tables and version history for decision context.",
        auth_methods=["api_key", "basic"],
        provides=["Documentation", "Decisions", "Version history"],
        scopes=_PLATFORM_SCOPES,
        coming_soon=True,
    ),
    ConnectorEntry(
        id="cx-figma",
        name="Figma",
        vendor="Figma, Inc.",
        category="design",
        kind="design",
        description=(
            "Reads files, frames, components and design tokens so screens can be "
            "linked to the requirements and code that realise them."
        ),
        auth_methods=["oauth2", "api_key"],
        provides=["Screens", "Components", "Design tokens"],
        scopes=_PLATFORM_SCOPES,
        coming_soon=True,
    ),
    ConnectorEntry(
        id="cx-servicenow",
        name="ServiceNow",
        vendor="ServiceNow, Inc.",
        category="ticketing",
        kind="ticketing",
        description="Reads change requests, CAB decisions, CMDB items and incidents.",
        auth_methods=["oauth2", "basic"],
        provides=["Change requests", "CMDB", "Incidents"],
        scopes=_PLATFORM_SCOPES,
        coming_soon=True,
    ),
]


_IMPLEMENTED: list[ConnectorEntry] = [
    _from_class(
        WorkdayConnector,
        credential_fields=WORKDAY_FIELDS,
        setup_steps=TENANT_SETUP_STEPS,
        required_artifacts=setup_checklist(),
        artifact_build_steps=REPORT_BUILD_STEPS,
        limitations=WORKDAY_LIMITATIONS,
    ),
    _from_class(
        AzureDevOpsConnector,
        credential_fields=AZURE_DEVOPS_FIELDS,
        setup_steps=AZURE_DEVOPS_SETUP_STEPS,
        limitations=AZURE_DEVOPS_LIMITATIONS,
    ),
    _from_class(
        JiraConnector,
        credential_fields=JIRA_FIELDS,
        setup_steps=JIRA_SETUP_STEPS,
        limitations=JIRA_LIMITATIONS,
    ),
    _from_class(
        GitHubConnector,
        credential_fields=GITHUB_FIELDS,
        setup_steps=GITHUB_SETUP_STEPS,
        limitations=GITHUB_LIMITATIONS,
    ),
    _from_class(ApiSpecConnector),
]

def _index(entries: list[ConnectorEntry]) -> dict[str, ConnectorEntry]:
    """Build the registry, refusing duplicate ids.

    A dict comprehension would let a later declared-only entry silently
    overwrite an implemented one of the same id — which happened when Azure
    DevOps was implemented while a 'coming soon' placeholder still existed. The
    connector vanished from the catalogue as connectable and nothing failed.
    """
    out: dict[str, ConnectorEntry] = {}
    for entry in entries:
        if entry.id in out:
            raise ValueError(
                f"Duplicate connector id {entry.id!r}. Remove the placeholder "
                "entry when a connector becomes implemented."
            )
        out[entry.id] = entry
    return out


REGISTRY: dict[str, ConnectorEntry] = _index([*_IMPLEMENTED, *_PLANNED])


def get(connector_id: str) -> ConnectorEntry | None:
    return REGISTRY.get(connector_id)


def build(connector_id: str, config: dict | None = None) -> EnterpriseConnector:
    """Instantiate a connector, or explain why that is not possible."""
    entry = REGISTRY.get(connector_id)
    if entry is None:
        raise KeyError(f"Unknown connector: {connector_id}")
    if entry.implementation is None:
        raise NotImplementedError(
            f"The {entry.name} connector is declared but not yet implemented."
        )
    return entry.implementation(config)


def all_entries() -> list[ConnectorEntry]:
    """Implemented connectors first — what works should be easiest to find."""
    return sorted(REGISTRY.values(), key=lambda e: (e.coming_soon, e.name))
