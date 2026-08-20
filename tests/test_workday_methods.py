"""
The four extraction surfaces added beyond SOAP and RaaS.

Tested against recorded response shapes, like `test_workday.py`, because a test
requiring a live tenant is a test that never runs. The shapes here reproduce
what each surface actually returns — GraphQL's nested NON_NULL/LIST wrappers,
OpenAPI's `$ref` at varying depths, and Workday's one-row-per-step runtime
reports — since those are precisely what naive parsing mishandles.

The browser tests deliberately never launch a browser. What is worth testing
there is the *safety envelope*: that the recipe language cannot express a
write, and that a missing session degrades instead of failing. Whether
Playwright can click a button is Playwright's test, not ours.
"""

from __future__ import annotations

from dataclasses import asdict

import httpx
import pytest

from api.connectors.workday.auth import WorkdayAuth, WorkdayCredentials
from api.connectors.workday.browser import (
    FORBIDDEN_TARGETS,
    NAVIGATION_ONLY,
    BrowserSession,
    BrowserUnavailable,
    Recipe,
    RecipeError,
    Step,
)
from api.connectors.workday.connector import WorkdayConnector
from api.connectors.workday.events import (
    Pseudonymiser,
    mark_undocumented,
    parse_instances,
)
from api.connectors.workday.graphql import (
    WorkdayGraphClient,
    WorkdayGraphError,
    parse_introspection,
)
from api.connectors.workday.recipes import RECIPE_PACK, validate_pack
from api.connectors.workday.rest import (
    WorkdayRestClient,
    WorkdayRestError,
    parse_operations,
    parse_schemas,
)


def _oauth_creds(**overrides) -> WorkdayCredentials:
    values = {
        "host": "https://wd2-impl-services1.workday.com",
        "tenant": "acme_preview",
        "method": "oauth_refresh_token",
        "token_endpoint": "https://wd2-impl-services1.workday.com/ccx/oauth2/token",
        "client_id": "cid",
        "client_secret": "csecret",
        "refresh_token": "rtoken",
    }
    values.update(overrides)
    return WorkdayCredentials(**values)


def _basic_creds() -> WorkdayCredentials:
    return WorkdayCredentials(
        host="https://wd2-impl-services1.workday.com",
        tenant="acme_preview",
        method="isu_basic",
        username="isu",
        password="pw",
    )


def _config(creds: WorkdayCredentials, **extra) -> dict:
    """Connector config from a credentials object.

    `WorkdayCredentials` is slotted, so `__dict__` does not exist; `asdict`
    is the supported way to flatten it.
    """
    return {**asdict(creds), **extra}


def _authed(creds: WorkdayCredentials) -> WorkdayAuth:
    auth = WorkdayAuth(creds)
    # Pre-seed the token so tests exercise the surface, not the token dance.
    auth._access_token = "token"
    auth._expires_at = 4_102_444_800.0  # year 2100
    return auth


# ============================================================ REST / OpenAPI


SPEC = {
    "paths": {
        "/workers": {
            "get": {
                "summary": "Retrieve workers",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Worker"}
                            }
                        }
                    }
                },
            },
            "post": {
                "operationId": "createWorker",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Worker"}
                        }
                    }
                },
            },
        },
        "/workers/{id}/jobs": {
            "get": {
                "summary": "Worker jobs",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Job"},
                                }
                            }
                        }
                    }
                },
            }
        },
    },
    "components": {
        "schemas": {
            "Worker": {
                "description": "A person",
                "properties": {
                    "id": {"type": "string"},
                    "primaryJob": {"$ref": "#/components/schemas/Job"},
                },
            },
            "Job": {"properties": {"title": {"type": "string"}}},
            # A scalar wrapper: has no properties, so it is not a business
            # object and must not become a node.
            "Currency": {"type": "string", "enum": ["USD", "MYR"]},
        }
    },
}


def test_openapi_operations_are_parsed_with_their_schemas():
    ops = parse_operations("staffing", SPEC)

    by_key = {(o.method, o.path): o for o in ops}
    assert ("GET", "/workers") in by_key
    assert ("POST", "/workers") in by_key
    assert by_key[("GET", "/workers")].summary == "Retrieve workers"
    assert "Worker" in by_key[("GET", "/workers")].schemas


def test_refs_are_found_at_any_depth():
    """`$ref` sits under items/content/schema at varying depths.

    Reading only known keys silently drops the edge between an API path and the
    object it carries, which is the only reason the spec is ingested at all.
    """
    ops = {(o.method, o.path): o for o in parse_operations("staffing", SPEC)}
    assert ops[("GET", "/workers/{id}/jobs")].schemas == ["Job"]


def test_schemas_without_properties_are_not_business_objects():
    names = {s.name for s in parse_schemas("staffing", SPEC)}
    assert "Worker" in names
    assert "Job" in names
    assert "Currency" not in names


def test_schema_properties_resolve_refs_to_type_names():
    worker = next(s for s in parse_schemas("staffing", SPEC) if s.name == "Worker")
    assert worker.properties["id"] == "string"
    assert worker.properties["primaryJob"] == "Job"


def test_rest_is_unavailable_on_isu_credentials():
    """Workday's REST API is bearer-only.

    Reporting this as unavailable rather than raising keeps a working ISU
    connection from being described as broken.
    """
    client = WorkdayRestClient(_authed(_basic_creds()))
    assert client.available is False
    with pytest.raises(WorkdayRestError, match="requires OAuth"):
        client.fetch_spec("staffing")


def test_rest_404_explains_that_absence_is_normal():
    client = WorkdayRestClient(_authed(_oauth_creds()))
    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(404, text="nope"))
    )
    with pytest.raises(WorkdayRestError, match="not every service is enabled"):
        client.fetch_spec("absence", client=http)


def test_rest_probe_does_not_raise():
    client = WorkdayRestClient(_authed(_oauth_creds()))
    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(403, text="denied"))
    )
    ok, message = client.probe("staffing", client=http)
    assert ok is False
    assert "not authorised" in message


# ================================================================= Graph API


INTROSPECTION = {
    "__schema": {
        "queryType": {"name": "Query"},
        "types": [
            {
                "kind": "OBJECT",
                "name": "Worker",
                "description": "A person",
                "fields": [
                    {
                        "name": "id",
                        "type": {"kind": "SCALAR", "name": "ID", "ofType": None},
                    },
                    {
                        # Deeply wrapped: [Job!]! — three levels before the name.
                        "name": "jobs",
                        "type": {
                            "kind": "NON_NULL",
                            "name": None,
                            "ofType": {
                                "kind": "LIST",
                                "name": None,
                                "ofType": {
                                    "kind": "NON_NULL",
                                    "name": None,
                                    "ofType": {"kind": "OBJECT", "name": "Job"},
                                },
                            },
                        },
                    },
                ],
            },
            {
                "kind": "OBJECT",
                "name": "Job",
                "fields": [
                    {
                        "name": "title",
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    }
                ],
            },
            # Introspection plumbing, which must not become graph nodes.
            {
                "kind": "OBJECT",
                "name": "__Type",
                "fields": [
                    {
                        "name": "kind",
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    }
                ],
            },
            # Interfaces describe polymorphism the ontology cannot express.
            {"kind": "INTERFACE", "name": "Node", "fields": []},
        ],
    }
}


def test_introspection_unwraps_nested_type_modifiers():
    """`[Job!]!` points at Job. The wrappers say how many and whether null."""
    types = {t.name: t for t in parse_introspection(INTROSPECTION)}
    assert types["Worker"].fields["jobs"] == "Job"


def test_object_valued_fields_become_references_and_scalars_do_not():
    """A scalar describes the object; a reference connects it to another.

    Only the second is an edge, and treating scalars as edges would produce a
    node per string field.
    """
    worker = {t.name: t for t in parse_introspection(INTROSPECTION)}["Worker"]
    assert worker.references == {"jobs": "Job"}
    assert "id" in worker.fields
    assert "id" not in worker.references


def test_introspection_skips_internals_and_interfaces():
    names = {t.name for t in parse_introspection(INTROSPECTION)}
    assert names == {"Worker", "Job"}


def test_graphql_errors_inside_a_200_are_not_success():
    """GraphQL reports failure with HTTP 200.

    Treating that as success ingests an empty graph and calls the run clean,
    which is the worst available outcome.
    """
    client = WorkdayGraphClient(_authed(_oauth_creds()))
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"errors": [{"message": "no access"}]})
        )
    )
    with pytest.raises(WorkdayGraphError, match="no access"):
        client.introspect(client=http)


def test_graph_api_absence_is_reported_as_optional():
    client = WorkdayGraphClient(_authed(_oauth_creds()))
    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(404))
    )
    ok, message = client.probe(client=http)
    assert ok is False
    assert "not enabled everywhere" in message


def test_graph_records_only_reference_declared_types():
    """A dangling reference would create a node whose only content is a name
    the graph invented."""
    connector = WorkdayConnector(
        _config(_oauth_creds(), granted_scopes=["read.api_surface"])
    )
    connector.auth = _authed(_oauth_creds())
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"data": INTROSPECTION})
        )
    )
    records = list(connector._graph_schema(http))

    targets = {t for r in records for _, t in r.relations}
    assert targets == {"workday:gqltype:Job"}
    assert all(r.layer == "capability" for r in records)


# =========================================================== runtime BP runs


RUNTIME_ROWS = [
    {
        "Business_Process_Instance_ID": "BP-1",
        "Business_Process_Type": "Change Job",
        "Definition_ID": "CJ",
        "Step_Order": "2",
        "Step_Name": "Approval (Manager)",
        "Completed_By": "Alice Tan",
        "Overall_Status": "Completed",
    },
    {
        "Business_Process_Instance_ID": "BP-1",
        "Business_Process_Type": "Change Job",
        "Definition_ID": "CJ",
        "Step_Order": "1",
        "Step_Name": "Initiation",
        "Completed_By": "Bob Lee",
        "Overall_Status": "Completed",
    },
    {
        "Business_Process_Instance_ID": "BP-1",
        "Business_Process_Type": "Change Job",
        "Definition_ID": "CJ",
        "Step_Order": "3",
        "Step_Name": "Manual Payroll Correction",
        "Completed_By": "Alice Tan",
        "Overall_Status": "Completed",
    },
]


def test_runtime_rows_group_into_instances_in_source_order():
    """Rows arrive per step and out of order; the chain must not be."""
    instances = parse_instances(RUNTIME_ROWS)
    assert len(instances) == 1
    assert [s.name for s in instances[0].steps] == [
        "Initiation",
        "Approval (Manager)",
        "Manual Payroll Correction",
    ]
    assert [s.sequence for s in instances[0].steps] == [1, 2, 3]


def test_worker_names_are_pseudonymised_by_default():
    """The transcript asks for minimisation, and minimising downstream means
    the PII was already written to evidence."""
    instances = parse_instances(
        RUNTIME_ROWS, pseudonymise=Pseudonymiser("acme_preview")
    )
    actors = {s.actor for s in instances[0].steps}
    assert "Alice Tan" not in actors
    assert "Bob Lee" not in actors
    assert all(a.startswith("worker:") for a in actors)


def test_pseudonyms_are_stable_within_a_tenant_and_differ_across_tenants():
    """Stable so "the same person approved all of these" stays visible;
    tenant-keyed so cross-tenant correlation cannot happen by accident."""
    a = Pseudonymiser("acme")
    b = Pseudonymiser("globex")
    assert a("Alice Tan") == a("Alice Tan")
    assert a("Alice Tan") != b("Alice Tan")


def test_undocumented_steps_are_flagged_against_the_configuration():
    """The transcript's headline finding: a step that runs but is configured
    nowhere."""
    instances = parse_instances(RUNTIME_ROWS)
    mark_undocumented(
        instances, {"workday:bp:CJ": {"initiation", "approval (manager)"}}
    )

    drifted = [s.name for s in instances[0].steps if s.undocumented]
    assert drifted == ["Manual Payroll Correction"]


def test_no_baseline_means_no_drift_claimed():
    """Absence of a definition is not evidence of drift.

    Claiming otherwise would flag every step of every process the report pack
    has not reached — a wall of false findings that trains people to ignore it.
    """
    instances = parse_instances(RUNTIME_ROWS)
    mark_undocumented(instances, {})
    assert not any(s.undocumented for s in instances[0].steps)


def test_observed_steps_are_ordered_and_scoped_per_instance():
    """Two runs of the same process each have a step 2, and that is not a
    conflict — scoping to the definition would make the unique index reject the
    second run."""
    connector = WorkdayConnector(
        _config(_basic_creds(), granted_scopes=["read.process_runs"])
    )
    instance = parse_instances(RUNTIME_ROWS)[0]
    records = list(connector._records_for_run(instance))

    step_records = [r for r in records if "step" in r.natural_key]
    assert len(step_records) == 3
    for record in step_records:
        order = record.ordering[("HAS_OBSERVED_STEP", instance.natural_key)]
        assert order.scope == "workday:bpinstance:BP-1"

    assert records[0].relations == [("IMPLEMENTS", "workday:bp:CJ")]
    assert records[0].layer == "runtime"


def test_suffixed_runtime_step_orders_sort_between_integers():
    """Workday uses "2a" routinely; it belongs between 2 and 3."""
    rows = [
        {
            "Business_Process_Instance_ID": "BP-9",
            "Step_Order": order,
            "Step_Name": f"Step {order}",
        }
        for order in ("3", "1", "2a", "2")
    ]
    steps = parse_instances(rows)[0].steps
    assert [s.name for s in steps] == ["Step 1", "Step 2", "Step 2a", "Step 3"]


# ========================================================== browser discovery


def test_recipe_language_cannot_express_a_write():
    """The safety property that matters.

    A browser session inherits a real person's permissions, so "we simply will
    not write" has to be structural rather than a convention.
    """
    with pytest.raises(RecipeError, match="not a permitted action"):
        Step(action="fill", target="Salary").validate()

    for label in ("Submit", "Approve", "Delete"):
        with pytest.raises(RecipeError, match="may not click"):
            Step(action="click", target=label).validate()


def test_forbidden_targets_are_a_subset_of_click_semantics():
    """Guards against someone adding a mutating verb to the vocabulary."""
    assert "fill" not in NAVIGATION_ONLY
    assert "submit" not in NAVIGATION_ONLY
    assert "submit" in FORBIDDEN_TARGETS


def test_a_recipe_that_captures_nothing_is_rejected():
    recipe = Recipe(
        id="pointless",
        title="Goes somewhere",
        unlocks="nothing",
        steps=[Step(action="search_task", target="View Worker")],
    )
    with pytest.raises(RecipeError, match="captures nothing"):
        recipe.validate()


def test_shipped_recipe_pack_is_valid():
    validate_pack()
    assert len(RECIPE_PACK) >= 3
    assert all(r.workday_release for r in RECIPE_PACK)


def test_recipes_round_trip_through_json():
    """Tenant-recorded recipes arrive as JSON, and validation must apply to
    them exactly as it does to the shipped pack."""
    original = RECIPE_PACK[0]
    restored = Recipe.from_dict(
        {
            "id": original.id,
            "title": original.title,
            "unlocks": original.unlocks,
            "steps": [
                {"action": s.action, "target": s.target, "name": s.name,
                 "selector": s.selector, "optional": s.optional}
                for s in original.steps
            ],
        }
    )
    assert [s.action for s in restored.steps] == [s.action for s in original.steps]


def test_a_malicious_recipe_from_json_is_rejected():
    with pytest.raises(RecipeError):
        Recipe.from_dict(
            {
                "id": "evil",
                "title": "Approve everything",
                "steps": [
                    {"action": "search_task", "target": "My Tasks"},
                    {"action": "click", "target": "Approve"},
                    {"action": "capture", "selector": "body"},
                ],
            }
        )


def test_browser_discovery_degrades_without_a_session():
    """Three independent preconditions with different remedies."""
    connector = WorkdayConnector(
        _config(_basic_creds(), granted_scopes=["discover.browser"])
    )
    ready, why = connector.browser_ready()
    assert ready is False
    # Either Playwright is absent or no session was captured; both are
    # actionable messages rather than a stack trace.
    assert "Playwright" in why or "session has been captured" in why

    assert list(connector._browser_discovery()) == []


def test_browser_scope_not_granted_is_reported_distinctly():
    connector = WorkdayConnector(
        _config(_basic_creds(), granted_scopes=["read.organisation"])
    )
    ready, why = connector.browser_ready()
    assert ready is False
    assert "not enabled" in why


def test_a_configured_plan_url_is_walked_even_when_soap_found_nothing():
    """Screens must not be gated behind the integration user.

    `absence_plan_urls` is keyed by plan id, and the plan ids come from SOAP.
    An earlier version required the plan to already exist before walking it,
    so a tenant with screen discovery and no ISU — which is every tenant
    before the integration user is provisioned — produced no walk targets,
    returned silently, and reported success. Indistinguishable from a tenant
    that genuinely has no leave plans.

    Screens are the only surface reaching accrual amounts and lookup tables,
    so this is the configuration that most needs to survive a missing ISU.
    """
    connector = WorkdayConnector(
        _config(
            _basic_creds(),
            granted_scopes=["read.absence", "discover.browser"],
            absence_plan_urls={"HKG_ANNUAL": "https://wd.example/d/inst/1$1/2$3.htmld"},
            browser_session_state='{"cookies":[{"name":"wd","value":"x"}]}',
        )
    )

    walked: dict = {}

    def _fake_walk(state, targets, headless=True):
        walked["targets"] = targets
        raise BrowserUnavailable("stopped before launching a browser")

    from api.connectors.workday import connector as connector_module

    original = connector_module.absence_walk.walk
    connector_module.absence_walk.walk = _fake_walk
    try:
        plans: dict = {}  # SOAP found nothing
        connector._enrich_from_screens(plans)
    finally:
        connector_module.absence_walk.walk = original

    assert walked.get("targets"), "a configured URL must produce a walk target"
    assert walked["targets"][0]["planId"] == "HKG_ANNUAL"


def test_screens_survive_an_api_that_cannot_authenticate(monkeypatch):
    """A tenant with a session and no integration user must still extract.

    Screen discovery authenticates with a captured browser session and does
    not touch the API credentials, so an OAuth failure has no bearing on it.
    Three separate places used to end the run on that failure — the access
    check, `snapshot`'s opening SOAP calls, and the absence plan inventory —
    and each produced the same outcome: a run that reported failure while the
    one surface that *was* configured went unread.

    That is the normal state of every tenant before its ISU is provisioned.
    """
    from api.connectors.workday import connector as connector_module
    from api.connectors.workday.auth import WorkdayAuthError

    def _no_token(*_args, **_kwargs):
        raise WorkdayAuthError("Workday returned 503 from the token endpoint.")

    monkeypatch.setattr(
        connector_module.WorkdayAuth, "access_token", _no_token, raising=False
    )

    # Every HTTP surface must fail at the transport, not by connecting to a
    # host that does not resolve — otherwise this test spends minutes in
    # connect timeouts. Patching only the token leaves SOAP and RaaS dialling
    # out, because both authenticate lazily.
    def _no_soap(*_args, **_kwargs):
        raise connector_module.WorkdaySoapError("no route to tenant")

    def _no_raas(*_args, **_kwargs):
        raise connector_module.RaasError("no route to tenant")

    monkeypatch.setattr(
        connector_module.WorkdaySoapClient, "paged", _no_soap, raising=False
    )
    monkeypatch.setattr(
        connector_module.WorkdaySoapClient, "call", _no_soap, raising=False
    )
    monkeypatch.setattr(
        connector_module.RaasClient, "fetch", _no_raas, raising=False
    )
    monkeypatch.setattr(
        connector_module.RaasClient, "probe", _no_raas, raising=False
    )

    connector = WorkdayConnector(
        _config(
            _oauth_creds(),
            # `discover.browser` is deliberately *not* granted: this test is
            # about the API surfaces failing without ending the run, and
            # granting it would launch a real browser against a real host.
            granted_scopes=["read.absence"],
        )
    )

    # What matters is that nothing raised and the API failure was recorded
    # rather than swallowed.
    records = list(connector.snapshot())
    assert connector.api_error, "an API failure must be reported, not hidden"
    assert isinstance(records, list)


def test_session_state_is_treated_as_a_secret():
    """The cookies *are* the administrator until they expire."""
    from api.core.secrets import SENSITIVE_FIELDS, redact

    assert "browser_session_state" in SENSITIVE_FIELDS
    assert redact({"browser_session_state": "cookies"}) == {
        "browser_session_state": "••••••••"
    }


def test_captured_session_reports_presence_without_exposing_state():
    session = BrowserSession(tenant="acme", state_json='{"cookies":[]}')
    assert session.is_present() is True
    assert BrowserSession(tenant="acme", state_json="").is_present() is False


# ============================================================== wiring checks


def test_new_surfaces_are_skipped_when_scopes_are_not_granted():
    """A connection granted only the backbone must not attempt the rest."""
    connector = WorkdayConnector(
        _config(_basic_creds(), granted_scopes=["read.organisation"])
    )
    capability_ids = {c.id for c in connector.discover_capabilities()}
    assert "workday.rest_surface" not in capability_ids
    assert "workday.process_runs" not in capability_ids
    assert "workday.browser_discovery" not in capability_ids


def test_api_surface_is_not_promised_to_isu_connections():
    """Workday refuses REST and Graph for ISU credentials, so advertising them
    would be a promise the next run breaks."""
    connector = WorkdayConnector(
        _config(_basic_creds(), granted_scopes=["read.api_surface"])
    )
    capability_ids = {c.id for c in connector.discover_capabilities()}
    assert "workday.rest_surface" not in capability_ids


def test_api_surface_is_available_to_oauth_connections():
    connector = WorkdayConnector(
        _config(_oauth_creds(), granted_scopes=["read.api_surface"])
    )
    capability_ids = {c.id for c in connector.discover_capabilities()}
    assert "workday.rest_surface" in capability_ids
    assert "workday.graph_schema" in capability_ids


def test_minimisation_defaults_to_on():
    """A default that leaks PII unless someone opts out is the wrong way round."""
    assert WorkdayConnector(_config(_basic_creds())).minimise_worker_data is True
    assert (
        WorkdayConnector(
            _config(_basic_creds(), minimise_worker_data=False)
        ).minimise_worker_data
        is False
    )


def test_runtime_report_is_in_the_pack():
    from api.connectors.workday.reports import REPORTS_BY_ID

    spec = REPORTS_BY_ID["bp_runtime"]
    required = {f.name for f in spec.fields if f.required}
    assert "Business_Process_Instance_ID" in required
    assert "Step_Order" in required
