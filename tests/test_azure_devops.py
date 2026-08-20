"""
The Azure DevOps connector.

Tested against recorded response shapes rather than a live organisation. The
fixtures reproduce what the REST API actually returns — secret variables as
`null` with the flag preserved, service-connection passwords absent rather than
masked, the `vsrm` host for releases, and approvals inline on classic release
environments but a separate preview call for YAML ones. Those asymmetries are
what naive extraction gets wrong.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from api.connectors.azure_devops import (
    API_VERSION,
    CHECKS_API_VERSION,
    VSRM_HOST,
    AzureDevOpsConnector,
    _pat_header,
)
from api.connectors.base import NotConfigured

PROJECT = {
    "id": "p-1",
    "name": "Payroll Platform",
    "description": "Payroll",
    "state": "wellFormed",
    "visibility": "private",
}

BUILD_DEFINITION = {
    "id": 42,
    "name": "payroll-ci",
    "path": "\\",
    "revision": 7,
    "queueStatus": "enabled",
    "repository": {"name": "payroll", "type": "TfsGit", "defaultBranch": "refs/heads/main"},
    "process": {"type": 2, "yamlFilename": "azure-pipelines.yml"},
    "variables": {
        "buildConfiguration": {"value": "Release"},
        # Azure DevOps returns secret values as null and keeps the flag.
        "DB_PASSWORD": {"value": None, "isSecret": True},
    },
    "variableGroups": [{"id": 9}],
    "triggers": [{"triggerType": "continuousIntegration"}],
    "_links": {"web": {"href": "https://dev.azure.com/contoso/_build?definitionId=42"}},
}


def _connector(**config) -> AzureDevOpsConnector:
    values = {"organization": "contoso", "pat": "TOKEN"}
    values.update(config)
    return AzureDevOpsConnector(values)


def _transport(routes: dict[str, dict]) -> httpx.MockTransport:
    """Route by path, so a call to the wrong host or path fails loudly."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.url.host}{request.url.path}"
        if key not in routes:
            return httpx.Response(404, json={"message": f"no route for {key}"})
        return httpx.Response(200, json=routes[key])

    return httpx.MockTransport(handler)


# --- authentication ------------------------------------------------------


def test_pat_header_is_basic_with_empty_username():
    """Azure DevOps expects ':PAT' base64-encoded, not the PAT alone.

    Getting this wrong produces a 203 with an HTML sign-in page rather than a
    401, so it fails in a way that does not look like an auth failure.
    """
    header = _pat_header("TOKEN")
    assert header.startswith("Basic ")
    decoded = base64.b64decode(header.removeprefix("Basic ")).decode()
    assert decoded == ":TOKEN"


def test_unconfigured_refuses_rather_than_calling_out():
    with pytest.raises(NotConfigured):
        AzureDevOpsConnector({})._client()


def test_validate_access_reports_which_surface_is_missing():
    """A missing scope must be named, not collapsed into 'connection failed'."""
    conn = _connector()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/_apis/projects"):
            return httpx.Response(200, json={"value": [PROJECT]})
        if "/build/definitions" in path:
            return httpx.Response(200, json={"value": []})
        # Release, environments and service endpoints are all forbidden.
        return httpx.Response(403, json={"message": "denied"})

    original = conn._client

    def patched(host=None):
        client = original(host)
        client._transport = httpx.MockTransport(handler)
        return client

    conn._client = patched  # type: ignore[method-assign]
    check = conn.validate_access()

    assert check.ok is True
    assert "read.build" in check.effective_scopes
    assert "read.release" in check.missing_scopes
    assert "read.environment" in check.missing_scopes
    assert "read.release" in check.message


def test_validate_access_without_credentials_is_specific():
    assert "organisation" in AzureDevOpsConnector({}).validate_access().message
    assert "token" in AzureDevOpsConnector({"organization": "x"}).validate_access().message


# --- extraction ----------------------------------------------------------


def _snapshot(conn: AzureDevOpsConnector, routes: dict[str, dict]) -> list:
    original = conn._client

    def patched(host=None):
        client = original(host)
        client._transport = _transport(routes)
        return client

    conn._client = patched  # type: ignore[method-assign]
    return list(conn.snapshot())


def test_pipeline_keeps_secret_flag_but_never_a_secret_value():
    """The dependency is the useful part; the value must not be stored."""
    conn = _connector(projects="Payroll Platform")
    records = _snapshot(
        conn,
        {
            "dev.azure.com/contoso/_apis/projects": {"value": [PROJECT]},
            "dev.azure.com/contoso/Payroll Platform/_apis/build/definitions": {
                "value": [BUILD_DEFINITION]
            },
        },
    )

    pipeline = next(r for r in records if r.natural_key.startswith("ado:pipeline:"))
    variables = pipeline.payload["variables"]
    assert variables["DB_PASSWORD"]["isSecret"] is True
    assert variables["DB_PASSWORD"]["value"] is None
    assert variables["buildConfiguration"]["value"] == "Release"


def test_pipeline_records_revision_for_drift_detection():
    """No webhook reports a definition edit, so the revision is the sentinel."""
    conn = _connector(projects="Payroll Platform")
    records = _snapshot(
        conn,
        {
            "dev.azure.com/contoso/_apis/projects": {"value": [PROJECT]},
            "dev.azure.com/contoso/Payroll Platform/_apis/build/definitions": {
                "value": [BUILD_DEFINITION]
            },
        },
    )
    pipeline = next(r for r in records if r.natural_key.startswith("ado:pipeline:"))
    assert pipeline.payload["revision"] == 7


def test_yaml_and_classic_pipelines_are_distinguished():
    """They differ in how drift can be detected, so the style is recorded."""
    classic = {**BUILD_DEFINITION, "id": 43, "name": "legacy", "process": {"type": 1}}
    conn = _connector(projects="Payroll Platform")
    records = _snapshot(
        conn,
        {
            "dev.azure.com/contoso/_apis/projects": {"value": [PROJECT]},
            "dev.azure.com/contoso/Payroll Platform/_apis/build/definitions": {
                "value": [BUILD_DEFINITION, classic]
            },
        },
    )
    styles = {
        r.payload["name"]: r.payload["style"]
        for r in records
        if r.natural_key.startswith("ado:pipeline:")
    }
    assert styles == {"payroll-ci": "yaml", "legacy": "classic"}


def test_natural_key_is_scoped_by_project():
    """Definition ids repeat across projects; an unscoped key would merge them."""
    conn = _connector(projects="Payroll Platform")
    records = _snapshot(
        conn,
        {
            "dev.azure.com/contoso/_apis/projects": {"value": [PROJECT]},
            "dev.azure.com/contoso/Payroll Platform/_apis/build/definitions": {
                "value": [BUILD_DEFINITION]
            },
        },
    )
    pipeline = next(r for r in records if r.natural_key.startswith("ado:pipeline:"))
    assert pipeline.natural_key == "ado:pipeline:p-1:42"


def test_missing_surface_is_skipped_not_fatal():
    """A PAT without the release scope still yields everything else."""
    conn = _connector(projects="Payroll Platform")
    records = _snapshot(
        conn,
        {
            "dev.azure.com/contoso/_apis/projects": {"value": [PROJECT]},
            # No build/environment/endpoint routes at all: every one 404s.
        },
    )
    assert [r.natural_key for r in records] == ["ado:project:p-1"]


def test_environment_checks_are_read_from_the_preview_api():
    conn = _connector(projects="Payroll Platform")
    records = _snapshot(
        conn,
        {
            "dev.azure.com/contoso/_apis/projects": {"value": [PROJECT]},
            "dev.azure.com/contoso/Payroll Platform/_apis/distributedtask/environments": {
                "value": [{"id": 5, "name": "production", "resources": []}]
            },
            "dev.azure.com/contoso/Payroll Platform/_apis/pipelines/checks/configurations": {
                "value": [
                    {
                        "id": 77,
                        "type": {"name": "Approval"},
                        "timeout": 43200,
                        "settings": {
                            "approvers": [{"displayName": "Release Managers"}],
                            "minRequiredApprovers": 1,
                        },
                    }
                ]
            },
        },
    )
    check = next(r for r in records if r.kind == "policy")
    assert check.payload["approvers"] == ["Release Managers"]
    assert check.payload["type"] == "Approval"
    assert ("GOVERNED_BY", "ado:environment:p-1:5") in check.relations


def test_unreadable_checks_emit_nothing_rather_than_claiming_no_approvals():
    """'Unknown' and 'none' mean opposite things to someone auditing a gate."""
    conn = _connector(projects="Payroll Platform")
    records = _snapshot(
        conn,
        {
            "dev.azure.com/contoso/_apis/projects": {"value": [PROJECT]},
            "dev.azure.com/contoso/Payroll Platform/_apis/distributedtask/environments": {
                "value": [{"id": 5, "name": "production", "resources": []}]
            },
            # The preview checks endpoint is absent -> 404.
        },
    )
    assert any(r.natural_key == "ado:environment:p-1:5" for r in records)
    assert not [r for r in records if r.kind == "policy"]


def test_release_definitions_use_the_vsrm_host():
    """Constructing this from the org URL is the classic integration mistake."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.path.endswith("/_apis/projects"):
            return httpx.Response(200, json={"value": [PROJECT]})
        if "/release/definitions" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": 3,
                            "name": "payroll-release",
                            "revision": 2,
                            "environments": [
                                {
                                    "name": "prod",
                                    "rank": 1,
                                    "preDeployApprovals": {
                                        "approvals": [
                                            {
                                                "isAutomated": False,
                                                "approver": {"displayName": "CAB"},
                                            }
                                        ]
                                    },
                                }
                            ],
                        }
                    ]
                },
            )
        return httpx.Response(404, json={})

    conn = _connector(projects="Payroll Platform")
    original = conn._client

    def patched(host=None):
        client = original(host)
        client._transport = httpx.MockTransport(handler)
        return client

    conn._client = patched  # type: ignore[method-assign]
    records = list(conn.snapshot())

    assert VSRM_HOST in seen
    release = next(r for r in records if r.natural_key == "ado:release:3")
    assert release.payload["gatedStages"] == ["prod"]
    assert release.payload["stages"][0]["approvers"] == ["CAB"]


def test_service_connection_carries_no_credentials():
    conn = _connector(projects="Payroll Platform")
    records = _snapshot(
        conn,
        {
            "dev.azure.com/contoso/_apis/projects": {"value": [PROJECT]},
            "dev.azure.com/contoso/Payroll Platform/_apis/serviceendpoint/endpoints": {
                "value": [
                    {
                        "id": "sc-1",
                        "name": "prod-subscription",
                        "type": "azurerm",
                        "url": "https://management.azure.com/",
                        "authorization": {
                            "scheme": "ServicePrincipal",
                            "parameters": {"serviceprincipalid": "abc"},
                        },
                    }
                ]
            },
        },
    )
    endpoint = next(r for r in records if r.natural_key == "ado:serviceconnection:sc-1")
    blob = str(endpoint.payload)
    assert endpoint.payload["scheme"] == "ServicePrincipal"
    assert "serviceprincipalid" not in blob
    assert "abc" not in blob


def test_pipeline_links_to_its_variable_group():
    conn = _connector(projects="Payroll Platform")
    records = _snapshot(
        conn,
        {
            "dev.azure.com/contoso/_apis/projects": {"value": [PROJECT]},
            "dev.azure.com/contoso/Payroll Platform/_apis/build/definitions": {
                "value": [BUILD_DEFINITION]
            },
        },
    )
    pipeline = next(r for r in records if r.natural_key.startswith("ado:pipeline:"))
    assert ("DEPENDS_ON", "ado:variablegroup:9") in pipeline.relations


def test_projects_filter_limits_extraction():
    other = {**PROJECT, "id": "p-2", "name": "Other"}
    conn = _connector(projects="Payroll Platform")
    records = _snapshot(
        conn,
        {"dev.azure.com/contoso/_apis/projects": {"value": [PROJECT, other]}},
    )
    assert [r.natural_key for r in records] == ["ado:project:p-1"]


# --- declared contract ---------------------------------------------------


def test_api_versions_are_pinned():
    """7.1 is stable; checks are preview and must say so at the call site."""
    assert API_VERSION == "7.1"
    assert CHECKS_API_VERSION.endswith("-preview.1")


def test_no_scope_grants_write():
    assert not [s for s in AzureDevOpsConnector.scopes if s.writes]
