# Meridian backend

The system of record for enterprise change. This document covers what exists,
what does not, and the reasoning behind the parts that are easy to get wrong.

## Running it

```bash
docker compose up -d                      # Postgres 17 (+pgvector) and Redis
cp .env.example .env                      # every value has a working default
python -m pip install -e ".[dev]"
python -m api.seed                        # a small, honest working set
python -m uvicorn api.main:app --reload   # http://localhost:8000
```

`GET /health` reports what is degraded:

```json
{"status":"ok","llm":"stub","connectorsImplemented":["cx-apispec","cx-github","cx-jira"]}
```

**Postgres runs on host port 5433, not 5432.** A locally installed Postgres
commonly already holds 5432, and when it does it wins the bind while Docker
still reports the mapping as published — the connection then succeeds against
the wrong server and fails on authentication with a confusing message.

Tests need the containers running; they use a separate `meridian_test`
database, created automatically.

```bash
python -m pytest          # 35 tests
```

## Architecture

```
api/
  core/        config, database session, id and time conventions
  domain/      SQLAlchemy models mirroring src/lib/types.ts
  ledger/      the hash chain — server-authoritative
  graph/       normalisation, traversal, entity resolution
  connectors/  the EnterpriseConnector contract + three real implementations
  ingest/      connector → evidence → normalise → audit
  agents/      the LLM boundary, impact analysis, test generation
  services/    approvals, execution — where governance rules are enforced
  routers/     HTTP, one endpoint per src/lib/api.ts function
  schemas/     snake_case ORM → camelCase wire
```

## The decisions worth knowing

### The ledger is a byte-for-byte port

`api/ledger/chain.py::canonicalise` reproduces `src/lib/audit.ts::canonicalise`
exactly, field order included. If the two drift, a chain written by one and
verified by the other reports tampering that did not happen — a false alarm on
the single control the product is built around.

One divergence is subtle enough to be worth naming: JavaScript's `String(1)` is
`"1"` while Python's `str(1.0)` is `"1.0"`. A temperature of exactly 1 would
hash differently on the two sides while every fractional value agreed, so the
chain would verify in testing and fail in production. `_js_number` handles it
and `tests/test_canonicalise.py` locks it down.

Appends take a Postgres advisory lock. Two concurrent writers would otherwise
read the same head, compute the same `seq`, and fork the chain.

### Graph edges are reified assertions

An edge is not a foreign key between two nodes. It is a row with an author,
evidence, a confidence, a validity window and a superseding chain. Storing it
as a bare relationship throws all of that away and leaves you unable to answer
"who said so, and what did they look at" — which is the question an audit
actually asks.

The frontend still receives the simpler `GraphEdge` shape. That is a
presentation choice; the extra dimensions are queryable whether or not the
current UI draws them.

`confidence: 'confirmed'` is returned **only** when a human confirmed the link.
Machine-proposed edges can never present as facts.

### Entity resolution matches on natural key, never on label

Two nodes merge only when they carry the same source-system identifier. Merging
on display name is how a graph silently acquires wrong edges — and the
wrongness is invisible, because the result looks tidy.

Cross-source links (a GitHub PR mentioning a Jira key) are deliberately *not*
auto-resolved. They are recorded as unresolved so a mapping step can pick them
up with its own confidence.

### Impact analysis: the graph decides what, the model decides why

Traversal runs first and is deterministic. The model never adds a node to the
result; it can only grade and explain the ones traversal found. A node id in
the model's reply that was not in its input is dropped and reported as a
hallucinated citation.

Traversal is bidirectional (a change to a field affects what reads it *and* is
constrained by what exposes it), cycle-guarded (configuration graphs are full
of cycles), and confidence-aware. `path_confidence` is the **weakest** link on
the path — a chain is only as strong as its weakest edge, and reporting the
strongest would overstate what the graph knows.

Blind spots are computed, not asked of the model. An analysis that lists
nothing it could not reason about is claiming omniscience.

### The verified/asserted rule is enforced, not displayed

A gate carrying `requires_evidence_grade: 'verified'` is refused server-side
while only asserted evidence exists, with the reasons returned as prose the
reviewer can act on. A rule enforced only in the UI is a suggestion — anyone
with a terminal can approve past it, and the audit trail then records a
decision the product's own policy said was impossible.

The grade is mechanical: `automatable AND has artifacts` ⇒ verified, otherwise
asserted. It is never taken from the caller, because a runner that could
declare its own output verified would make the distinction meaningless.

Related rules in the same place:

- A *rejection* is never blocked. Blockers are reasons not to approve; using
  them to prevent a rejection would trap a package that should be sent back.
- `fixed` and `closed` are distinct. Only a passing re-test closes a defect —
  `PATCH /defects/{id}/status` to `closed` returns 409 without one.
- Overriding an AI recommendation without a written rationale is refused
  (EU AI Act Art. 14). `overridden` is derived from the two values, not claimed
  by the client.

### Nothing fabricates evidence

This is the constraint that shaped the most code.

- A case no runner reported is `skipped`, never `passed`.
- With no `ANTHROPIC_API_KEY`, agent endpoints return **labelled** stub output
  (`source: "stub"`) — impact items come back `severity: "none"` with "nothing
  has assessed this", not a plausible guess.
- `api/seed.py` seeds organisation, graph, policies and environments, but **no
  test evidence, approvals or cost history**. A seeded "verified" run would
  satisfy a real gate.
- Analytics aggregate from `cost_events` rows written by the code that spent
  the money. `cycleTime` returns empty rather than inventing a baseline this
  installation does not have.
- `crawlSite`, `generateCasesFromCrawl` and `runProposedCases` throw
  `NotImplementedYet`. Meridian cannot drive a browser yet.

### Connectors: three real, seven declared

Implemented and working: **Jira** (projects, fields, statuses, workflows with
transitions, issue changelogs), **GitHub** (repos, CI workflows, PRs with
issue-key extraction), **API specs** (OpenAPI/Swagger/Postman → endpoints,
schemas, `$ref` relations).

Declared but not built, and flagged `comingSoon` in the catalogue: Workday,
SAP, Dynamics 365, Azure DevOps, Confluence, Figma, ServiceNow. Shipping a
hundred stub classes that raise `NotImplementedError` would make the product
look finished while every connection failed.

Each connector separates the three truths the transcript insists on:

```
platform capability  ≠  tenant configuration  ≠  observed runtime behaviour
```

`discover_capabilities` reports what the product supports, `snapshot` what this
customer configured, `observe` what actually ran. A connector that conflates
them produces a graph that cannot answer "is this configured, or did someone
just do it once".

Connectors never write to the graph. They emit `RawRecord`s; evidence is stored
**before** normalisation, so if normalisation produces something suspicious the
raw record is still on disk to check against.

## Wiring the frontend

Components only ever talk to `src/lib/api.ts`. To go live, re-export the live
client from there:

```ts
// src/lib/api.ts
export { liveApi as api, ApiError, NotImplementedYet, setActor } from './api-live'
```

`src/lib/http.ts` holds the fetch mechanics and `VITE_API_URL`
(default `http://localhost:8000/api`).

Two things the UI should handle that the mock never produced:

1. **`ApiError` with `reasons`** — a 409 from a gate carries the specific list
   of blockers. Surface them; the refusal *is* the feature.
2. **`NotImplementedYet`** — show it as "not built yet", not as an error.

`GET /approvals/{pkg}/gates/{gate}/blockers` answers "would this be refused"
before the user tries.

## Not built

Stated plainly so nothing here is mistaken for finished.

- **Authentication.** The actor comes from `X-Actor-*` headers with a
  documented default (`api/routers/deps.py`). Until this lands, the audit chain
  attributes actions to a *claimed* identity, not a verified one.
- **Migrations.** `create_all` at startup; adequate for development, but it
  will not alter an existing table. Alembic is a dependency and unused.
- **Background jobs.** Redis is running and unused. Sync is synchronous, so a
  large tenant will block a request; `MAX_RECORDS` caps a run at 20,000 and
  *reports* the truncation rather than hiding it.
- **Object storage.** Evidence writes to `./evidence` with content hashes. The
  interface is the same for S3; only the write path changes.
- **Vector search.** pgvector is installed. `queries.search` is `ILIKE` and
  says so.
- **Test closure evaluation.** The model and endpoints exist; the service that
  recomputes exit criteria from live results does not.
