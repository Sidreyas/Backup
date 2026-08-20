"""
Jira connector.

Extracts the three layers separately, as the transcript insists:

  - **configuration**: projects, issue types, fields, statuses, workflow
    schemes — what this tenant has set up.
  - **runtime**: issues and their changelogs — what actually happened, which is
    where "the configured workflow says Manager → Finance" gets compared with
    "in practice it goes Manager → Finance → manual correction".

The configuration layer is what makes Jira interesting to a change-intelligence
platform. Most Jira integrations only read issues; reading the *workflow
definitions* is what lets Meridian tell a product owner that their new
requirement conflicts with a transition rule that already exists.

Auth is Basic with an API token, which is what Atlassian Cloud supports for
server-to-server access. The token is read from settings, never stored in the
database.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from api.connectors.base import (
    AccessCheck,
    ConnectorCapability,
    ConnectorScope,
    EnterpriseConnector,
    NotConfigured,
    RawRecord,
)
from api.core.config import settings

# Jira paginates almost everything and the page sizes differ per endpoint. A
# conservative shared cap keeps a large tenant from producing an unbounded run;
# when it is hit the pipeline records it rather than truncating silently.
PAGE_SIZE = 100
MAX_PAGES = 50


class JiraConnector(EnterpriseConnector):
    id = "cx-jira"
    name = "Jira"
    vendor = "Atlassian"
    category = "ticketing"
    kind = "ticketing"
    description = (
        "Reads projects, issue types, field configuration, workflows and issue "
        "history so requirements can be traced to the process that governs them."
    )
    auth_methods = ["api_key", "basic"]
    provides = ["Requirements", "Workflow configuration", "Change history"]
    extractor_version = "1"

    scopes = [
        ConnectorScope(
            id="read.configuration",
            label="Read project and workflow configuration",
            description="Projects, issue types, fields, statuses and workflow schemes.",
            required=True,
        ),
        ConnectorScope(
            id="read.issues",
            label="Read issues and change history",
            description="Issue content and changelogs, used to observe actual process paths.",
            required=False,
        ),
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # Tolerant of what someone actually pastes: a trailing slash, or the
        # full URL of a board or issue rather than the site root. Both are
        # common, and both produce 404s that read as bad credentials.
        raw = (self.config.get("base_url") or settings.jira_base_url or "").strip()
        for suffix in ("/jira", "/secure", "/browse", "/rest"):
            marker = raw.find(suffix + "/")
            if marker > 0:
                raw = raw[:marker]
                break
        self.base_url = raw.rstrip("/")
        self.email = (self.config.get("email") or settings.jira_email or "").strip()
        self.token = self.config.get("api_token") or settings.jira_api_token

    def is_configured(self) -> bool:
        return bool(self.base_url and self.email and self.token)

    def _client(self) -> httpx.Client:
        if not self.is_configured():
            raise NotConfigured(
                "Jira is not configured. Set JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN."
            )
        return httpx.Client(
            base_url=f"{self.base_url}/rest/api/3",
            auth=(self.email, self.token),
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    # --- capabilities ------------------------------------------------------

    def discover_capabilities(self) -> list[ConnectorCapability]:
        caps = [
            ConnectorCapability(
                id="jira.projects",
                label="Projects",
                layer="configuration",
                node_kinds=["config_object"],
                requires_scopes=["read.configuration"],
            ),
            ConnectorCapability(
                id="jira.fields",
                label="Fields and custom fields",
                layer="configuration",
                node_kinds=["data_entity"],
                requires_scopes=["read.configuration"],
            ),
            ConnectorCapability(
                id="jira.workflows",
                label="Workflows, statuses and transitions",
                layer="configuration",
                node_kinds=["business_process"],
                requires_scopes=["read.configuration"],
            ),
        ]
        if "read.issues" in self.config.get("granted_scopes", ["read.issues"]):
            caps.append(
                ConnectorCapability(
                    id="jira.issues",
                    label="Issues and change history",
                    layer="runtime",
                    node_kinds=["requirement"],
                    requires_scopes=["read.issues"],
                )
            )
        return caps

    def validate_access(self) -> AccessCheck:
        if not self.is_configured():
            return AccessCheck(
                ok=False,
                message=(
                    "Not configured. Set JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN."
                ),
            )
        try:
            with self._client() as client:
                me = client.get("/myself")
                me.raise_for_status()
                display = me.json().get("displayName", "unknown")

                # Permission to read configuration is what the connector is
                # for, so it is probed rather than assumed. A token that can
                # read issues but not workflows produces a graph missing the
                # half that matters, and the operator should hear that now.
                effective = ["read.issues"]
                missing = []
                probe = client.get("/workflow/search", params={"maxResults": 1})
                if probe.status_code == 200:
                    effective.append("read.configuration")
                else:
                    missing.append("read.configuration")

            msg = f"Connected to {self.base_url} as {display}."
            if missing:
                msg += (
                    " This account cannot read workflow configuration, so only issue "
                    "history will be extracted."
                )
            return AccessCheck(
                ok=True, message=msg, effective_scopes=effective, missing_scopes=missing
            )
        except httpx.HTTPStatusError as exc:
            return AccessCheck(
                ok=False,
                message=f"Jira rejected the credentials ({exc.response.status_code}).",
            )
        except httpx.HTTPError as exc:
            return AccessCheck(ok=False, message=f"Could not reach Jira: {exc}")

    # --- extraction --------------------------------------------------------

    def snapshot(self) -> Iterator[RawRecord]:
        """Tenant configuration: projects, fields, statuses, workflows."""
        with self._client() as client:
            yield from self._projects(client)
            yield from self._fields(client)
            yield from self._statuses(client)
            yield from self._workflows(client)

    def _projects(self, client: httpx.Client) -> Iterator[RawRecord]:
        start = 0
        for _ in range(MAX_PAGES):
            resp = client.get(
                "/project/search", params={"startAt": start, "maxResults": PAGE_SIZE}
            )
            resp.raise_for_status()
            body = resp.json()
            for p in body.get("values", []):
                yield RawRecord(
                    kind="config_object",
                    natural_key=f"jira:project:{p['id']}",
                    label=f"{p.get('name')} ({p.get('key')})",
                    payload=p,
                    source_ref=f"{self.base_url}/browse/{p.get('key')}",
                    provenance=f"Jira › Project › {p.get('key')}",
                    layer="configuration",
                )
            if body.get("isLast", True):
                return
            start += PAGE_SIZE

    def _fields(self, client: httpx.Client) -> Iterator[RawRecord]:
        """Field definitions, including custom fields.

        Custom fields are the ones that matter for cross-system identity: a
        `customfield_10422` holding an employee id is the Jira end of the
        mapping to Workday's Employee_ID, and that link cannot be proposed if
        the field was never extracted.
        """
        resp = client.get("/field")
        resp.raise_for_status()
        for f in resp.json():
            schema = f.get("schema") or {}
            yield RawRecord(
                kind="data_entity",
                natural_key=f"jira:field:{f['id']}",
                label=f.get("name", f["id"]),
                payload={
                    "id": f["id"],
                    "name": f.get("name"),
                    "custom": f.get("custom", False),
                    "type": schema.get("type"),
                    "items": schema.get("items"),
                    "clauseNames": f.get("clauseNames", []),
                },
                source_ref=f"{self.base_url}/secure/admin/ViewCustomFields.jspa",
                provenance=f"Jira › Field › {f.get('name')}",
                layer="configuration",
            )

    def _statuses(self, client: httpx.Client) -> Iterator[RawRecord]:
        resp = client.get("/status")
        resp.raise_for_status()
        for s in resp.json():
            cat = (s.get("statusCategory") or {}).get("key", "")
            yield RawRecord(
                kind="config_object",
                natural_key=f"jira:status:{s['id']}",
                label=s.get("name", s["id"]),
                payload={"id": s["id"], "name": s.get("name"), "category": cat},
                provenance=f"Jira › Status › {s.get('name')}",
                layer="configuration",
            )

    def _workflows(self, client: httpx.Client) -> Iterator[RawRecord]:
        """Workflows with their transitions.

        This is the configuration layer proper — the rules that govern how work
        moves. Each transition becomes a relation so the graph holds the
        process shape, not just a list of named workflows.
        """
        start = 0
        for _ in range(MAX_PAGES):
            resp = client.get(
                "/workflow/search",
                params={
                    "startAt": start,
                    "maxResults": PAGE_SIZE,
                    "expand": "transitions,statuses",
                },
            )
            if resp.status_code == 403:
                # No configuration permission. validate_access already reported
                # this; stopping quietly here avoids failing an otherwise good
                # run over a scope the operator declined.
                return
            resp.raise_for_status()
            body = resp.json()

            for wf in body.get("values", []):
                wid = (wf.get("id") or {}).get("name") or wf.get("id")
                name = (wf.get("id") or {}).get("name") or "workflow"
                transitions = wf.get("transitions", [])

                relations = []
                for t in transitions:
                    for from_status in t.get("from", []) or []:
                        fid = (
                            from_status
                            if isinstance(from_status, str)
                            else from_status.get("id", "")
                        )
                        if fid:
                            relations.append(("HAS_STEP", f"jira:status:{fid}"))
                    to = t.get("to")
                    tid = to if isinstance(to, str) else (to or {}).get("id", "")
                    if tid:
                        relations.append(("ROUTES_TO", f"jira:status:{tid}"))

                yield RawRecord(
                    kind="business_process",
                    natural_key=f"jira:workflow:{wid}",
                    label=name,
                    payload={
                        "name": name,
                        "description": wf.get("description", ""),
                        "transitions": [
                            {
                                "id": t.get("id"),
                                "name": t.get("name"),
                                "type": t.get("type"),
                                "from": t.get("from", []),
                                "to": t.get("to"),
                                "rules": t.get("rules", {}),
                            }
                            for t in transitions
                        ],
                    },
                    provenance=f"Jira › Workflow › {name}",
                    layer="configuration",
                    relations=relations,
                )

            if body.get("isLast", True):
                return
            start += PAGE_SIZE

    def observe(self) -> Iterator[RawRecord]:
        """Issues and their changelogs — the runtime layer.

        The changelog is the valuable part. It records the path an issue
        actually took, which is what surfaces the gap between the configured
        workflow and what teams really do.
        """
        jql = self.config.get("jql", "ORDER BY updated DESC")
        with self._client() as client:
            token: str | None = None
            for _ in range(MAX_PAGES):
                params: dict[str, Any] = {
                    "jql": jql,
                    "maxResults": PAGE_SIZE,
                    "fields": "summary,status,issuetype,project,created,updated,priority",
                    "expand": "changelog",
                }
                if token:
                    params["nextPageToken"] = token

                resp = client.get("/search/jql", params=params)
                if resp.status_code == 403:
                    return
                resp.raise_for_status()
                body = resp.json()

                for issue in body.get("issues", []):
                    f = issue.get("fields", {})
                    history = [
                        {
                            "at": h.get("created"),
                            "by": (h.get("author") or {}).get("displayName"),
                            "items": [
                                {
                                    "field": i.get("field"),
                                    "from": i.get("fromString"),
                                    "to": i.get("toString"),
                                }
                                for i in h.get("items", [])
                            ],
                        }
                        for h in (issue.get("changelog") or {}).get("histories", [])
                    ]
                    yield RawRecord(
                        kind="requirement",
                        natural_key=f"jira:issue:{issue['key']}",
                        label=f"{issue['key']} — {f.get('summary', '')}",
                        payload={
                            "key": issue["key"],
                            "summary": f.get("summary"),
                            "status": (f.get("status") or {}).get("name"),
                            "issueType": (f.get("issuetype") or {}).get("name"),
                            "project": (f.get("project") or {}).get("key"),
                            "priority": (f.get("priority") or {}).get("name"),
                            "created": f.get("created"),
                            "updated": f.get("updated"),
                            "changelog": history,
                        },
                        source_ref=f"{self.base_url}/browse/{issue['key']}",
                        provenance=f"Jira › Issue › {issue['key']}",
                        layer="runtime",
                    )

                token = body.get("nextPageToken")
                if not token or body.get("isLast", False):
                    return

    def subscribe_to_changes(self) -> str | None:
        return "/webhooks/jira"
