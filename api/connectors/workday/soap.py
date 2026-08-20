"""
A minimal Workday SOAP client.

Hand-rolled rather than `zeep`. Workday's WSDLs are enormous — the
`Human_Resources` schema alone is tens of megabytes — and parsing them at
runtime costs seconds per service and hundreds of megabytes of memory for a
handful of `Get_*` calls whose request shape is three elements deep. Building
the envelope directly is less code, starts instantly, and fails in ways that
point at the actual problem.

The trade is that this client does not validate requests against the schema. It
does not need to: every request it sends is constructed here from a fixed
template, not from user input.

Responses are parsed into plain dictionaries with namespaces stripped. Workday
responses nest six or seven levels deep with a `wd:` prefix on every element,
and carrying that into the normaliser would put XML plumbing into code whose
job is domain mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

import httpx

from api.connectors.base import ConnectorError
from api.connectors.workday.auth import WorkdayAuth

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
WSSE_NS = (
    "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
)
WD_NS = "urn:com.workday/bsvc"

# Workday caps most Get_* responses at 999 per page. Requesting more is
# silently clamped, so the ceiling is stated rather than discovered.
MAX_PAGE_SIZE = 999

# A run stops here regardless of what the tenant holds. An unbounded extraction
# against a large tenant would run for hours; the cap is reported by the
# pipeline rather than applied silently.
MAX_PAGES = 50


class WorkdaySoapError(ConnectorError):
    """A SOAP fault or transport failure, phrased for an operator."""


@dataclass(slots=True)
class SoapResult:
    records: list[dict[str, Any]]
    total_pages: int
    total_results: int


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def element_to_dict(element: ElementTree.Element) -> Any:
    """Collapse an XML subtree into dictionaries, lists and strings.

    Repeated sibling tags become a list. Workday uses repetition for
    genuinely-plural things (multiple `Integration_System_Data` blocks), so
    keeping only the last would silently discard most of a response.

    Attributes are preserved with an `@` prefix because Workday puts real data
    there — `wd:Descriptor` on a reference carries the human-readable name, and
    `wd:type` distinguishes a WID from a Reference ID.
    """
    result: dict[str, Any] = {}

    for key, value in element.attrib.items():
        result[f"@{_strip_ns(key)}"] = value

    children = list(element)
    if not children:
        text = (element.text or "").strip()
        if not result:
            return text
        if text:
            result["#text"] = text
        return result

    for child in children:
        name = _strip_ns(child.tag)
        value = element_to_dict(child)
        if name in result:
            existing = result[name]
            if isinstance(existing, list):
                existing.append(value)
            else:
                result[name] = [existing, value]
        else:
            result[name] = value

    return result


class WorkdaySoapClient:
    """Calls one Workday SOAP service."""

    def __init__(self, auth: WorkdayAuth, service: str, *, timeout: float = 120.0) -> None:
        self.auth = auth
        self.service = service
        self.timeout = timeout

    @property
    def endpoint(self) -> str:
        creds = self.auth.credentials
        return (
            f"{creds.normalised_host()}/ccx/service/"
            f"{creds.tenant}/{self.service}/{creds.api_version}"
        )

    def _security_header(self) -> str:
        """WS-Security for basic auth; empty for OAuth.

        Workday accepts a bearer token on SOAP in place of the WS-Security
        header, so the two paths differ only here.
        """
        if self.auth.credentials.method != "isu_basic":
            return ""
        creds = self.auth.credentials
        return (
            f'<soapenv:Header><wsse:Security soapenv:mustUnderstand="1" '
            f'xmlns:wsse="{WSSE_NS}">'
            f"<wsse:UsernameToken>"
            f"<wsse:Username>{_escape(creds.qualified_username())}</wsse:Username>"
            f'<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/'
            f'oasis-200401-wss-username-token-profile-1.0#PasswordText">'
            f"{_escape(creds.password)}</wsse:Password>"
            f"</wsse:UsernameToken></wsse:Security></soapenv:Header>"
        )

    def _envelope(self, operation: str, body: str) -> str:
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<soapenv:Envelope xmlns:soapenv="{SOAP_NS}" xmlns:wd="{WD_NS}">'
            f"{self._security_header()}"
            f"<soapenv:Body><wd:{operation} "
            f'wd:version="{self.auth.credentials.api_version}">'
            f"{body}"
            f"</wd:{operation}></soapenv:Body></soapenv:Envelope>"
        )

    def call(
        self,
        operation: str,
        *,
        request_body: str = "",
        page: int = 1,
        page_size: int = MAX_PAGE_SIZE,
        client: httpx.Client | None = None,
    ) -> dict[str, Any]:
        """One SOAP call. Returns the response body as nested dicts."""
        response_filter = (
            f"<wd:Response_Filter>"
            f"<wd:Page>{page}</wd:Page>"
            f"<wd:Count>{min(page_size, MAX_PAGE_SIZE)}</wd:Count>"
            f"</wd:Response_Filter>"
        )
        envelope = self._envelope(operation, request_body + response_filter)

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            # Workday ignores SOAPAction but some proxies in front of it do not.
            "SOAPAction": operation,
        }
        if self.auth.uses_oauth:
            headers["Authorization"] = f"Bearer {self.auth.access_token(client)}"

        owns_client = client is None
        http_client = client or httpx.Client(timeout=self.timeout)
        try:
            response = http_client.post(
                self.endpoint, content=envelope.encode("utf-8"), headers=headers
            )
        except httpx.HTTPError as exc:
            raise WorkdaySoapError(
                f"Could not reach the Workday {self.service} service: {exc}"
            ) from exc
        finally:
            if owns_client:
                http_client.close()

        if response.status_code in {401, 403}:
            raise WorkdaySoapError(
                f"Workday refused the {operation} call ({response.status_code}). The "
                "Integration System User is probably missing a security domain, or "
                "'Activate Pending Security Policy Changes' has not been run since "
                "the permissions were granted."
            )

        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise WorkdaySoapError(
                f"Workday returned a response that is not valid XML ({exc})."
            ) from exc

        fault = root.find(f".//{{{SOAP_NS}}}Fault")
        if fault is not None:
            raise WorkdaySoapError(_explain_fault(fault, operation))

        body = root.find(f"{{{SOAP_NS}}}Body")
        if body is None or len(body) == 0:
            return {}
        parsed = element_to_dict(body[0])
        return parsed if isinstance(parsed, dict) else {}

    def paged(
        self,
        operation: str,
        *,
        response_key: str,
        request_body: str = "",
        client: httpx.Client | None = None,
    ) -> SoapResult:
        """Every page of a Get_* operation, concatenated.

        `response_key` names the repeating element inside `Response_Data`,
        because Workday names it differently per operation
        (`Integration_System`, `Job_Profile`, `Organization`…) and there is no
        way to infer it from the operation name.
        """
        records: list[dict[str, Any]] = []
        total_pages = 1
        total_results = 0

        for page in range(1, MAX_PAGES + 1):
            payload = self.call(
                operation, request_body=request_body, page=page, client=client
            )

            results = payload.get("Response_Results")
            if isinstance(results, dict):
                total_pages = int(_as_text(results.get("Total_Pages")) or 1)
                total_results = int(_as_text(results.get("Total_Results")) or 0)

            data = payload.get("Response_Data")
            if isinstance(data, dict):
                found = data.get(response_key)
                if isinstance(found, list):
                    records.extend(f for f in found if isinstance(f, dict))
                elif isinstance(found, dict):
                    records.append(found)

            if page >= total_pages:
                break

        return SoapResult(
            records=records, total_pages=total_pages, total_results=total_results
        )


def _as_text(value: Any) -> str:
    """Read a scalar from a parsed node that may be a string or a dict."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("#text", "")).strip()
    return ""


def reference_id(node: Any, *, id_type: str | None = None) -> str:
    """Pull a stable identifier out of a Workday reference block.

    Workday references carry several ids at once — a WID plus one or more
    business-key ids like `Organization_Reference_ID`. The WID is stable within
    a tenant but meaningless across tenants; the business key is the one a
    human recognises. Entity resolution needs whichever is actually present, so
    this prefers a requested type, then any non-WID id, then the WID.
    """
    if not isinstance(node, dict):
        return ""

    ids = node.get("ID")
    if isinstance(ids, dict):
        ids = [ids]
    if not isinstance(ids, list):
        return ""

    entries = [
        (str(entry.get("@type", "")), _as_text(entry))
        for entry in ids
        if isinstance(entry, dict)
    ]

    if id_type:
        for kind, value in entries:
            if kind == id_type and value:
                return value

    for kind, value in entries:
        if kind != "WID" and value:
            return value

    for kind, value in entries:
        if kind == "WID" and value:
            return value

    return ""


def descriptor(node: Any) -> str:
    """The human-readable label Workday attaches to a reference."""
    if isinstance(node, dict):
        return str(node.get("@Descriptor", "")).strip()
    return ""


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_VALIDATION_HINT = re.compile(r"processing error|validation error", re.IGNORECASE)


def _explain_fault(fault: ElementTree.Element, operation: str) -> str:
    """Turn a SOAP fault into an actionable message."""
    parts = []
    for child in fault.iter():
        tag = _strip_ns(child.tag)
        if tag in {"faultstring", "Detail_Message", "message"}:
            text = (child.text or "").strip()
            if text and text not in parts:
                parts.append(text)

    detail = " — ".join(parts) if parts else "no detail returned"

    if _VALIDATION_HINT.search(detail):
        return (
            f"Workday rejected {operation}: {detail}. This usually means the "
            "Integration System User cannot see the requested data rather than "
            "that the request was malformed."
        )
    return f"Workday returned a fault for {operation}: {detail}"
