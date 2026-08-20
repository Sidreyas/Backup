"""
Connectors, normalisation and the ingestion pipeline.

The connectors themselves are tested against a fake HTTP transport rather than
a live tenant: a test that needs someone's Jira credentials is a test that
never runs. What is verified here is the part that is actually ours — that a
connector's output becomes the right nodes and assertions, that resolution
matches on natural key rather than label, and that a partial failure still
lands what it collected.
"""

from __future__ import annotations

import json

import httpx
import pytest

from api.connectors.apispec import ApiSpecConnector
from api.connectors.base import ConnectorError, EnterpriseConnector, RawRecord
from api.connectors.github import ISSUE_KEY
from api.connectors.jira import JiraConnector
from api.core.ids import new_id
from api.domain import enums
from api.domain.models import Assertion, ExtractionRun, GraphNode, KnowledgeSource
from api.graph.normalize import Normalizer
from api.ingest.pipeline import ingest


# ------------------------------------------------------------- normalisation


@pytest.fixture
def run(db) -> ExtractionRun:
    r = ExtractionRun(
        id=new_id("xr"), connector_id="cx-test", extractor_version="1", workspace_id="ws-test"
    )
    db.add(r)
    db.flush()
    return r


@pytest.fixture
def source(db) -> KnowledgeSource:
    s = KnowledgeSource(
        id=new_id("src"),
        workspace_id="ws-test",
        name="Test source",
        kind=enums.SourceKind.TICKETING,
        provider="Test",
    )
    db.add(s)
    db.flush()
    return s


def _normalizer(db, run, source) -> Normalizer:
    return Normalizer(db, run, source_id=source.id, workspace_id="ws-test")


def test_records_become_nodes_and_assertions(db, run, source):
    records = [
        RawRecord(
            kind="business_process",
            natural_key="test:wf:1",
            label="Approval workflow",
            payload={"description": "Two-step approval"},
            relations=[("HAS_STEP", "test:status:1")],
        ),
        RawRecord(
            kind="config_object",
            natural_key="test:status:1",
            label="Pending approval",
            payload={},
        ),
    ]
    result = _normalizer(db, run, source).ingest(records)

    assert result.nodes_created == 2
    assert result.assertions_proposed == 1

    assertion = db.query(Assertion).filter(Assertion.extraction_run_id == run.id).one()
    # Structure a source states about itself is strong evidence — but still a
    # claim about what the extractor read, never a confirmed fact.
    assert assertion.confidence == enums.LinkConfidence.HIGH
    assert assertion.status == enums.AssertionStatus.PROPOSED
    assert assertion.confirmed_by is None


def test_resolution_matches_natural_key_not_label(db, run, source):
    """Two unrelated objects both called "Approval" must not merge.

    Merging on display name is how a graph silently acquires wrong edges, and
    the wrongness is invisible because the result looks tidy.
    """
    first = [
        RawRecord(kind="config_object", natural_key="test:a", label="Approval", payload={})
    ]
    _normalizer(db, run, source).ingest(first)

    second = [
        RawRecord(kind="config_object", natural_key="test:b", label="Approval", payload={})
    ]
    result = _normalizer(db, run, source).ingest(second)

    assert result.nodes_created == 1
    assert db.query(GraphNode).filter(GraphNode.label == "Approval").count() == 2


def test_re_extraction_updates_rather_than_duplicates(db, run, source):
    records = [
        RawRecord(kind="config_object", natural_key="test:a", label="Original", payload={})
    ]
    _normalizer(db, run, source).ingest(records)

    renamed = [
        RawRecord(kind="config_object", natural_key="test:a", label="Renamed", payload={})
    ]
    result = _normalizer(db, run, source).ingest(renamed)

    assert result.nodes_created == 0
    assert result.nodes_updated == 1
    # A node is an identity; a renamed object is the same object.
    assert db.query(GraphNode).filter(GraphNode.natural_key == "test:a").one().label == "Renamed"


def test_repeated_identical_assertion_is_not_duplicated(db, run, source):
    """Without this every sync would append a copy and the graph would grow
    without changing."""
    records = [
        RawRecord(
            kind="business_process",
            natural_key="test:wf",
            label="WF",
            payload={},
            relations=[("HAS_STEP", "test:st")],
        ),
        RawRecord(kind="config_object", natural_key="test:st", label="ST", payload={}),
    ]
    _normalizer(db, run, source).ingest(records)
    _normalizer(db, run, source).ingest(records)

    live = db.query(Assertion).filter(Assertion.superseded_at.is_(None)).count()
    assert live == 1


def test_invalid_records_are_rejected_and_reported(db, run, source):
    """A graph that quietly accepts malformed nodes is worse than one that is
    visibly incomplete."""
    records = [
        RawRecord(kind="not_a_real_kind", natural_key="test:x", label="X", payload={}),
        RawRecord(kind="config_object", natural_key="", label="No key", payload={}),
        RawRecord(kind="config_object", natural_key="test:ok", label="Fine", payload={}),
    ]
    result = _normalizer(db, run, source).ingest(records)

    assert result.nodes_created == 1
    assert len(result.rejected) == 2
    assert {r["reason"] for r in result.rejected} == {
        "unknown node kind 'not_a_real_kind'",
        "missing natural key",
    }


def test_unknown_predicate_is_refused(db, run, source):
    records = [
        RawRecord(
            kind="config_object",
            natural_key="test:a",
            label="A",
            payload={},
            relations=[("MADE_UP_PREDICATE", "test:b")],
        ),
        RawRecord(kind="config_object", natural_key="test:b", label="B", payload={}),
    ]
    result = _normalizer(db, run, source).ingest(records)
    assert result.assertions_proposed == 0
    assert any(r.get("reason") == "unknown predicate" for r in result.rejected)


def test_unresolved_relation_target_is_recorded_not_invented(db, run, source):
    """A GitHub PR mentioning a Jira key is evidence of a link, not proof. The
    target is not in this source, so nothing is asserted and the gap is kept."""
    records = [
        RawRecord(
            kind="code_module",
            natural_key="github:pr:1",
            label="PR #1",
            payload={},
            relations=[("IMPLEMENTED_BY", "jira:issue:MER-1")],
        )
    ]
    result = _normalizer(db, run, source).ingest(records)

    assert result.assertions_proposed == 0
    assert result.rejected[0]["reason"] == "target not found in this source"


# ------------------------------------------------------------------ pipeline


class _FakeConnector(EnterpriseConnector):
    id = "cx-fake"
    name = "Fake"
    extractor_version = "1"

    def __init__(self, records, *, fail_after=None):
        super().__init__({})
        self._records = records
        self._fail_after = fail_after

    def discover_capabilities(self):
        return []

    def validate_access(self):
        from api.connectors.base import AccessCheck

        return AccessCheck(ok=True, message="fine")

    def snapshot(self):
        for i, record in enumerate(self._records):
            if self._fail_after is not None and i == self._fail_after:
                raise ConnectorError("the tenant closed the connection")
            yield record


def test_pipeline_writes_evidence_before_normalising(db, source, tmp_path, monkeypatch):
    """If normalisation produces something suspicious, the raw record it came
    from must still be on disk to check against."""
    monkeypatch.setattr("api.ingest.pipeline.EVIDENCE_ROOT", tmp_path)

    connector = _FakeConnector(
        [RawRecord(kind="config_object", natural_key="test:a", label="A", payload={})]
    )
    outcome = ingest(db, connector, source=source, workspace_id="ws-test")

    assert outcome.status == "complete"
    assert outcome.nodes_created == 1

    written = list(tmp_path.glob("*.json"))
    assert len(written) == 1
    assert json.loads(written[0].read_text())[0]["naturalKey"] == "test:a"


def test_partial_failure_keeps_what_was_collected(db, source, tmp_path, monkeypatch):
    """A partial graph with a stated reason is more useful than nothing."""
    monkeypatch.setattr("api.ingest.pipeline.EVIDENCE_ROOT", tmp_path)

    records = [
        RawRecord(kind="config_object", natural_key=f"test:{i}", label=f"N{i}", payload={})
        for i in range(5)
    ]
    connector = _FakeConnector(records, fail_after=3)
    outcome = ingest(db, connector, source=source, workspace_id="ws-test")

    assert outcome.status == "partial"
    assert outcome.nodes_created == 3
    assert "closed the connection" in outcome.error


def test_coverage_reflects_what_was_usable_not_what_was_seen(
    db, source, tmp_path, monkeypatch
):
    """Reporting 100% while rejecting records would be exactly the flattering
    number this product exists to avoid."""
    monkeypatch.setattr("api.ingest.pipeline.EVIDENCE_ROOT", tmp_path)

    records = [
        RawRecord(kind="config_object", natural_key="test:a", label="A", payload={}),
        RawRecord(kind="bogus_kind", natural_key="test:b", label="B", payload={}),
    ]
    ingest(db, _FakeConnector(records), source=source, workspace_id="ws-test")
    assert source.coverage == 50


# --------------------------------------------------------------- connectors


def test_jira_reports_unconfigured_rather_than_erroring():
    """A connector nobody has configured is unconfigured, not broken."""
    connector = JiraConnector({"base_url": "", "email": "", "api_token": ""})
    assert not connector.is_configured()
    check = connector.validate_access()
    assert not check.ok
    assert "JIRA_BASE_URL" in check.message


def test_jira_parses_workflows_into_process_structure(monkeypatch):
    """The configuration layer is the point. Most Jira integrations read only
    issues; reading workflow definitions is what lets Meridian tell a product
    owner their change conflicts with a transition rule that already exists.
    """
    workflows = {
        "isLast": True,
        "values": [
            {
                "id": {"name": "Absence Workflow"},
                "description": "",
                "transitions": [
                    {
                        "id": "1",
                        "name": "Submit",
                        "type": "directed",
                        "from": [{"id": "10"}],
                        "to": {"id": "20"},
                        "rules": {},
                    }
                ],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "/workflow/search" in request.url.path:
            return httpx.Response(200, json=workflows)
        return httpx.Response(200, json={"values": [], "isLast": True})

    connector = JiraConnector(
        {"base_url": "https://acme.atlassian.net", "email": "a@b.c", "api_token": "t"}
    )
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        connector,
        "_client",
        lambda: httpx.Client(
            transport=transport, base_url="https://acme.atlassian.net/rest/api/3"
        ),
    )

    records = list(connector._workflows(connector._client()))
    assert len(records) == 1
    wf = records[0]
    assert wf.kind == "business_process"
    assert wf.layer == "configuration"
    assert ("HAS_STEP", "jira:status:10") in wf.relations
    assert ("ROUTES_TO", "jira:status:20") in wf.relations


def test_github_issue_key_pattern_is_conservative():
    """A false link is worse than a missing one in a graph people must trust."""
    assert ISSUE_KEY.findall("Fixes MER-1042 and PROJ-7") == ["MER-1042", "PROJ-7"]
    # Lowercase words followed by a number are overwhelmingly not issue keys.
    assert ISSUE_KEY.findall("see step-3 of v-2") == []


def test_apispec_extracts_endpoints_and_schemas(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Absence API", "version": "1.0"},
        "paths": {
            "/absences": {
                "post": {
                    "operationId": "createAbsence",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Absence"}
                            }
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Absence": {
                    "type": "object",
                    "required": ["days"],
                    "properties": {
                        "days": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                }
            }
        },
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")

    records = list(ApiSpecConnector({"source": str(path)}).snapshot())
    kinds = {r.kind for r in records}
    assert kinds == {"integration", "data_entity"}

    op = next(r for r in records if r.label == "POST /absences")
    # The $ref is followed into a relation, so impact analysis can answer
    # "which endpoints expose this field".
    assert ("READS", "apispec:schema:Absence API:Absence") in op.relations

    schema = next(r for r in records if r.kind == "data_entity")
    fields = {f["name"]: f["required"] for f in schema.payload["fields"]}
    assert fields == {"days": True, "reason": False}


def test_apispec_rejects_a_document_that_is_neither(tmp_path):
    path = tmp_path / "random.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")

    check = ApiSpecConnector({"source": str(path)}).validate_access()
    assert not check.ok
    assert "neither an OpenAPI" in check.message
