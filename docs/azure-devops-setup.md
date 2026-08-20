# Connecting Azure DevOps

What Meridian extracts, what your Azure DevOps administrator has to do, and the
four limitations worth knowing before you start.

You were right to expect this to be easier than Workday. Most of what Meridian
needs is exposed by REST API, so there are no artefacts to build first — four
setup steps rather than eight, and no report pack.

## What it extracts

| Surface | What it gives you | PAT scope |
|---|---|---|
| Projects | Projects and their metadata | Project and team (read) |
| Pipelines | Build and YAML definitions, stages, variables, triggers | Build (read) |
| Releases | Classic release definitions and their approval gates | Release (read) |
| Environments | Environments, approval checks, deployment history | Environment (read **and manage**) |
| Service connections | What a pipeline is allowed to reach | Service endpoints (read) |
| Variable groups | Shared configuration a pipeline change can break | Variable groups (read) |

The question this answers is the last leg of the traceability chain: *this
Workday approval change touches which pipelines, gated by whose approval,
deploying to which environment.*

## The limitations

**1. No webhook for pipeline definition changes.** Every pipeline event Azure
DevOps publishes fires on a *run* — started, stage changed, completed — and
none fires when someone edits a definition. For YAML pipelines the definition
lives in Git, so `git.push` is a partial proxy; for classic build and release
definitions there is no equivalent at all. Meridian detects drift by polling
each definition's `revision` integer, which increments on edit. Cheap to check,
so a full re-extraction is only paid for when something actually changed.

**2. Cross-repo YAML templates cannot be resolved read-only.** A pipeline that
`extends` a template in another repository has no REST representation naming
the resolved file. The only supported full expansion is `POST /preview` with
`previewRun: true` — which queues a dry run. Meridian will not do that: a
connector that says it is read-only must not queue anything. The definition is
extracted as stored, so a step living in a shared template is not visible.

**3. Approvals and checks are a preview API.** `7.1-preview.1`, and the
`settings` field carrying approver identities has no published schema. Meridian
reads it best-effort and emits nothing when it cannot — an environment whose
checks are unreadable must not be recorded as an environment with no checks,
because those mean opposite things to someone auditing a release gate.

**4. Reading environments needs a manage scope.** Microsoft publishes no
read-only equivalent of Environment; the only option is "Environment (read and
manage)". Meridian never writes, so this grant is broader than its use. Skip it
and everything else still works — you lose environments, approval gates and
deployment history.

## What your administrator does

Meridian shows this as an interactive checklist when you connect. Summarised:

1. **Create a personal access token** — `User settings › Personal access
   tokens › New Token`. Scope it to the organisation you are connecting and set
   an expiry your team will rotate. Shown once; copy it before closing.
2. **Grant read-only scopes** — ⚠ the step people get wrong. Tick the *Read*
   variant of: Project and team, Build, Release, Service endpoints, Variable
   groups. Never a write or manage box.
3. **Decide on the Environment scope** — see limitation 4. A deliberate
   decision, not an oversight.
4. **Note which projects to read** — optional. Leave empty to read everything
   the token can see; name them to keep the first extraction quick on a large
   organisation.

## Authentication

- **Personal access token** — the default. Sent as HTTP Basic with an empty
  username and the PAT as the password, base64-encoded. Getting this wrong
  returns a 203 with an HTML sign-in page rather than a 401, which is why it is
  worth stating exactly.
- **Microsoft Entra ID** — for organisations that do not permit PATs. Microsoft
  recommends this for new applications, and the legacy Azure DevOps OAuth flow
  is deprecated with full removal scheduled for 2026, so PATs are supported
  here but not the long-term path.

## Secrets

Azure DevOps never returns them, and Meridian keeps that shape:

- Secret pipeline and variable-group values come back `null` with
  `isSecret: true`. The flag is preserved — "this pipeline depends on a secret
  called `DB_PASSWORD`" is exactly what impact analysis needs, and the value is
  not.
- Service-connection credentials are omitted from the response entirely rather
  than masked.

## Rate limits

Microsoft publishes real numbers here, unlike Workday. The limit is 200 TSTUs
(throughput units) in a sliding five-minute window, tracked separately per
pipeline. Throttling signals arrive *before* requests fail: `Retry-After` is
sent on **HTTP 200** responses while a request is merely delayed, alongside
`X-RateLimit-Remaining` and `X-RateLimit-Reset`. A client that only inspects
headers on a 429 misses every early warning.

## API versions

Pinned to `7.1`, which is stable and fully documented. The docs default to
`7.2`, but that is tied to an unreleased server version. Approvals and checks
are the one exception, available only as `7.1-preview.1`, and that version skew
is declared at the call site rather than hidden in a constant.
