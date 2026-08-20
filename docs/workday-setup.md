# Connecting Workday

What Meridian can extract, what your Workday administrator has to do, and the
one significant limitation you should know before you start.

## The limitation, first

**Workday has no API that returns business process definitions.** This is not a
gap in Meridian — it is a gap in Workday's published interface, and it is worth
stating plainly because the approval logic in your business processes is
usually the thing a proposed change actually touches.

Verified against Workday's v46.2 (2026R1) service directory: all eight SOAP
operations containing `Business_Process` act on *running instances* —
`Approve_`, `Deny_`, `Cancel_`, `Rescind_`, `Send_Back_`, `Reassign_`,
`Put_Business_Process_Delegation` — plus `Get_Business_Process_Delegations`,
which returns delegation assignments. There is no `Get_Business_Process_
Definition`. There is likewise no read API for condition rules, custom field
definitions, calculated fields, or domain security policies. The one REST
business-process endpoint applies only to Workday Extend processes and submits
rather than reads.

Workday's **reporting layer** reaches all of it. So Meridian's Workday
connector uses three surfaces:

| Surface | What it gives you | Setup needed |
|---|---|---|
| **SOAP** | Organisations, job profiles, locations, integration systems | Integration user + permissions |
| **RaaS** (custom reports) | Business process definitions and steps, condition rules, custom fields, security policies | The above, plus reports built in your tenant |
| **REST** | Token validation only | — |

You can connect with SOAP alone and get a useful graph. Each report you add
deepens it.

A fourth surface, **browser discovery**, reads configuration that has no API at
any permission level — the lookup bands and conditional branches inside a
calculated field, field validation, picklist values. For what each surface
reaches and what none of them do, see
[workday-extraction.md](workday-extraction.md).

## What your Workday administrator does

Meridian shows this as an interactive checklist when you connect, with the task
names in monospace and the reason for each step. Summarised here:

1. **`Create Integration System User`** — set Session Timeout to `0`, tick
   "Do Not Allow UI Sessions", exempt from password expiry. An expired password
   on an integration account fails silently at 2am.

   The UI-session tick is a *recommended setting*, not a platform constraint —
   an ISU is an ordinary account created by a dedicated task, and leaving the
   box unticked permits UI sign-in. Tick it: an integration credential that can
   also drive screens is the standing risk this account type exists to avoid.
   Screen discovery uses a separate named account, by design.
2. **`Create Security Group`** — type **Integration System Security Group
   (Unconstrained)**. Constrained groups limit visibility by organisation and
   produce a partial graph that looks complete.
3. **`Maintain Permissions for Security Group`** — grant **Get/View only**,
   never Put or Modify. Meridian never writes to Workday. Suggested domains:
   Business Process Administration, Integration Build, Integration Event,
   Organization Information, Job Information, Worker Data: Public Worker
   Reports, Custom Report Creation.
4. **`Activate Pending Security Policy Changes`** — ⚠️ **the most commonly
   missed step.** Permissions do nothing until this runs, and its absence
   produces 403 errors that look exactly like wrong credentials.
5. **`Register API Client for Integrations`** — note *for Integrations*; the
   plain `Register API Client` task is a different thing and does not support
   non-expiring refresh tokens. Tick **Non-Expiring Refresh Tokens**. Copy the
   Client ID and Secret now — the secret is shown once.
6. **`Manage Refresh Tokens for Integrations`** — generate a token against the
   ISU from step 1. Also shown once.
7. **`View API Clients`** — copy the **Token Endpoint** exactly. Do not
   assemble it from the tenant name: Workday hosts differ by pod
   (`wd2-impl-services1.workday.com`, `wd5-services1.myworkday.com`) and a
   constructed URL usually resolves to a real host that rejects the request.
8. **`Create Custom Report`** ×9 — optional, high value. See below.

## Authentication

Three methods, because your security team may only permit one:

- **OAuth 2.0 refresh token** — the default, and verified as universally
  available.
- **OAuth 2.0 JWT bearer** — for teams that will not store a shared secret.
  Requires `pip install 'pyjwt[crypto]'` and an x509 key registered via
  `Create x509 Public Key`.
- **Integration System User credentials** — WS-Security username/password. The
  simplest, and the only option in some older tenants. What gates this is the
  tenant's authentication policy (whether "User Name Password" is an allowed
  type for the account's security group) plus Integration Permissions — not the
  account being an ISU. If SOAP rejects a correctly-permissioned account, check
  the authentication policy before the credentials.

**`client_credentials` is deliberately not offered.** Several third-party
guides claim Workday supports it for integrations, but no Workday-authored
source shows it in the `Register API Client for Integrations` grant dropdown
and no release note announces it. Depending on it would be an availability
risk; the refresh-token grant works everywhere.

## The discovery report pack

Nine reports. Every one is optional. The build procedure is the same for all
nine, and Meridian shows it as four numbered steps above the report list:

1. **`Create Custom Report`** — search this task; name it as listed below.
2. **Report Type: Advanced** — not Simple. Only Advanced reports can be
   web-enabled, and the type cannot be changed after creation.
3. **Tick "Enable As Web Service"** (Advanced tab) — ⚠ the most missed
   setting. Without it the report works perfectly inside Workday and is
   invisible to Meridian.
4. **`Share`** with the integration security group from step 2 — not with
   individual users. An unshared report returns a permission error, not empty
   data, which reads as bad credentials.

| Report | Data source | Unlocks |
|---|---|---|
| `CFG_BP_Definitions` | Business Process Definitions | Which processes exist and what they govern |
| `CFG_BP_Steps` | Business Process Steps | **The approval chain** — order, type, approver, conditions |
| `CFG_Condition_Rules` | Condition Rules | The logic behind conditional routing |
| `CFG_Custom_Fields` | Custom Fields / Calculated Fields | Bespoke fields and what they derive from |
| `CFG_Security_Groups` | Security Groups | Segregation of duties |
| `CFG_Custom_Report_Inventory` | Custom Reports | Reporting a field change silently breaks |
| `CFG_BP_Runtime` | BP Transaction Log | What actually ran, versus what is configured |
| `CFG_Time_Off_Plans` | Time Off Plans | Leave plan configuration — carryover, caps, balance period |
| `CFG_Time_Off_Accruals` | Accruals | How entitlement is earned, and which calculation decides it |

Meridian lists the exact columns each report needs, in the connect wizard,
expandable per report. Column names are matched leniently — if you name a
column `Order` instead of `Step_Order`, it still resolves.

`CFG_BP_Steps` is the highest-value one. From it Meridian builds a step node
per row, `HAS_STEP` from its definition, `NEXT_STEP` edges derived by sorting
on step order, `APPROVED_BY` to the security group, and `GOVERNED_BY` to the
condition rule. That is what turns "we have a Change Job process" into a graph
that can answer "what breaks if we add a Regional HR approval above 15 days".

## Credentials and storage

Credentials are encrypted at rest (`api/core/secrets.py`) with a key held
outside the database, so a database dump is not a credential leak. Set
`MERIDIAN_SECRET_KEY` before connecting:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Without it the app runs but **refuses to store credentials** rather than
writing them in plaintext. The connect form says so rather than failing
obscurely.

Secrets are never returned by the API — read-back shows `••••••••` as a
presence marker, so you can tell "a secret is stored" from "no secret set"
without the value crossing the wire.

## What "test connection" tells you

Granular by design, because "connection failed" is useless when six things had
to be configured. The test reports which surfaces are reachable:

- whether OAuth authentication succeeded,
- whether SOAP organisational data can be read,
- whether integration systems can be read (a separate domain),
- **how many of the nine discovery reports exist**, and which are missing.

A tenant with valid credentials and no reports connects successfully and says
that business process logic is not yet reachable — rather than silently
producing a thin graph.

## Rate limits

Workday publishes no official numbers, and third-party claims conflict
(10 req/s, 5 req/s, "no stated limit"). The connector is conservative: paged
requests at 999 records, a 20,000-record cap per run that is **reported** when
hit rather than silently applied, and pinned API version `v46.2`.

## Known gaps

- **No change webhook.** Workday publishes no outbound notification for
  configuration changes, so drift is detected by re-extracting and comparing,
  not in real time.
- **Object Transporter.** Workday's OX tool does migrate BP configuration
  between tenants, which suggests a non-public SOAP surface exists. Worth
  investigating if BP extraction becomes critical enough to warrant it; not
  something to build on today.
