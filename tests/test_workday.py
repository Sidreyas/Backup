"""
The Workday connector.

Tested against recorded response shapes rather than a live tenant: a test that
needs someone's Workday credentials is a test that never runs. The XML and JSON
fixtures below reproduce the structures Workday actually returns — repeated
elements, `wd:` namespaces, reference blocks carrying several ids, and the
single-row-is-an-object quirk in RaaS — because those shapes are exactly what
naive parsing gets wrong.
"""

from __future__ import annotations

from xml.etree import ElementTree

import httpx
import pytest

from api.connectors.workday.auth import WorkdayAuth, WorkdayCredentials, WorkdayAuthError
from api.connectors.workday.connector import WorkdayConnector, _slug
from api.connectors.workday.raas import _extract_rows, field_list, field_value
from api.connectors.workday.reports import REPORT_PACK, TENANT_SETUP_STEPS
from api.connectors.workday.soap import (
    WorkdaySoapClient,
    WorkdaySoapError,
    descriptor,
    element_to_dict,
    reference_id,
)

WD = "urn:com.workday/bsvc"
ENV = "http://schemas.xmlsoap.org/soap/envelope/"


def _basic_creds(**overrides) -> WorkdayCredentials:
    values = {
        "host": "https://wd2-impl-services1.workday.com",
        "tenant": "acme_preview",
        "method": "isu_basic",
        "username": "meridian_isu",
        "password": "secret",
    }
    values.update(overrides)
    return WorkdayCredentials(**values)


# ------------------------------------------------------------- credentials


def test_missing_fields_are_reported_per_auth_method():
    """The form should mark every gap at once, not one per submission."""
    oauth = WorkdayCredentials(method="oauth_refresh_token")
    assert "Token endpoint" in oauth.missing()
    assert "Refresh token" in oauth.missing()
    # Basic-auth fields are not required when OAuth was chosen.
    assert "Password" not in oauth.missing()

    basic = WorkdayCredentials(method="isu_basic")
    assert "Password" in basic.missing()
    assert "Refresh token" not in basic.missing()


def test_username_is_qualified_once():
    """Workday wants `user@tenant`. A user who typed it already must not get
    `user@tenant@tenant`, which fails with an unhelpful auth error."""
    assert _basic_creds().qualified_username() == "meridian_isu@acme_preview"
    assert (
        _basic_creds(username="meridian_isu@acme_preview").qualified_username()
        == "meridian_isu@acme_preview"
    )


def test_host_normalisation_adds_scheme_but_keeps_pod():
    """Pod hostnames are not derivable, so whatever the customer pasted is
    preserved — only a missing scheme is filled in."""
    creds = _basic_creds(host="wd5-services1.myworkday.com/")
    assert creds.normalised_host() == "https://wd5-services1.myworkday.com"


def test_basic_auth_has_no_bearer_token():
    auth = WorkdayAuth(_basic_creds())
    assert not auth.uses_oauth
    with pytest.raises(WorkdayAuthError):
        auth.access_token()


def test_oauth_failure_explains_the_setup_mistake():
    """`invalid_client` maps to a specific tenant-setup error. Passing the raw
    OAuth code through would leave an admin guessing among six setup steps."""
    creds = _basic_creds(
        method="oauth_refresh_token",
        token_endpoint="https://wd2-impl-services1.workday.com/ccx/oauth2/acme_preview/token",
        client_id="cid",
        client_secret="secret",
        refresh_token="rt",
    )
    auth = WorkdayAuth(creds)

    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, json={"error": "invalid_client"})
    )
    with httpx.Client(transport=transport) as client:
        with pytest.raises(WorkdayAuthError) as exc:
            auth.access_token(client)

    assert "View API Clients" in str(exc.value)


def test_refresh_token_grant_is_used_not_client_credentials():
    """`client_credentials` is not verifiably available in Workday's
    'Register API Client for Integrations' task, so the connector must not
    depend on it."""
    creds = _basic_creds(
        method="oauth_refresh_token",
        token_endpoint="https://example.invalid/token",
        client_id="cid",
        client_secret="s",
        refresh_token="rt",
    )
    auth = WorkdayAuth(creds)
    assert auth._grant_payload()["grant_type"] == "refresh_token"


# -------------------------------------------------------------------- SOAP


def test_repeated_elements_become_lists():
    """Workday repeats sibling tags for plural data. Keeping only the last
    would silently discard most of a response."""
    xml = f"""
    <wd:Response_Data xmlns:wd="{WD}">
      <wd:Organization><wd:Name>One</wd:Name></wd:Organization>
      <wd:Organization><wd:Name>Two</wd:Name></wd:Organization>
      <wd:Organization><wd:Name>Three</wd:Name></wd:Organization>
    </wd:Response_Data>
    """
    parsed = element_to_dict(ElementTree.fromstring(xml))
    assert len(parsed["Organization"]) == 3
    assert parsed["Organization"][2]["Name"] == "Three"


def test_attributes_are_preserved():
    """`wd:Descriptor` carries the human-readable name and `wd:type`
    distinguishes a WID from a business key — both are real data."""
    xml = f"""
    <wd:Organization_Reference xmlns:wd="{WD}" wd:Descriptor="Global HR">
      <wd:ID wd:type="WID">abc123</wd:ID>
      <wd:ID wd:type="Organization_Reference_ID">GLOBAL_HR</wd:ID>
    </wd:Organization_Reference>
    """
    node = element_to_dict(ElementTree.fromstring(xml))
    assert descriptor(node) == "Global HR"
    assert reference_id(node, id_type="Organization_Reference_ID") == "GLOBAL_HR"


def test_reference_id_prefers_business_key_over_wid():
    """A WID is stable within a tenant but meaningless across them. The
    business key is what a human recognises and what survives a refresh."""
    xml = f"""
    <wd:Ref xmlns:wd="{WD}">
      <wd:ID wd:type="WID">3aa5550b7fe348b98d7b5741afc65534</wd:ID>
      <wd:ID wd:type="Location_ID">LOC-KL-01</wd:ID>
    </wd:Ref>
    """
    node = element_to_dict(ElementTree.fromstring(xml))
    assert reference_id(node) == "LOC-KL-01"


def test_reference_id_falls_back_to_wid_when_alone():
    xml = f'<wd:Ref xmlns:wd="{WD}"><wd:ID wd:type="WID">onlywid</wd:ID></wd:Ref>'
    node = element_to_dict(ElementTree.fromstring(xml))
    assert reference_id(node) == "onlywid"


def _soap_response(body_xml: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=(
            f'<?xml version="1.0"?>'
            f'<env:Envelope xmlns:env="{ENV}" xmlns:wd="{WD}">'
            f"<env:Body>{body_xml}</env:Body></env:Envelope>"
        ).encode(),
        headers={"content-type": "text/xml"},
    )


def test_paged_walks_every_page():
    """A tenant with more organisations than one page must not be truncated
    into a graph that looks complete."""
    pages = {
        1: ("A", 2),
        2: ("B", 2),
    }
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.content.decode().split("<wd:Page>")[1].split("<")[0])
        seen.append(page)
        name, total = pages[page]
        return _soap_response(
            f"<wd:Get_Organizations_Response>"
            f"<wd:Response_Results><wd:Total_Pages>{total}</wd:Total_Pages>"
            f"<wd:Total_Results>2</wd:Total_Results></wd:Response_Results>"
            f"<wd:Response_Data><wd:Organization>"
            f"<wd:Organization_Data><wd:Organization_Name>{name}</wd:Organization_Name>"
            f"</wd:Organization_Data></wd:Organization></wd:Response_Data>"
            f"</wd:Get_Organizations_Response>"
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    soap = WorkdaySoapClient(WorkdayAuth(_basic_creds()), "Staffing")
    result = soap.paged("Get_Organizations", response_key="Organization", client=client)

    assert seen == [1, 2]
    assert len(result.records) == 2


def test_soap_fault_is_explained():
    def handler(request: httpx.Request) -> httpx.Response:
        return _soap_response(
            f'<env:Fault xmlns:env="{ENV}">'
            f"<faultstring>Processing error occurred</faultstring>"
            f"</env:Fault>"
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    soap = WorkdaySoapClient(WorkdayAuth(_basic_creds()), "Staffing")

    with pytest.raises(WorkdaySoapError) as exc:
        soap.call("Get_Organizations", client=client)
    assert "cannot see the requested data" in str(exc.value)


def test_403_names_the_activation_step():
    """Forgetting 'Activate Pending Security Policy Changes' is the most common
    Workday setup failure and looks exactly like bad credentials."""
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(403, text="denied"))
    )
    soap = WorkdaySoapClient(WorkdayAuth(_basic_creds()), "Staffing")

    with pytest.raises(WorkdaySoapError) as exc:
        soap.call("Get_Organizations", client=client)
    assert "Activate Pending Security Policy Changes" in str(exc.value)


def test_ws_security_header_only_for_basic_auth():
    soap_basic = WorkdaySoapClient(WorkdayAuth(_basic_creds()), "Staffing")
    assert "UsernameToken" in soap_basic._security_header()

    oauth = _basic_creds(method="oauth_refresh_token")
    soap_oauth = WorkdaySoapClient(WorkdayAuth(oauth), "Staffing")
    assert soap_oauth._security_header() == ""


def test_credentials_are_xml_escaped():
    """A password containing `&` or `<` would otherwise produce malformed XML
    and an error that points nowhere near the real cause."""
    creds = _basic_creds(password="p&ss<word>")
    header = WorkdaySoapClient(WorkdayAuth(creds), "Staffing")._security_header()
    assert "p&amp;ss&lt;word&gt;" in header


def test_endpoint_pins_the_api_version():
    soap = WorkdaySoapClient(WorkdayAuth(_basic_creds()), "Human_Resources")
    assert soap.endpoint.endswith("/ccx/service/acme_preview/Human_Resources/v46.2")


# -------------------------------------------------------------------- RaaS


def test_single_row_report_is_still_a_list():
    """Workday returns an object rather than a list when a report yields
    exactly one row. Treating that as 'no rows' silently loses data."""
    assert _extract_rows({"Report_Entry": {"Name": "Only"}}) == [{"Name": "Only"}]


def test_empty_report_is_not_an_error():
    assert _extract_rows({}) == []


def test_field_value_reads_workday_descriptor_objects():
    """Report columns come back as bare strings or as
    `{Descriptor, ID}` depending on the field type."""
    row = {
        "Step_Type": "Approval",
        "Group": {"Descriptor": "Compensation Partner", "ID": "abc"},
    }
    assert field_value(row, "Step_Type") == "Approval"
    assert field_value(row, "Group") == "Compensation Partner"


def test_field_value_accepts_alternative_column_names():
    """Report authors rename columns. A rigid match would reject a report that
    is otherwise correct."""
    assert field_value({"Order": "3"}, "Step_Order", "Order") == "3"


def test_field_list_handles_repeating_columns():
    row = {"Members": [{"Descriptor": "HR Partner"}, {"Descriptor": "Manager"}]}
    assert field_list(row, "Members") == ["HR Partner", "Manager"]


# ------------------------------------------------------- report extraction


def _connector() -> WorkdayConnector:
    return WorkdayConnector(
        {
            "host": "https://wd2-impl-services1.workday.com",
            "tenant": "acme_preview",
            "method": "isu_basic",
            "username": "isu",
            "password": "x",
            "report_owner": "isu",
        }
    )


def test_bp_steps_build_an_ordered_chain():
    """The report gives position, not adjacency. NEXT_STEP is what makes the
    process a graph rather than a list, so it is derived by sorting."""
    rows = [
        {"Definition_ID": "BP_CHANGE_JOB", "Step_Order": "3", "Step_Type": "Approval",
         "Step_Name": "Comp Partner", "Group": "Compensation Partner"},
        {"Definition_ID": "BP_CHANGE_JOB", "Step_Order": "1", "Step_Type": "Initiation",
         "Step_Name": "Submit"},
        {"Definition_ID": "BP_CHANGE_JOB", "Step_Order": "2", "Step_Type": "Approval",
         "Step_Name": "Manager", "Group": "Manager",
         "Condition_Rule": "Grade Change"},
    ]
    records = list(_connector()._rows_bp_steps(rows))
    assert len(records) == 3

    by_order = {r.payload["order"]: r for r in records}

    # Every step belongs to its definition.
    for record in records:
        assert ("HAS_STEP", "workday:bp:BP_CHANGE_JOB") in record.relations

    # Order 1 → 2 → 3, derived from Step_Order rather than report row order.
    #
    # Either hop predicate counts: step 2 carries a condition rule, so the edge
    # entering it is CONDITIONAL_NEXT_STEP. What this asserts is that adjacency
    # is derived by sorting, not which of the two hops it turned out to be.
    hops = {"NEXT_STEP", "CONDITIONAL_NEXT_STEP"}
    first_next = [t for p, t in by_order["1"].relations if p in hops]
    assert first_next and first_next[0].endswith(_slug("2"))

    # The last step has no successor.
    assert not [p for p, _ in by_order["3"].relations if p in hops]

    # Approvers and condition rules become edges, not just text.
    assert ("APPROVED_BY", "workday:secgroup:manager") in by_order["2"].relations
    assert ("GOVERNED_BY", "workday:rule:grade-change") in by_order["2"].relations


def test_bp_step_order_tolerates_workday_suffixes():
    """Workday step order can be '2a'. A float() that throws would drop the
    step entirely."""
    rows = [
        {"Definition_ID": "BP", "Step_Order": "2a", "Step_Type": "Approval"},
        {"Definition_ID": "BP", "Step_Order": "1", "Step_Type": "Action"},
    ]
    records = list(_connector()._rows_bp_steps(rows))
    assert len(records) == 2


def test_calculated_fields_record_their_sources():
    rows = [
        {
            "Field_Name": "Length of Service",
            "Business_Object": "Worker",
            "Source_Fields": ["Hire Date", "Current Date"],
        }
    ]
    record = next(_connector()._rows_custom_fields(rows))
    assert record.payload["calculated"] is True
    assert ("HAS_FIELD", "workday:object:worker") in record.relations
    assert ("READS", "workday:field:hire-date") in record.relations


def test_bp_definition_scoped_to_an_organisation_links_to_it():
    rows = [
        {
            "Definition_ID": "BP_MY",
            "Business_Process_Definition": "Change Job — Malaysia",
            "Business_Process_Type": "Change Job",
            "Organization": "MY_ENTITY",
        }
    ]
    record = next(_connector()._rows_bp_definitions(rows))
    assert record.kind == "business_process"
    assert ("CONFIGURES", "workday:org:MY_ENTITY") in record.relations


def test_rows_without_identity_are_skipped():
    """A row with neither an id nor a name cannot be resolved to anything, and
    inventing a key for it would create an orphan node on every sync."""
    assert list(_connector()._rows_bp_definitions([{"Status": "Active"}])) == []
    assert list(_connector()._rows_condition_rules([{"Description": "x"}])) == []


def test_slug_is_stable_across_syncs():
    """Report rows often carry a name and nothing else, so the slug is the
    node identity. It must not drift between runs."""
    assert _slug("Compensation Partner") == "compensation-partner"
    assert _slug("Change Job — Malaysia") == _slug("Change Job — Malaysia")
    assert _slug("") == "unnamed"


# ------------------------------------------------------------ the pack


def test_every_report_declares_why_it_is_needed():
    """The pack asks a customer for real work. Each item must justify itself,
    or the setup screen becomes a list of demands."""
    for spec in REPORT_PACK:
        assert spec.why_report, f"{spec.id} has no justification"
        assert spec.data_source, f"{spec.id} does not say what to build it on"
        assert spec.produces, f"{spec.id} does not say what it yields"
        assert any(f.required for f in spec.fields)


def test_setup_steps_name_real_workday_tasks():
    """Paraphrased task names force an admin to guess between similar tasks,
    and guessing wrong creates an account that looks right and cannot
    authenticate."""
    tasks = {step["task"] for step in TENANT_SETUP_STEPS}
    assert "Create Integration System User" in tasks
    assert "Register API Client for Integrations" in tasks
    assert "Activate Pending Security Policy Changes" in tasks


def test_the_activation_step_is_flagged_critical():
    activate = next(
        s for s in TENANT_SETUP_STEPS if s["task"] == "Activate Pending Security Policy Changes"
    )
    assert activate.get("critical") is True


def test_report_building_is_optional():
    """A connector that cannot be tried until an analyst spends a day in the
    report builder does not get adopted."""
    reports = next(s for s in TENANT_SETUP_STEPS if s["id"] == "reports")
    assert reports.get("optional") is True


# ---------------------------------------------------------- form validation


def test_validation_asks_only_for_the_chosen_method():
    """An empty form must not demand every field from all three auth methods —
    including two different fields both labelled 'Integration System User',
    which is worse guidance than none."""
    from api.services.connections import validate_required

    empty = validate_required("cx-workday", {})
    assert empty == ["Workday host", "Tenant name", "Authentication method"]

    oauth = validate_required(
        "cx-workday", {"method": "oauth_refresh_token", "host": "h", "tenant": "t"}
    )
    assert "Refresh token" in oauth
    assert "Password" not in oauth

    basic = validate_required(
        "cx-workday", {"method": "isu_basic", "host": "h", "tenant": "t"}
    )
    assert basic == ["Integration System User", "Password"]


def test_validation_deduplicates_shared_labels():
    """Two auth methods can share a label; listing it twice reads as a bug."""
    from api.services.connections import validate_required

    result = validate_required(
        "cx-workday", {"method": "oauth_jwt", "host": "h", "tenant": "t"}
    )
    assert len(result) == len(set(result))


def test_secrets_are_split_from_settings():
    """Driven by the connector's declared fields, so a new connector cannot
    accidentally have a secret stored as a plain setting."""
    from api.services.connections import split_credentials

    secret, settings = split_credentials(
        "cx-workday",
        {
            "host": "https://example.workday.com",
            "client_secret": "shh",
            "refresh_token": "rt",
            "tenant": "acme",
        },
    )
    assert set(secret) == {"client_secret", "refresh_token"}
    assert set(settings) == {"host", "tenant"}
