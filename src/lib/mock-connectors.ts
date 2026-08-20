import type { Id, IngestStatus, SourceKind } from './types'

/**
 * A connector is the *connection* to an external system: how Meridian
 * authenticates, what it is allowed to read, and whether that access still
 * works. It is deliberately separate from KnowledgeSource, which describes
 * what was indexed once the connection succeeded — a distinction that matters
 * because a connector can be healthy while its source is empty, and a source
 * can hold good data long after its credentials expired.
 */

export type AuthMethod = 'oauth2' | 'api_key' | 'basic' | 'service_account' | 'webhook'

export type ConnectorCategory =
  | 'hcm'
  | 'erp'
  | 'ticketing'
  | 'code'
  | 'docs'
  | 'design'
  | 'messaging'
  | 'custom'

/** How often Meridian pulls. Manual means it only syncs when asked. */
export type SyncCadence = 'realtime' | 'hourly' | 'daily' | 'weekly' | 'manual'

/**
 * A scope Meridian asks for. `required` scopes cannot be declined without the
 * connector losing its purpose; optional ones trade capability for caution,
 * which is a decision the customer's security team should get to make.
 */
export interface ConnectorScope {
  id: string
  label: string
  description: string
  required: boolean
  /** Whether this scope can write back to the external system. */
  writes: boolean
}

/** A connector type available to install, whether or not it is connected. */
export interface ConnectorDefinition {
  id: Id
  name: string
  vendor: string
  category: ConnectorCategory
  kind: SourceKind
  description: string
  authMethods: AuthMethod[]
  scopes: ConnectorScope[]
  /** What this connector contributes to the governance record. */
  provides: string[]
  /** Set for connectors the customer built themselves. */
  custom?: boolean
  /** Not yet generally available; shown but not installable. */
  comingSoon?: boolean
}

/** An installed connection to an external system. */
export interface Connection {
  id: Id
  connectorId: Id
  /** What the customer named this connection, e.g. "Production Tenant". */
  label: string
  status: IngestStatus
  authMethod: AuthMethod
  grantedScopes: string[]
  cadence: SyncCadence
  lastSyncedAt: string | null
  nextSyncAt: string | null
  /** Who owns this connection operationally, for the "who do I ask" question. */
  owner: string
  connectedBy: string
  connectedAt: string
  /** Records pulled on the last successful sync. */
  recordCount: number
  /** Present when status is 'error'. */
  error?: string
  /** Populated by a connection test, newest first. */
  lastTestedAt?: string | null
  /** Links this connection to the KnowledgeSource it feeds, when it has one. */
  sourceId?: Id
}

/* ------------------------------------------------------------- definitions */

const OAUTH_READ: ConnectorScope[] = [
  {
    id: 'read.metadata',
    label: 'Read configuration metadata',
    description: 'Object definitions, field-level config and business rules.',
    required: true,
    writes: false,
  },
  {
    id: 'read.records',
    label: 'Read transactional records',
    description: 'Sampled records used to build baselines for comparison testing.',
    required: false,
    writes: false,
  },
]

export const CONNECTORS: ConnectorDefinition[] = [
  {
    id: 'cx-workday',
    name: 'Workday',
    vendor: 'Workday, Inc.',
    category: 'hcm',
    kind: 'platform',
    description:
      'Reads HCM configuration, business process definitions and calculated fields so changes can be traced to the rules they alter.',
    authMethods: ['oauth2', 'service_account'],
    provides: ['Configuration baseline', 'Business process rules', 'Integration payloads'],
    scopes: [
      ...OAUTH_READ,
      {
        id: 'read.payroll',
        label: 'Read payroll results',
        description:
          'Payroll outputs used to prove a change did not alter what people are paid. Sensitive.',
        required: false,
        writes: false,
      },
    ],
  },
  {
    id: 'cx-sap',
    name: 'SAP S/4HANA',
    vendor: 'SAP SE',
    category: 'erp',
    kind: 'platform',
    description:
      'Reads finance and logistics configuration, including customising tables, so impact analysis can follow a change through to posting behaviour.',
    authMethods: ['oauth2', 'service_account'],
    provides: ['Customising tables', 'Config transport history', 'Posting rules'],
    scopes: OAUTH_READ,
  },
  {
    id: 'cx-jira',
    name: 'Jira',
    vendor: 'Atlassian',
    category: 'ticketing',
    kind: 'ticketing',
    description:
      'Links requirements to the delivery tickets that implement them, so the audit trail reaches back to why work was started.',
    authMethods: ['oauth2', 'api_key'],
    provides: ['Issue links', 'Sprint history', 'Requirement provenance'],
    scopes: [
      ...OAUTH_READ,
      {
        id: 'write.comment',
        label: 'Post comments on issues',
        description: 'Writes approval outcomes back to the originating ticket.',
        required: false,
        writes: true,
      },
    ],
  },
  {
    id: 'cx-github',
    name: 'GitHub',
    vendor: 'GitHub, Inc.',
    category: 'code',
    kind: 'repository',
    description:
      'Reads repositories and pull requests so generated code and its review history become part of the evidence record.',
    authMethods: ['oauth2', 'api_key'],
    provides: ['Commit provenance', 'Pull request reviews', 'CI outcomes'],
    scopes: [
      ...OAUTH_READ,
      {
        id: 'write.status',
        label: 'Publish commit statuses',
        description: 'Reports gate outcomes as a status check on the pull request.',
        required: false,
        writes: true,
      },
    ],
  },
  {
    id: 'cx-slack',
    name: 'Slack',
    vendor: 'Slack Technologies',
    category: 'messaging',
    kind: 'document',
    description:
      'Routes approval requests to the people who own them and records the decision back into the audit chain.',
    authMethods: ['oauth2'],
    provides: ['Approval routing', 'Decision notifications'],
    scopes: [
      {
        id: 'chat.write',
        label: 'Send messages',
        description: 'Posts approval requests to the channel or person you nominate.',
        required: true,
        writes: true,
      },
      {
        id: 'users.read',
        label: 'Read the user directory',
        description: 'Maps approvers to Slack accounts so requests reach the right person.',
        required: true,
        writes: false,
      },
    ],
  },
  {
    id: 'cx-confluence',
    name: 'Confluence',
    vendor: 'Atlassian',
    category: 'docs',
    kind: 'wiki',
    description:
      'Indexes specifications and design decisions so a requirement can cite the document it came from.',
    authMethods: ['oauth2', 'api_key'],
    provides: ['Specification text', 'Decision records'],
    scopes: OAUTH_READ,
  },
  {
    id: 'cx-sharepoint',
    name: 'SharePoint',
    vendor: 'Microsoft',
    category: 'docs',
    kind: 'document',
    description:
      'Reads BRD and PRD libraries so business requirements enter the graph in the form the business wrote them.',
    authMethods: ['oauth2', 'service_account'],
    provides: ['Requirement documents', 'Version history'],
    scopes: OAUTH_READ,
  },
  {
    id: 'cx-figma',
    name: 'Figma',
    vendor: 'Figma, Inc.',
    category: 'design',
    kind: 'design',
    description:
      'Reads design files so a UI change can be shown alongside the screen it affects.',
    authMethods: ['oauth2', 'api_key'],
    provides: ['Screen designs', 'Component usage'],
    scopes: [OAUTH_READ[0]!],
  },
  {
    id: 'cx-d365',
    name: 'Dynamics 365',
    vendor: 'Microsoft',
    category: 'erp',
    kind: 'platform',
    description:
      'Reads Dataverse tables and business rules for Field Service and adjacent modules.',
    authMethods: ['oauth2', 'service_account'],
    provides: ['Dataverse schema', 'Business rules', 'Plugin registrations'],
    scopes: OAUTH_READ,
  },
  {
    id: 'cx-servicenow',
    name: 'ServiceNow',
    vendor: 'ServiceNow, Inc.',
    category: 'ticketing',
    kind: 'ticketing',
    description:
      'Reads change requests so a Meridian approval can satisfy an existing CAB process rather than duplicating it.',
    authMethods: ['oauth2', 'basic'],
    provides: ['Change requests', 'CAB decisions'],
    scopes: OAUTH_READ,
    comingSoon: true,
  },
  {
    id: 'cx-oracle',
    name: 'Oracle Fusion',
    vendor: 'Oracle',
    category: 'erp',
    kind: 'platform',
    description: 'Reads Fusion configuration for ERP and HCM pillars.',
    authMethods: ['oauth2', 'service_account'],
    provides: ['Configuration baseline', 'Approval rules'],
    scopes: OAUTH_READ,
    comingSoon: true,
  },
]

/* ------------------------------------------------------------- connections */

export const CONNECTIONS: Connection[] = [
  {
    id: 'cn-wd',
    connectorId: 'cx-workday',
    label: 'Production Tenant',
    status: 'connected',
    authMethod: 'oauth2',
    grantedScopes: ['read.metadata', 'read.records', 'read.payroll'],
    cadence: 'hourly',
    lastSyncedAt: '2026-08-06T06:15:00Z',
    nextSyncAt: '2026-08-07T11:15:00Z',
    owner: 'HR Systems',
    connectedBy: 'Sathish Kumar',
    connectedAt: '2026-03-11T09:00:00Z',
    recordCount: 14382,
    lastTestedAt: '2026-08-06T06:15:00Z',
    sourceId: 'src-wd',
  },
  {
    id: 'cn-sap',
    connectorId: 'cx-sap',
    label: 'Finance Config — PRD',
    status: 'syncing',
    authMethod: 'service_account',
    grantedScopes: ['read.metadata'],
    cadence: 'daily',
    lastSyncedAt: '2026-08-05T19:40:00Z',
    nextSyncAt: '2026-08-07T19:40:00Z',
    owner: 'Finance IT',
    connectedBy: 'M. Chen',
    connectedAt: '2026-02-02T14:30:00Z',
    recordCount: 38104,
    lastTestedAt: '2026-08-05T19:40:00Z',
    sourceId: 'src-sap',
  },
  {
    id: 'cn-repo',
    connectorId: 'cx-github',
    label: 'acme/integration-services',
    status: 'connected',
    authMethod: 'oauth2',
    grantedScopes: ['read.metadata', 'read.records', 'write.status'],
    cadence: 'realtime',
    lastSyncedAt: '2026-08-06T07:02:00Z',
    nextSyncAt: null,
    owner: 'Platform Engineering',
    connectedBy: 'S. Okonkwo',
    connectedAt: '2026-01-20T11:15:00Z',
    recordCount: 6721,
    lastTestedAt: '2026-08-06T07:02:00Z',
    sourceId: 'src-repo',
  },
  {
    id: 'cn-conf',
    connectorId: 'cx-confluence',
    label: 'HR Transformation space',
    status: 'stale',
    authMethod: 'api_key',
    grantedScopes: ['read.metadata'],
    cadence: 'weekly',
    lastSyncedAt: '2026-06-28T11:20:00Z',
    nextSyncAt: '2026-08-09T11:20:00Z',
    owner: 'HR Transformation PMO',
    connectedBy: 'J. Almeida',
    connectedAt: '2026-01-08T08:45:00Z',
    recordCount: 891,
    lastTestedAt: '2026-06-28T11:20:00Z',
    sourceId: 'src-conf',
  },
  {
    id: 'cn-brd',
    connectorId: 'cx-sharepoint',
    label: 'BRD / PRD Repository',
    status: 'connected',
    authMethod: 'service_account',
    grantedScopes: ['read.metadata', 'read.records'],
    cadence: 'daily',
    lastSyncedAt: '2026-08-04T14:00:00Z',
    nextSyncAt: '2026-08-07T14:00:00Z',
    owner: 'Business Analysis',
    connectedBy: 'Sathish Kumar',
    connectedAt: '2026-02-17T10:05:00Z',
    recordCount: 402,
    lastTestedAt: '2026-08-04T14:00:00Z',
    sourceId: 'src-brd',
  },
  {
    id: 'cn-figma',
    connectorId: 'cx-figma',
    label: 'Employee Self-Service',
    status: 'connected',
    authMethod: 'oauth2',
    grantedScopes: ['read.metadata'],
    cadence: 'weekly',
    lastSyncedAt: '2026-08-03T09:12:00Z',
    nextSyncAt: '2026-08-10T09:12:00Z',
    owner: 'Product Design',
    connectedBy: 'L. Ferreira',
    connectedAt: '2026-04-02T16:20:00Z',
    recordCount: 268,
    lastTestedAt: '2026-08-03T09:12:00Z',
    sourceId: 'src-figma',
  },
  {
    id: 'cn-jira',
    connectorId: 'cx-jira',
    label: 'HRIS Delivery',
    status: 'connected',
    authMethod: 'oauth2',
    grantedScopes: ['read.metadata', 'read.records'],
    cadence: 'hourly',
    lastSyncedAt: '2026-08-06T07:30:00Z',
    nextSyncAt: '2026-08-07T11:30:00Z',
    owner: 'Delivery',
    connectedBy: 'M. Chen',
    connectedAt: '2026-01-15T13:40:00Z',
    recordCount: 3244,
    lastTestedAt: '2026-08-06T07:30:00Z',
    sourceId: 'src-jira',
  },
  {
    id: 'cn-d365',
    connectorId: 'cx-d365',
    label: 'Field Service — PRD',
    status: 'error',
    authMethod: 'oauth2',
    grantedScopes: ['read.metadata'],
    cadence: 'daily',
    lastSyncedAt: '2026-07-30T16:45:00Z',
    nextSyncAt: null,
    owner: 'Service Ops',
    connectedBy: 'R. Nakamura',
    connectedAt: '2026-05-19T09:30:00Z',
    recordCount: 0,
    error: 'OAuth consent expired — admin re-consent required for Dataverse scope',
    lastTestedAt: '2026-08-07T06:00:00Z',
    sourceId: 'src-d365',
  },
]
