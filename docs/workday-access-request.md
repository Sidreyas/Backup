# Requesting Workday access

Send this to whoever holds **Security Administrator** rights — not the business
contact, who will forward it anyway and lose a week.

The email is nothing but the ask. No explanation of how to do it, no
justification, no reassurance — their administrator knows Workday, and anything
else is noise they have to read past. What it does spell out is the **domain
list** and the **report names**, because those are the specification rather than
instructions.

The answers to "why do you need that" are kept below the email, for when they
ask. The product isn't named anywhere.

---

## The email

> **Subject:** Workday integration access — read-only
>
> Hi [name],
>
> To connect to [tenant] we need read-only access. We read configuration. The
> only thing that would be added to your tenant is the reports below, and only
> if you'd rather we built them than did it yourselves.
>
> What we need:
>
> **An integration system user**, named by your convention — no UI access, no
> session timeout, exempt from password expiry.
>
> **An unconstrained integration system security group** containing that user,
> with **Get and View** access to:
>
> | Domain |
> |---|
> | Business Process Administration |
> | Integration Build |
> | Integration Event |
> | Organization Information |
> | Job Information |
> | Worker Data: Public Worker Reports |
> | Custom Report Creation |
> | Absence (Time Off / Leave of Absence) |
>
> **An API client registered for integrations**, with non-expiring refresh
> tokens and the Integration functional area in scope.
>
> **Nine custom reports, enabled as web services** and shared with that group.
> We're happy to build these ourselves — for that we'd need report-creation
> rights on the login you've already given us, and someone to share them with
> the group afterwards.
>
> | Report name | Data source |
> |---|---|
> | `CFG_BP_Definitions` | Business Process Definitions |
> | `CFG_BP_Steps` | Business Process Steps |
> | `CFG_Condition_Rules` | Condition Rules |
> | `CFG_Custom_Fields` | Custom Fields / Calculated Fields |
> | `CFG_Security_Groups` | Security Groups |
> | `CFG_Custom_Report_Inventory` | Custom Reports |
> | `CFG_BP_Runtime_Events` | Business Process Transaction Log |
> | `CFG_Time_Off_Plans` | Time Off Plans |
> | `CFG_Time_Off_Accruals` | Accruals |
>
> **The login you've already given us to stay active.** Nothing to change.
>
> **Sent back to us**, through [your vault] rather than email: Client ID,
> Client Secret, Refresh Token, Token Endpoint as displayed, and the
> integration user's username.
>
> Happy to join a call with your Workday administrator if that's easier.
>
> Thanks,
> [name]

---

## If they ask why

**Why unconstrained?** A constrained group returns a partial view of the tenant,
and we can't tell a partial view from a complete one. Wrong answers that look
right are worse than no access.

**Why custom reports and not the API?** Workday has no API for business process
definitions, condition rules, or calculated fields — we checked against the
v46.2 (2026R1) web services directory. The reporting layer reaches all of it.

**Why the existing login as well as the integration user?** Some configuration
exists only on Workday screens — the lookup bands behind a leave calculation,
field validation, conditional visibility — and no API returns it at any
permission level. Someone signs in once through a local tool; we receive the
session, never the password, and it expires.

**What about personal data?** We read configuration, not people. We don't
request worker records, leave balances, or absence dates. If a
worker-identifying column appears in a report, the extraction stops rather than
quietly filtering it. Where run history is read, we record that the same person
acted twice — never who they were.

**Could it change anything?** No. Write, submit, approve and modify are absent
from the code, not merely unused — the browser layer refuses to run a step
labelled save, submit or approve. If we build the reports, that is a person in a
browser, not the tool, and only with your say-so.

**What are the report columns?** We'll send the exact list. Names are matched
leniently, so close is fine. If only one report is realistic to start with,
`CFG_BP_Steps` — it carries the approval chain.

---

## Keep these back for the follow-up

These are the three things that actually go wrong, so you can diagnose in one
message instead of a week of round trips.

**403s that look like bad credentials.** Workday stages security changes and
they take effect only on activation — the `Activate Pending Security Policy
Changes` task. This is the most common cause of everything looking correct and
nothing working.

**A report that works in Workday but is invisible to us.** It wasn't web-service
enabled, or it was built as Simple rather than Advanced. Only Advanced can be
web-enabled, and the report type can't be changed after creation, so it needs
rebuilding rather than editing.

**A token endpoint that reaches a real host and rejects us.** It was
reconstructed from the tenant name rather than copied from `View API Clients`.
Workday hosts differ by pod, so a plausible URL usually resolves to something
real that isn't theirs.

One more, if the API client was registered with the plain `Register API Client`
task instead of `Register API Client for Integrations`: refresh tokens will
expire. Different task, similar name.

---

## Credential rotation

If any credential arrived by email or chat, ask for it to be rotated once the
work is done, in the same thread. Treat it as compromised from the moment it was
sent — that isn't a criticism of the sender, it's just what the channel means.

The sandbox login we already hold came through plaintext email. Preview tenants
often carry a copy of real configuration even when the people in them are
fictional, so it's worth rotating once exploration wraps up.
