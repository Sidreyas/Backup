# What Meridian extracts from Workday

Four extraction surfaces, what each one reaches, and — the part that matters
most — what none of them reach.

This is the *capability* reference. For the administrator-facing setup
procedure (tasks to run, permissions to grant, reports to build) see
[workday-setup.md](workday-setup.md).

Everything here was verified against Workday's Web Services Directory at
**v46.2 (2026R1)** and the code in `api/connectors/workday/`. Where a claim
rests on partner documentation rather than a Workday-authored source, it says
so.

---

## The shape of the problem

Workday splits what you want to know across surfaces that do not overlap:

| Surface | Answers | Needs |
|---|---|---|
| **SOAP** | What exists — orgs, jobs, locations, integrations | ISU + Integration Permissions |
| **RaaS** | How it is configured — processes, rules, security, absence maths | The above, plus reports built in the tenant |
| **REST / GraphQL** | What the *platform* offers | OAuth client bound to the ISU |
| **Browser** | What a calculation actually decides | A signed-in human |

The one-sentence version: **RaaS tells you a calculation exists and what it
reads. Only the browser tells you what it decides.**

That is not a workaround for missing permissions. There is no API for it at
any permission level, which is the single most important fact on this page.

---

## 1. SOAP

Operational data. The org spine that everything else scopes to.

**Seven operations, as called by `connector.py` today:**

| Operation | Yields |
|---|---|
| `Get_Organizations` | Supervisory orgs, companies, cost centres |
| `Get_Job_Profiles` | Job profiles |
| `Get_Job_Families` | Job families — also the access probe |
| `Get_Locations` | Locations |
| `Get_Integration_Systems` | Integration system inventory |
| `Get_Integration_Events` | Runtime: which integrations fired, status, timings |
| `Get_Time_Off_Plans` | Absence plan **headers** — not the accrual maths |

Organisations come first deliberately: nearly every business process
definition is scoped to one, so without them the process nodes have nothing
to attach to.

**Not a permissions limit.** The v46.2 catalog holds 60+ services — payroll,
compensation, benefits, recruiting. Meridian calls seven. Reaching the rest is
connector work, not a tenant-side grant.

**Permissions:** SOAP requires **Integration Permissions** (Get/View) on each
domain. This differs from REST — see §3.

---

## 2. RaaS — the report pack

Where the configuration actually lives. **None of this exists until someone
builds the reports in the tenant**, web-service-enables them, and shares them
with the integration security group.

Nine reports, defined in `api/connectors/workday/reports.py`:

### Process and logic

| Report | Carries |
|---|---|
| `bp_definitions` | Process type, definition, reference ID, scope org, effective date, status |
| `bp_steps` | Order, step type, **security group**, **condition rule**, optional flag, subprocess |
| `condition_rules` | Rule name, ID, business object, expression *(where exposed)* |
| `custom_fields` | Field, business object, type, **source fields** |

`bp_steps` is the highest-value report in the pack. From it Meridian builds a
step node per row, `HAS_STEP` from the definition, `NEXT_STEP` by sorting on
order, `APPROVED_BY` to the security group, and `CONDITIONAL_NEXT_STEP`
carrying the gating condition. That is the difference between "we have a
Change Job process" and a graph that can answer *what breaks if we add a
Regional HR approval above 15 days*.

### Governance

| Report | Carries |
|---|---|
| `security_groups` | Group, type, domain, access level, members |
| `custom_reports` | Report inventory, data source, owner, **whether web-service enabled** |

The web-service flag matters more than it looks: a RaaS-enabled report *is*
integration surface. Changing a field it reads breaks something downstream
silently.

### Runtime

| Report | Carries |
|---|---|
| `bp_runtime` | Instance ID, step status, overall status, timings, due date, actor |

The actor is **pseudonymised on ingest**. Meridian records that the same
person acted twice, never who they were.

This is the only source for what *actually happened*, as opposed to what is
configured — the other half of any drift comparison.

### Absence

| Report | Carries |
|---|---|
| `time_off_plans` | Unit of time, plan type, balance period, carryover limit and expiry, max balance, country |
| `time_off_accruals` | Accrual, amount, frequency, **calculated field**, **accrual condition**, eligibility rule, worker type |

**Unit of time is required, not cosmetic.** A plan's numbers are meaningless
without knowing whether they are days or hours.

`Accrual_Amount` is blank whenever a calculated field decides it — which is
precisely the case for every statutory plan worth asking about. The report
names the calculation. It does not contain it. See §4.

---

## 3. REST and GraphQL — capability, not configuration

The surface most likely to be oversold, so stated flatly:

**REST OpenAPI ingestion** and **GraphQL introspection** describe *what the
platform exposes* — available operations, schemas, types, fields. They
describe the API. They do not describe your tenant's configuration.

The connector files both under the `read.api_surface` scope for exactly that
reason. Useful for knowing which objects exist and what a future integration
could touch. It will not answer "why does this leave plan behave this way."

**Both require OAuth 2.0.** Basic auth with raw ISU credentials is not
accepted; calls carry a Bearer token. Note that OAuth and the ISU **compose**
rather than substitute — the API client is registered against the ISU, so the
ISU remains the identity and permission carrier. "OAuth instead of an ISU" is
a common and misleading simplification.

**Permission asymmetry worth knowing:** REST needs only **Report/Task
permissions**, while SOAP needs **Integration Permissions**. Granting one and
assuming the other follows produces partial access that reads like a bug.

---

## 4. Browser discovery

Everything in this section has **no API at any permission level**, confirmed
against v46.2. This is not a fallback for a missing ISU. It is the only route.

### What it reaches

- **Calculated field internals** — the reason this surface exists:
  - **Lookup Calculation** bands: `0–2 years → 7 days`, `2+ years → 14 days`
  - **Conditional Calculation** ordered branches, in evaluation order
- **Lookup tables** as their own nodes, so a table shared across several plans
  is visibly shared rather than duplicated
- **Accrual detail** beyond the report's header row — frequency, condition,
  eligibility as actually configured
- **Effective-dated continuation rows** — how a plan changed over time
- **Field validation, conditional visibility, picklist values**

`Calculation.is_resolved` tracks whether a calculation's contents were
actually recovered. A named-but-empty calculation node is a **recorded gap**,
never silent absence — `summary_gaps()` names each one.

### What it refuses

Worker balances, absence dates, employee identifiers.

`assert_no_worker_data` **refuses the extraction** rather than filtering
columns. A filter that silently drops a column looks identical to a column
that was never there, and the difference matters when the data is
medical-adjacent.

### What it cannot do

Navigation and reading only. `NAVIGATION_ONLY` vocabulary and
`FORBIDDEN_TARGETS` mean discovery cannot submit, approve, or save.

### Why it cannot run unattended

Workday has no OAuth for its UI, so the session comes from a real human
signing in — including MFA — via the desktop capture helper. Meridian never
receives the password, only the resulting session, and that session expires in
roughly 30–60 minutes.

**The lapse is the security property, not a limitation to engineer around.** A
capture that worked forever would mean storing a password and defeating MFA.

Workday does not error when a session expires — it serves the login page — so
the walk checks `_looks_signed_out()` after every navigation. A walk that did
not would happily extract the login form's fields as configuration.

Long runs therefore end **partially** by design: `WalkResult.partial` carries
what was reached, and scheduled extraction belongs on the API and report
surfaces.

---

## Identity: which account for which surface

Two corrections to widely-repeated claims, both verified:

**An ISU is not barred from the UI.** "Do Not Allow UI Sessions" is a
*checkbox* on the Create ISU task — strongly recommended, but an optional
setting on an otherwise ordinary account, not a platform-enforced property.

**A named user is not barred from SOAP.** Access is gated by the tenant's
authentication policy (whether username/password is an allowed type) and by
Integration Permissions on the relevant domains. Neither is tied to being an
ISU. Named users usually fail — for permission reasons that are configurable,
not an authentication ban.

So one account *can* technically serve every surface. **Use two anyway:**

| Account | Surface | Rationale |
|---|---|---|
| **ISU** + OAuth client | SOAP, RaaS, REST, GraphQL | No UI access, read-only domains, survives staff changes |
| **Named service account** | Browser discovery | A session must come from a real login |

The argument is design, not platform constraint: one account doing both means
the API credential also carries UI access, and if that account holds write
domains you have built the standing risk the ISU pattern exists to prevent.
Separate identities give separate audit trails.

If a client's security team insists on one account, it works — confirm write
domains are excluded.

⚠️ **Implication for connector logic:** never infer screen capability from the
auth method. A tenant that left the checkbox unticked has an ISU that *can*
hold a UI session. `browser_ready()` must key on whether a session exists.

---

## What the graph looks like

Emitted by the Workday connector:

**Node kinds** — `config_object`, `data_entity`, `business_process`, `policy`,
`integration`, `report`, `screen`

**Edge types** — `HAS_STEP`, `CONDITIONAL_NEXT_STEP`, `APPROVED_BY`,
`GOVERNED_BY`, `DEPENDS_ON`, `REFERENCES_OBJECT`, `READS`, `READS_OBJECT`,
`HAS_FIELD`, `CONFIGURES`

This is the shape `/api/ask` queries. Retrieval is deterministic; the model
explains only what was found, and fabricated citations are dropped and
reported.

---

## Known gaps

**No configuration-change webhook.** Workday publishes no outbound
notification when configuration changes, so drift is found by re-extracting
and comparing — not in real time.

**Integrations are shallow.** Meridian gets the integration *system* inventory
and event history. Not EIB field mappings, not Studio internals.

**Coverage is seven SOAP calls and nine reports.** Payroll configuration,
compensation plans, and custom objects are not reached today. The pipeline is
built to extend; "all tenant configuration" is not what it currently reads.

**Object Transporter — unresolved, and the highest-value lead.** Workday's OX
tool migrates configuration between tenants and "uses web service operations
… so only objects supported by web services can be migrated." Partner sources
state it handles business processes; Workday's own concept page does not name
them. If BP definitions are genuinely reachable that way, it would replace two
of the nine reports with an API call.

Two caveats keep this from being actionable: it is a tenant-to-tenant
migration tool rather than a read API, so it may not return usable structured
routing; and confirming it requires an authenticated Workday Community or
tenant check, which the customer can perform and we cannot. Worth asking. Not
worth building on yet.

**Rate limits are unpublished.** Third-party claims conflict (10 req/s, 5
req/s, "no stated limit"). The connector is conservative: 999 records per
page, a 20,000-record cap per run that is **reported when hit** rather than
silently applied, and a pinned API version.
