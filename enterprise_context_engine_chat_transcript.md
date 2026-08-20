# Enterprise Context Engine and Knowledge Graph — Conversation Transcript

## User

I want to extract the configurations, workflows and fields info from the workday

## Assistant

You cannot extract the complete Workday tenant configuration through one universal API. The right approach is a **hybrid Workday discovery connector** combining tenant reports, RaaS, REST/SOAP metadata, event APIs, and controlled UI discovery.

## What we need to extract

### 1. Business objects and fields

For each Workday business object, capture:

- Business object name and identifier
- Standard fields
- Custom fields
- Field type and cardinality
- Required/optional status
- Allowed values and reference objects
- Calculated fields and dependencies
- Validation rules
- Security domains
- API resource and operation mappings
- Fields visible on individual tasks and screens

Examples:

```text
Worker
├── Employee ID
├── Legal Name
├── Supervisory Organization
├── Position
├── Cost Center
├── Worker Type
├── Custom_Field_ABC
└── Calculated_Field_Service_Length
```

Workday exposes parts of this model through REST OpenAPI definitions, SOAP WSDL/XSD files, Graph API schemas, custom-object WSDLs and tenant reports. Workday’s API tooling itself uses REST OpenAPI specifications, SOAP WSDLs and Graph API schemas as metadata sources.

### 2. Business-process workflows

For every configured process, extract:

- Process type
- Default, organization-based and rule-based definitions
- Initiation conditions
- Entry conditions
- Step sequence
- Approval steps
- Review steps
- To-do steps
- Integration steps
- Notifications
- Subprocesses
- Routing rules
- Security groups
- Escalation rules
- Validation conditions
- Completion actions
- Rescind, correction and cancellation behaviour
- Effective dates and version history

Example normalized workflow:

```yaml
process: Change Job
definition: Change Job - Malaysia Employees
scope:
  organization: Malaysia
  worker_type: Employee

steps:
  - order: 1
    type: initiation
    actor: HR Partner

  - order: 2
    type: approval
    actor: Current Manager
    condition: proposed_grade_change == false

  - order: 3
    type: approval
    actor: Compensation Partner
    condition: compensation_change > 10%

  - order: 4
    type: integration
    integration: Payroll Outbound

  - order: 5
    type: notification
    recipient: Employee
```

The Business Process REST APIs expose runtime events, including completed, in-progress and remaining steps, parent processes, subprocesses, statuses, comments and attachments. However, these APIs primarily describe **process instances**, not necessarily the entire design-time tenant definition.

### 3. Tenant configuration

Capture tenant-level configuration such as:

- Organizations and hierarchies
- Supervisory organizations
- Companies
- Cost centres
- Locations
- Job profiles
- Positions
- Compensation structures
- Worktags
- Custom objects
- Custom fields
- Calculated fields
- Condition rules
- Validation rules
- Security groups
- Security domains
- Business-process security policies
- Custom reports
- Integrations
- Notifications
- Document templates
- Tenant feature settings

Workday has tenant-configuration reports that can be used to retrieve portions of the tenant setup.

---

# Recommended extraction architecture

```text
                      Workday Tenant
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
   Tenant Reports      Workday APIs      UI Discovery
   and RaaS             REST / SOAP       Browser Agent
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
                  Workday Discovery Gateway
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
     Raw Evidence       Normalization      Change Detection
     Store              Engine             Engine
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
                    Enterprise Knowledge Graph
```

## Connector 1: Workday tenant reports and RaaS

This should be the primary mechanism for extracting configured tenant information.

Create Workday custom reports for:

- Business-process definitions
- Business-process steps
- Condition rules
- Security groups attached to steps
- Custom fields
- Calculated fields
- Custom objects
- Integration systems
- Custom reports
- Organizations and hierarchies
- Domains and security policies
- Worktags and related validation
- Reference IDs

Expose these reports through **Reports-as-a-Service**, which lets an external system invoke a custom report as a REST-style endpoint.

Example:

```http
GET https://{tenant-host}/ccx/service/customreport2/{tenant}/{owner}/{report}
Accept: application/json
```

The returned data should be stored together with:

```json
{
  "source": "workday_raas",
  "tenant": "customer-prod",
  "report": "SQ_BP_Definition_Inventory",
  "extracted_at": "2026-08-07T09:00:00Z",
  "workday_reference_id": "BP_Change_Job_MY",
  "evidence_uri": "object-storage://evidence/..."
}
```

### Advantages

- Tenant-specific information
- Governed through Workday security
- Easier to version and schedule
- Supports structured XML, JSON or CSV extraction
- Customer can review exactly what is exposed

### Limitation

The customer normally has to create or install the initial report catalogue. Your product should therefore provide a **Workday Discovery Report Pack**.

---

## Connector 2: SOAP metadata discovery

Workday SOAP services are valuable for:

- Object structures
- Supported fields
- Request and response schemas
- Reference types
- Enumerations
- Custom-object extensions
- Version comparison

Workday provides WSDL and XSD definitions for its SOAP web services, and tenant-specific custom-object WSDLs can be retrieved from the tenant.

Build a WSDL parser that creates nodes such as:

```text
SOAP Service
  → Operation
      → Request Object
          → Field
              → Type
              → Required
              → Reference Type
      → Response Object
```

Example graph relationships:

```text
Change_Job
  SUPPORTS_OPERATION → Change_Job_Request
  ACCEPTS_FIELD → Worker_Reference
  ACCEPTS_FIELD → Effective_Date
  INITIATES_PROCESS → Change_Job_BP
```

Do not confuse this with actual tenant configuration. WSDL primarily tells you what Workday **supports**, while reports and tenant discovery tell you what the customer has **configured**.

---

## Connector 3: REST OpenAPI discovery

Use Workday’s REST API Explorer and OpenAPI specifications to ingest:

- Services
- Versions
- Endpoints
- Resources
- Request schemas
- Response schemas
- Security scopes/domains
- Field definitions
- Enumerations

Store the API definition separately from tenant implementation:

```text
PlatformCapability: Change Job REST API
TenantImplementation: Malaysia Change Job Workflow
```

Then connect them:

```text
TenantImplementation
  IMPLEMENTS
PlatformCapability
```

This distinction is central to your platform.

---

## Connector 4: Workday Graph API

Where available, ingest the Workday Graph API schema for:

- Business objects
- Event objects
- Attachments
- Queries
- Mutations
- Relationships
- Security requirements

Graph API support will not replace tenant reports, but it can substantially improve object relationship discovery.

---

## Connector 5: Runtime business-process events

Use the Business Process Events REST APIs to collect actual workflow execution evidence:

- Process initiated
- Current status
- Completed steps
- Pending steps
- Remaining steps
- Actual approvers
- Due dates
- Subprocesses
- Comments
- Attachments
- Cancellation or rescind events

This allows your platform to compare:

```text
Configured workflow
        versus
Observed workflow execution
```

Example drift:

```text
Configured:
Manager → HR Partner → Compensation Partner

Observed:
Manager → HR Partner → Manual Payroll Correction

Finding:
Undocumented manual step regularly occurs after process completion.
```

Sensitive worker data should be minimized or tokenized during this extraction.

---

## Connector 6: Controlled browser discovery

Some configuration may only be fully understandable through Workday tenant screens and reports. A browser agent can navigate authorized Workday administration tasks and capture:

- Task names
- Form sections
- Visible fields
- Required indicators
- Dropdown values
- Related actions
- Validation messages
- Conditional field visibility
- Process diagrams
- Security-policy displays
- Configuration screens

The browser agent should not simply scrape HTML. It should generate structured evidence:

```json
{
  "task": "Edit Business Process Definition",
  "business_process": "Hire",
  "section": "Steps",
  "fields": [
    {
      "label": "Order",
      "type": "number",
      "required": true
    },
    {
      "label": "Step Type",
      "type": "lookup",
      "values_observed": [
        "Approval",
        "Action",
        "Review",
        "To Do"
      ]
    }
  ],
  "screenshot_evidence": "evidence://workday/...",
  "observed_at": "2026-08-07T09:20:00Z"
}
```

---

## User

Which agent ans opensource tools we can use ? Like vercel agent browser, firecrawl, scrapling etc .,

## Assistant

For extracting **Workday configurations, business processes, workflows, fields, validation rules, security assignments, and tenant-specific customisations**, do not rely on one crawler. Use a layered toolkit combining deterministic browser automation, AI-assisted navigation, structured extraction, and evidence capture.

## Recommended stack

### 1. Playwright — primary automation engine

Use Playwright as the foundation.

It is the best choice for:

- Workday login and tenant navigation
- Handling iframes, pop-ups, dynamic components and downloads
- Capturing network traffic and API responses
- Saving screenshots, traces and HTML snapshots
- Deterministic repeatable extraction
- Reusing authenticated browser profiles

**Recommendation:** Make Playwright the execution layer even when an AI agent is deciding what to click.

---

### 2. Vercel Agent Browser — exploration and agent-driven discovery

Vercel’s `agent-browser` is useful for letting an LLM interact with Workday through compact browser commands.

Good use cases:

- Exploring unfamiliar Workday tenant screens
- Discovering navigation paths
- Running one-time tenant assessments
- Identifying relevant reports and configuration pages
- Producing an initial workflow map
- Converting exploration into repeatable scripts

**Positioning:** Excellent discovery agent, but I would not use it alone for production extraction. Once it discovers the path, convert the flow into Playwright code.

---

### 3. Stagehand — hybrid deterministic and AI automation

Stagehand is particularly suitable when Workday page structure changes between tenants or releases.

It provides three useful concepts:

- `observe`: find possible actions or elements
- `act`: perform an AI-selected browser action
- `extract`: return structured information

**Positioning:** Probably the best AI-assisted layer above Playwright for your production connector.

---

### 4. Skyvern — long-running autonomous workflows

Skyvern is useful when the agent must complete complex multi-step flows such as:

- Search for a business process
- Open the definition
- Visit every step
- Capture conditions, approvals and routing
- Download associated reports
- Repeat for hundreds of processes

**Positioning:** Better than agent-browser for orchestration of longer, semi-autonomous workflows, but heavier operationally.

---

### 5. Browser Use — agent reasoning and browser control

Browser Use is useful for exploratory agents that receive goals such as:

> Find every custom field associated with the Worker business object and extract its configuration.

It works well for:

- Research-style navigation
- Unknown page paths
- Dynamic decision-making
- Agent experimentation
- Human-supervised tenant discovery

However, autonomous browser agents can choose different paths between runs. Keep Browser Use for discovery and fallback rather than treating it as your authoritative production extractor.

---

## Where Firecrawl fits

For Workday, Firecrawl is useful for:

- Public Workday documentation
- Workday Community pages where access permits
- Implementation guides
- Configuration workbooks published as HTML
- Customer-provided internal documentation portals
- Knowledge ingestion into your RAG or graph platform

It is **not the correct primary tool for extracting a logged-in Workday tenant**, because Workday extraction requires stateful navigation, search, pop-ups, interactive reports, authentication and sometimes browser downloads.

Use Firecrawl for **documentation knowledge**, not for the main tenant-discovery agent.

---

## Where Scrapling fits

Scrapling is useful for:

- Parsing downloaded HTML
- Extracting repeated tables
- Processing static report outputs
- Normalising HTML fragments
- Crawling internal documentation
- Handling minor selector changes

However, it is less suitable than Playwright or Stagehand for navigating the complete Workday application.

Use Scrapling **after the browser has reached or downloaded the content**.

---

## Other tools worth considering

| Tool | Best role in the Workday connector |
|---|---|
| **Playwright MCP** | Give an LLM controlled browser access through structured accessibility data |
| **Steel Browser** | Self-hosted browser session infrastructure for agents |
| **Crawl4AI** | Convert documentation and accessible pages into LLM-friendly structured content |
| **Crawlee** | Large-scale crawling, queues, retries and browser-worker management |
| **Scrapy** | High-volume parsing of static exports and documentation |
| **Apache Tika** | Parse Workday-generated PDF, Excel and document exports |
| **Docling** | Extract structured content from PDFs, tables and documents |
| **mitmproxy** | Inspect browser requests and identify Workday backend calls |
| **HAR capture** | Record the requests Workday sends while users navigate reports |
| **OpenTelemetry** | Trace every extraction action and its evidence |
| **Temporal** | Reliable orchestration, retries, checkpoints and human approval |
| **Camunda** | Enterprise workflow orchestration and approval workflows |

# My recommended architecture

```text
                    Workday Tenant
                         │
              ┌──────────┴──────────┐
              │                     │
      Official Workday APIs    Browser Discovery
      RaaS / SOAP / REST       Playwright
      Integration Services     Stagehand
              │                agent-browser
              │                Skyvern fallback
              └──────────┬──────────┘
                         │
               Raw Evidence Collector
            HTML / JSON / HAR / Screenshots
             Reports / PDFs / Excel / XML
                         │
              Extraction and Parsing
        Scrapling / Tika / Docling / custom parsers
                         │
                Normalisation Layer
       Business objects / fields / processes / rules
                         │
                 Knowledge Graph
       Object → Field → Process → Step → Condition
       → Role → Security Group → Integration → Report
                         │
               Provenance and Versioning
        tenant / timestamp / source / screenshot /
           page / API / confidence / extractor
```

## Recommended combination

For your first implementation:

```text
Playwright
+ Stagehand
+ agent-browser
+ mitmproxy or HAR capture
+ Scrapling
+ Docling/Tika
+ Temporal
+ PostgreSQL
+ Neo4j or another graph database
```

# Extraction-agent design

I would create specialised agents rather than one general Workday agent.

## 1. Tenant Navigator Agent

Discovers:

- Workday navigation structure
- Search behaviour
- Available administrative pages
- Accessible reports
- User permission boundaries

## 2. Business Object Agent

Extracts:

- Business-object name
- Parent and child objects
- Standard fields
- Custom fields
- Calculated fields
- References
- Data types
- Required status
- Allowed values

## 3. Business Process Agent

Extracts:

- Process definition
- Initiation conditions
- Steps
- Order
- Approval chain
- Review steps
- To-do steps
- Integration steps
- Routing conditions
- Security groups
- Escalations
- Notifications

## 4. Security Agent

Extracts:

- Domain security policies
- Business-process security policies
- Security groups
- Role assignments
- View and modify rights
- Constrained and unconstrained access

## 5. Report and Integration Agent

Extracts:

- Custom reports
- Report fields
- Filters and prompts
- Data sources
- RaaS endpoints
- EIB definitions
- Studio integrations
- Integration system users
- Scheduled integrations

## 6. Evidence Validation Agent

Checks:

- Screenshot matches extracted configuration
- Number of fields matches visible table counts
- Process steps are in the correct order
- Duplicate objects are merged correctly
- Extraction confidence is sufficient
- Sensitive values are redacted

# Important engineering principle

Do not allow the LLM to directly generate the authoritative configuration record.

Use this process:

```text
LLM navigates
→ browser captures evidence
→ deterministic parser extracts values
→ schema validator checks output
→ LLM resolves only ambiguous mappings
→ evidence and provenance are stored
```

## User

My objective is to extract it for my knowledge graph which will be used with ai agents

## Assistant

Then the objective should not be “scrape Workday.” It should be:

> **Continuously reconstruct a tenant-specific Workday implementation model, with evidence and provenance, that AI agents can reason over.**

The browser agents are only one set of collectors.

## Recommended architecture

```text
Workday Tenant
    │
    ├── Official APIs: REST / SOAP / Graph
    ├── RaaS and custom reports
    ├── Exported configuration workbooks
    ├── Business-process runtime events
    ├── Browser-based configuration discovery
    └── Screenshots, documents and integration definitions
            │
            ▼
    Evidence Acquisition Layer
            │
    ┌───────┴────────────────────────────┐
    │                                    │
Deterministic collectors          Discovery agents
Playwright                       Stagehand
API clients                      agent-browser
Report parsers                   Browser Use
HAR/network capture              Playwright MCP
    │                                    │
    └───────────────┬────────────────────┘
                    ▼
            Raw Evidence Store
      JSON / XML / HTML / CSV / PDF
      screenshots / traces / HAR files
                    │
                    ▼
       Extraction and Normalisation
                    │
          Canonical Workday Model
                    │
                    ▼
        Versioned Knowledge Graph
                    │
         Graph retrieval services
                    │
                    ▼
        Requirements and Change Agents
```

## The key design principle

Separate these three concepts:

```text
Workday platform capability
        ≠
Customer tenant configuration
        ≠
Observed runtime behaviour
```

For example:

```text
Platform capability:
Workday supports an Approval business-process step.

Tenant configuration:
The Malaysia Change Job process has an approval by Compensation Partner
when salary change exceeds 10%.

Runtime observation:
A specific Change Job request passed through Manager and Compensation Partner
and remained pending for four days.
```

Your graph needs all three layers.

# Suggested graph ontology

## Core nodes

### Tenant and organizational scope

```text
Tenant
Company
Business Entity
Region
Country
Organization
Supervisory Organization
Cost Center
Location
```

### Workday model

```text
Business Object
Field
Custom Field
Calculated Field
Custom Object
Reference Type
Validation Rule
Condition Rule
Worktag
```

### Processes

```text
Business Process Type
Business Process Definition
Process Version
Process Step
Approval Step
Review Step
Action Step
To-Do Step
Integration Step
Notification Step
Subprocess
```

### Security

```text
Security Domain
Security Group
Role
Business Process Security Policy
Domain Security Policy
Permission
```

### Integration and reporting

```text
API Service
API Endpoint
SOAP Operation
Custom Report
Report Data Source
Report Field
RaaS Endpoint
Integration System
EIB
Studio Integration
Scheduled Integration
```

### Evidence and provenance

```text
Evidence
Extraction Run
Source System
Screenshot
API Response
Report Export
Browser Observation
Document
Extractor Version
```

## Important relationships

```text
TENANT_CONFIGURES
BELONGS_TO_TENANT
HAS_FIELD
REFERENCES_OBJECT
DERIVED_FROM_FIELD
VALIDATED_BY
CONTROLLED_BY_RULE
IMPLEMENTS_PROCESS
HAS_VERSION
HAS_STEP
NEXT_STEP
ROUTES_TO
TRIGGERED_WHEN
APPROVED_BY
SECURED_BY
VISIBLE_TO
MODIFIABLE_BY
INVOKES_INTEGRATION
READS_OBJECT
WRITES_OBJECT
EXPOSED_BY_API
REPORTED_BY
OBSERVED_IN
SUPPORTED_BY_EVIDENCE
SUPERSEDES
CONFLICTS_WITH
```

# Best tool assignment

## Playwright: authoritative browser collector

Use Playwright for:

- Authenticated navigation
- Opening configuration tasks
- Running reports
- Downloading exports
- Capturing DOM and accessibility trees
- Recording HAR and browser traces
- Taking evidence screenshots
- Replaying known extraction flows

**This should be the production execution engine.**

## Vercel Agent Browser: exploration tool

Use `agent-browser` for:

- Initial Workday tenant exploration
- Rapidly discovering navigation paths
- Engineer-assisted investigations
- Finding which screen or report contains a configuration
- Creating candidate extraction recipes

**Do not make it the authoritative graph-writing component.**

## Stagehand: adaptive extraction

Use Stagehand where:

- Different customers have slightly different page structures
- Labels or layouts change between Workday releases
- A fixed selector is unreliable
- You need schema-constrained extraction from a page

Good pattern:

```text
Stagehand identifies the relevant element
        ↓
Playwright captures the exact DOM and page state
        ↓
Deterministic parser extracts the configuration
```

# Use extraction recipes, not unrestricted agents

Each type of Workday configuration should have a versioned extraction recipe.

Example:

```yaml
recipe_id: workday.business_process.definition.v1
entity_type: BusinessProcessDefinition

discovery:
  search_terms:
    - "View Business Process Definition"
    - "Business Process Definitions"

navigation:
  - search_for_task
  - select_business_process
  - open_definition
  - open_steps_tab

extract:
  process_name:
    source: page_heading

  process_type:
    source: metadata_section
    label: Business Process Type

  steps:
    source: steps_table
    fields:
      - order
      - step_type
      - description
      - security_group
      - condition_rule
      - due_date
      - escalation

evidence:
  - screenshot
  - accessibility_snapshot
  - html_snapshot
  - network_trace

validation:
  - process_name_required
  - step_order_unique
  - at_least_one_step
```

# Graph ingestion pipeline

## 1. Capture immutable evidence

Before transforming anything, store the raw source.

## 2. Extract candidate facts

```json
{
  "subject": "wd:bp-definition/change-job-malaysia",
  "predicate": "wd:hasStep",
  "object": "wd:bp-step/compensation-approval",
  "validFrom": "2026-01-01",
  "confidence": 0.97,
  "evidenceId": "ev_019284"
}
```

## 3. Validate

Validate against:

- JSON Schema
- Pydantic models
- SHACL graph constraints
- Uniqueness rules
- Referential integrity
- Cross-source consistency

## 4. Entity resolution

Resolve using:

- Workday WID
- Reference ID
- API identifier
- Tenant ID
- Object type
- Effective date
- Normalized label

Never merge solely using display names.

## 5. Version and diff

Do not overwrite configuration nodes.

```text
Change Job v6
    SUPERSEDED_BY
Change Job v7
```

# Recommended storage pattern

```text
Object storage
    Raw screenshots, HTML, HAR, XML, reports and documents

PostgreSQL
    Extraction runs, connector state, evidence metadata,
    jobs, mappings and normalized staging records

Graph database
    Workday entities, relationships, versions and provenance

Vector index
    Descriptions, documents, report definitions, help text,
    implementation notes and meeting content
```

# How AI agents should query it

Expose graph tools such as:

```text
get_business_process_definition(process, tenant, effective_date)

get_fields_for_task(task, tenant)

trace_field_usage(field_id)

find_process_dependencies(process_id)

find_security_groups_with_access(object_id)

compare_process_versions(process_id, version_a, version_b)

assess_change_impact(change_request)

get_evidence_for_fact(fact_id)

find_configuration_conflicts(requirement)

generate_test_scenarios(process_id)
```

## User

I would want to do for azure Devops, jira, sap, dynamics 365 also

## Assistant

You should design this as a **multi-system enterprise configuration intelligence platform**, not separate one-off scrapers. Each connector should feed the same canonical graph, evidence, versioning, and change-impact model.

# The right product architecture

```text
Workday        SAP          Dynamics 365       Jira        Azure DevOps
   │            │                │               │               │
   ├────────────┴────────────────┴───────────────┴───────────────┤
   │                Enterprise Source Connectors                 │
   │ API collectors | reports | exports | events | browser agent│
   └───────────────────────────┬─────────────────────────────────┘
                               │
                     Raw evidence and snapshots
                               │
                 Source-specific normalization
                               │
                   Canonical enterprise ontology
                               │
            Entity resolution, versioning and provenance
                               │
                        Knowledge graph
                               │
             Agent tools and change-intelligence APIs
```

The goal is to answer questions such as:

> “This Jira requirement changes the employee grade approval process. Which Workday workflow, SAP payroll configuration, Dynamics integration, Azure DevOps components and test cases are affected?”

# 1. Common canonical model

Do not force every system into identical terminology. Create a shared upper ontology and retain source-specific subtypes.

## Shared enterprise entities

```text
Enterprise
Business Entity
Business Unit
Application
Module
Environment
Business Capability
Business Process
Process Step
Business Rule
Data Object
Field
Form
Screen
Role
Security Group
Permission
Integration
API
Report
Requirement
User Story
Acceptance Criterion
Test Case
Source Code Component
Deployment
Configuration Item
Evidence
Change
```

## Shared relationships

```text
IMPLEMENTS
CONFIGURES
SUPPORTS_CAPABILITY
HAS_STEP
USES_FIELD
READS_OBJECT
WRITES_OBJECT
TRIGGERED_BY
CONTROLLED_BY_RULE
APPROVED_BY
SECURED_BY
INTEGRATES_WITH
MAPPED_TO
DEPENDS_ON
IMPLEMENTED_BY
TESTED_BY
DOCUMENTED_BY
DEPLOYED_TO
SUPPORTED_BY_EVIDENCE
SUPERSEDES
CONFLICTS_WITH
```

Then add platform-specific entities:

```text
WorkdayBusinessProcessDefinition
SAPBusinessObject
DataverseTable
JiraWorkflow
AzureDevOpsWorkItemType
```

# 2. Azure DevOps connector

Extract:

- Organizations
- Projects
- Teams
- Repositories
- Area paths
- Iteration paths
- Environments
- Service connections
- Work-item types
- Fields
- Field rules
- States
- State transitions
- Process templates
- Backlogs
- Boards
- Queries
- Work items
- Links and dependencies
- Revisions and history
- YAML pipelines
- Classic build and release definitions
- Stages
- Jobs
- Tasks
- Variables
- Variable groups
- Approvals and checks
- Deployment history

Use:

- REST API for periodic snapshots
- Git clone for code and YAML
- Service Hooks for incremental changes
- Webhooks into your ingestion gateway

# 3. Jira connector

Extract:

- Projects
- Project types
- Issue types
- Fields
- Custom fields
- Field contexts
- Field configurations
- Screens
- Screen schemes
- Workflows
- Statuses
- Transitions
- Workflow schemes
- Conditions
- Validators
- Post-functions
- Permissions
- Notification schemes
- Automation rules
- Components
- Versions
- Epics
- Stories
- Tasks
- Bugs
- Comments
- Attachments
- Change history

Model separately:

```text
Jira workflow configuration
Jira issue execution history
Jira requirement content
```

# 4. Dynamics 365 connector

Extract from Dataverse:

- Tables/entities
- Columns/attributes
- Relationships
- Choice sets
- Alternate keys
- Calculated columns
- Rollup columns
- Required levels
- Validation constraints
- Model-driven apps
- Forms
- Views
- Dashboards
- Business rules
- Business process flows
- Security roles
- Teams
- Field-level security
- Power Automate flows
- Plugins
- Custom APIs
- Solutions
- Dependencies
- Managed/unmanaged layers

Recommended hierarchy:

```text
1. Dataverse metadata API
2. Solution export and unpacking
3. Power Platform administration APIs
4. Power Automate connector APIs
5. Browser discovery only for gaps
```

# 5. SAP connector

SAP must be treated as a connector family:

```text
SAP S/4HANA
SAP ECC
SAP SuccessFactors
SAP Ariba
SAP BTP
SAP Integration Suite
SAP Analytics Cloud
SAP Fiori
SAP BW
SAP MDG
```

Extract:

- Business objects
- Tables and views
- CDS views
- OData services
- BAPIs and RFCs
- IDocs
- Transactions
- Programs
- Function modules
- Classes
- Enhancements
- User exits and BAdIs
- Customizing configuration
- Organizational structures
- Roles and authorization objects
- Background jobs
- Flexible workflows
- Fiori applications
- Transport history

# 6. Browser-agent strategy across all systems

Recommended hierarchy:

```text
Official API
    ↓
Supported export
    ↓
System metadata endpoint
    ↓
Repository or configuration package
    ↓
Read-only customer-installed extractor
    ↓
Browser automation
    ↓
Vision-based extraction
```

# 7. Connector framework

Every connector should implement the same contract:

```python
class EnterpriseConnector:
    def discover_capabilities(self): ...
    def validate_access(self): ...
    def snapshot_configuration(self): ...
    def snapshot_runtime_objects(self): ...
    def subscribe_to_changes(self): ...
    def collect_evidence(self): ...
    def normalize_entities(self): ...
    def resolve_identifiers(self): ...
    def calculate_diff(self): ...
    def checkpoint(self): ...
```

# 8. Cross-system identity resolution

Create explicit mapping entities:

```text
CanonicalDataElement: Employee Identifier
    ├── REPRESENTED_BY → Workday.Employee_ID
    ├── REPRESENTED_BY → SAP.PERNR
    ├── REPRESENTED_BY → Dynamics.employeeid
    └── REFERENCED_BY → Jira.customfield_10422
```

# 9. Cross-system traceability graph

```text
Business Requirement
    ↓ REALIZED_BY
Jira Epic
    ↓ DECOMPOSED_INTO
Azure DevOps User Story
    ↓ IMPLEMENTED_BY
Git Commit / Pull Request
    ↓ MODIFIES
Dynamics Plugin / SAP Enhancement / Workday Integration
    ↓ CHANGES
Business Process / Field / Rule
    ↓ TESTED_BY
Test Case
    ↓ EXECUTED_IN
Environment
    ↓ PRODUCES
Test Evidence
```

## User

It also includes different things like figma, code base, bugs, PRD, brd, api spec, postman collections, change requests etc., research what all the enterprise systems and connectors we need to have and an ontology for graph and design the provenance and edge nodes, wikis etc.,

## Assistant

Your platform should ingest the complete **enterprise change lifecycle**, not merely application configurations:

```text
Business intent
→ requirement
→ design
→ implementation
→ configuration
→ integration
→ testing
→ deployment
→ production behaviour
→ incident/feedback
→ subsequent change
```

The knowledge graph becomes the enterprise’s **implementation truth and change-intelligence layer**.

# 1. Enterprise connector landscape

## A. Business requirements and product management

| Category | Systems to support | Information to extract |
|---|---|---|
| Product management | Jira Product Discovery, Aha!, Productboard, Azure DevOps Boards | Ideas, opportunities, features, priorities, roadmaps, assumptions, outcomes |
| Requirements | Jira, Azure DevOps, Jama Connect, IBM DOORS Next, Polarion, Codebeamer | Epics, capabilities, requirements, user stories, acceptance criteria, traceability |
| Documents | SharePoint, OneDrive, Google Drive, Box, Dropbox, file shares | PRD, BRD, FRD, SRS, SoW, proposals, spreadsheets, PDFs |
| Change management | ServiceNow, Jira Service Management, BMC Helix, Freshservice | Change requests, approvals, CAB decisions, risk assessments, implementation plans |
| Portfolio management | Planview, Clarity, ServiceNow SPM, Microsoft Project | Programmes, projects, funding, milestones, benefits, dependencies |

## B. Knowledge, wikis and collaboration

- Confluence
- SharePoint Online
- Notion
- Guru
- Slab
- GitHub Wiki
- GitLab Wiki
- Microsoft Teams
- Slack
- Google Chat
- Exchange Online
- Gmail
- Teams meetings
- Zoom
- Google Meet
- Webex
- Miro
- Mural
- Microsoft Whiteboard
- FigJam
- ServiceNow Knowledge
- Custom intranets

Extract:

- Pages and hierarchy
- Sections and tables
- Authors and reviewers
- Mentions and links
- Decisions
- Actions
- Questions and answers
- Meeting transcripts
- Attachments
- Comments and reactions
- Version history
- Superseded content

## C. UX and design systems

- Figma
- FigJam
- Sketch
- Adobe XD archives
- Miro
- Mural
- Lucidchart
- Visio
- Draw.io
- Structurizr
- Enterprise Architect
- Signavio
- ARIS
- Bizagi
- BPMN repositories

For Figma extract:

- Files, pages, frames and sections
- Components and component sets
- Instances and overrides
- Variables and design tokens
- Text fields
- Interaction links
- Prototypes
- Comments
- Version metadata
- Library relationships
- Dev-mode references
- Links to tickets and code

Important graph path:

```text
Requirement
→ REPRESENTED_BY
FigmaFrame
→ CONTAINS
UIComponent
→ IMPLEMENTED_BY
FrontendComponent
→ CALLS
APIEndpoint
```

## D. Engineering and source control

- GitHub
- GitLab
- Azure Repos
- Bitbucket
- Gerrit
- Sourcegraph
- GitHub Actions
- GitLab CI
- Azure Pipelines
- Jenkins
- CircleCI
- Argo CD
- JFrog Artifactory
- Nexus
- Azure Artifacts
- Terraform
- Bicep
- CloudFormation
- Pulumi
- Helm
- LaunchDarkly
- Split
- Unleash

Extract:

```text
Repository
→ Branch
→ Commit
→ Pull Request
→ File
→ Symbol
→ Function/Class
→ API/Database/Queue dependency
```

## E. APIs, integration and messaging

- OpenAPI
- Swagger
- RAML
- GraphQL SDL
- protobuf
- Smithy
- AsyncAPI
- Avro
- Kafka schema registries
- Postman
- Insomnia
- Bruno
- Apigee
- MuleSoft
- Kong
- Azure API Management
- AWS API Gateway
- SAP Integration Suite
- Azure Logic Apps
- Kafka
- Azure Service Bus
- RabbitMQ
- IBM MQ
- AWS SNS/SQS
- Informatica
- Talend
- Fivetran
- Airbyte
- Azure Data Factory

## F. Enterprise business applications

### Human capital management

- Workday
- SAP SuccessFactors
- Oracle HCM
- UKG
- ADP

### ERP and finance

- SAP S/4HANA and ECC
- Oracle Fusion ERP
- Microsoft Dynamics 365 Finance
- NetSuite
- Infor

### CRM and customer service

- Salesforce
- Dynamics 365 Sales and Customer Service
- ServiceNow CSM
- SAP CX
- HubSpot Enterprise

### IT service and workflow management

- ServiceNow
- Jira Service Management
- BMC Helix
- Ivanti
- Freshservice

### Supply chain, procurement and manufacturing

- SAP Ariba
- Coupa
- Oracle SCM
- Dynamics 365 Supply Chain
- SAP EWM
- Siemens Teamcenter
- PTC Windchill

### Low-code platforms

- Microsoft Power Platform
- Salesforce Flow and Lightning
- ServiceNow App Engine
- OutSystems
- Mendix
- Appian

## G. Databases, analytics and data platforms

- PostgreSQL
- SQL Server
- Oracle
- MySQL
- DB2
- SAP HANA
- Snowflake
- BigQuery
- Redshift
- Synapse
- Databricks
- dbt
- Spark
- Power BI
- Tableau
- Looker
- Qlik
- Microsoft Purview
- Collibra
- Alation
- OpenMetadata
- DataHub
- Airflow
- Dagster
- Prefect
- Azure Data Factory

## H. Testing and quality engineering

- TestRail
- Zephyr
- Xray
- Azure Test Plans
- qTest
- Playwright
- Selenium
- Cypress
- BrowserStack
- Postman/Newman
- Karate
- REST Assured
- JMeter
- k6
- Gatling
- LoadRunner
- Appium
- Sauce Labs
- SonarQube
- CodeQL
- Fortify
- Checkmarx
- Datadog
- Dynatrace
- New Relic
- Grafana

## I. Operations, observability and incidents

- ServiceNow incidents and problems
- Jira bugs
- Azure DevOps bugs
- PagerDuty
- Opsgenie
- Datadog
- Dynatrace
- New Relic
- Splunk
- Elastic
- Sentinel
- OpenTelemetry
- Sentry
- Kubernetes
- Cloud audit logs
- CMDB systems

## J. Identity, security and governance

- Entra ID
- Active Directory
- Okta
- Ping
- CyberArk
- BeyondTrust
- Azure Policy
- AWS Config
- Google Cloud Asset Inventory
- Microsoft Purview
- Collibra
- ServiceNow GRC
- Archer
- SAST, DAST, SCA and CSPM tools
- SBOM sources

# 2. Canonical enterprise ontology

## Layer 1: Organizational context

```text
Enterprise
LegalEntity
BusinessUnit
Department
Team
Person
Role
Stakeholder
Vendor
Customer
Location
Environment
```

## Layer 2: Strategy and business intent

```text
Objective
Outcome
Capability
ValueStream
BusinessProcess
Policy
Regulation
Control
Risk
Metric
```

## Layer 3: Demand and change

```text
Idea
Requirement
BusinessRequirement
FunctionalRequirement
NonFunctionalRequirement
UserStory
AcceptanceCriterion
ChangeRequest
Defect
Incident
Problem
Decision
Assumption
Constraint
Dependency
```

## Layer 4: Experience and design

```text
Journey
Persona
UseCase
ProcessModel
DesignFile
DesignFrame
UIComponent
Screen
Form
Field
DesignToken
PrototypeInteraction
ArchitectureModel
ArchitectureComponent
```

## Layer 5: Application and configuration

```text
Application
ApplicationModule
Tenant
ConfigurationItem
BusinessObject
DataObject
FieldDefinition
BusinessRule
ValidationRule
WorkflowDefinition
WorkflowVersion
WorkflowStep
SecurityPolicy
Permission
Report
Integration
ScheduledJob
```

## Layer 6: Software delivery

```text
Repository
Branch
Commit
PullRequest
CodeFile
CodeSymbol
Build
Artifact
Package
Pipeline
PipelineStage
Deployment
FeatureFlag
Release
```

## Layer 7: API and data

```text
API
APIVersion
Endpoint
Operation
Schema
Message
Event
Topic
Queue
Database
Dataset
Table
Column
DataPipeline
DataTransformation
```

## Layer 8: Validation and operations

```text
TestPlan
TestCase
TestStep
TestRun
TestResult
Evidence
Alert
Incident
Problem
RootCause
RuntimeTrace
LogEvent
SLO
```

## Layer 9: Knowledge artifacts

```text
Document
DocumentVersion
DocumentSection
WikiPage
Message
Email
Meeting
Transcript
Comment
Attachment
Diagram
DecisionRecord
```

## Layer 10: Governance and provenance

```text
SourceSystem
SourceAccount
ExtractionRun
ExtractionRecipe
Agent
HumanAgent
SoftwareAgent
Observation
Assertion
EvidenceArtifact
Validation
Approval
Conflict
Mapping
Version
```

# 3. Use assertions as edge nodes

Instead of:

```text
Requirement-42 IMPLEMENTED_BY Commit-91
```

Create a reified assertion:

```text
Requirement-42
    ← SUBJECT — Assertion-1001 — OBJECT →
Commit-91
```

Assertion attributes:

- predicate
- assertedBy
- evidence
- confidence
- observedAt
- validFrom
- status

# 4. Edge taxonomy

## Intent and decomposition

```text
SUPPORTS_OBJECTIVE
REALIZES_CAPABILITY
DECOMPOSES_INTO
REFINES
DERIVED_FROM
ADDRESSES
SATISFIES
```

## Requirement traceability

```text
SPECIFIED_IN
HAS_ACCEPTANCE_CRITERION
CONSTRAINED_BY
DEPENDS_ON
CONFLICTS_WITH
SUPERSEDES
DUPLICATES
APPROVED_BY
```

## Design traceability

```text
REPRESENTED_BY
DESIGNED_IN
USES_COMPONENT
HAS_INTERACTION
MAPS_TO_SCREEN
MAPS_TO_FIELD
```

## Implementation

```text
IMPLEMENTED_BY
MODIFIES
INTRODUCED_BY
REVIEWED_IN
MERGED_IN
BUILT_BY
PACKAGED_AS
DEPLOYED_AS
```

## Application configuration

```text
CONFIGURES
HAS_FIELD
HAS_RULE
HAS_WORKFLOW
HAS_STEP
NEXT_STEP
CONDITIONAL_NEXT_STEP
ROUTES_TO
APPROVED_BY_ROLE
SECURED_BY
```

## API and integration

```text
EXPOSES
CALLS
CONSUMES
PRODUCES
PUBLISHES
SUBSCRIBES_TO
MAPS_FIELD_TO
TRANSFORMS
READS
WRITES
```

## Testing

```text
VERIFIED_BY
TESTED_BY
EXERCISED_BY
EXECUTED_IN
PRODUCED_RESULT
FAILED_DUE_TO
CREATED_DEFECT
```

## Operations

```text
OBSERVED_IN
GENERATED_ALERT
AFFECTED
CAUSED
CONTRIBUTED_TO
REMEDIATED_BY
ROLLED_BACK_BY
```

## Knowledge and communication

```text
DOCUMENTED_IN
DISCUSSED_IN
MENTIONED_IN
DECIDED_IN
EXPLAINED_BY
ATTACHED_TO
REFERENCES
```

## Ownership and governance

```text
OWNED_BY
MAINTAINED_BY
APPROVED_BY
ACCOUNTABLE_TO
GOVERNED_BY
CLASSIFIED_AS
```

# 5. Provenance model

Use a W3C PROV-O-inspired model:

```text
PROV Entity
    Document version
    API response
    Screenshot
    Code commit
    Extracted fact
    Graph assertion

PROV Activity
    Extraction run
    Transformation
    Entity resolution
    Validation
    Human approval
    Agent inference

PROV Agent
    Human user
    Connector
    AI agent
    Service account
    Source system
```

# 6. Truth and authority model

```text
A1 — authoritative structured source
A2 — authoritative rendered source
B1 — governed enterprise record
B2 — operational observation
C1 — human assertion
C2 — AI-inferred relationship
```

# 7. Versioning and temporal graph

Use bi-temporal records:

- `valid_time`
- `system_time`

Do not overwrite old nodes.

# 8. Evidence design

Store heavy evidence outside the graph:

- API responses
- HTML
- XML
- PDFs
- DOCX
- spreadsheets
- screenshots
- videos
- browser traces
- HAR files
- Git patches
- exported solution packages
- SAP transports
- logs

# 9. Entity resolution and mappings

Use explicit mapping nodes with:

- source
- target
- canonical concept
- mapping type
- transformation
- confidence
- approved by
- evidence

# 10. AI-agent access layer

Expose controlled tools:

```text
search_enterprise_concepts()
get_entity_context()
trace_requirement_to_production()
find_change_impact()
compare_configurations()
find_conflicting_requirements()
get_current_implementation()
get_design_to_code_traceability()
find_untested_process_paths()
find_drift_from_approved_design()
get_assertion_evidence()
propose_entity_mapping()
create_candidate_assertion()
```

# 11. Recommended connector priorities

## Foundation connectors

1. SharePoint, OneDrive and Microsoft Teams
2. Confluence and Jira
3. Azure DevOps
4. GitHub, GitLab and Bitbucket
5. Figma
6. Postman and API specification repositories
7. ServiceNow
8. Google Drive and Gmail

## Enterprise application connectors

9. Dynamics 365 and Power Platform
10. Workday
11. Salesforce
12. SAP SuccessFactors
13. SAP S/4HANA and ECC
14. Oracle Fusion
15. MuleSoft and SAP Integration Suite

## Runtime and validation

16. TestRail, Xray, Zephyr and Azure Test Plans
17. Playwright, Selenium and Postman/Newman
18. Datadog, Dynatrace, Splunk and OpenTelemetry
19. Cloud platforms and Kubernetes
20. Data catalogues and lineage platforms

## User

End of the once this context engine and knowledge/context graph is ready we can use these to build rich test cases, change requests, new features and enhancements which makes the business owners and ba and qa lead and different personas life easier

## Assistant

Exactly. The **context engine and knowledge graph are the foundation**, but the commercial value comes from the persona-specific applications built on top of them.

The product should convert scattered enterprise information into a continuously evolving understanding of:

```text
What the business requested
→ what was approved
→ what was designed
→ what is configured
→ what was implemented
→ how systems interact
→ what was tested
→ what is running in production
→ what changed or drifted
```

# Product vision

> An enterprise change-intelligence platform that understands the organization’s business processes, requirements, application configurations, integrations, code, data, tests and operational behaviour, and uses that context to help teams safely define, assess, implement and validate change.

# Core user journey

```text
Business user proposes a change
        ↓
Context engine understands the request
        ↓
Graph identifies existing implementation
        ↓
AI agent asks relevant clarification questions
        ↓
Platform identifies impacts and conflicts
        ↓
Requirement and acceptance criteria are created
        ↓
Design, implementation and test recommendations are generated
        ↓
Change is implemented in existing delivery systems
        ↓
Tests are generated and executed
        ↓
Production configuration and behaviour are validated
        ↓
Graph is updated with the new enterprise truth
```

# Persona-specific capabilities

## Business owner

The platform should provide:

- Current process
- Impacted business units and countries
- Existing workflows
- Current approval roles
- Conflicting policies
- Regulatory considerations
- Impacted teams and systems
- Similar historical changes
- Decisions the owner must make
- Estimated scope and risk

## Business analyst

Outputs:

```text
Business requirement
Functional requirements
Non-functional requirements
User stories
Acceptance criteria
Business rules
Process flows
Data requirements
Field-level changes
Integration requirements
Assumptions
Constraints
Dependencies
Open questions
Traceability matrix
```

## Product owner

Capabilities:

- Epic and feature definition
- Story decomposition
- Prioritisation
- Dependency analysis
- Release planning
- Duplicate-feature detection
- Scope control
- Value and risk assessment

## Solution architect

Outputs:

- Current-state architecture
- Proposed-state architecture
- Impacted application components
- Integration changes
- API changes
- Data-flow changes
- Security implications
- Non-functional requirements
- Migration considerations
- Architecture decision records
- Build-versus-configure recommendations

## Developer and engineering lead

Provide:

- Relevant repositories and components
- Related pull requests and commits
- Existing implementation patterns
- API contracts
- Data models
- Feature flags
- Dependency paths
- Coding standards
- Security requirements
- Known defects
- Existing test coverage

## QA lead

Generate tests using:

```text
Requirement
+ acceptance criteria
+ business-process paths
+ field definitions
+ validation rules
+ role permissions
+ API contracts
+ integrations
+ existing bugs
+ production incidents
+ historical test results
```

## Change manager

Generate:

- Business justification
- Scope
- Impacted services and applications
- Configuration and code changes
- Implementation plan
- Test evidence
- Risk assessment
- Security impact
- Downtime requirement
- Dependency list
- Backout plan
- Validation plan
- Communication plan
- Required approvers
- CAB briefing
- Post-implementation checks

# Core product modules

1. Context Explorer
2. Change Workspace
3. Requirements Copilot
4. Impact Analysis Engine
5. Test Intelligence
6. Change and Release Intelligence
7. Drift and Truth Reconciliation

# Agent architecture

```text
Change Orchestrator
├── Requirement Elicitation Agent
├── Business Process Agent
├── Configuration Analysis Agent
├── Architecture Agent
├── Data and Integration Agent
├── Security Agent
├── Impact Analysis Agent
├── Test Design Agent
├── Test Execution Agent
├── Change Management Agent
└── Evidence Validation Agent
```

# Product differentiation

> **Every output is grounded in the organization’s actual processes, configurations, code, data, integrations, historical decisions, incidents and evidence.**

## User

This product makes the life of product owner life easy by eliciting the key questions and things needed for the feature or the change and conflicts it’s going to have with the current configuration and setup. Similarly we will be able to handover workpackage for ai agent to develop or humans develop and attribute the token the cost and users per features, test cases, bug fixes etc and also the different and so much more

## Assistant

Yes. The product is essentially an **enterprise feature and change operating system**.

Its job is to take an initial business idea, understand the organization’s actual environment, ask the right questions, identify conflicts and dependencies, and produce an implementation-ready work package for either humans or AI agents.

## Core product outcome

A product owner should be able to describe a feature or change in plain language.

The platform then determines:

- Which systems, processes and business units are involved
- How the process currently works
- Existing fields, rules, workflows and permissions
- Similar features or historical change requests
- Conflicting requirements or configurations
- Missing decisions and unanswered questions
- Downstream API, data, reporting and integration impacts
- Security, compliance and segregation-of-duty concerns
- Required regression and acceptance testing

# Work-package generation

```text
Business intent
├── Current-state analysis
├── Target-state definition
├── Scope and exclusions
├── Business requirements
├── Functional requirements
├── Non-functional requirements
├── User stories
├── Acceptance criteria
├── Business rules
├── UI and UX changes
├── Data and field changes
├── Workflow changes
├── API and integration changes
├── Security considerations
├── Impacted components
├── Implementation tasks
├── Test scenarios
├── Test data
├── Deployment plan
├── Rollback plan
└── Traceability and evidence
```

The work package can be handed to:

- An AI coding agent
- An application-configuration agent
- A developer
- A business analyst
- A QA team
- A systems integrator
- A change-management team

# AI-agent execution package

```yaml
work_package:
  feature: Discount approval above 20%

  objective:
    Prevent unauthorized high-value discounts.

  current_state:
    workflow: Dynamics Opportunity Approval v4
    existing_threshold: 30%
    applicable_entities:
      - Malaysia
      - Singapore

  target_state:
    threshold: 20%
    additional_approval_role: Regional Finance Director

  affected_components:
    - Dynamics business rule
    - Power Automate approval flow
    - opportunity form
    - pricing API
    - finance reporting dataset

  repositories:
    - pricing-service
    - dynamics-plugins

  candidate_files:
    - src/pricing/discount-policy.ts
    - plugins/OpportunityApproval.cs

  acceptance_criteria:
    - Approval is required above 20%.
    - Orders cannot proceed while approval is pending.
    - Rejected requests return to draft.
    - All approval actions are audited.

  constraints:
    - No change to existing orders.
    - API compatibility must be preserved.

  tests_required:
    - boundary at 19.99%
    - boundary at 20%
    - approval granted
    - approval rejected
    - unauthorized override
```

# Cost and effort attribution

Track:

- Feature
- User story
- Task
- Repository
- Agent
- Model
- Prompt or agent run
- Input tokens
- Output tokens
- Cached tokens
- Tool calls
- Browser execution time
- Code-generation attempts
- Test-generation attempts
- Failed runs
- Human corrections

# Unit economics

Metrics:

- Cost per feature
- Cost per user story
- Cost per acceptance criterion
- Cost per test case
- Cost per automated test
- Cost per bug fixed
- Cost per deployment
- Cost per production incident
- Tokens per accepted code change
- Tokens per successful test
- AI cost versus human effort
- Rework cost
- First-pass acceptance rate
- Cost of missing context
- Cost of defects escaping to production

# Quality and productivity benchmarking

Compare:

```text
Feature complexity
vs
delivery duration
vs
human effort
vs
AI consumption
vs
defect count
vs
business outcome
```

# Closed-loop learning

```text
Change request
→ requirement
→ implementation
→ testing
→ deployment
→ runtime outcome
→ incidents and user feedback
→ updated graph
→ better future recommendations
```

# Additional high-value capabilities

- Feature feasibility assessment
- Duplicate and overlapping change detection
- Dynamic regression selection
- Automatic defect context
- Outcome tracking
- Human and AI contribution attribution
- Model and agent performance benchmarking

# Product positioning

> **An enterprise context and change-intelligence platform that turns business ideas into implementation-ready, evidence-backed work packages for human and AI delivery teams.**

A broader category description:

> **Enterprise Feature Intelligence and AI Delivery Governance Platform**

Its closed loop is:

```text
Understand
→ challenge
→ define
→ assess
→ generate
→ implement
→ test
→ release
→ measure
→ learn
```
