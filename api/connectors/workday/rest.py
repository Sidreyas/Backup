"""
The REST surface, read as a *capability* description.

The transcript lists REST/OpenAPI discovery as its own connector, and the
reason is easy to miss: Workday's REST API is transactional, so it is nearly
useless as a source of configuration. Asking it for business process
definitions returns nothing. What it *does* return, uniquely, is the tenant's
own OpenAPI document — and that document is a statement about what this tenant
can do, which is the "capability" layer the ontology keeps separate from
configuration.

Why that layer matters. When an integration breaks, the question is rarely only
"what changed in the config" — it is "was this ever exposed at all". A field
that exists in Workday but appears in no API path cannot be read by a
downstream system no matter how the process is configured, and that is a
different failure with a different fix. Recording the API surface makes the
question answerable instead of a guess.

So this module deliberately does not extract worker data. It reads the spec,
records paths and schemas as capability records, and stops. Everything else
REST offers belongs to a product Meridian is not building.

REST is Bearer-only. Unlike RaaS, an ISU username/password will not work here,
which is why every entry point degrades to "unavailable" rather than failing
when the connection uses Basic auth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from api.connectors.base import ConnectorError
from api.connectors.workday.auth import WorkdayAuth, WorkdayAuthError

#: Workday publishes one OpenAPI document per API subdomain. These are the ones
#: whose surface says something about configuration reach; `staffing` and `hr`
#: carry the objects most integrations touch. The list is a starting set, not a
#: closed one — `service_paths()` reads whatever the tenant actually advertises.
DEFAULT_SERVICES = ("common", "staffing", "hr", "compensation", "absence")


class WorkdayRestError(ConnectorError):
    """A REST call failed in a way the operator can act on."""


@dataclass(slots=True)
class ApiOperation:
    """One operation the tenant's API exposes."""

    service: str
    method: str
    path: str
    summary: str
    #: Schema names this operation reads or writes, as referenced by the spec.
    #: These are what let an API path be linked to the business object it
    #: touches, which is the only reason the spec is worth ingesting.
    schemas: list[str] = field(default_factory=list)

    @property
    def natural_key(self) -> str:
        return f"workday:api:{self.service}:{self.method.lower()}:{self.path}"


@dataclass(slots=True)
class ApiSchema:
    """A business object as the REST API describes it."""

    service: str
    name: str
    properties: dict[str, str]
    description: str = ""

    @property
    def natural_key(self) -> str:
        return f"workday:apischema:{self.service}:{self.name}"


class WorkdayRestClient:
    """Reads the tenant's OpenAPI documents.

    Read-only by construction: the only HTTP verb this class issues is GET, and
    the only paths it requests are spec documents. It cannot be pointed at a
    transactional endpoint even by mistake.
    """

    def __init__(self, auth: WorkdayAuth, *, timeout: float = 60.0) -> None:
        self.auth = auth
        self.timeout = timeout

    @property
    def available(self) -> bool:
        """Whether this connection can use REST at all.

        Basic/ISU connections cannot: Workday's REST API accepts only bearer
        tokens. Reporting this as unavailable rather than raising keeps a
        perfectly good ISU-based connection from looking broken.
        """
        return self.auth.uses_oauth

    def spec_url(self, service: str) -> str:
        creds = self.auth.credentials
        return (
            f"{creds.normalised_host()}/ccx/api/{service}/{creds.api_version}"
            f"/{creds.tenant}/openapi.json"
        )

    def fetch_spec(
        self, service: str, *, client: httpx.Client | None = None
    ) -> dict[str, Any]:
        """Fetch one service's OpenAPI document."""
        if not self.available:
            raise WorkdayRestError(
                "The REST API requires OAuth. This connection uses Integration "
                "System User credentials, which Workday accepts for SOAP and "
                "reports but not for REST."
            )

        owns_client = client is None
        http_client = client or httpx.Client(timeout=self.timeout)
        try:
            headers = self.auth.rest_headers(http_client)
            response = http_client.get(self.spec_url(service), headers=headers)
        except WorkdayAuthError as exc:
            raise WorkdayRestError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise WorkdayRestError(
                f"Could not reach the Workday REST API for '{service}': {exc}"
            ) from exc
        finally:
            if owns_client:
                http_client.close()

        if response.status_code == 404:
            raise WorkdayRestError(
                f"This tenant does not expose the '{service}' REST API. That is "
                "normal — not every service is enabled in every tenant."
            )
        if response.status_code in {401, 403}:
            raise WorkdayRestError(
                f"The API client is not authorised for the '{service}' REST API. "
                "Check the scopes on the API Client in Workday."
            )
        if response.status_code >= 400:
            raise WorkdayRestError(
                f"Workday returned {response.status_code} for the '{service}' "
                "OpenAPI document."
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise WorkdayRestError(
                f"The '{service}' OpenAPI document was not valid JSON."
            ) from exc

        if not isinstance(body, dict):
            raise WorkdayRestError(
                f"The '{service}' OpenAPI document was not an object."
            )
        return body

    def probe(
        self, service: str, *, client: httpx.Client | None = None
    ) -> tuple[bool, str]:
        """Check one service without failing a run.

        Mirrors `RaasClient.probe` so capability discovery can report which
        services are reachable rather than stopping at the first that is not.
        """
        try:
            spec = self.fetch_spec(service, client=client)
        except WorkdayRestError as exc:
            return False, str(exc)
        return True, f"{len(spec.get('paths') or {})} path(s) exposed."


# --- spec parsing ----------------------------------------------------------
#
# Parsing is separate from fetching so it can be tested against a fixture
# document without any network at all. That split is what makes the OpenAPI
# path the most testable of the six extraction methods.

_VERBS = ("get", "post", "put", "patch", "delete")


def parse_operations(service: str, spec: dict[str, Any]) -> list[ApiOperation]:
    """Every operation the document declares."""
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return []

    out: list[ApiOperation] = []
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for verb in _VERBS:
            operation = item.get(verb)
            if not isinstance(operation, dict):
                continue
            out.append(
                ApiOperation(
                    service=service,
                    method=verb.upper(),
                    path=str(path),
                    summary=str(
                        operation.get("summary") or operation.get("operationId") or ""
                    ).strip(),
                    schemas=_referenced_schemas(operation),
                )
            )
    return out


def parse_schemas(service: str, spec: dict[str, Any]) -> list[ApiSchema]:
    """Every business object the document describes.

    Only object-typed schemas with properties are returned. Enum and scalar
    wrappers are noise at the graph level — they describe how a value is
    encoded, not what the tenant models.
    """
    components = spec.get("components")
    if not isinstance(components, dict):
        return []
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return []

    out: list[ApiSchema] = []
    for name, definition in schemas.items():
        if not isinstance(definition, dict):
            continue
        properties = definition.get("properties")
        if not isinstance(properties, dict) or not properties:
            continue

        typed: dict[str, str] = {}
        for prop, meta in properties.items():
            if isinstance(meta, dict):
                typed[str(prop)] = str(
                    meta.get("type") or _ref_name(meta.get("$ref")) or "object"
                )
            else:
                typed[str(prop)] = "object"

        out.append(
            ApiSchema(
                service=service,
                name=str(name),
                properties=typed,
                description=str(definition.get("description") or "").strip(),
            )
        )
    return out


def _referenced_schemas(operation: dict[str, Any]) -> list[str]:
    """Schema names an operation touches, from its body and its responses.

    Walks the whole subtree rather than reading known keys, because `$ref`
    appears at different depths depending on whether the operation wraps its
    payload, and a missed reference silently drops an edge between an API path
    and the object it carries.
    """
    found: list[str] = []
    _collect_refs(operation, found)
    # Preserve first-seen order; `dict.fromkeys` deduplicates without sorting,
    # which keeps output stable between runs for the same document.
    return list(dict.fromkeys(found))


def _collect_refs(node: Any, into: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                name = _ref_name(value)
                if name:
                    into.append(name)
            else:
                _collect_refs(value, into)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, into)


def _ref_name(ref: Any) -> str:
    """`#/components/schemas/Worker` -> `Worker`."""
    if not isinstance(ref, str) or "/" not in ref:
        return ""
    return ref.rsplit("/", 1)[-1].strip()
