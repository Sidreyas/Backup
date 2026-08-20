"""
Workday Query Language.

Two things are worth testing here, and neither is "does it parse JSON".

The first is that WQL reports its own unavailability instead of raising. WQL is
OAuth-only, and most connections in this product are not — an ISU connection that
looked broken because WQL is absent would send someone to fix a connection that
works.

The second is pagination honesty. A query language over a customer's live tenant
has two failure modes that look identical from the outside: stopping early, and
never stopping. Both produce a graph that claims to be complete, so the tests
here pin down exactly when paging ends and what happens when it should not have
started.
"""

from __future__ import annotations

import httpx
import pytest

from api.connectors.workday.auth import WorkdayAuth, WorkdayCredentials
from api.connectors.workday.wql import (
    DEFAULT_PAGE_SIZE,
    MAX_QUERY_IN_URL,
    WorkdayWqlError,
    WqlClient,
)

HOST = "https://wcpdev.wd101.myworkday.com"
TENANT = "aia_wcpdev1"


def _oauth_auth() -> WorkdayAuth:
    return WorkdayAuth(
        WorkdayCredentials(
            host=HOST,
            tenant=TENANT,
            method="oauth_refresh_token",
            client_id="cid",
            client_secret="secret",
            refresh_token="refresh",
            token_endpoint=f"{HOST}/ccx/oauth2/{TENANT}/token",
        )
    )


def _isu_auth() -> WorkdayAuth:
    return WorkdayAuth(
        WorkdayCredentials(
            host=HOST,
            tenant=TENANT,
            method="isu_basic",
            username="isu",
            password="pw",
        )
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _token_or(handler):
    """Answer the token request, then delegate everything else."""

    def routed(request: httpx.Request) -> httpx.Response:
        if "token" in request.url.path:
            return httpx.Response(
                200, json={"access_token": "tok", "expires_in": 3600}
            )
        return handler(request)

    return routed


# --- availability -----------------------------------------------------------


def test_an_isu_connection_reports_wql_unavailable_rather_than_raising():
    """An ISU connection is not broken. It simply cannot use WQL."""
    wql = WqlClient(_isu_auth())

    assert wql.available is False
    ok, message = wql.probe()
    assert ok is False
    assert "OAuth" in message


def test_using_wql_on_an_isu_connection_explains_which_surfaces_do_work():
    """The error has to say what the credentials *are* good for.

    Otherwise the reader concludes the credentials are wrong and goes to rotate
    them, when the actual answer is that WQL needs a different auth method.
    """
    wql = WqlClient(_isu_auth())

    with pytest.raises(WorkdayWqlError) as raised:
        wql.query("SELECT planName FROM timeOffPlans")

    assert "SOAP and reports" in str(raised.value)


# --- urls -------------------------------------------------------------------


def test_the_url_follows_the_ccx_api_convention():
    """Built the same way as the REST client, which is proven against a tenant.

    Worth pinning: probing this tenant on the UI host returned an HTML 404 for
    every path including real ones, so a wrong prefix here would be invisible
    until it looked like "WQL is not enabled".
    """
    wql = WqlClient(_oauth_auth())

    assert wql.data_url() == f"{HOST}/ccx/api/wql/v1/{TENANT}/data"
    assert wql.sources_url() == f"{HOST}/ccx/api/wql/v1/{TENANT}/dataSources"


# --- data sources -----------------------------------------------------------


def test_data_sources_are_returned_with_their_aliases():
    """The alias is what a query says after FROM."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"alias": "timeOffPlans", "descriptor": "Time Off Plans"},
                    {"alias": "allWorkers", "descriptor": "All Workers"},
                ]
            },
        )

    with _client(_token_or(handler)) as client:
        sources = WqlClient(_oauth_auth()).data_sources(client=client)

    assert [s.alias for s in sources] == ["timeOffPlans", "allWorkers"]
    assert sources[0].label == "Time Off Plans"
    assert all(s.queryable for s in sources)


def test_a_data_source_without_an_alias_is_kept_and_marked_unqueryable():
    """"Exists but WQL cannot reach it" is the most useful thing to report.

    Filtering these out would turn the answer to "can WQL replace the report
    pack" from "no, and here is what it misses" into a shorter list that looks
    like full coverage.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"alias": "timeOffPlans", "descriptor": "Time Off Plans"},
                    {"descriptor": "Business Process Definitions"},
                ]
            },
        )

    with _client(_token_or(handler)) as client:
        sources = WqlClient(_oauth_auth()).data_sources(client=client)

    assert len(sources) == 2
    unqueryable = [s for s in sources if not s.queryable]
    assert [s.label for s in unqueryable] == ["Business Process Definitions"]


# --- queries ----------------------------------------------------------------


def test_a_short_query_goes_in_the_url():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["query"] = request.url.params.get("query")
        return httpx.Response(200, json={"data": [{"planName": "HKG Annual Leave"}]})

    with _client(_token_or(handler)) as client:
        page = WqlClient(_oauth_auth()).query(
            "SELECT planName FROM timeOffPlans", client=client
        )

    assert seen["method"] == "GET"
    assert seen["query"] == "SELECT planName FROM timeOffPlans"
    assert page.rows == [{"planName": "HKG Annual Leave"}]


def test_a_long_query_switches_to_post():
    """Workday rejects a query too long for the URL.

    Discovering that as a 400 mid-extraction, on the one query broad enough to
    matter, is the failure this avoids.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        return httpx.Response(200, json={"data": []})

    long_query = "SELECT " + ", ".join(f"field{i}" for i in range(400)) + " FROM x"
    assert len(long_query) > MAX_QUERY_IN_URL

    with _client(_token_or(handler)) as client:
        WqlClient(_oauth_auth()).query(long_query, client=client)

    assert seen["method"] == "POST"


def test_an_empty_query_is_refused_before_a_request_is_made():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": []})

    with _client(_token_or(handler)) as client:
        with pytest.raises(WorkdayWqlError):
            WqlClient(_oauth_auth()).query("   ", client=client)

    assert calls == [], "an empty query must not reach the tenant"


# --- pagination -------------------------------------------------------------


def test_paging_follows_offsets_until_a_short_page():
    pages = [
        [{"n": i} for i in range(3)],
        [{"n": i} for i in range(3, 6)],
        [{"n": 6}],
    ]
    seen_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", 0))
        seen_offsets.append(offset)
        index = offset // 3
        data = pages[index] if index < len(pages) else []
        return httpx.Response(200, json={"data": data})

    with _client(_token_or(handler)) as client:
        rows = list(
            WqlClient(_oauth_auth()).paged(
                "SELECT n FROM x", page_size=3, client=client
            )
        )

    assert [r["n"] for r in rows] == [0, 1, 2, 3, 4, 5, 6]
    assert seen_offsets == [0, 3, 6]


def test_a_missing_total_does_not_end_paging_after_one_page():
    """Workday does not always populate `total`.

    Treating an absent total as zero would stop after the first page and look
    like a complete extraction — the exact failure this product exists to avoid.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", 0))
        data = [{"n": offset}, {"n": offset + 1}] if offset < 4 else []
        return httpx.Response(200, json={"data": data})  # no "total"

    with _client(_token_or(handler)) as client:
        wql = WqlClient(_oauth_auth())
        first = wql.query("SELECT n FROM x", limit=2, client=client)
        rows = list(wql.paged("SELECT n FROM x", page_size=2, client=client))

    # The page genuinely carries no total, so the test is exercising the case it
    # claims to: paging continued on page length alone.
    assert first.total is None
    assert first.exhausted is False
    assert len(rows) == 4


def test_exceeding_the_row_cap_raises_rather_than_truncating():
    """A truncated extraction is indistinguishable from a complete one."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"n": 1}, {"n": 2}]})

    with _client(_token_or(handler)) as client:
        gen = WqlClient(_oauth_auth()).paged(
            "SELECT n FROM x", page_size=2, max_rows=3, client=client
        )
        with pytest.raises(WorkdayWqlError) as raised:
            list(gen)

    assert "Narrow it with a WHERE clause" in str(raised.value)


# --- errors -----------------------------------------------------------------


def test_a_403_names_the_domain_and_the_functional_area():
    """The remedy is two specific settings, so the error states both.

    "Not authorised" alone sends an administrator to the Integration functional
    area, which is where every other Workday integration lives and is the wrong
    place for this one.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied")

    with _client(_token_or(handler)) as client:
        with pytest.raises(WorkdayWqlError) as raised:
            WqlClient(_oauth_auth()).data_sources(client=client)

    message = str(raised.value)
    assert "Workday Query Language" in message
    assert "System" in message


def test_a_404_warns_against_a_reconstructed_host():
    """The trap this project already documented for the token endpoint.

    A guessed Workday host usually resolves to a real one that rejects the
    request, so a 404 here is at least as likely to be a wrong host as a disabled
    service.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="<html>not found</html>")

    with _client(_token_or(handler)) as client:
        with pytest.raises(WorkdayWqlError) as raised:
            WqlClient(_oauth_auth()).query("SELECT a FROM b", client=client)

    assert "View API Clients" in str(raised.value)


def test_a_syntax_error_is_surfaced_verbatim():
    """Workday names the offending token; our own summary would lose it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"errors": [{"error": "Unexpected token 'FORM' at position 24"}]}
        )

    with _client(_token_or(handler)) as client:
        with pytest.raises(WorkdayWqlError) as raised:
            WqlClient(_oauth_auth()).query("SELECT a FORM b", client=client)

    assert "Unexpected token 'FORM' at position 24" in str(raised.value)


def test_an_auth_failure_inside_a_query_surfaces_as_a_wql_error():
    """A guarded WQL call must not end an extraction with an auth class.

    This is the bug that cost a run earlier in this project: the absence reports
    path caught `RaasError` but not `WorkdayAuthError`, and the token failure
    escaped through `snapshot` and took browser discovery with it.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if "token" in request.url.path:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"data": []})

    with _client(handler) as client:
        with pytest.raises(WorkdayWqlError):
            WqlClient(_oauth_auth()).query("SELECT a FROM b", client=client)


def test_a_non_json_response_is_reported_as_such():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    with _client(_token_or(handler)) as client:
        with pytest.raises(WorkdayWqlError) as raised:
            WqlClient(_oauth_auth()).data_sources(client=client)

    assert "not valid JSON" in str(raised.value)


def test_probe_reports_reachability_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"alias": "timeOffPlans"}]})

    with _client(_token_or(handler)) as client:
        ok, message = WqlClient(_oauth_auth()).probe(client=client)

    assert ok is True
    assert "reachable" in message


def test_probe_reports_a_failure_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied")

    with _client(_token_or(handler)) as client:
        ok, message = WqlClient(_oauth_auth()).probe(client=client)

    assert ok is False
    assert "Workday Query Language" in message


def test_the_default_page_size_is_not_the_row_cap():
    """Two different numbers doing two different jobs.

    Collapsing them would make one page the whole extraction.
    """
    from api.connectors.workday.wql import MAX_ROWS

    assert DEFAULT_PAGE_SIZE < MAX_ROWS


# --- field metadata ---------------------------------------------------------
#
# Added after a documented correction. Workday states that "Workday creates
# aliases for calculated fields, whether Workday-delivered or not", so calculated
# fields are addressable in WQL. The limitation that circulates elsewhere — that
# report-to-WQL *conversion* drops them — is about the conversion feature, not
# about whether the field can be queried, and conflating the two understated WQL.


def test_fields_are_returned_with_their_aliases():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/dataSources/ds-1/fields")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"alias": "planName", "descriptor": "Plan Name", "type": "text"},
                    {
                        "alias": "hkgAnnualLeaveDaysEntitlement",
                        "descriptor": "HKG Annual Leave Days Entitlement",
                        "type": "Calculated Field",
                    },
                ]
            },
        )

    with _client(_token_or(handler)) as client:
        fields = WqlClient(_oauth_auth()).fields("ds-1", client=client)

    assert [f.alias for f in fields] == [
        "planName",
        "hkgAnnualLeaveDaysEntitlement",
    ]
    assert fields[1].label == "HKG Annual Leave Days Entitlement"


def test_a_calculated_field_is_recognised_from_an_explicit_flag():
    """An explicit boolean is believed over any name heuristic."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"alias": "a", "type": "text", "isCalculated": True},
                    {"alias": "b", "type": "text", "isCalculated": False},
                ]
            },
        )

    with _client(_token_or(handler)) as client:
        fields = WqlClient(_oauth_auth()).fields("ds-1", client=client)

    assert fields[0].calculated is True
    assert fields[1].calculated is False


def test_an_unflagged_field_is_not_guessed_to_be_calculated():
    """False beats a guess.

    A stored field mislabelled as calculated sends someone hunting for a formula
    that was never there, which costs more than not knowing.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"alias": "planName", "type": "text"}]}
        )

    with _client(_token_or(handler)) as client:
        fields = WqlClient(_oauth_auth()).fields("ds-1", client=client)

    assert fields[0].calculated is False


def test_the_whole_field_payload_is_kept():
    """The open question is whether a definition travels with the field.

    A curated subset would discard the answer before it could be read, so the raw
    payload is retained even when this module has no use for the extra keys.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "alias": "entitlement",
                        "type": "Calculated Field",
                        "formula": "lookup(yearsOfService)",
                        "someFutureKey": {"nested": 1},
                    }
                ]
            },
        )

    with _client(_token_or(handler)) as client:
        fields = WqlClient(_oauth_auth()).fields("ds-1", client=client)

    assert fields[0].raw["formula"] == "lookup(yearsOfService)"
    assert fields[0].raw["someFutureKey"] == {"nested": 1}


def test_listing_fields_without_a_data_source_id_is_refused_before_a_request():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": []})

    with _client(_token_or(handler)) as client:
        with pytest.raises(WorkdayWqlError):
            WqlClient(_oauth_auth()).fields("", client=client)

    assert calls == []
