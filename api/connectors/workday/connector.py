"""
The Workday connector.

Six extraction surfaces, used for what each is actually good for:

  - **SOAP** (`Integrations`, `Human_Resources`, `Staffing`) — organisational
    structure, job profiles, locations, integration systems. Reliable, always
    available, and the backbone of the graph.
  - **RaaS** — business process definitions, steps, condition rules, custom
    fields, security policies. Everything the APIs cannot reach. Requires the
    customer to build reports; each one is optional and adds a layer.
  - **REST/OpenAPI** — the tenant's own API surface. Transactional data is
    ignored; the spec is read as a *capability* statement, because a field no
    API exposes cannot be read downstream however the process is configured.
  - **Graph API** — GraphQL introspection, the richest machine-readable
    statement of which objects relate to which. OAuth-only, and not enabled in
    every tenant.
  - **Runtime process runs** — what approval chains actually did, step by step,
    which is the only way to see that a documented process has an undocumented
    step in practice.
  - **Browser discovery** — recorded, read-only navigation replayed against an
    administrator-captured session. The last resort, and the only surface that
    reaches conditional visibility, validation messages and picklist values.

The connector keeps the transcript's three layers apart. `snapshot()` returns
tenant *configuration* — what this customer has set up — alongside *capability*
records describing what the platform exposes. `observe()` returns *runtime*
behaviour: integration events and process runs that actually happened.
Conflating them would leave the graph unable to answer "is this configured, or
did someone do it once", which is the question drift analysis exists to ask.

Every surface past the first two degrades rather than fails. A tenant without
the Graph API, without OAuth, or without a captured browser session still gets
a complete SOAP and RaaS graph, and is told plainly what it is missing.

Nothing here writes to the graph. Records go to the normaliser, which validates
them against the ontology before anything is persisted.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from api.connectors.base import (
    AccessCheck,
    ConnectorCapability,
    ConnectorError,
    ConnectorScope,
    EnterpriseConnector,
    NotConfigured,
    RawRecord,
    RelationOrder,
)
from api.connectors.workday import absence_walk
from api.connectors.workday.absence import (
    AbsencePiiError,
    TimeOffPlan,
    describe,
    parse_plan_rows,
    summary_gaps,
)
from api.connectors.workday.absence_screen import (
    attach_accrual_detail,
    attach_calculations,
    parse_plan_screen,
)
from api.connectors.workday.auth import WorkdayAuth, WorkdayAuthError, WorkdayCredentials
from api.connectors.workday.browser import (
    BrowserSession,
    BrowserUnavailable,
    Evidence,
    RecipeRunner,
    playwright_available,
)
from api.connectors.workday.events import (
    ProcessInstance,
    Pseudonymiser,
    mark_undocumented,
    parse_instances,
)
from api.connectors.workday.graphql import (
    DEFAULT_GRAPH_DEPTH,
    WorkdayGraphClient,
    WorkdayGraphError,
)
from api.connectors.workday.raas import RaasClient, RaasError, field_list, field_value
from api.connectors.workday.recipes import RECIPE_PACK
from api.connectors.workday.reports import REPORT_PACK, REPORTS_BY_ID
from api.connectors.workday.rest import (
    DEFAULT_SERVICES,
    WorkdayRestClient,
    WorkdayRestError,
    parse_operations,
    parse_schemas,
)
from api.connectors.workday.soap import (
    WorkdaySoapClient,
    WorkdaySoapError,
    descriptor,
    reference_id,
)
from api.connectors.workday.wql import WqlClient


class WorkdayConnector(EnterpriseConnector):
    id = "cx-workday"
    name = "Workday"
    vendor = "Workday, Inc."
    category = "hcm"
    kind = "platform"
    description = (
        "Reads HCM configuration, business process definitions and calculated "
        "fields so changes can be traced to the rules they alter."
    )
    auth_methods = ["oauth2", "service_account", "basic"]
    provides = [
        "Configuration baseline",
        "Business process rules",
        "Organisational structure",
        "Integration inventory",
    ]
    extractor_version = "1"

    scopes = [
        ConnectorScope(
            id="read.organisation",
            label="Read organisational structure",
            description=(
                "Supervisory organisations, companies, cost centres, locations and "
                "job profiles. Read via SOAP."
            ),
            required=True,
        ),
        ConnectorScope(
            id="read.integrations",
            label="Read integration systems",
            description=(
                "Integration systems, their attributes and maps, so an outbound "
                "interface can be traced to the data it carries."
            ),
            required=False,
        ),
        ConnectorScope(
            id="read.reports",
            label="Read discovery reports",
            description=(
                "Runs the custom reports that expose business process definitions, "
                "steps, condition rules and custom fields — none of which any "
                "Workday API returns."
            ),
            required=False,
        ),
        ConnectorScope(
            id="read.events",
            label="Read integration events",
            description=(
                "Which integrations actually ran and whether they succeeded. Used to "
                "compare configured behaviour with observed behaviour."
            ),
            required=False,
        ),
        ConnectorScope(
            id="read.api_surface",
            label="Read the API surface",
            description=(
                "The tenant's own OpenAPI and GraphQL schemas. Records which "
                "objects are exposed to integrations at all — a field no API "
                "returns cannot be read downstream however the process is "
                "configured. Requires OAuth; unavailable on ISU connections."
            ),
            required=False,
        ),
        ConnectorScope(
            id="read.process_runs",
            label="Read business process run history",
            description=(
                "What processes actually did, step by step, so configured "
                "routing can be compared with observed routing. Worker names "
                "are pseudonymised on ingest."
            ),
            required=False,
        ),
        ConnectorScope(
            id="read.absence",
            label="Read absence configuration",
            description=(
                "Time off plans, accrual rules, eligibility and carryover — the "
                "configuration behind every leave policy. Plan configuration "
                "only; worker balances and absence dates are never read."
            ),
            required=False,
        ),
        ConnectorScope(
            id="discover.browser",
            label="Browser discovery",
            description=(
                "Replays recorded, read-only navigation paths against an "
                "administrator-captured session to read configuration that "
                "exists only on Workday screens. Never logs in on its own and "
                "cannot click anything that commits a change."
            ),
            required=False,
        ),
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        raw = dict(self.config or {})
        creds_input = raw.get("credentials") or raw

        self.credentials = WorkdayCredentials(
            host=str(creds_input.get("host", "")),
            tenant=str(creds_input.get("tenant", "")),
            method=str(creds_input.get("method", "oauth_refresh_token")),
            token_endpoint=str(creds_input.get("token_endpoint", "")),
            client_id=str(creds_input.get("client_id", "")),
            client_secret=str(creds_input.get("client_secret", "")),
            refresh_token=str(creds_input.get("refresh_token", "")),
            private_key_pem=str(creds_input.get("private_key_pem", "")),
            jwt_issuer=str(creds_input.get("jwt_issuer", "")),
            jwt_subject=str(creds_input.get("jwt_subject", "")),
            username=str(creds_input.get("username", "")),
            password=str(creds_input.get("password", "")),
            api_version=str(creds_input.get("api_version", "v46.2")),
        )
        self.auth = WorkdayAuth(self.credentials)

        #: Report owner as it appears in Workday — usually the ISU's account
        #: name, since the ISU owns reports it created.
        self.report_owner: str = str(raw.get("report_owner", "")) or self.credentials.username

        #: Per-report name overrides, so a customer who named a report
        #: differently does not have to rename it to match the pack.
        self.report_names: dict[str, str] = dict(raw.get("report_names") or {})

        self.granted_scopes: list[str] = list(
            raw.get("granted_scopes") or [s.id for s in self.scopes]
        )

        #: Which REST services to read specs from. Overridable because tenants
        #: enable different service sets and probing all of them wastes a
        #: request per absent one.
        self.rest_services: tuple[str, ...] = tuple(
            raw.get("rest_services") or DEFAULT_SERVICES
        )

        #: Pseudonymise worker names in runtime data. Defaults to on: the
        #: transcript asks for minimisation, and a default that leaks PII
        #: unless someone opts out is the wrong way round.
        self.minimise_worker_data: bool = bool(raw.get("minimise_worker_data", True))

        #: An administrator-captured browser session, if one exists. Never
        #: created here — `capture_session` requires a human at a real login.
        session_state = str(raw.get("browser_session_state", "") or "")
        self.browser_session: BrowserSession | None = (
            BrowserSession(
                tenant=self.credentials.tenant,
                state_json=session_state,
                captured_by=str(raw.get("browser_session_captured_by", "") or ""),
                captured_at=str(raw.get("browser_session_captured_at", "") or ""),
            )
            if session_state
            else None
        )

        #: Recipes to replay. Defaults to the shipped pack; a tenant with
        #: recorded screens of its own supplies them here.
        self.recipes = list(raw.get("recipes") or RECIPE_PACK)

        #: Time off plan screen URLs, keyed by plan id. Supplied rather than
        #: derived: Workday's instance URLs carry tenant-specific ids
        #: (`1$1733/2039$14`) that cannot be constructed, and a guessed one
        #: resolves to a real page that is not the plan.
        self.absence_plan_urls: dict[str, str] = dict(
            raw.get("absence_plan_urls") or {}
        )

        #: Headless for scheduled runs. Overridable because watching a walk is
        #: the fastest way to diagnose a recipe that a Workday release broke.
        self.browser_headless: bool = bool(raw.get("browser_headless", True))

        #: Set by the absence walk. Read by the ingestion pipeline so a run cut
        #: short by session expiry is recorded as partial rather than complete.
        self.absence_walk_partial: bool = False
        self.absence_walk_reason: str = ""

        #: Set when the API surfaces failed but the run continued on screens.
        #: Reported rather than swallowed: "no integration user yet" and "the
        #: tenant is down" produce the same empty API result and need
        #: different responses.
        self.api_error: str = ""

    # --- configuration ------------------------------------------------------

    def is_configured(self) -> bool:
        return not self.credentials.missing()

    def report_name(self, report_id: str) -> str:
        override = self.report_names.get(report_id)
        if override:
            return override
        spec = REPORTS_BY_ID.get(report_id)
        return spec.report_name if spec else report_id

    def _granted(self, scope: str) -> bool:
        return scope in self.granted_scopes

    # --- access -------------------------------------------------------------

    def validate_access(self) -> AccessCheck:
        """Check credentials and report exactly which surfaces are reachable.

        Deliberately granular. "Connection failed" is useless when six things
        had to be configured; this reports which of them worked, so the admin
        knows whether to revisit the API client, the security group, or the
        reports.
        """
        gaps = self.credentials.missing()
        if gaps:
            return AccessCheck(
                ok=False,
                message=(
                    "Not configured. Still needed: " + ", ".join(gaps) + "."
                ),
            )

        effective: list[str] = []
        missing: list[str] = []
        notes: list[str] = []

        # Whether the API surfaces are reachable at all. Screen discovery does
        # not use them — it authenticates with a captured browser session — so
        # an API failure must not end the check while screens are available.
        # Returning early here made a tenant with a valid session and no
        # integration user extract nothing through the product path, which is
        # every tenant before its ISU is provisioned.
        api_reachable = True

        with httpx.Client(timeout=60.0) as client:
            if self.auth.uses_oauth:
                try:
                    self.auth.access_token(client)
                    notes.append("Authenticated with OAuth 2.0.")
                except WorkdayAuthError as exc:
                    api_reachable = False
                    missing.append("read.organisation")
                    notes.append(str(exc))
            else:
                notes.append("Using Integration System User credentials.")

            # SOAP is the backbone of the API surfaces; if it fails none of the
            # others are worth probing, but screens are unaffected.
            if api_reachable:
                try:
                    soap = WorkdaySoapClient(self.auth, "Human_Resources")
                    soap.call(
                        "Get_Job_Families", page=1, page_size=1, client=client
                    )
                    effective.append("read.organisation")
                    notes.append("Read organisational data via SOAP.")
                except WorkdaySoapError as exc:
                    api_reachable = False
                    missing.append("read.organisation")
                    notes.append(
                        "Authenticated, but the Human_Resources service refused "
                        f"the request. {exc}"
                    )

            if api_reachable:
                try:
                    integrations = WorkdaySoapClient(self.auth, "Integrations")
                    integrations.call(
                        "Get_Integration_Systems", page=1, page_size=1, client=client
                    )
                    effective.append("read.integrations")
                except WorkdaySoapError:
                    missing.append("read.integrations")
                    notes.append(
                        "Cannot read integration systems — the ISU is missing the "
                        "Integration Build domain."
                    )

            # Report probing is what tells the customer how much of the deep
            # configuration is currently reachable.
            if api_reachable and self._granted("read.reports") and self.report_owner:
                raas = RaasClient(self.auth)
                found: list[str] = []
                absent: list[str] = []
                for spec in REPORT_PACK:
                    ok, _ = raas.probe(
                        self.report_owner, self.report_name(spec.id), client=client
                    )
                    (found if ok else absent).append(spec.title)

                if found:
                    effective.append("read.reports")
                    notes.append(f"{len(found)} discovery report(s) reachable.")
                if absent:
                    notes.append(
                        f"{len(absent)} report(s) not yet built: {', '.join(absent[:3])}"
                        + ("…" if len(absent) > 3 else "")
                        + ". Business process logic stays invisible until they exist."
                    )

            # The OAuth-only surfaces. Their absence is a limitation to report,
            # never a failure: the connector's backbone does not depend on them.
            if api_reachable and self._granted("read.api_surface"):
                if not self.auth.uses_oauth:
                    notes.append(
                        "The REST and Graph APIs need OAuth; this connection uses "
                        "Integration System User credentials, so the API surface "
                        "cannot be read."
                    )
                    missing.append("read.api_surface")
                else:
                    rest = WorkdayRestClient(self.auth)
                    reachable = [
                        service
                        for service in self.rest_services
                        if rest.probe(service, client=client)[0]
                    ]
                    graph_ok, _ = WorkdayGraphClient(self.auth).probe(client=client)

                    if reachable or graph_ok:
                        effective.append("read.api_surface")
                    if reachable:
                        notes.append(
                            f"{len(reachable)} REST service(s) readable: "
                            + ", ".join(reachable[:3])
                            + ("…" if len(reachable) > 3 else "")
                            + "."
                        )
                    notes.append(
                        "Graph API reachable."
                        if graph_ok
                        else "Graph API not enabled in this tenant — optional."
                    )

                    # WQL is probed alongside REST because it shares REST's one
                    # hard precondition — a bearer token — and reporting it here
                    # means the answer to "can we query data sources directly"
                    # arrives the moment an API client exists, rather than after
                    # someone thinks to go and check.
                    #
                    # It is worth reporting even when unreachable: WQL would let a
                    # customer skip building the nine discovery reports, so a note
                    # saying it is one domain away is more actionable than silence.
                    wql_ok, wql_why = WqlClient(self.auth).probe(client=client)
                    notes.append(
                        f"WQL reachable — data sources can be queried directly, "
                        f"without the report pack. {wql_why}"
                        if wql_ok
                        else (
                            f"WQL not reachable: {wql_why} Granting the 'Workday "
                            "Query Language' domain in the System functional area "
                            "would remove the need for the discovery reports."
                        )
                    )

            if (
                api_reachable
                and self._granted("read.process_runs")
                and self.report_owner
            ):
                raas = RaasClient(self.auth)
                runs_ok, _ = raas.probe(
                    self.report_owner, self.report_name("bp_runtime"), client=client
                )
                if runs_ok:
                    effective.append("read.process_runs")
                    notes.append(
                        "Run history readable — configured routing can be compared "
                        "with what actually happened."
                    )
                else:
                    notes.append(
                        "The run history report is not built, so Meridian can read "
                        "what is configured but not what actually ran."
                    )

        # Browser discovery is checked outside the HTTP client: its
        # preconditions are a local install and a captured session, not a
        # network call.
        if self._granted("discover.browser"):
            ready, why = self.browser_ready()
            if ready:
                effective.append("discover.browser")
                notes.append("Screen discovery ready.")
            else:
                missing.append("discover.browser")
                notes.append(why)

        # Fail only when *nothing* is reachable. One working surface is a
        # usable connection: screens alone reach configuration no API returns,
        # and the API alone is the normal state before a session is captured.
        if not effective:
            return AccessCheck(
                ok=False,
                message=(
                    f"Connected to {self.credentials.tenant}, but no surface is "
                    "readable. " + " ".join(notes)
                ),
                missing_scopes=missing,
            )

        return AccessCheck(
            ok=True,
            message=f"Connected to {self.credentials.tenant}. " + " ".join(notes),
            effective_scopes=effective,
            missing_scopes=missing,
        )

    def discover_capabilities(self) -> list[ConnectorCapability]:
        """What this connection can actually extract, given its permissions."""
        caps = [
            ConnectorCapability(
                id="workday.organisations",
                label="Organisations and hierarchy",
                layer="configuration",
                node_kinds=["config_object"],
                requires_scopes=["read.organisation"],
            ),
            ConnectorCapability(
                id="workday.job_profiles",
                label="Job profiles and families",
                layer="configuration",
                node_kinds=["data_entity"],
                requires_scopes=["read.organisation"],
            ),
            ConnectorCapability(
                id="workday.locations",
                label="Locations",
                layer="configuration",
                node_kinds=["config_object"],
                requires_scopes=["read.organisation"],
            ),
        ]

        if self._granted("read.integrations"):
            caps.append(
                ConnectorCapability(
                    id="workday.integrations",
                    label="Integration systems",
                    layer="configuration",
                    node_kinds=["integration"],
                    requires_scopes=["read.integrations"],
                )
            )

        if self._granted("read.reports"):
            caps.extend(
                ConnectorCapability(
                    id=f"workday.report.{spec.id}",
                    label=spec.title,
                    layer="configuration",
                    node_kinds=["business_process", "config_object", "data_entity"],
                    requires_scopes=["read.reports"],
                )
                for spec in REPORT_PACK
            )

        if self._granted("read.events"):
            caps.append(
                ConnectorCapability(
                    id="workday.integration_events",
                    label="Integration run history",
                    layer="runtime",
                    node_kinds=["integration"],
                    requires_scopes=["read.events"],
                )
            )

        # OAuth-only surfaces. Reported as available only when the connection
        # can actually reach them, so the UI does not promise an ISU connection
        # something Workday will refuse.
        if self._granted("read.api_surface") and self.auth.uses_oauth:
            caps.extend(
                [
                    ConnectorCapability(
                        id="workday.rest_surface",
                        label="REST API surface",
                        layer="capability",
                        node_kinds=["integration", "data_entity"],
                        requires_scopes=["read.api_surface"],
                    ),
                    ConnectorCapability(
                        id="workday.graph_schema",
                        label="Graph API object model",
                        layer="capability",
                        node_kinds=["data_entity"],
                        requires_scopes=["read.api_surface"],
                    ),
                ]
            )

        if self._granted("read.absence"):
            caps.append(
                ConnectorCapability(
                    id="workday.absence",
                    label="Time off plans and accruals",
                    layer="configuration",
                    node_kinds=["config_object"],
                    requires_scopes=["read.absence"],
                )
            )

        if self._granted("read.process_runs"):
            caps.append(
                ConnectorCapability(
                    id="workday.process_runs",
                    label="Business process run history",
                    layer="runtime",
                    node_kinds=["business_process", "config_object"],
                    requires_scopes=["read.process_runs"],
                )
            )

        # Only advertised once a session exists. A capability the connection
        # cannot currently exercise is a promise the next run will break.
        if self._granted("discover.browser") and self.browser_ready()[0]:
            caps.append(
                ConnectorCapability(
                    id="workday.browser_discovery",
                    label="Screen discovery",
                    layer="configuration",
                    node_kinds=["screen", "data_entity"],
                    requires_scopes=["discover.browser"],
                )
            )

        return caps

    # --- extraction ---------------------------------------------------------

    def snapshot(self) -> Iterator[RawRecord]:
        """Tenant configuration."""
        if not self.is_configured():
            raise NotConfigured(
                "Workday is not configured. Still needed: "
                + ", ".join(self.credentials.missing())
                + "."
            )

        with httpx.Client(timeout=180.0) as client:
            # The API surfaces are attempted as a group. A tenant can have a
            # captured browser session and no integration user — the normal
            # state before an ISU is provisioned — and there an unguarded SOAP
            # call ends the whole run, taking screen discovery with it even
            # though screens do not use these credentials at all.
            #
            # Failure is recorded and reported, never silent: `api_error` is
            # surfaced on the run so a genuine outage is not mistaken for a
            # tenant that was only ever configured for screens.
            try:
                yield from self._organisations(client)
                yield from self._job_profiles(client)
                yield from self._locations(client)

                if self._granted("read.integrations"):
                    yield from self._integration_systems(client)
            except (WorkdayAuthError, WorkdaySoapError) as exc:
                self.api_error = str(exc)

            if not self.api_error and self._granted("read.reports") and self.report_owner:
                yield from self._reports(client)

            # Absence runs regardless: `_absence` reads SOAP, reports and
            # screens, and degrades to whichever are available. It is the one
            # surface that still yields something useful with no API at all.
            if self._granted("read.absence"):
                yield from self._absence(client)

            # Capability layer: what the platform exposes, as opposed to what
            # this tenant configured. Both OAuth-only, so an ISU connection
            # simply skips them.
            if not self.api_error and self._granted("read.api_surface"):
                yield from self._api_surface(client)
                yield from self._graph_schema(client)

        # Browser discovery runs outside the httpx client: it drives a real
        # browser and shares nothing with the HTTP surfaces.
        if self._granted("discover.browser"):
            yield from self._browser_discovery()

    def observe(self) -> Iterator[RawRecord]:
        """Runtime: what actually ran.

        Two independent surfaces. Integration events say which interfaces
        fired; process runs say what the approval chains actually did, which is
        the side of the drift comparison the configuration cannot supply.
        """
        if not self.is_configured():
            return

        if self._granted("read.process_runs") and self.report_owner:
            with httpx.Client(timeout=180.0) as client:
                yield from self._process_runs(client)

        if not self._granted("read.events"):
            return

        with httpx.Client(timeout=180.0) as client:
            soap = WorkdaySoapClient(self.auth, "Integrations")
            try:
                result = soap.paged(
                    "Get_Integration_Events",
                    response_key="Integration_Event",
                    client=client,
                )
            except WorkdaySoapError:
                # A missing runtime scope must not fail a configuration run —
                # the configuration is the valuable part.
                return

            for row in result.records:
                data = _first_dict(row.get("Integration_Event_Data")) or {}
                event_ref = row.get("Integration_Event_Reference")
                key = reference_id(event_ref) or descriptor(event_ref)
                if not key:
                    continue

                system_ref = data.get("Integration_System_Reference")
                system_key = reference_id(system_ref)

                yield RawRecord(
                    kind="integration",
                    natural_key=f"workday:event:{key}",
                    label=descriptor(event_ref) or f"Integration event {key}",
                    payload={
                        "status": _text(data.get("Integration_Event_Status")),
                        "initiatedAt": _text(data.get("Initiated_DateTime")),
                        "completedAt": _text(data.get("Completed_DateTime")),
                        "system": descriptor(system_ref),
                    },
                    provenance=f"Workday › Integration Event › {key}",
                    layer="runtime",
                    relations=(
                        [("READS", f"workday:integration:{system_key}")]
                        if system_key
                        else []
                    ),
                )

    # --- SOAP extractors ----------------------------------------------------

    def _organisations(self, client: httpx.Client) -> Iterator[RawRecord]:
        """Supervisory organisations, companies, cost centres.

        The spine of a Workday tenant: nearly every business process definition
        is scoped to an organisation, so without these the process nodes have
        nothing to attach to.
        """
        soap = WorkdaySoapClient(self.auth, "Staffing")
        result = soap.paged(
            "Get_Organizations", response_key="Organization", client=client
        )

        for row in result.records:
            data = _first_dict(row.get("Organization_Data")) or {}
            ref = row.get("Organization_Reference")
            key = reference_id(ref, id_type="Organization_Reference_ID")
            if not key:
                continue

            org_type = _text(data.get("Organization_Type_Reference")) or descriptor(
                data.get("Organization_Type_Reference")
            )
            parent_ref = data.get("Superior_Organization_Reference")
            parent_key = reference_id(parent_ref, id_type="Organization_Reference_ID")

            yield RawRecord(
                kind="config_object",
                natural_key=f"workday:org:{key}",
                label=_text(data.get("Organization_Name")) or descriptor(ref) or key,
                payload={
                    "code": _text(data.get("Organization_Code")),
                    "type": org_type,
                    "description": _text(data.get("Organization_Description")),
                    "inactive": _text(data.get("Inactive")),
                    "availabilityDate": _text(data.get("Availability_Date")),
                },
                source_ref=f"{self.credentials.normalised_host()}/{self.credentials.tenant}",
                provenance=f"Workday › Organization › {key}",
                layer="configuration",
                relations=(
                    [("DEPENDS_ON", f"workday:org:{parent_key}")] if parent_key else []
                ),
            )

    def _job_profiles(self, client: httpx.Client) -> Iterator[RawRecord]:
        soap = WorkdaySoapClient(self.auth, "Human_Resources")
        result = soap.paged(
            "Get_Job_Profiles", response_key="Job_Profile", client=client
        )

        for row in result.records:
            data = _first_dict(row.get("Job_Profile_Data")) or {}
            ref = row.get("Job_Profile_Reference")
            key = reference_id(ref, id_type="Job_Profile_ID")
            if not key:
                continue

            basic = _first_dict(data.get("Job_Profile_Basic_Data")) or {}
            family_ref = basic.get("Job_Family_Reference")
            family_key = reference_id(family_ref)

            yield RawRecord(
                kind="data_entity",
                natural_key=f"workday:jobprofile:{key}",
                label=_text(basic.get("Job_Profile_Name")) or descriptor(ref) or key,
                payload={
                    "summary": _text(basic.get("Job_Description_Summary")),
                    "inactive": _text(basic.get("Inactive")),
                    "managementLevel": descriptor(basic.get("Management_Level_Reference")),
                    "jobFamily": descriptor(family_ref),
                },
                provenance=f"Workday › Job Profile › {key}",
                layer="configuration",
                relations=(
                    [("REFERENCES_OBJECT", f"workday:jobfamily:{family_key}")]
                    if family_key
                    else []
                ),
            )

    def _locations(self, client: httpx.Client) -> Iterator[RawRecord]:
        soap = WorkdaySoapClient(self.auth, "Human_Resources")
        result = soap.paged("Get_Locations", response_key="Location", client=client)

        for row in result.records:
            data = _first_dict(row.get("Location_Data")) or {}
            ref = row.get("Location_Reference")
            key = reference_id(ref, id_type="Location_ID")
            if not key:
                continue

            yield RawRecord(
                kind="config_object",
                natural_key=f"workday:location:{key}",
                label=_text(data.get("Location_Name")) or descriptor(ref) or key,
                payload={
                    "type": descriptor(data.get("Location_Type_Reference")),
                    "usage": descriptor(data.get("Location_Usage_Reference")),
                    "timeProfile": descriptor(data.get("Time_Profile_Reference")),
                    "inactive": _text(data.get("Inactive")),
                },
                provenance=f"Workday › Location › {key}",
                layer="configuration",
            )

    def _integration_systems(self, client: httpx.Client) -> Iterator[RawRecord]:
        """Integration systems — the outbound surface a change can break."""
        soap = WorkdaySoapClient(self.auth, "Integrations")
        try:
            result = soap.paged(
                "Get_Integration_Systems",
                response_key="Integration_System",
                client=client,
            )
        except WorkdaySoapError:
            # Reported by validate_access; a missing optional domain should not
            # abort an otherwise good extraction.
            return

        for row in result.records:
            data = _first_dict(row.get("Integration_System_Data")) or {}
            ref = row.get("Integration_System_Reference")
            key = reference_id(ref, id_type="Integration_System_ID")
            if not key:
                continue

            yield RawRecord(
                kind="integration",
                natural_key=f"workday:integration:{key}",
                label=_text(data.get("Integration_System_Name")) or descriptor(ref) or key,
                payload={
                    "template": descriptor(data.get("Integration_Template_Reference")),
                    "enabled": _text(data.get("Integration_System_Enabled")),
                    "description": _text(data.get("Integration_System_Description")),
                },
                provenance=f"Workday › Integration System › {key}",
                layer="configuration",
            )

    # --- RaaS extractors ----------------------------------------------------

    def _reports(self, client: httpx.Client) -> Iterator[RawRecord]:
        """Run whichever discovery reports exist.

        Each report is independent: a tenant with only the BP definitions
        report still gets process nodes. A report that is absent or unreadable
        is skipped rather than failing the run, because the alternative is that
        one missing optional report costs the customer their entire graph.
        """
        raas = RaasClient(self.auth)
        handlers = {
            "bp_definitions": self._rows_bp_definitions,
            "bp_steps": self._rows_bp_steps,
            "condition_rules": self._rows_condition_rules,
            "custom_fields": self._rows_custom_fields,
            "security_groups": self._rows_security_groups,
            "custom_reports": self._rows_custom_reports,
        }

        for spec in REPORT_PACK:
            handler = handlers.get(spec.id)
            if handler is None:
                continue
            try:
                response = raas.fetch(
                    self.report_owner, self.report_name(spec.id), client=client
                )
            except RaasError:
                continue
            yield from handler(response.rows)

    def _rows_bp_definitions(self, rows: list[dict]) -> Iterator[RawRecord]:
        for row in rows:
            key = field_value(row, "Definition_ID", "definitionId", "Business_Process_ID")
            name = field_value(
                row, "Business_Process_Definition", "businessProcessDefinition"
            )
            if not key and not name:
                continue
            key = key or _slug(name)

            org = field_value(row, "Organization", "organization")
            relations = []
            if org:
                relations.append(("CONFIGURES", f"workday:org:{org}"))

            yield RawRecord(
                kind="business_process",
                natural_key=f"workday:bp:{key}",
                label=name or key,
                payload={
                    "processType": field_value(row, "Business_Process_Type"),
                    "definition": name,
                    "effectiveDate": field_value(row, "Effective_Date"),
                    "organization": org,
                    "status": field_value(row, "Status"),
                    "description": field_value(row, "Description"),
                },
                provenance=f"Workday › Business Process Definition › {key}",
                layer="configuration",
                relations=relations,
            )

    def _rows_bp_steps(self, rows: list[dict]) -> Iterator[RawRecord]:
        """Steps, plus the ordering between them.

        `NEXT_STEP` edges are derived by sorting each definition's steps on
        `Step_Order`. The report gives position, not adjacency, and adjacency is
        what makes the process a graph rather than a list.

        Position is *also* kept on the assertion, because adjacency alone
        cannot answer "what is the third approval" or "what sits above the
        15-day threshold". A step carrying a condition rule gets
        `CONDITIONAL_NEXT_STEP` instead, so a gated hop is not asserted as one
        the process always takes.
        """
        by_definition: dict[str, list[tuple[float, str, dict]]] = {}

        for row in rows:
            definition = field_value(row, "Definition_ID", "Business_Process_Definition")
            if not definition:
                continue

            order_text = field_value(row, "Step_Order", "Order")
            try:
                order = float(order_text)
            except ValueError:
                # Workday step order can be "2a". The numeric prefix orders it
                # and the suffix breaks ties in report order.
                digits = "".join(c for c in order_text if c.isdigit() or c == ".")
                order = float(digits) if digits else float(len(by_definition.get(definition, [])))

            step_name = field_value(row, "Step_Name", "Step") or f"Step {order_text}"
            key = f"{_slug(definition)}:{_slug(order_text or step_name)}"
            group = field_value(row, "Group", "Security_Group", "Groups")
            condition = field_value(row, "Condition_Rule", "Condition")

            relations = [("HAS_STEP", f"workday:bp:{definition}")]
            if group:
                relations.append(("APPROVED_BY", f"workday:secgroup:{_slug(group)}"))
            if condition:
                relations.append(("GOVERNED_BY", f"workday:rule:{_slug(condition)}"))

            record = RawRecord(
                kind="config_object",
                natural_key=f"workday:bpstep:{key}",
                label=f"{step_name} ({field_value(row, 'Step_Type') or 'Step'})",
                payload={
                    "definition": definition,
                    "order": order_text,
                    "stepType": field_value(row, "Step_Type"),
                    "group": group,
                    "conditionRule": condition,
                    "optional": field_value(row, "Optional"),
                    "subprocess": field_value(row, "Subprocess"),
                },
                provenance=f"Workday › Business Process Step › {definition} #{order_text}",
                layer="configuration",
                relations=relations,
            )
            by_definition.setdefault(definition, []).append((order, key, record))

        for definition, steps in by_definition.items():
            steps.sort(key=lambda item: item[0])
            scope = f"workday:bp:{definition}"

            for index, (_, _, record) in enumerate(steps):
                # Position is kept, not just used to derive adjacency and then
                # discarded. "Which step is third" and "what sits above the
                # 15-day threshold" are the questions a change-impact analysis
                # actually asks, and edge direction alone cannot answer them.
                #
                # The index is used rather than the source's own order value:
                # Workday step order can be "2a", so the report's numbering is
                # not necessarily dense or integral, while position within the
                # sorted list always is.
                position = index + 1
                record.ordering[("HAS_STEP", scope)] = RelationOrder(
                    sequence=position, scope=scope
                )

                if index + 1 < len(steps):
                    next_record = steps[index + 1][2]
                    target = f"workday:bpstep:{steps[index + 1][1]}"

                    # The condition belongs to the step being *entered*, not
                    # the one being left. "Compensation Partner approves when
                    # the change exceeds 10%" gates arrival at that step; the
                    # preceding step runs unconditionally.
                    condition = next_record.payload.get("conditionRule")

                    # A gated hop is a different claim from an unconditional
                    # one. Recording both as NEXT_STEP would assert that the
                    # process always proceeds this way, which is exactly what
                    # a conditional approval does not do.
                    predicate = "CONDITIONAL_NEXT_STEP" if condition else "NEXT_STEP"
                    record.relations.append((predicate, target))
                    record.ordering[(predicate, target)] = RelationOrder(
                        sequence=position,
                        scope=scope,
                        condition={"rule": condition} if condition else None,
                    )
                yield record

    def _rows_condition_rules(self, rows: list[dict]) -> Iterator[RawRecord]:
        for row in rows:
            name = field_value(row, "Condition_Rule", "Rule_Name", "Name")
            if not name:
                continue
            key = field_value(row, "Rule_ID") or _slug(name)
            yield RawRecord(
                kind="policy",
                natural_key=f"workday:rule:{_slug(name)}",
                label=name,
                payload={
                    "ruleId": key,
                    "description": field_value(row, "Description"),
                    "expression": field_value(row, "Expression", "Condition"),
                    "businessObject": field_value(row, "Business_Object"),
                },
                provenance=f"Workday › Condition Rule › {name}",
                layer="configuration",
            )

    def _rows_custom_fields(self, rows: list[dict]) -> Iterator[RawRecord]:
        for row in rows:
            name = field_value(row, "Field_Name", "Custom_Field", "Name")
            if not name:
                continue
            key = field_value(row, "Field_ID") or _slug(name)
            business_object = field_value(row, "Business_Object", "Object")

            relations = []
            if business_object:
                relations.append(
                    ("HAS_FIELD", f"workday:object:{_slug(business_object)}")
                )
            for source in field_list(row, "Source_Fields", "Source_Field"):
                relations.append(("READS", f"workday:field:{_slug(source)}"))

            yield RawRecord(
                kind="data_entity",
                natural_key=f"workday:field:{_slug(name)}",
                label=name,
                payload={
                    "fieldId": key,
                    "businessObject": business_object,
                    "fieldType": field_value(row, "Field_Type", "Type"),
                    "description": field_value(row, "Description"),
                    "calculated": bool(field_list(row, "Source_Fields", "Source_Field")),
                },
                provenance=f"Workday › Custom Field › {name}",
                layer="configuration",
                relations=relations,
            )

    def _rows_security_groups(self, rows: list[dict]) -> Iterator[RawRecord]:
        for row in rows:
            name = field_value(row, "Security_Group", "Group_Name", "Name")
            if not name:
                continue
            yield RawRecord(
                kind="policy",
                natural_key=f"workday:secgroup:{_slug(name)}",
                label=name,
                payload={
                    "groupType": field_value(row, "Group_Type", "Type"),
                    "domain": field_value(row, "Domain"),
                    "accessLevel": field_value(row, "Access_Level", "Access"),
                    "members": field_list(row, "Members", "Member"),
                },
                provenance=f"Workday › Security Group › {name}",
                layer="configuration",
            )

    def _rows_custom_reports(self, rows: list[dict]) -> Iterator[RawRecord]:
        for row in rows:
            name = field_value(row, "Report_Name", "Custom_Report", "Name")
            if not name:
                continue
            data_source = field_value(row, "Data_Source", "Report_Data_Source")
            relations = (
                [("READS_OBJECT", f"workday:object:{_slug(data_source)}")]
                if data_source
                else []
            )
            yield RawRecord(
                kind="report",
                natural_key=f"workday:report:{_slug(name)}",
                label=name,
                payload={
                    "reportType": field_value(row, "Report_Type", "Type"),
                    "dataSource": data_source,
                    "owner": field_value(row, "Owner"),
                    "webServiceEnabled": field_value(row, "Web_Service_Enabled"),
                },
                provenance=f"Workday › Custom Report › {name}",
                layer="configuration",
                relations=relations,
            )

    # --- absence extractors --------------------------------------------------

    def _absence(self, client: httpx.Client) -> Iterator[RawRecord]:
        """Time off plans, from reports and SOAP together.

        Both surfaces are read because neither is sufficient. SOAP enumerates
        the plans that exist — reliable, and it works before any report has
        been built. The reports carry the accrual amounts, eligibility and
        carryover that make a plan describable. Merging them means a tenant
        with no reports still gets an inventory, and one with reports gets the
        detail attached to the same nodes.
        """
        plans: dict[str, TimeOffPlan] = {}

        for plan in self._absence_plans_soap(client):
            plans[plan.plan_id] = plan

        for plan in self._absence_plans_reports(client):
            existing = plans.get(plan.plan_id)
            if existing is None:
                plans[plan.plan_id] = plan
                continue
            # Report detail wins over the SOAP stub: it is strictly richer, and
            # the stub exists only so plans appear at all without reports.
            plan.via = f"{existing.via}+{plan.via}" if existing.via else plan.via
            plans[plan.plan_id] = plan

        # Screens last, because they are the only surface that reaches the
        # accrual amounts and lookup tables — and the only one that can fail
        # halfway. Whatever SOAP and the reports produced is already in `plans`
        # by this point, so a session that expires mid-walk costs the screen
        # detail for the remaining plans and nothing else.
        self.absence_walk_partial = False
        self.absence_walk_reason = ""
        if self._granted("discover.browser"):
            self._enrich_from_screens(plans)

        for plan in plans.values():
            yield from self._records_for_plan(plan)

    def _enrich_from_screens(self, plans: dict[str, TimeOffPlan]) -> None:
        """Walk each plan's screens and fold the detail onto it.

        Mutates `plans` in place rather than returning records: the screen data
        is *additional detail about plans that already exist*, and emitting it
        as separate records would produce a second node per plan that entity
        resolution then has to merge back.
        """
        ready, _ = self.browser_ready()
        if not ready or self.browser_session is None:
            return

        # A configured URL is sufficient on its own. Requiring the plan to
        # already exist would gate screens behind SOAP — and screens are the
        # only surface reaching accrual amounts and lookup tables, so a tenant
        # with browser discovery and no integration user would have extracted
        # nothing while reporting success. Whoever supplied a plan URL is
        # asserting the plan exists; that is the same standard applied to the
        # URL itself, which also cannot be verified in advance.
        for plan_id, url in self.absence_plan_urls.items():
            if plan_id not in plans:
                plans[plan_id] = TimeOffPlan(
                    plan_id=plan_id,
                    name=plan_id,
                    via="screen",
                )

        targets = [
            {"url": url, "name": plans[plan_id].name, "planId": plan_id}
            for plan_id, url in self.absence_plan_urls.items()
            if plan_id in plans
        ]
        if not targets:
            # No plan URLs configured. Screen discovery needs an instance URL
            # per plan and Workday's are tenant-specific, so they are supplied
            # rather than derived — a constructed one resolves to a real page
            # that is not the plan.
            return

        try:
            result = absence_walk.walk(
                self.browser_session.state_json,
                targets,
                headless=self.browser_headless,
            )
        except BrowserUnavailable as exc:
            self.absence_walk_reason = str(exc)
            return

        self.absence_walk_partial = result.partial
        self.absence_walk_reason = result.reason

        by_url = {t["url"]: t["planId"] for t in targets}
        for capture in result.captures:
            plan_id = by_url.get(capture.plan_url)
            plan = plans.get(plan_id) if plan_id else None
            if plan is None:
                continue

            # Adopt the tenant's own name when this plan came from a configured
            # URL rather than SOAP, where `name` was seeded with the plan id.
            if capture.screen_name and plan.name == plan.plan_id:
                plan.name = capture.screen_name

            screen_plan = parse_plan_screen(
                {"tabs_detail": capture.tabs_detail},
                plan_id=plan.plan_id,
                name=plan.name,
                unit_of_time=plan.unit_of_time,
                balance_period=plan.balance_period,
            )
            # Screen values win where present: they are what the tenant
            # actually renders, and the report pack does not reach them at all.
            plan.carryover_limit = screen_plan.carryover_limit or plan.carryover_limit
            plan.carryover_expiry = (
                screen_plan.carryover_expiry or plan.carryover_expiry
            )
            plan.maximum_balance = screen_plan.maximum_balance or plan.maximum_balance
            plan.country = plan.country or screen_plan.country
            if screen_plan.accruals:
                plan.accruals = screen_plan.accruals
            if screen_plan.eligibility:
                plan.eligibility = screen_plan.eligibility
            plan.via = f"{plan.via}+screen" if plan.via else "screen"

            attach_accrual_detail(plan, capture.accruals)
            attach_calculations(plan, capture.lookups)

    def _absence_plans_soap(self, client: httpx.Client) -> Iterator[TimeOffPlan]:
        """Plan inventory via Absence_Management.

        Returns names and ids but not the rules behind them — Workday's absence
        service is as thin on configuration as the rest of the API surface.
        Worth calling anyway: it needs no tenant setup, so a brand-new
        connection shows the customer their plans immediately.
        """
        soap = WorkdaySoapClient(self.auth, "Absence_Management")
        try:
            result = soap.paged(
                "Get_Time_Off_Plans", response_key="Time_Off_Plan", client=client
            )
        except (WorkdaySoapError, WorkdayAuthError) as exc:
            # Absence is not enabled in every tenant, the ISU may lack the
            # domain, and there may be no integration user at all yet. None of
            # those should fail a configuration run — the screen walk below
            # does not use these credentials.
            #
            # `WorkdayAuthError` belongs here as much as `WorkdaySoapError`:
            # authentication fails *before* SOAP is reached, so catching only
            # the latter let a tenant with no API credentials abort a run that
            # screens would have completed.
            self.api_error = self.api_error or str(exc)
            return

        for row in result.records:
            data = _first_dict(row.get("Time_Off_Plan_Data")) or {}
            ref = row.get("Time_Off_Plan_Reference")
            key = reference_id(ref) or descriptor(ref)
            if not key:
                continue
            yield TimeOffPlan(
                plan_id=key,
                name=_text(data.get("Time_Off_Plan_Name")) or descriptor(ref) or key,
                plan_type=descriptor(data.get("Time_Off_Type_Reference")),
                unit_of_time=descriptor(data.get("Unit_of_Time_Reference")),
                inactive=_text(data.get("Inactive")).lower() in {"1", "true"},
                via="soap",
                raw=data,
            )

    def _absence_plans_reports(self, client: httpx.Client) -> Iterator[TimeOffPlan]:
        """Plan detail from the two absence reports, merged on plan id."""
        if not self._granted("read.reports") or not self.report_owner:
            return

        raas = RaasClient(self.auth)
        rows: list[dict] = []
        for report_id in ("time_off_plans", "time_off_accruals"):
            try:
                response = raas.fetch(
                    self.report_owner, self.report_name(report_id), client=client
                )
            except WorkdayAuthError as exc:
                # Authentication, not a missing report. `RaasError` alone was not
                # enough: `raas.fetch` acquires a token before it makes the
                # request, so a tenant whose API client is unusable raises from
                # inside the fetch with a class this loop did not catch. That
                # escaped `_absence`, escaped `snapshot`, and ended the run —
                # taking screen discovery with it, even though screens
                # authenticate with a captured session and never touch these
                # credentials.
                #
                # Returning rather than continuing: the second report would fail
                # identically, and a second 503 tells nobody anything new.
                self.api_error = self.api_error or str(exc)
                return
            except RaasError:
                continue
            rows.extend(response.rows)

        if not rows:
            return

        try:
            yield from parse_plan_rows(rows, via="report")
        except AbsencePiiError as exc:
            # Refuse the whole report rather than filtering. A report built on
            # the wrong data source needs rebuilding, and quietly dropping the
            # offending columns would hide that while still having received
            # the data.
            raise ConnectorError(str(exc)) from exc

    def _records_for_plan(self, plan: TimeOffPlan) -> Iterator[RawRecord]:
        """One plan as graph records.

        The plain-language summary is computed here and stored on the node.
        Deliberately not left to read time: the summary is a *claim about the
        configuration as extracted*, and recomputing it later against a graph
        that has moved on would produce a sentence no evidence supports.
        """
        gaps = summary_gaps(plan)
        yield RawRecord(
            kind="config_object",
            natural_key=plan.natural_key,
            label=plan.name,
            payload={
                "planType": plan.plan_type,
                "unitOfTime": plan.unit_of_time,
                "balancePeriod": plan.balance_period,
                "carryoverLimit": plan.carryover_limit,
                "carryoverExpiry": plan.carryover_expiry,
                "maximumBalance": plan.maximum_balance,
                "minimumIncrement": plan.minimum_increment,
                "country": plan.country,
                "inactive": plan.inactive,
                "complex": plan.is_complex,
                "accrualCount": len(plan.accruals),
                "eligibilityCount": len(plan.eligibility),
                "via": plan.via,
                # What a business user reads. Templated from extracted fields,
                # never generated, and it names its own gaps.
                "summary": describe(plan),
                "summaryGaps": gaps,
                "summaryComplete": not gaps,
            },
            provenance=f"Workday › Time Off Plan › {plan.name}",
            layer="configuration",
            relations=(
                [("CONFIGURES", f"workday:org:{_slug(plan.country)}")]
                if plan.country
                else []
            ),
        )

        # The country as a node. Without it the CONFIGURES edge dangles and the
        # normaliser drops it, which silently costs the graph the ability to
        # answer "what applies in Hong Kong" — a question at least as likely as
        # any about a specific plan.
        #
        # A SOAP extraction of the same country produces `workday:org:<id>`
        # from a Workday reference id, so these may not merge automatically.
        # That is entity resolution's job, not this connector's: guessing at
        # the id here would be a fabricated identifier.
        if plan.country:
            yield RawRecord(
                kind="config_object",
                natural_key=f"workday:org:{_slug(plan.country)}",
                label=plan.country,
                payload={"kind": "country", "source": "absence"},
                provenance=f"Workday › Country › {plan.country}",
                layer="configuration",
            )

        for index, accrual in enumerate(plan.accruals, start=1):
            relations = [("HAS_STEP", plan.natural_key)]
            if accrual.calculation:
                relations.append(
                    ("DEPENDS_ON", f"workday:field:{_slug(accrual.calculation)}")
                )
            # Only link to a condition rule when the condition names one. The
            # screen parser puts prose here for accrual *overrides* ("this
            # accrual has a different accrual frequency"), which is a
            # description of the accrual, not a named rule — turning it into a
            # GOVERNED_BY target invented a rule node whose entire content was
            # a sentence Meridian wrote about itself.
            if accrual.condition and not accrual.condition.startswith("this accrual"):
                relations.append(
                    ("GOVERNED_BY", f"workday:rule:{_slug(accrual.condition)}")
                )

            record = RawRecord(
                kind="config_object",
                natural_key=f"{plan.natural_key}:accrual:{_slug(accrual.name)}",
                label=accrual.name,
                payload={
                    "amount": accrual.amount,
                    "unit": accrual.unit or plan.unit_of_time,
                    "frequency": accrual.frequency,
                    "condition": accrual.condition,
                    "calculation": accrual.calculation,
                    "isCalculated": accrual.is_calculated,
                    "effectiveDate": accrual.effective_date,
                },
                provenance=f"Workday › Accrual › {plan.name} › {accrual.name}",
                layer="configuration",
                relations=relations,
            )
            # Accruals are ordered: a plan that grants an initial award and
            # then accrues monthly applies them in sequence, and reversing that
            # changes the first year's entitlement.
            record.ordering[("HAS_STEP", plan.natural_key)] = RelationOrder(
                sequence=index, scope=plan.natural_key
            )
            yield record

            # The calculation as its own node, not just a string on the
            # accrual. This is what makes "what breaks if I change the UK FTE
            # calculation" answerable: a calculated field is shared between
            # plans, and until it is a node the graph cannot say what depends
            # on it. Emitted after the accrual so the DEPENDS_ON edge above
            # resolves instead of dangling.
            yield from self._records_for_calculation(accrual)

        for rule in plan.eligibility:
            yield RawRecord(
                kind="config_object",
                natural_key=f"workday:eligibility:{_slug(rule.name)}",
                label=rule.name,
                payload={"criteria": rule.criteria, "references": rule.references},
                provenance=f"Workday › Eligibility › {rule.name}",
                layer="configuration",
                relations=[("SECURED_BY", plan.natural_key)],
            )

    def _records_for_calculation(self, accrual: Any) -> Iterator[RawRecord]:
        """A calculated field, and the lookup table behind it.

        Both are shared objects — one calculation drives accruals on several
        plans, one lookup table can back several calculations — so they are
        nodes in their own right rather than attributes of whichever accrual
        happened to reach them first. That sharing is precisely what a change
        impact analysis needs to see.

        Emitted even when unresolved: knowing that an accrual depends on a
        calculation nobody has read yet is more useful than a silent gap, and
        `resolved: false` on the node is what lets the graph say so.
        """
        if not accrual.calculation:
            return

        resolved = getattr(accrual, "resolved", None)
        calc_key = f"workday:field:{_slug(accrual.calculation)}"
        relations: list[tuple[str, str]] = []

        table_key = ""
        if resolved is not None and resolved.table_name:
            table_key = f"workday:lookup:{_slug(resolved.table_name)}"
            relations.append(("DEPENDS_ON", table_key))

        # A conditional branch whose result names another calculated field is
        # a real dependency, and the reason GBR's chain does not terminate in
        # one hop. Recorded as an edge so the traversal can follow it once
        # that field is extracted.
        referenced: list[str] = []
        if resolved is not None:
            for branch in resolved.branches:
                result = (branch.result or "").strip()
                if result and not _looks_like_value(result):
                    relations.append(
                        ("DEPENDS_ON", f"workday:field:{_slug(result)}")
                    )
                    referenced.append(result)

        yield RawRecord(
            kind="data_entity",
            natural_key=calc_key,
            label=accrual.calculation,
            payload={
                "calculationType": getattr(resolved, "kind", "") if resolved else "",
                "resolved": bool(resolved and resolved.is_resolved),
                "criteria": getattr(resolved, "criteria", "") if resolved else "",
                "branches": [
                    {
                        "order": b.order,
                        "condition": b.condition,
                        "result": b.result,
                    }
                    for b in (resolved.branches if resolved else [])
                ],
            },
            provenance=f"Workday › Calculated Field › {accrual.calculation}",
            layer="configuration",
            relations=relations,
        )

        # Stubs for calculations this walk referenced but did not visit.
        #
        # The alternative is a dangling edge, which the normaliser drops — and
        # a dropped edge is indistinguishable from a dependency that does not
        # exist. A stub marked `resolved: false` says the opposite: this rule
        # is real, something depends on it, and nobody has read it yet. That
        # is the extraction frontier, and it should be queryable rather than
        # invisible.
        for name in referenced:
            yield RawRecord(
                kind="data_entity",
                natural_key=f"workday:field:{_slug(name)}",
                label=name,
                payload={"resolved": False, "referencedBy": accrual.calculation},
                provenance=f"Workday › Calculated Field › {name} (referenced)",
                layer="configuration",
            )

        if resolved is None or not resolved.table_name:
            return

        yield RawRecord(
            kind="data_entity",
            natural_key=table_key,
            label=resolved.table_name,
            payload={
                # The bands are the answer to "how much leave does someone
                # get". Stored structurally rather than as prose so a question
                # about a specific service band can be answered by lookup
                # instead of by re-reading a sentence.
                "keyedOn": resolved.criteria,
                "bands": [
                    {"search": b.search, "result": b.result} for b in resolved.bands
                ],
                "bandCount": len(resolved.bands),
            },
            provenance=f"Workday › Lookup Table › {resolved.table_name}",
            layer="configuration",
        )

    # --- REST / OpenAPI extractors ------------------------------------------

    def _api_surface(self, client: httpx.Client) -> Iterator[RawRecord]:
        """The tenant's REST surface, as capability records.

        Layer is "capability", not "configuration": an OpenAPI document
        describes what the *platform* exposes to this tenant, which is a
        different truth from what the tenant has set up. Filing it as
        configuration would let a platform feature masquerade as a customer
        decision.
        """
        rest = WorkdayRestClient(self.auth)
        if not rest.available:
            return

        for service in self.rest_services:
            try:
                spec = rest.fetch_spec(service, client=client)
            except WorkdayRestError:
                # A service this tenant does not enable is normal, not a fault.
                continue

            for schema in parse_schemas(service, spec):
                yield RawRecord(
                    kind="data_entity",
                    natural_key=schema.natural_key,
                    label=schema.name,
                    payload={
                        "service": service,
                        "description": schema.description,
                        "properties": schema.properties,
                        "propertyCount": len(schema.properties),
                    },
                    provenance=f"Workday › REST › {service} › {schema.name}",
                    layer="capability",
                )

            for operation in parse_operations(service, spec):
                relations = [
                    (
                        "EXPOSES_OBJECT",
                        f"workday:apischema:{service}:{name}",
                    )
                    for name in operation.schemas
                ]
                yield RawRecord(
                    kind="integration",
                    natural_key=operation.natural_key,
                    label=f"{operation.method} {operation.path}",
                    payload={
                        "service": service,
                        "method": operation.method,
                        "path": operation.path,
                        "summary": operation.summary,
                    },
                    provenance=f"Workday › REST › {service} › {operation.path}",
                    layer="capability",
                    relations=relations,
                )

    # --- Graph API extractors ------------------------------------------------

    def _graph_schema(self, client: httpx.Client) -> Iterator[RawRecord]:
        """Workday's object model, from GraphQL introspection.

        The richest available statement of which objects relate to which, and
        the closest thing Workday publishes to a machine-readable map of
        itself. Capability layer for the same reason as REST.
        """
        graph = WorkdayGraphClient(self.auth)
        if not graph.available:
            return

        try:
            types = graph.introspect(client=client)
        except WorkdayGraphError:
            # Not enabled in every tenant, and its absence must not fail a run.
            return

        known = {t.name for t in types}
        for gql_type in types:
            # Only reference an object the schema actually declares. A dangling
            # target would create an empty placeholder node whose only content
            # is a name the graph invented.
            relations = [
                ("REFERENCES_OBJECT", f"workday:gqltype:{target}")
                for target in gql_type.references.values()
                if target in known and target != gql_type.name
            ]
            yield RawRecord(
                kind="data_entity",
                natural_key=gql_type.natural_key,
                label=gql_type.name,
                payload={
                    "description": gql_type.description,
                    "fields": gql_type.fields,
                    "references": gql_type.references,
                    "fieldCount": len(gql_type.fields),
                    "depth": DEFAULT_GRAPH_DEPTH,
                },
                provenance=f"Workday › Graph API › {gql_type.name}",
                layer="capability",
                relations=relations,
            )

    # --- runtime process extractors ------------------------------------------

    def _configured_steps(self, client: httpx.Client) -> dict[str, set[str]]:
        """Step names per definition, for drift comparison.

        Read separately from `_reports` because drift needs the configured side
        as a lookup, not as a stream of records. Returns empty on any failure:
        without a baseline the honest answer is "no drift detected", never
        "every step is undocumented".
        """
        if not self._granted("read.reports") or not self.report_owner:
            return {}

        raas = RaasClient(self.auth)
        try:
            response = raas.fetch(
                self.report_owner, self.report_name("bp_steps"), client=client
            )
        except RaasError:
            return {}

        configured: dict[str, set[str]] = {}
        for row in response.rows:
            definition = field_value(row, "Definition_ID", "Business_Process_ID")
            name = field_value(row, "Step_Name", "Step")
            if not definition or not name:
                continue
            # Raw, not slugged — must key identically to `parse_instances`, or
            # the baseline lookup misses and every observed step is reported as
            # undocumented drift.
            key = f"workday:bp:{definition}"
            configured.setdefault(key, set()).add(" ".join(name.lower().split()))
        return configured

    def _process_runs(self, client: httpx.Client) -> Iterator[RawRecord]:
        """What processes actually did, versus what they were configured to do."""
        raas = RaasClient(self.auth)
        try:
            response = raas.fetch(
                self.report_owner, self.report_name("bp_runtime"), client=client
            )
        except RaasError:
            return

        pseudonymiser = (
            Pseudonymiser(self.credentials.tenant) if self.minimise_worker_data else None
        )
        instances = parse_instances(response.rows, pseudonymise=pseudonymiser)
        mark_undocumented(instances, self._configured_steps(client))

        for instance in instances:
            yield from self._records_for_run(instance)

    def _records_for_run(self, instance: ProcessInstance) -> Iterator[RawRecord]:
        drifted = [s.name for s in instance.steps if s.undocumented]

        yield RawRecord(
            kind="business_process",
            natural_key=instance.natural_key,
            label=f"{instance.definition_label} — run {instance.instance_id}",
            payload={
                "instanceId": instance.instance_id,
                "status": instance.status,
                "initiatedAt": instance.initiated_at,
                "completedAt": instance.completed_at,
                "stepCount": len(instance.steps),
                "undocumentedSteps": drifted,
            },
            provenance=f"Workday › BP run › {instance.instance_id}",
            layer="runtime",
            relations=[("IMPLEMENTS", instance.definition_key)],
        )

        for step in instance.steps:
            record = RawRecord(
                kind="config_object",
                natural_key=f"{instance.natural_key}:step:{step.sequence}",
                label=step.name,
                payload={
                    "status": step.status,
                    "actor": step.actor,
                    "completedAt": step.completed_at,
                    "dueAt": step.due_at,
                    "undocumented": step.undocumented,
                },
                provenance=(
                    f"Workday › BP run › {instance.instance_id} › step {step.sequence}"
                ),
                layer="runtime",
                relations=[("HAS_OBSERVED_STEP", instance.natural_key)],
            )
            record.ordering[("HAS_OBSERVED_STEP", instance.natural_key)] = RelationOrder(
                sequence=step.sequence, scope=instance.scope
            )
            yield record

    # --- browser discovery ---------------------------------------------------

    def browser_ready(self) -> tuple[bool, str]:
        """Whether browser discovery can run, and why not when it cannot.

        Two independent preconditions with different remedies — install the
        extra, versus have an administrator sign in — so they are reported
        separately rather than as one "unavailable".
        """
        if not self._granted("discover.browser"):
            return False, "Browser discovery is not enabled for this connection."
        if not playwright_available():
            return False, (
                "Playwright is not installed on the server. Install the browser "
                "extra to enable screen discovery."
            )
        if not self.browser_session or not self.browser_session.is_present():
            return False, (
                "No Workday session has been captured. An administrator must "
                "sign in to Workday once, in a browser, before discovery can run."
            )
        return True, "Ready."

    def _browser_discovery(self) -> Iterator[RawRecord]:
        """Replay recorded navigation paths and emit what they captured.

        Every recipe runs independently: one broken by a Workday release must
        not cost the others, because releases move screens piecemeal.
        """
        ready, _ = self.browser_ready()
        if not ready or self.browser_session is None:
            return

        runner = RecipeRunner(self.browser_session, self.credentials.normalised_host())
        for recipe in self.recipes:
            try:
                evidence = runner.run(recipe)
            except BrowserUnavailable:
                continue
            yield from self._records_for_evidence(recipe.id, recipe, evidence)

    def _records_for_evidence(
        self, recipe_id: str, recipe: Any, evidence: Evidence
    ) -> Iterator[RawRecord]:
        """Turn one screen capture into graph records.

        Confidence is not set here — the normaliser assigns it — but the layer
        is "configuration" because a screen shows what this tenant has set up.
        Screens are the least reliable of the six surfaces, so the payload
        keeps the recipe id and observation time: when two surfaces disagree,
        the question is immediately which one to re-check.
        """
        yield RawRecord(
            kind="screen",
            natural_key=f"workday:screen:{recipe_id}",
            label=recipe.title,
            payload={
                "task": evidence.task,
                "section": evidence.section,
                "fieldCount": len(evidence.fields),
                "rowCount": len(evidence.rows),
                "skipped": evidence.skipped,
                "observedAt": evidence.observed_at,
                "recipe": recipe_id,
            },
            provenance=f"Workday › Screen › {recipe.title}",
            layer="configuration",
        )

        for field_data in evidence.fields:
            label = str(field_data.get("label") or "").strip()
            if not label:
                continue
            yield RawRecord(
                kind="data_entity",
                natural_key=f"workday:screenfield:{recipe_id}:{_slug(label)}",
                label=label,
                payload={
                    "type": field_data.get("type"),
                    "required": field_data.get("required"),
                    # The value set is the thing no API returns: it is the
                    # tenant's configured picklist, observed rather than
                    # documented.
                    "valuesObserved": field_data.get("values_observed") or [],
                    "observedAt": evidence.observed_at,
                },
                provenance=f"Workday › Screen › {recipe.title} › {label}",
                layer="configuration",
                relations=[("HAS_FIELD", f"workday:screen:{recipe_id}")],
            )

    def subscribe_to_changes(self) -> str | None:
        """Workday has no outbound webhook for configuration change.

        Integration events can be subscribed to, but configuration edits are
        not published anywhere, so drift is only detectable by re-extracting
        and diffing. Returning None keeps the scheduler honest about that.
        """
        return None


# --- helpers ---------------------------------------------------------------


def _looks_like_value(text: str) -> bool:
    """Whether a branch result is an answer rather than another rule name.

    "UK Statutory 28 days prorated based on FTE%" is an answer; "GBR Statutory
    Holiday Entitlement for Mid Year Hire" is the name of a further calculated
    field. The distinction decides whether to emit a DEPENDS_ON edge, and
    getting it wrong either way is visible: a missed edge hides a dependency,
    an invented one creates a node for a rule that does not exist.

    Heuristic, deliberately. Workday does not mark which results are terminal,
    and the alternative — following every result and seeing what resolves — is
    a request per branch against a system we are trying not to hammer.

    Keyed on *numbers*, not vocabulary. An earlier version matched the word
    "statutory", which appears in both "UK Statutory 28 days prorated" (an
    answer) and "GBR Statutory Holiday Entitlement for Mid Year Hire" (a rule
    name) — so every branch read as terminal and no dependency edge was
    emitted at all. A quantity is what makes a result an answer.
    """
    stripped = text.strip()
    if stripped.replace(".", "", 1).isdigit():
        return True
    has_digit = any(char.isdigit() for char in stripped)
    lowered = stripped.lower()
    return has_digit and any(
        marker in lowered for marker in ("day", "hour", "week", "%")
    )


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        text = value.get("#text")
        if isinstance(text, str):
            return text.strip()
        return str(value.get("@Descriptor", "")).strip()
    return ""


def _first_dict(value: Any) -> dict | None:
    """Workday returns `*_Data` blocks as either an object or a list of one."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return None


def _slug(value: str) -> str:
    """A stable key from a display name.

    Used only where Workday gives no reference id — report rows often carry a
    name and nothing else. Deterministic so the same name resolves to the same
    node across syncs.
    """
    cleaned = "".join(c.lower() if c.isalnum() else "-" for c in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "unnamed"


__all__ = ["WorkdayConnector", "ConnectorError"]
