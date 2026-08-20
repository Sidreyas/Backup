"""
Reports as a Service.

This is the most important module in the Workday connector, and the reason is
worth stating plainly: **Workday has no API that returns business process
definitions.** All eight `Business_Process` SOAP operations act on running
instances (approve, deny, cancel, rescind, send back, reassign); the only
`Get_*` among them returns delegations. There is no `Get_Business_Process_
Definition`, no `Get_Condition_Rules`, no `Get_Security_Groups`, and no read
API for custom or calculated fields.

Workday's *reporting* layer reaches all of it. A custom report built on the
right data source can expose business process definitions, their steps, the
security groups on each step, condition rules, custom fields and calculated
fields — and RaaS turns any Advanced report into an HTTP endpoint.

The consequence for the product is structural: the Workday connector cannot be
purely self-service. The customer has to create reports in their tenant before
the deep configuration is reachable. Meridian's job is to make that as close to
mechanical as possible — hence `reports.py`, which defines exactly which
reports are needed and what each one must contain, and the setup guidance the
API hands to the UI.

RaaS accepts both Basic (ISU) and Bearer auth, unlike REST which is Bearer
only. That matters because RaaS is the surface carrying the configuration, so
it must work whichever auth method the customer's security team permitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from api.connectors.base import ConnectorError
from api.connectors.workday.auth import WorkdayAuth


class RaasError(ConnectorError):
    """A RaaS call failed in a way the operator can act on."""


@dataclass(slots=True)
class RaasResponse:
    rows: list[dict[str, Any]]
    #: The report as invoked, for evidence and for the error message when a
    #: customer's report is named differently from the pack's expectation.
    url: str


class RaasClient:
    """Invokes custom reports exposed as web services."""

    def __init__(self, auth: WorkdayAuth, *, timeout: float = 180.0) -> None:
        self.auth = auth
        self.timeout = timeout

    def url_for(self, owner: str, report: str, *, fmt: str = "json") -> str:
        """The `customreport2` form, which is current for Advanced reports.

        The older `/ccx/service/{tenant}/{owner}/{report}` form still resolves
        in many tenants, but only `customreport2` is documented as current, and
        mixing the two produces failures that look like permission problems.
        """
        creds = self.auth.credentials
        return (
            f"{creds.normalised_host()}/ccx/service/customreport2/"
            f"{creds.tenant}/{owner}/{report}?format={fmt}"
        )

    def fetch(
        self,
        owner: str,
        report: str,
        *,
        params: dict[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> RaasResponse:
        """Invoke one report and return its rows."""
        url = self.url_for(owner, report)
        auth_kwargs = self.auth.raas_auth_kwargs(client)

        headers = {"Accept": "application/json"}
        headers.update(auth_kwargs.pop("headers", {}))

        owns_client = client is None
        http_client = client or httpx.Client(timeout=self.timeout)
        try:
            response = http_client.get(
                url, params=params or {}, headers=headers, **auth_kwargs
            )
        except httpx.HTTPError as exc:
            raise RaasError(f"Could not reach the Workday report {report}: {exc}") from exc
        finally:
            if owns_client:
                http_client.close()

        if response.status_code == 404:
            raise RaasError(
                f"Workday has no report '{report}' owned by '{owner}'. Check the "
                "report name and owner exactly as they appear in Workday, and "
                "confirm 'Enable As Web Service' is ticked on its Advanced tab."
            )
        if response.status_code in {401, 403}:
            raise RaasError(
                f"The Integration System User cannot run '{report}'. Share the "
                "report with the ISU's security group — an unshared report "
                "returns a permission error rather than empty data."
            )
        if response.status_code >= 400:
            raise RaasError(
                f"Workday returned {response.status_code} for report '{report}'."
            )

        # A report that returns HTML is almost always a login redirect — the
        # credentials were rejected in a way that produced a page rather than
        # a status code, and reporting "no rows" would hide that entirely.
        content_type = response.headers.get("content-type", "")
        if "html" in content_type.lower():
            raise RaasError(
                f"Workday returned an HTML page for '{report}' instead of data. "
                "This usually means the credentials were not accepted."
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise RaasError(
                f"Workday returned a non-JSON response for '{report}'. Confirm the "
                "report is an Advanced report — Simple reports cannot be exposed "
                "as a web service."
            ) from exc

        return RaasResponse(rows=_extract_rows(body), url=url)

    def probe(
        self, owner: str, report: str, *, client: httpx.Client | None = None
    ) -> tuple[bool, str]:
        """Check whether a report exists and is readable, without failing a run.

        Used by capability discovery, so the connection screen can tell the
        customer which of the pack's reports are still missing rather than
        failing the whole extraction on the first absent one.
        """
        try:
            result = self.fetch(owner, report, client=client)
        except RaasError as exc:
            return False, str(exc)
        return True, f"{len(result.rows)} row(s) returned."


def _extract_rows(body: Any) -> list[dict[str, Any]]:
    """Pull the row list out of a RaaS JSON payload.

    Workday wraps rows in `{"Report_Entry": [...]}`. A report returning exactly
    one row yields an object rather than a list, and a report returning none
    omits the key entirely — both are normal and neither is an error.
    """
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]

    if not isinstance(body, dict):
        return []

    entries = body.get("Report_Entry")
    if isinstance(entries, list):
        return [row for row in entries if isinstance(row, dict)]
    if isinstance(entries, dict):
        return [entries]

    # Some tenants return the rows at the top level under a different wrapper.
    # Taking the first list-of-dicts value is a heuristic, and it is applied
    # only after the documented shape has been ruled out.
    for value in body.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value

    return []


def field_value(row: dict[str, Any], *names: str) -> str:
    """Read a field from a report row, tolerating naming variation.

    Report column names are chosen by whoever built the report. The pack
    specifies exact names, but customers rename columns, so each lookup accepts
    several spellings before giving up. Workday also returns some fields as
    `{"Descriptor": ..., "ID": ...}` rather than a bare string.
    """
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("Descriptor", "descriptor", "#text", "ID", "value"):
                if key in value and isinstance(value[key], str):
                    return value[key].strip()
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str):
                return first.strip()
            if isinstance(first, dict):
                for key in ("Descriptor", "descriptor", "#text"):
                    if key in first and isinstance(first[key], str):
                        return first[key].strip()
    return ""


def field_list(row: dict[str, Any], *names: str) -> list[str]:
    """Read a repeating field as a list of display strings."""
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if isinstance(value, list):
            out = []
            for item in value:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
                elif isinstance(item, dict):
                    text = field_value({"v": item}, "v")
                    if text:
                        out.append(text)
            return out
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, dict):
            text = field_value({"v": value}, "v")
            return [text] if text else []
    return []
