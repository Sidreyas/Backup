"""
Workday Query Language.

A SQL-like language over the same data sources custom reports are built on:

    SELECT planName, unitOfTime FROM timeOffPlans

Why this is worth having when the connector already reads SOAP, RaaS and
screens: **it removes the nine reports from the customer's setup.** RaaS reaches
business process definitions and condition rules, which no API returns — but only
through reports somebody has to build first, as Advanced, web-service enabled, and
shared with the right group. Three settings, each of which fails silently when
missed. WQL queries the same data sources directly, so the ask becomes one
security domain instead of nine report-building exercises.

What it does not fix:

  - **Still OAuth-only.** The API is bearer-token only, exactly like REST. An
    Integration System User cannot use it, so this does not unblock a tenant
    without one — it makes the tenant *with* one much cheaper to set up.
  - **Read-only, permanently.** That is a feature here rather than a limitation.

**Calculated fields are addressable, and it is worth being precise about that.**
Workday states plainly that "Workday creates aliases for calculated fields,
whether Workday-delivered or not". So a calculated field can be named in a SELECT
like any other field. The limitation that circulates in third-party guides — that
report-to-WQL *conversion* drops calculated fields — is about the automated
conversion feature, not about whether the field can be queried. Conflating the two
understates WQL considerably.

What remains genuinely open is **value versus definition**, and it is the
distinction this whole connector turns on. Selecting a calculated field returns
what it *evaluates to* for each row. Meridian needs what it *is* — the lookup
bands behind "HKG Annual Leave Days Entitlement", the seven-days-rising-to-
fourteen. A column of computed numbers per worker is not that, and is worker data
we deliberately refuse.

`fields()` is the hopeful path: it returns a data source's fields as metadata
rather than as values, which is the right *kind* of answer. Whether the payload
carries a calculated field's formula or only its name, type and alias is a
question for a live tenant, not for documentation — so this module reports the
whole field payload rather than a curated subset, precisely so that question can
be answered from a real response.

`dataSources()` is the interesting call, more than `query()`. It answers what this
tenant will let us reach, from the tenant itself, rather than from documentation
about what Workday tenants generally contain. Everything else in this module
exists to act on that answer.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from api.connectors.base import ConnectorError
from api.connectors.workday.auth import WorkdayAuth, WorkdayAuthError

#: Above this, Workday requires POST rather than GET, because the query travels
#: in the query string otherwise. Documented as 2,048; the margin avoids arguing
#: about whether the limit counts the encoded or the raw form.
MAX_QUERY_IN_URL = 1_900

#: Rows per request. Workday caps a *response* at roughly a million populated
#: cells, which is a cell budget rather than a row count — so the safe page size
#: depends on how many columns the query selects. A thousand rows of a
#: twenty-column query is comfortably inside it; a thousand rows of a
#: two-hundred-column query is not, which is why `paged` accepts an override.
DEFAULT_PAGE_SIZE = 1_000

#: A stop on total rows per call to `paged`.
#:
#: Not a Workday limit — ours. An unbounded generator over a live tenant is how
#: an extraction becomes an outage, and the failure is asymmetric: pulling too
#: few rows produces a visible gap, pulling too many degrades the customer's
#: production system while looking like progress.
MAX_ROWS = 200_000


class WorkdayWqlError(ConnectorError):
    """A WQL call failed in a way the operator can act on."""


@dataclass(slots=True)
class WqlDataSource:
    """One data source WQL can query in this tenant.

    `alias` is what a query says after FROM. A source with no alias is listed in
    the tenant but not WQL-queryable, and keeping those rather than filtering them
    out is deliberate: "this data source exists and WQL cannot reach it" is the
    single most useful thing this module can report.
    """

    alias: str
    label: str = ""
    description: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def queryable(self) -> bool:
        return bool(self.alias)


@dataclass(slots=True)
class WqlField:
    """One field of a data source.

    `calculated` is inferred rather than asserted. Workday's field payload does
    not advertise a single reliable "this is a calculated field" flag across
    releases, so this reads whatever the response offers and falls back to False.
    Guessing True from a name pattern would be worse than not knowing: a stored
    field mislabelled as calculated would send someone looking for a formula that
    does not exist.
    """

    alias: str
    label: str = ""
    type: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def calculated(self) -> bool:
        for key in ("calculated", "isCalculated", "calculatedField"):
            value = self.raw.get(key)
            if isinstance(value, bool):
                return value
        return "calculated" in str(self.type).lower()


@dataclass(slots=True)
class WqlPage:
    """One page of results."""

    rows: list[dict[str, Any]]
    total: int | None = None
    offset: int = 0
    limit: int = 0

    @property
    def exhausted(self) -> bool:
        """Whether this page is the last one.

        Judged by a short page rather than by comparing against `total`: Workday
        does not always populate a total, and treating an absent total as zero
        would end pagination after the first page while looking like a complete
        extraction.
        """
        return len(self.rows) < self.limit if self.limit else True


class WqlClient:
    """Reads Workday data sources through WQL."""

    def __init__(self, auth: WorkdayAuth, *, timeout: float = 180.0) -> None:
        self.auth = auth
        self.timeout = timeout

    @property
    def available(self) -> bool:
        """Whether this connection can use WQL at all.

        Mirrors `WorkdayRestClient.available`, and for the same reason: an
        ISU-credentialled connection is perfectly good for SOAP and reports, and
        reporting WQL as unavailable is more useful than raising on a connection
        that is working as designed.
        """
        return self.auth.uses_oauth

    # --- urls ---------------------------------------------------------------

    def _base(self) -> str:
        creds = self.auth.credentials
        return f"{creds.normalised_host()}/ccx/api/wql/v1/{creds.tenant}"

    def data_url(self) -> str:
        return f"{self._base()}/data"

    def sources_url(self) -> str:
        return f"{self._base()}/dataSources"

    # --- plumbing -----------------------------------------------------------

    def _request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        client: httpx.Client | None = None,
        what: str,
    ) -> dict[str, Any]:
        if not self.available:
            raise WorkdayWqlError(
                "WQL requires OAuth. This connection uses Integration System "
                "User credentials, which Workday accepts for SOAP and reports "
                "but not for WQL."
            )

        owns_client = client is None
        http = client or httpx.Client(timeout=self.timeout)
        try:
            headers = self.auth.rest_headers(http)
            if json_body is not None:
                response = http.post(url, headers=headers, json=json_body)
            else:
                response = http.get(url, headers=headers, params=params or {})
        except WorkdayAuthError as exc:
            # Surfaced as a WQL error rather than propagating: callers guard the
            # WQL surface, and an auth class escaping from inside a query is how
            # a guarded call ends an entire extraction.
            raise WorkdayWqlError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise WorkdayWqlError(f"Could not reach the WQL API: {exc}") from exc
        finally:
            if owns_client:
                http.close()

        if response.status_code == 404:
            raise WorkdayWqlError(
                "This tenant does not expose the WQL API. Either the Workday "
                "Query Language service is not enabled, or the host is wrong — "
                "copy it from 'View API Clients' rather than building it from "
                "the tenant name."
            )
        if response.status_code in {401, 403}:
            raise WorkdayWqlError(
                "The API client is not authorised for WQL. It needs the "
                "'Workday Query Language' domain in the System functional area, "
                "and the API client must include System in its scope — the "
                "Integration functional area alone is not enough."
            )
        if response.status_code == 400:
            raise WorkdayWqlError(
                f"Workday rejected the {what}: {_first_error(response)}"
            )
        if response.status_code >= 400:
            raise WorkdayWqlError(
                f"Workday returned {response.status_code} for the {what}."
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise WorkdayWqlError(
                f"The WQL response for the {what} was not valid JSON."
            ) from exc
        if not isinstance(body, dict):
            raise WorkdayWqlError(f"The WQL response for the {what} was not an object.")
        return body

    # --- calls --------------------------------------------------------------

    def data_sources(
        self, *, client: httpx.Client | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> list[WqlDataSource]:
        """Every data source this tenant exposes to WQL.

        The most valuable call here. It answers, from the tenant, which
        configuration WQL can reach — including whether business process
        definitions are among them, which decides whether WQL can replace the
        report pack or only supplement it.
        """
        body = self._request(
            self.sources_url(),
            params={"limit": limit},
            client=client,
            what="data source list",
        )
        out: list[WqlDataSource] = []
        for row in body.get("data") or []:
            if not isinstance(row, dict):
                continue
            out.append(
                WqlDataSource(
                    alias=str(row.get("alias") or ""),
                    label=str(row.get("descriptor") or row.get("label") or ""),
                    description=str(row.get("description") or ""),
                    raw=row,
                )
            )
        return out

    def fields(
        self,
        data_source_id: str,
        *,
        client: httpx.Client | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[WqlField]:
        """Every field of one data source, with its alias.

        Metadata rather than values, which is what makes this the interesting
        call. `data_sources()` says which tables exist; this says what is inside
        one, including the calculated fields — Workday assigns those aliases too,
        so they appear here alongside stored fields.

        The full payload for each field is kept in `raw`. Deliberately: whether a
        calculated field's *definition* travels with it is the open question this
        method exists to answer, and a curated subset would discard the answer
        before anyone could read it.
        """
        if not data_source_id:
            raise WorkdayWqlError("A data source id is required to list fields.")

        body = self._request(
            f"{self.sources_url()}/{data_source_id}/fields",
            params={"limit": limit},
            client=client,
            what=f"field list for data source {data_source_id}",
        )
        out: list[WqlField] = []
        for row in body.get("data") or []:
            if not isinstance(row, dict):
                continue
            out.append(
                WqlField(
                    alias=str(row.get("alias") or ""),
                    label=str(row.get("descriptor") or row.get("label") or ""),
                    type=str(row.get("type") or row.get("fieldType") or ""),
                    raw=row,
                )
            )
        return out

    def query(
        self,
        wql: str,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        client: httpx.Client | None = None,
    ) -> WqlPage:
        """Run one query and return one page."""
        wql = wql.strip()
        if not wql:
            raise WorkdayWqlError("An empty WQL query was passed.")

        params = {"query": wql, "limit": limit, "offset": offset}
        # Long queries move to POST because Workday rejects them in the URL. The
        # threshold is on the query alone rather than the whole URL: the host and
        # tenant are known short, and measuring the assembled URL would make the
        # choice depend on tenant name length.
        if len(wql) > MAX_QUERY_IN_URL:
            body = self._request(
                self.data_url(), json_body=params, client=client, what="query"
            )
        else:
            body = self._request(
                self.data_url(), params=params, client=client, what="query"
            )

        rows = [r for r in (body.get("data") or []) if isinstance(r, dict)]
        total = body.get("total")
        return WqlPage(
            rows=rows,
            total=int(total) if isinstance(total, int) else None,
            offset=offset,
            limit=limit,
        )

    def paged(
        self,
        wql: str,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_rows: int = MAX_ROWS,
        client: httpx.Client | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Every row, following offsets until the pages run out.

        Stops at `max_rows` and raises rather than truncating quietly. A silent
        cut produces a partial extraction that looks complete, and the graph would
        then record the absence of the remaining rows as fact.
        """
        offset = 0
        seen = 0
        while True:
            page = self.query(wql, limit=page_size, offset=offset, client=client)
            for row in page.rows:
                yield row
                seen += 1
                if seen >= max_rows:
                    raise WorkdayWqlError(
                        f"The WQL query returned more than {max_rows:,} rows. "
                        "Narrow it with a WHERE clause rather than accepting a "
                        "partial result — a truncated extraction is "
                        "indistinguishable from a complete one once it is in the "
                        "graph."
                    )
            if page.exhausted or not page.rows:
                return
            offset += len(page.rows)

    def probe(self, *, client: httpx.Client | None = None) -> tuple[bool, str]:
        """Check WQL without failing a run.

        Mirrors `RaasClient.probe` and `WorkdayRestClient.probe`, so capability
        discovery can report WQL alongside the other surfaces instead of stopping
        at the first one that is unavailable.
        """
        if not self.available:
            return False, (
                "WQL needs OAuth; this connection uses Integration System User "
                "credentials."
            )
        try:
            sources = self.data_sources(client=client, limit=1)
        except WorkdayWqlError as exc:
            return False, str(exc)
        return True, f"WQL reachable; {len(sources)} data source(s) in the first page."


def _first_error(response: httpx.Response) -> str:
    """The most specific message Workday gave, or the raw body.

    WQL syntax errors are the common 400 here, and the message names the offending
    token — worth surfacing verbatim rather than replacing with our own summary.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        for key in ("error", "message", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                return str(first.get("error") or first.get("message") or first)
            return str(first)
    return response.text[:300]
