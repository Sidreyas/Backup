"""
Azure DevOps connector.

Extracts the delivery pipeline: projects, pipeline definitions, environments,
service connections, variable groups and deployment history. The question this
exists to answer is the last leg of the transcript's traceability chain — "this
Workday approval change touches which pipelines, gated by whose approval, and
deploying to which environment".

Unlike Workday, most of this *is* reachable by API. Three things are not, and
they shape the design:

  1. **No webhook for pipeline definition changes.** Every pipeline event Azure
     DevOps publishes fires on execution — run/stage/job state, completion —
     never on someone editing a definition. For YAML pipelines the definition
     lives in Git so `git.push` is a proxy; for classic build and release
     definitions there is no equivalent. Drift is therefore detected by polling
     the `revision` integer, which every definition carries and which
     increments on edit. Cheap to poll, and it means a re-extraction is only
     paid for when something actually changed.

  2. **Cross-repo YAML templates cannot be resolved read-only.** A pipeline
     that `extends` a template in another repository has no REST representation
     that names the resolved file. The only supported full expansion is
     `POST /preview` with `previewRun: true`, which queues a dry run — so it is
     deliberately *not* called here. A connector that says it is read-only must
     not queue anything. What is extracted is the definition as stored.

  3. **Approvals and checks are a preview API** (`7.1-preview.1`) whose
     `settings` payload — the field carrying approver identities — has no
     published schema. It is read on a best-effort basis and its absence is
     reported rather than treated as "no approvals configured", because those
     two states mean very different things to someone auditing a release gate.

Secrets are never returned by Azure DevOps: service-connection credentials are
omitted from the response and secret variables come back `null` with
`isSecret: true`. Both are preserved as-is — knowing a secret variable *exists*
is exactly the kind of dependency a change-impact analysis needs.
"""

from __future__ import annotations

import base64
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

#: Pinned. 7.1 is stable and fully documented; 7.2 appears in the docs but is
#: tied to an unreleased server version, and preview endpoints are opted into
#: explicitly at the call site rather than globally.
API_VERSION = "7.1"

#: Approvals and checks exist only as preview. Named separately so the version
#: skew is visible where it is used rather than hidden in a constant.
CHECKS_API_VERSION = "7.1-preview.1"

#: Release definitions live on a different host. Constructing this from the
#: org URL is the single most common Azure DevOps integration mistake.
VSRM_HOST = "vsrm.dev.azure.com"

PAGE_SIZE = 200
MAX_PAGES = 25


def _pat_header(pat: str) -> str:
    """Azure DevOps PAT auth: Basic, empty username, PAT as password."""
    return "Basic " + base64.b64encode(f":{pat}".encode()).decode("ascii")


class AzureDevOpsConnector(EnterpriseConnector):
    id = "cx-azure-devops"
    name = "Azure DevOps"
    vendor = "Microsoft"
    category = "code"
    kind = "platform"
    description = (
        "Reads pipeline definitions, environments, approvals and deployment "
        "history so a requirement can be traced to the pipeline that ships it "
        "and the gate that holds it."
    )
    auth_methods = ["api_key", "oauth2"]
    provides = [
        "Pipeline definitions",
        "Environments and approvals",
        "Service connections",
        "Deployment history",
    ]
    extractor_version = "1"

    scopes = [
        ConnectorScope(
            id="read.project",
            label="Read projects and teams",
            description="Project and team metadata. PAT scope: Project and team (read).",
            required=True,
        ),
        ConnectorScope(
            id="read.build",
            label="Read pipeline definitions",
            description=(
                "Build and YAML pipeline definitions, including stages, tasks and "
                "variables. PAT scope: Build (read)."
            ),
            required=True,
        ),
        ConnectorScope(
            id="read.release",
            label="Read release definitions",
            description=(
                "Classic release definitions and their approval gates. PAT scope: "
                "Release (read)."
            ),
        ),
        ConnectorScope(
            id="read.environment",
            label="Read environments and deployment records",
            description=(
                "Environments and what deployed to them. Azure DevOps publishes no "
                "read-only scope for this — the PAT scope is Environment (read and "
                "manage). Meridian never writes; the grant is broader than the use."
            ),
        ),
        ConnectorScope(
            id="read.serviceendpoint",
            label="Read service connections",
            description=(
                "Service connections and what they target. Credentials are omitted "
                "by Azure DevOps. PAT scope: Service endpoints (read)."
            ),
        ),
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.organization = (
            self.config.get("organization") or settings.azure_devops_org or ""
        ).strip()
        self.pat = self.config.get("pat") or settings.azure_devops_pat or ""
        self.base_url = (
            self.config.get("base_url") or "https://dev.azure.com"
        ).rstrip("/")
        # Which projects to read. Left empty, every project the token can see is
        # read — fine for a small org, and explicitly scoped for a large one.
        raw_projects = self.config.get("projects") or ""
        self.projects: list[str] = (
            [p.strip() for p in raw_projects.split(",") if p.strip()]
            if isinstance(raw_projects, str)
            else list(raw_projects)
        )

    # --- plumbing ----------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.organization and self.pat)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": _pat_header(self.pat),
            "Accept": "application/json",
        }

    def _client(self, host: str | None = None) -> httpx.Client:
        if not self.is_configured():
            raise NotConfigured(
                "Azure DevOps is not configured. An organisation name and a "
                "personal access token are both required."
            )
        base = f"https://{host}/{self.organization}" if host else f"{self.base_url}/{self.organization}"
        return httpx.Client(base_url=base, timeout=30.0, headers=self._headers())

    def _get(
        self, client: httpx.Client, path: str, *, version: str = API_VERSION, **params
    ) -> dict | None:
        """A GET that treats 'not available' as data rather than as failure.

        403 and 404 are expected here: a PAT legitimately scoped to builds but
        not releases returns 403 for release definitions, and that is a fact to
        report, not an exception to raise.
        """
        resp = client.get(path, params={"api-version": version, **params})
        if resp.status_code in (401, 403, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    # --- capability discovery ---------------------------------------------

    def discover_capabilities(self) -> list[ConnectorCapability]:
        return [
            ConnectorCapability(
                id="ado.projects",
                label="Projects and teams",
                layer="configuration",
                node_kinds=["config_object"],
                requires_scopes=["read.project"],
            ),
            ConnectorCapability(
                id="ado.pipelines",
                label="Pipeline definitions",
                layer="configuration",
                node_kinds=["integration"],
                requires_scopes=["read.build"],
            ),
            ConnectorCapability(
                id="ado.releases",
                label="Release definitions and approval gates",
                layer="configuration",
                node_kinds=["integration", "policy"],
                requires_scopes=["read.release"],
            ),
            ConnectorCapability(
                id="ado.environments",
                label="Environments and their checks",
                layer="configuration",
                node_kinds=["config_object", "policy"],
                requires_scopes=["read.environment"],
            ),
            ConnectorCapability(
                id="ado.serviceconnections",
                label="Service connections",
                layer="configuration",
                node_kinds=["integration"],
                requires_scopes=["read.serviceendpoint"],
            ),
            ConnectorCapability(
                id="ado.deployments",
                label="Deployment history",
                layer="runtime",
                node_kinds=["config_object"],
                requires_scopes=["read.environment"],
            ),
        ]

    # --- access ------------------------------------------------------------

    def validate_access(self) -> AccessCheck:
        """Probe each surface separately.

        "Connection failed" is useless when five scopes had to be granted. What
        an operator needs is which of them actually work, because a PAT missing
        the release scope produces a graph with no approval gates and no
        indication that anything is absent.
        """
        if not self.organization:
            return AccessCheck(ok=False, message="No organisation name set.")
        if not self.pat:
            return AccessCheck(ok=False, message="No personal access token set.")

        effective: list[str] = []
        missing: list[str] = []

        try:
            with self._client() as client:
                projects = self._get(client, "/_apis/projects", **{"$top": 1})
                if projects is None:
                    return AccessCheck(
                        ok=False,
                        message=(
                            "Azure DevOps rejected the token. Check the organisation "
                            "name and that the token has not expired."
                        ),
                        missing_scopes=["read.project"],
                    )
                effective.append("read.project")

                names = self._project_names(client)
                probe = names[0] if names else None

                if probe:
                    for scope, path, host in (
                        ("read.build", f"/{probe}/_apis/build/definitions", None),
                        ("read.release", f"/{probe}/_apis/release/definitions", VSRM_HOST),
                        (
                            "read.environment",
                            f"/{probe}/_apis/distributedtask/environments",
                            None,
                        ),
                        (
                            "read.serviceendpoint",
                            f"/{probe}/_apis/serviceendpoint/endpoints",
                            None,
                        ),
                    ):
                        ok = self._probe(path, host)
                        (effective if ok else missing).append(scope)
        except httpx.HTTPError as exc:
            return AccessCheck(ok=False, message=f"Could not reach Azure DevOps: {exc}")

        count = len(effective)
        message = f"Connected to {self.organization}. {count} of 5 surfaces readable."
        if missing:
            message += " Not readable: " + ", ".join(missing) + "."
        return AccessCheck(
            ok=True, message=message, effective_scopes=effective, missing_scopes=missing
        )

    def _probe(self, path: str, host: str | None) -> bool:
        try:
            with self._client(host) as client:
                return self._get(client, path, **{"$top": 1}) is not None
        except httpx.HTTPError:
            return False

    def _project_names(self, client: httpx.Client) -> list[str]:
        if self.projects:
            return self.projects
        data = self._get(client, "/_apis/projects", **{"$top": PAGE_SIZE})
        return [p["name"] for p in (data or {}).get("value", [])]

    # --- configuration -----------------------------------------------------

    def snapshot(self) -> Iterator[RawRecord]:
        """What this organisation has configured."""
        with self._client() as client:
            data = self._get(client, "/_apis/projects", **{"$top": PAGE_SIZE})
            all_projects = (data or {}).get("value", [])
            wanted = set(self.projects)
            projects = [
                p for p in all_projects if not wanted or p["name"] in wanted
            ]

            for project in projects:
                name = project["name"]
                yield RawRecord(
                    kind="config_object",
                    natural_key=f"ado:project:{project['id']}",
                    label=name,
                    payload={
                        "name": name,
                        "description": project.get("description"),
                        "state": project.get("state"),
                        "visibility": project.get("visibility"),
                        "lastUpdateTime": project.get("lastUpdateTime"),
                    },
                    source_ref=f"{self.base_url}/{self.organization}/{name}",
                    provenance=f"Azure DevOps › Project › {name}",
                    layer="configuration",
                )

                yield from self._pipelines(client, project)
                yield from self._environments(client, project)
                yield from self._service_connections(client, project)
                yield from self._variable_groups(client, project)
                yield from self._release_definitions(project)

    def _pipelines(self, client: httpx.Client, project: dict) -> Iterator[RawRecord]:
        """Build and YAML pipeline definitions.

        Fetched with `includeAllProperties` so the response carries the process,
        variables and triggers. Without it Azure DevOps returns a shallow
        reference, and a pipeline with no visible steps is worse than absent —
        it looks extracted and answers nothing.
        """
        name = project["name"]
        data = self._get(
            client,
            f"/{name}/_apis/build/definitions",
            includeAllProperties="true",
            **{"$top": PAGE_SIZE},
        )
        if data is None:
            return

        for definition in data.get("value", []):
            repo = definition.get("repository") or {}
            process = definition.get("process") or {}
            variables = definition.get("variables") or {}

            # A YAML pipeline points at a file; a classic one carries its steps
            # inline. Which one this is changes how drift must be detected, so
            # it is recorded rather than inferred later.
            yaml_path = process.get("yamlFilename")
            style = "yaml" if yaml_path else "classic"

            relations: list[tuple[str, str]] = [
                ("BELONGS_TO", f"ado:project:{project['id']}")
            ]
            for group_id in definition.get("variableGroups") or []:
                gid = group_id.get("id") if isinstance(group_id, dict) else group_id
                if gid is not None:
                    relations.append(("DEPENDS_ON", f"ado:variablegroup:{gid}"))

            yield RawRecord(
                kind="integration",
                natural_key=f"ado:pipeline:{project['id']}:{definition['id']}",
                label=f"{name} › {definition.get('name')}",
                payload={
                    "name": definition.get("name"),
                    "style": style,
                    "yamlFilename": yaml_path,
                    "path": definition.get("path"),
                    "queueStatus": definition.get("queueStatus"),
                    # The drift sentinel. Polling this is how a configuration
                    # change is noticed at all, since no webhook reports one.
                    "revision": definition.get("revision"),
                    "repository": {
                        "name": repo.get("name"),
                        "type": repo.get("type"),
                        "defaultBranch": repo.get("defaultBranch"),
                    },
                    # Names and secrecy flags only — Azure DevOps returns null
                    # for secret values, and that is preserved rather than
                    # dropped, because the dependency is the useful part.
                    "variables": {
                        key: {
                            "isSecret": bool(value.get("isSecret")),
                            "value": None if value.get("isSecret") else value.get("value"),
                        }
                        for key, value in variables.items()
                        if isinstance(value, dict)
                    },
                    "triggers": [
                        t.get("triggerType") for t in definition.get("triggers") or []
                    ],
                },
                source_ref=(definition.get("_links") or {})
                .get("web", {})
                .get("href", ""),
                provenance=f"Azure DevOps › {name} › Pipeline › {definition.get('name')}",
                layer="configuration",
                relations=relations,
            )

    def _environments(self, client: httpx.Client, project: dict) -> Iterator[RawRecord]:
        """Environments, and the checks that gate deployment into them."""
        name = project["name"]
        data = self._get(
            client, f"/{name}/_apis/distributedtask/environments", **{"$top": PAGE_SIZE}
        )
        if data is None:
            return

        for env in data.get("value", []):
            yield RawRecord(
                kind="config_object",
                natural_key=f"ado:environment:{project['id']}:{env['id']}",
                label=f"{name} › {env.get('name')}",
                payload={
                    "name": env.get("name"),
                    "description": env.get("description"),
                    "resourceCount": len(env.get("resources") or []),
                },
                source_ref=f"{self.base_url}/{self.organization}/{name}/_environments/{env['id']}",
                provenance=f"Azure DevOps › {name} › Environment › {env.get('name')}",
                layer="configuration",
                relations=[("BELONGS_TO", f"ado:project:{project['id']}")],
            )
            yield from self._checks(client, project, env)

    def _checks(
        self, client: httpx.Client, project: dict, env: dict
    ) -> Iterator[RawRecord]:
        """Approval gates on an environment.

        Preview API, and its `settings` payload is undocumented. When it cannot
        be read, nothing is emitted — an environment with unknown checks must
        not be recorded as an environment with no checks, since the whole point
        of extracting these is to show where approval is required.
        """
        name = project["name"]
        data = self._get(
            client,
            f"/{name}/_apis/pipelines/checks/configurations",
            version=CHECKS_API_VERSION,
            resourceType="environment",
            resourceId=str(env["id"]),
            **{"$expand": "settings"},
        )
        if data is None:
            return

        for check in data.get("value", []):
            check_type = (check.get("type") or {}).get("name", "Check")
            settings_blob = check.get("settings") or {}
            approvers = [
                a.get("displayName")
                for a in settings_blob.get("approvers") or []
                if isinstance(a, dict) and a.get("displayName")
            ]

            yield RawRecord(
                kind="policy",
                natural_key=f"ado:check:{check['id']}",
                label=f"{env.get('name')} › {check_type}",
                payload={
                    "type": check_type,
                    "isDisabled": check.get("isDisabled", False),
                    "timeout": check.get("timeout"),
                    "approvers": approvers,
                    "minRequiredApprovers": settings_blob.get("minRequiredApprovers"),
                    "environment": env.get("name"),
                },
                source_ref=f"{self.base_url}/{self.organization}/{name}/_environments/{env['id']}/checks",
                provenance=(
                    f"Azure DevOps › {name} › {env.get('name')} › Approvals and checks"
                ),
                layer="configuration",
                relations=[
                    ("GOVERNED_BY", f"ado:environment:{project['id']}:{env['id']}")
                ],
            )

    def _service_connections(
        self, client: httpx.Client, project: dict
    ) -> Iterator[RawRecord]:
        """Service connections — where a pipeline is allowed to reach."""
        name = project["name"]
        data = self._get(client, f"/{name}/_apis/serviceendpoint/endpoints")
        if data is None:
            return

        for endpoint in data.get("value", []):
            yield RawRecord(
                kind="integration",
                natural_key=f"ado:serviceconnection:{endpoint['id']}",
                label=f"{name} › {endpoint.get('name')}",
                payload={
                    "name": endpoint.get("name"),
                    "type": endpoint.get("type"),
                    "url": endpoint.get("url"),
                    "scheme": (endpoint.get("authorization") or {}).get("scheme"),
                    "isShared": endpoint.get("isShared"),
                    "isReady": endpoint.get("isReady"),
                },
                source_ref=f"{self.base_url}/{self.organization}/{name}/_settings/adminservices",
                provenance=(
                    f"Azure DevOps › {name} › Service connection › {endpoint.get('name')}"
                ),
                layer="configuration",
                relations=[("BELONGS_TO", f"ado:project:{project['id']}")],
            )

    def _variable_groups(
        self, client: httpx.Client, project: dict
    ) -> Iterator[RawRecord]:
        """Variable groups — shared configuration a pipeline change can break."""
        name = project["name"]
        data = self._get(
            client, f"/{name}/_apis/distributedtask/variablegroups", **{"$top": PAGE_SIZE}
        )
        if data is None:
            return

        for group in data.get("value", []):
            variables = group.get("variables") or {}
            yield RawRecord(
                kind="config_object",
                natural_key=f"ado:variablegroup:{group['id']}",
                label=f"{name} › {group.get('name')}",
                payload={
                    "name": group.get("name"),
                    "description": group.get("description"),
                    "type": group.get("type"),
                    # Secret values come back null from Azure DevOps. The name
                    # and the flag are kept: "this pipeline depends on a secret
                    # called DB_PASSWORD" is exactly what impact analysis needs.
                    "variables": {
                        key: {"isSecret": bool(value.get("isSecret"))}
                        for key, value in variables.items()
                        if isinstance(value, dict)
                    },
                },
                source_ref=f"{self.base_url}/{self.organization}/{name}/_library",
                provenance=(
                    f"Azure DevOps › {name} › Variable group › {group.get('name')}"
                ),
                layer="configuration",
                relations=[("BELONGS_TO", f"ado:project:{project['id']}")],
            )

    def _release_definitions(self, project: dict) -> Iterator[RawRecord]:
        """Classic release definitions, from the vsrm host.

        Approvals come back inline here, unlike YAML pipelines where they are a
        separate preview call — so classic releases actually yield a richer
        gate picture than modern ones.
        """
        name = project["name"]
        try:
            with self._client(VSRM_HOST) as client:
                data = self._get(
                    client,
                    f"/{name}/_apis/release/definitions",
                    **{"$expand": "environments", "$top": PAGE_SIZE},
                )
        except httpx.HTTPError:
            return
        if data is None:
            return

        for definition in data.get("value", []):
            stages = []
            for env in definition.get("environments") or []:
                pre = (env.get("preDeployApprovals") or {}).get("approvals") or []
                approvers = [
                    (a.get("approver") or {}).get("displayName")
                    for a in pre
                    if not a.get("isAutomated") and (a.get("approver") or {}).get("displayName")
                ]
                stages.append(
                    {
                        "name": env.get("name"),
                        "rank": env.get("rank"),
                        "approvers": approvers,
                        "automated": not approvers,
                    }
                )

            # Sorted by rank rather than trusting response order. Stages are a
            # sequence — "which gate comes before production" is the question
            # asked of a release — and Azure DevOps does not promise the array
            # arrives ordered.
            #
            # These stay payload rather than becoming their own nodes with
            # ordered assertions: a classic release stage has no identity
            # outside its definition, and promoting it to a node would create
            # entities nothing else in the graph can reference.
            stages.sort(key=lambda s: s.get("rank") if s.get("rank") is not None else 0)

            yield RawRecord(
                kind="integration",
                natural_key=f"ado:release:{definition['id']}",
                label=f"{name} › {definition.get('name')}",
                payload={
                    "name": definition.get("name"),
                    "style": "classic-release",
                    "revision": definition.get("revision"),
                    "stages": stages,
                    "gatedStages": [s["name"] for s in stages if s["approvers"]],
                },
                source_ref=(definition.get("_links") or {})
                .get("web", {})
                .get("href", ""),
                provenance=f"Azure DevOps › {name} › Release › {definition.get('name')}",
                layer="configuration",
                relations=[("BELONGS_TO", f"ado:project:{project['id']}")],
            )

    # --- runtime -----------------------------------------------------------

    def observe(self) -> Iterator[RawRecord]:
        """What actually deployed.

        Configuration says a gate exists; deployment history says whether it
        ever held anything. Both are needed to answer "is this control real".
        """
        with self._client() as client:
            data = self._get(client, "/_apis/projects", **{"$top": PAGE_SIZE})
            wanted = set(self.projects)
            for project in (data or {}).get("value", []):
                if wanted and project["name"] not in wanted:
                    continue
                yield from self._deployments(client, project)

    def _deployments(self, client: httpx.Client, project: dict) -> Iterator[RawRecord]:
        name = project["name"]
        envs = self._get(
            client, f"/{name}/_apis/distributedtask/environments", **{"$top": PAGE_SIZE}
        )
        if envs is None:
            return

        for env in envs.get("value", []):
            records = self._get(
                client,
                f"/{name}/_apis/distributedtask/environments/{env['id']}"
                "/environmentdeploymentrecords",
                # `top`, not `$top`, on this endpoint specifically.
                top=PAGE_SIZE,
            )
            if records is None:
                continue

            for record in records.get("value", []):
                owner = record.get("owner") or {}
                yield RawRecord(
                    kind="config_object",
                    natural_key=f"ado:deployment:{record.get('id')}",
                    label=f"{env.get('name')} ← {record.get('stageName')}",
                    payload={
                        "stageName": record.get("stageName"),
                        "jobName": record.get("jobName"),
                        "result": record.get("result"),
                        "queueTime": record.get("queueTime"),
                        "startTime": record.get("startTime"),
                        "finishTime": record.get("finishTime"),
                        "definition": (record.get("definition") or {}).get("name"),
                        "owner": owner.get("name"),
                    },
                    source_ref=(record.get("owner") or {}).get("_links", {})
                    .get("web", {})
                    .get("href", ""),
                    provenance=(
                        f"Azure DevOps › {name} › {env.get('name')} › Deployment "
                        f"{record.get('id')}"
                    ),
                    layer="runtime",
                    relations=[
                        (
                            "DEPLOYED_TO",
                            f"ado:environment:{project['id']}:{env['id']}",
                        )
                    ],
                )

    def subscribe_to_changes(self) -> str | None:
        """Service hooks cover runs, not definitions.

        Returning the endpoint anyway is honest: run events are genuinely
        useful, and the gap — no event fires when someone edits a pipeline — is
        stated in the connector's declared limitations rather than hidden by
        returning None here.
        """
        return "/webhooks/azure-devops"
