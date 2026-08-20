"""
The Workday Graph API.

GraphQL, and the reason it earns a place beside REST is introspection. A REST
OpenAPI document tells you which paths exist; a GraphQL schema tells you which
*objects relate to which*, by name, in a form that is already a graph. That is
the closest thing Workday offers to a machine-readable map of its own object
model, and it maps onto Meridian's ontology with almost no interpretation.

What this is not: a way to reach business process definitions. The Graph API
exposes transactional objects — workers, organisations, jobs — the same
territory as REST. Querying it for configuration returns the same nothing. Its
value here is entirely the schema, not the data behind it.

Two consequences shape the module:

  - Introspection is the primary call, and it is a *capability*-layer read. The
    types and their relationships describe what Workday models, not what this
    tenant configured.
  - Data queries are deliberately narrow. Introspection alone cannot say which
    organisation types a tenant actually uses, so a small set of curated
    queries fills that in — and each one is written out explicitly rather than
    generated, because a generated query against an unknown schema is how you
    accidentally pull ten thousand worker records.

Availability is uneven. The Graph API is a newer surface and not enabled in
every tenant, so every path here degrades to "unavailable" rather than failing
the run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from api.connectors.base import ConnectorError
from api.connectors.workday.auth import WorkdayAuth, WorkdayAuthError

#: How many reference hops to keep when turning schema types into graph edges.
#: Workday's schema is densely self-referential — Worker → Position →
#: Organization → Worker — so ingesting every reference at every depth produces
#: a hairball in which everything reaches everything and blast radius means
#: nothing. One hop is the direct relationship the schema actually asserts.
DEFAULT_GRAPH_DEPTH = 1


class WorkdayGraphError(ConnectorError):
    """A Graph API call failed in a way the operator can act on."""


#: Introspection, narrowed. The full standard query pulls every directive,
#: every input type and the entire description tree, which on Workday's schema
#: is megabytes. This asks for exactly what becomes graph structure: type names,
#: their fields, and what each field points at.
INTROSPECTION_QUERY = """
query MeridianIntrospection {
  __schema {
    queryType { name }
    types {
      kind
      name
      description
      fields(includeDeprecated: false) {
        name
        description
        type { ...TypeRef }
      }
    }
  }
}

fragment TypeRef on __Type {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
      ofType { kind name }
    }
  }
}
"""


@dataclass(slots=True)
class GraphType:
    """One object type in Workday's schema."""

    name: str
    description: str = ""
    #: field name -> type name it resolves to, unwrapped of NON_NULL/LIST.
    fields: dict[str, str] = field(default_factory=dict)
    #: Fields pointing at another object type. These are the edges — a scalar
    #: field describes the object, a reference field connects it to another,
    #: and only the second kind belongs in the graph as a relation.
    references: dict[str, str] = field(default_factory=dict)

    @property
    def natural_key(self) -> str:
        return f"workday:gqltype:{self.name}"


class WorkdayGraphClient:
    """Queries the Workday Graph API.

    Bearer-only, like REST. `available` reports that up front so an ISU-based
    connection is described as limited rather than broken.
    """

    def __init__(self, auth: WorkdayAuth, *, timeout: float = 60.0) -> None:
        self.auth = auth
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return self.auth.uses_oauth

    def endpoint(self) -> str:
        creds = self.auth.credentials
        return (
            f"{creds.normalised_host()}/api/graphql/{creds.api_version}/{creds.tenant}"
        )

    def execute(
        self,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
        client: httpx.Client | None = None,
    ) -> dict[str, Any]:
        """Run one GraphQL document and return its `data` block."""
        if not self.available:
            raise WorkdayGraphError(
                "The Graph API requires OAuth. This connection uses Integration "
                "System User credentials, which Workday does not accept here."
            )

        owns_client = client is None
        http_client = client or httpx.Client(timeout=self.timeout)
        try:
            headers = self.auth.rest_headers(http_client)
            headers["Content-Type"] = "application/json"
            response = http_client.post(
                self.endpoint(),
                json={"query": query, "variables": variables or {}},
                headers=headers,
            )
        except WorkdayAuthError as exc:
            raise WorkdayGraphError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise WorkdayGraphError(
                f"Could not reach the Workday Graph API: {exc}"
            ) from exc
        finally:
            if owns_client:
                http_client.close()

        if response.status_code == 404:
            raise WorkdayGraphError(
                "This tenant does not expose the Graph API. It is a newer "
                "surface and is not enabled everywhere; the connector works "
                "without it."
            )
        if response.status_code in {401, 403}:
            raise WorkdayGraphError(
                "The API client is not authorised for the Graph API. It needs "
                "the 'Workday Graph API' scope on the API Client in Workday."
            )
        if response.status_code >= 400:
            raise WorkdayGraphError(
                f"Workday returned {response.status_code} from the Graph API."
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise WorkdayGraphError(
                "The Graph API returned a non-JSON response."
            ) from exc

        # GraphQL reports errors inside a 200. Treating that as success is the
        # classic way to ingest an empty graph and call it a clean run.
        errors = body.get("errors") if isinstance(body, dict) else None
        if errors:
            raise WorkdayGraphError(f"Graph API error: {_first_error(errors)}")

        data = body.get("data") if isinstance(body, dict) else None
        return data if isinstance(data, dict) else {}

    def introspect(self, *, client: httpx.Client | None = None) -> list[GraphType]:
        """Read the schema and return its object types."""
        data = self.execute(INTROSPECTION_QUERY, client=client)
        return parse_introspection(data)

    def probe(self, *, client: httpx.Client | None = None) -> tuple[bool, str]:
        """Check reachability without failing a run."""
        try:
            types = self.introspect(client=client)
        except WorkdayGraphError as exc:
            return False, str(exc)
        return True, f"{len(types)} object type(s) in the schema."


# --- parsing ---------------------------------------------------------------
#
# Split from the client so it can be tested against a fixture schema, which is
# how this module is verified without a tenant.

#: Introspection returns Workday's own plumbing alongside its object model.
#: These prefixes are the plumbing.
_INTERNAL_PREFIXES = ("__", "_")

_SCALARS = {"SCALAR", "ENUM"}


def parse_introspection(data: dict[str, Any]) -> list[GraphType]:
    """Turn an introspection response into object types.

    Keeps only `OBJECT` kinds with fields. Interfaces and unions describe
    polymorphism, which the ontology has no way to express and which would
    surface as duplicate nodes if flattened.
    """
    schema = data.get("__schema")
    if not isinstance(schema, dict):
        return []
    types = schema.get("types")
    if not isinstance(types, list):
        return []

    out: list[GraphType] = []
    for entry in types:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") != "OBJECT":
            continue

        name = str(entry.get("name") or "")
        if not name or name.startswith(_INTERNAL_PREFIXES):
            continue

        fields = entry.get("fields")
        if not isinstance(fields, list) or not fields:
            continue

        resolved: dict[str, str] = {}
        references: dict[str, str] = {}
        for item in fields:
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("name") or "")
            if not field_name or field_name.startswith(_INTERNAL_PREFIXES):
                continue

            kind, type_name = _unwrap(item.get("type"))
            if not type_name:
                continue
            resolved[field_name] = type_name
            # An OBJECT-valued field is a relation; a scalar is an attribute.
            if kind == "OBJECT" and not type_name.startswith(_INTERNAL_PREFIXES):
                references[field_name] = type_name

        if not resolved:
            continue

        out.append(
            GraphType(
                name=name,
                description=str(entry.get("description") or "").strip(),
                fields=resolved,
                references=references,
            )
        )
    return out


def _unwrap(type_ref: Any) -> tuple[str, str]:
    """Strip NON_NULL and LIST wrappers to the named type underneath.

    GraphQL nests these arbitrarily — `[Worker!]!` is three levels deep — and
    the wrapper says how many and whether null, neither of which changes what
    the field points at.
    """
    node = type_ref
    depth = 0
    while isinstance(node, dict) and depth < 12:
        name = node.get("name")
        kind = str(node.get("kind") or "")
        if name and kind not in {"NON_NULL", "LIST"}:
            return kind, str(name)
        node = node.get("ofType")
        depth += 1
    return "", ""


def _first_error(errors: Any) -> str:
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("message") or first)
        return str(first)
    return str(errors)


def is_scalar_kind(kind: str) -> bool:
    return kind in _SCALARS
