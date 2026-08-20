"""
API specification connector — OpenAPI, Swagger and Postman collections.

This is the connector that makes integration impact analysis possible. When a
product owner proposes changing a field, the question "which API contracts
expose that field, and who calls them" is answerable only if the specs are in
the graph as structure rather than as attachments.

It reads from a URL or a local path, so it covers both a live spec endpoint and
a spec checked into a repository. No credentials are required for a public
spec, which is why this connector is always "configured" — the thing that can
be missing is a source, not a secret.

The three formats collapse onto the same node kinds deliberately: an endpoint is
an endpoint whether it was described in OpenAPI or exercised in Postman, and a
graph that modelled them separately would fail to notice that a Postman request
tests an endpoint the spec declares.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import yaml

from api.connectors.base import (
    AccessCheck,
    ConnectorCapability,
    ConnectorError,
    ConnectorScope,
    EnterpriseConnector,
    RawRecord,
)

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}


class ApiSpecConnector(EnterpriseConnector):
    id = "cx-apispec"
    name = "API Specifications"
    vendor = "OpenAPI / Postman"
    category = "docs"
    kind = "document"
    description = (
        "Reads OpenAPI, Swagger and Postman collections so API contracts, their "
        "endpoints and their schemas are part of the impact graph."
    )
    auth_methods = ["api_key"]
    provides = ["API contracts", "Endpoint inventory", "Schema definitions"]
    extractor_version = "1"

    scopes = [
        ConnectorScope(
            id="read.spec",
            label="Read the specification document",
            description="Fetches the spec from a URL or reads it from disk.",
            required=True,
        )
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        #: Either a URL or a filesystem path.
        self.source: str = self.config.get("source", "")
        self.label: str = self.config.get("label", "")

    def is_configured(self) -> bool:
        return bool(self.source)

    def discover_capabilities(self) -> list[ConnectorCapability]:
        return [
            ConnectorCapability(
                id="apispec.endpoints",
                label="Endpoints and operations",
                layer="capability",
                node_kinds=["integration"],
                requires_scopes=["read.spec"],
            ),
            ConnectorCapability(
                id="apispec.schemas",
                label="Schemas and fields",
                layer="capability",
                node_kinds=["data_entity"],
                requires_scopes=["read.spec"],
            ),
        ]

    def validate_access(self) -> AccessCheck:
        if not self.source:
            return AccessCheck(
                ok=False, message="No specification source configured (URL or file path)."
            )
        try:
            doc = self._load()
        except ConnectorError as exc:
            return AccessCheck(ok=False, message=str(exc))

        if "openapi" in doc or "swagger" in doc:
            version = doc.get("openapi") or doc.get("swagger")
            title = (doc.get("info") or {}).get("title", "untitled")
            count = len(doc.get("paths") or {})
            return AccessCheck(
                ok=True,
                message=f"Read OpenAPI {version} — “{title}”, {count} paths.",
                effective_scopes=["read.spec"],
            )
        if "item" in doc and "info" in doc:
            name = (doc.get("info") or {}).get("name", "untitled")
            return AccessCheck(
                ok=True,
                message=f"Read Postman collection “{name}”.",
                effective_scopes=["read.spec"],
            )
        return AccessCheck(
            ok=False,
            message="The document is neither an OpenAPI specification nor a Postman collection.",
        )

    def _load(self) -> dict:
        """Fetch and parse. YAML is a superset of JSON, so one parser covers both."""
        raw: str
        if self.source.startswith(("http://", "https://")):
            try:
                resp = httpx.get(self.source, timeout=30.0, follow_redirects=True)
                resp.raise_for_status()
                raw = resp.text
            except httpx.HTTPError as exc:
                raise ConnectorError(f"Could not fetch the specification: {exc}") from exc
        else:
            path = Path(self.source)
            if not path.is_file():
                raise ConnectorError(f"No file at {self.source}.")
            raw = path.read_text(encoding="utf-8")

        try:
            return yaml.safe_load(raw) or {}
        except yaml.YAMLError as exc:
            raise ConnectorError(f"The specification could not be parsed: {exc}") from exc

    def snapshot(self) -> Iterator[RawRecord]:
        doc = self._load()
        if "openapi" in doc or "swagger" in doc:
            yield from self._openapi(doc)
        elif "item" in doc:
            yield from self._postman(doc)
        else:
            raise ConnectorError(
                "Unrecognised document: expected an OpenAPI specification or a Postman collection."
            )

    # --- OpenAPI -----------------------------------------------------------

    def _openapi(self, doc: dict) -> Iterator[RawRecord]:
        info = doc.get("info") or {}
        api_title = self.label or info.get("title", "API")
        api_version = info.get("version", "")
        api_key = f"apispec:api:{api_title}:{api_version}"

        yield RawRecord(
            kind="integration",
            natural_key=api_key,
            label=f"{api_title} {api_version}".strip(),
            payload={
                "title": api_title,
                "version": api_version,
                "description": info.get("description", ""),
                "servers": [s.get("url") for s in doc.get("servers", []) if s.get("url")],
                "specVersion": doc.get("openapi") or doc.get("swagger"),
            },
            source_ref=self.source,
            provenance=f"OpenAPI › {api_title} {api_version}".strip(),
            layer="capability",
        )

        for path, item in (doc.get("paths") or {}).items():
            if not isinstance(item, dict):
                continue
            for method, op in item.items():
                if method.lower() not in HTTP_METHODS or not isinstance(op, dict):
                    continue

                op_id = op.get("operationId") or f"{method.upper()} {path}"
                # Schema references this operation touches. Extracted rather
                # than resolved: a $ref names the schema, and the graph wants
                # the edge to the named thing, not an inlined copy of it.
                refs = sorted(_collect_refs(op))

                yield RawRecord(
                    kind="integration",
                    natural_key=f"apispec:op:{api_title}:{method.upper()}:{path}",
                    label=f"{method.upper()} {path}",
                    payload={
                        "operationId": op_id,
                        "method": method.upper(),
                        "path": path,
                        "summary": op.get("summary", ""),
                        "tags": op.get("tags", []),
                        "deprecated": op.get("deprecated", False),
                        "security": op.get("security", doc.get("security", [])),
                        "schemaRefs": refs,
                    },
                    source_ref=self.source,
                    provenance=f"OpenAPI › {api_title} › {method.upper()} {path}",
                    layer="capability",
                    relations=[("EXPOSES", api_key)]
                    + [("READS", f"apispec:schema:{api_title}:{r}") for r in refs],
                )

        schemas = ((doc.get("components") or {}).get("schemas")) or doc.get("definitions") or {}
        for name, schema in schemas.items():
            if not isinstance(schema, dict):
                continue
            props = schema.get("properties") or {}
            required = set(schema.get("required") or [])
            yield RawRecord(
                kind="data_entity",
                natural_key=f"apispec:schema:{api_title}:{name}",
                label=name,
                payload={
                    "name": name,
                    "type": schema.get("type", "object"),
                    "description": schema.get("description", ""),
                    "fields": [
                        {
                            "name": p,
                            "type": (spec or {}).get("type"),
                            "format": (spec or {}).get("format"),
                            "required": p in required,
                            "description": (spec or {}).get("description", ""),
                        }
                        for p, spec in props.items()
                    ],
                },
                source_ref=self.source,
                provenance=f"OpenAPI › {api_title} › schema {name}",
                layer="capability",
            )

    # --- Postman -----------------------------------------------------------

    def _postman(self, doc: dict) -> Iterator[RawRecord]:
        """A Postman collection.

        Emitted at the `capability` layer alongside OpenAPI, but each request
        also carries whether it has tests attached. A collection whose requests
        assert nothing is a directory of URLs, and the difference matters when
        the platform is asked what coverage exists.
        """
        info = doc.get("info") or {}
        name = self.label or info.get("name", "Collection")
        coll_key = f"apispec:postman:{name}"

        yield RawRecord(
            kind="integration",
            natural_key=coll_key,
            label=name,
            payload={"name": name, "description": info.get("description", "")},
            source_ref=self.source,
            provenance=f"Postman › {name}",
            layer="capability",
        )

        def walk(items: list, folder: str = "") -> Iterator[RawRecord]:
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                if "item" in entry:
                    sub = entry.get("name", "")
                    yield from walk(entry["item"], f"{folder}/{sub}".strip("/"))
                    continue

                req = entry.get("request")
                if not isinstance(req, dict):
                    continue

                url = req.get("url")
                raw_url = url.get("raw", "") if isinstance(url, dict) else str(url or "")
                method = req.get("method", "GET")

                has_tests = any(
                    ev.get("listen") == "test" and (ev.get("script") or {}).get("exec")
                    for ev in entry.get("event", [])
                    if isinstance(ev, dict)
                )

                label = entry.get("name", raw_url)
                yield RawRecord(
                    kind="integration",
                    natural_key=f"apispec:postman:{name}:{folder}:{label}",
                    label=f"{method} {label}",
                    payload={
                        "name": label,
                        "folder": folder,
                        "method": method,
                        "url": raw_url,
                        "hasTests": has_tests,
                    },
                    source_ref=self.source,
                    provenance=f"Postman › {name} › {folder or 'root'} › {label}",
                    layer="capability",
                    relations=[("EXPOSES", coll_key)],
                )

        yield from walk(doc.get("item", []))


def _collect_refs(node: Any, out: set[str] | None = None) -> set[str]:
    """Every schema name referenced anywhere under `node`.

    Walks the whole subtree because a `$ref` can appear in a request body, a
    response, a parameter or nested inside an array's `items`, and missing one
    means missing an edge the impact analysis depends on.
    """
    if out is None:
        out = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and "/" in ref:
            out.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _collect_refs(value, out)
    elif isinstance(node, list):
        for value in node:
            _collect_refs(value, out)
    return out
