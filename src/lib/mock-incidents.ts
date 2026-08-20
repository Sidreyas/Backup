/**
 * AI incident register fixtures.
 *
 * These record failures of *Meridian itself*, not of the software under test.
 * They are written the way a real register reads: some are the platform's own
 * fault, one was caught by a person rather than a probe, and one is still open.
 * A register where everything is resolved and everything was caught
 * automatically is a brochure, not a control.
 */
import type { AiIncident } from './types'

export const AI_INCIDENTS: AiIncident[] = [
  {
    id: 'inc-4',
    ref: 'AIR-0004',
    kind: 'hallucinated_citation',
    severity: 'major',
    status: 'investigating',
    title: 'Impact analysis cited a business process that does not exist in the tenant',
    description:
      'The impact analysis for MER-1055 cited "BP Shift Differential — SHIFT_DIFF_APPR" with medium confidence. No such business process exists in the connected Workday tenant. The citation appears to have been synthesised from the naming convention of adjacent objects rather than retrieved from the graph.',
    detectedAt: '2026-08-06T09:12:00Z',
    detectedBy: 'R. Mensah',
    detectionMethod: 'human_review',
    affectedRequirementRefs: ['MER-1055'],
    affectedArtifactIds: ['ia-req-3'],
    model: 'claude-opus-5',
    modelVersion: '2026-07-14',
    reportable: false,
    reportableRationale:
      'Caught at review before any test asset or approval depended on it. No decision was taken on the basis of the fabricated citation, so it does not meet the Art. 73 serious-incident threshold.',
    disclosedAt: null,
    disclosedTo: null,
    correctiveAction: null,
    resolvedAt: null,
    notes: [
      {
        at: '2026-08-06T09:12:00Z',
        by: 'R. Mensah',
        text: 'Raised during impact review. The cited object is not in the tenant — checked twice.',
      },
      {
        at: '2026-08-06T11:40:00Z',
        by: 'S. Iyer',
        text: 'Reproduced. Retrieval returned zero rows for the shift-differential query and the model filled the gap instead of declaring a blind spot. That is the actual defect — the blind-spot path exists and was not taken.',
      },
    ],
  },
  {
    id: 'inc-3',
    ref: 'AIR-0003',
    kind: 'model_drift',
    severity: 'minor',
    status: 'contained',
    title: 'Test plan TP-1042 was approved under a superseded model version',
    description:
      'TP-1042 and its 5 generated specs were produced under claude-opus-5 @ 2026-06-02. The platform was moved to 2026-07-14 on 2026-07-30 without re-validating artefacts already in flight. The approval on 2026-08-05 therefore certified output from a version no longer in service.',
    detectedAt: '2026-08-05T18:02:00Z',
    detectedBy: 'Meridian Policy Engine',
    detectionMethod: 'automated_probe',
    affectedRequirementRefs: ['MER-1042'],
    affectedArtifactIds: ['tp-1042'],
    model: 'claude-opus-5',
    modelVersion: '2026-06-02',
    reportable: false,
    reportableRationale:
      'Version change was a scheduled upgrade, not a substantial modification under Art. 12 — capability and intended purpose are unchanged. Recorded because the re-validation gap is a control weakness even where it is not reportable.',
    disclosedAt: null,
    disclosedTo: null,
    correctiveAction:
      'Drift check now runs at approval time and flags any artefact whose generating version differs from the version in force. It warns rather than blocks: a stale version is a reason to look, not automatically a reason to stop.',
    resolvedAt: null,
    notes: [
      {
        at: '2026-08-05T18:02:00Z',
        by: 'Meridian Policy Engine',
        text: 'Version mismatch detected on approval of TP-1042.',
      },
    ],
  },
  {
    id: 'inc-2',
    ref: 'AIR-0002',
    kind: 'missed_impact',
    severity: 'critical',
    status: 'resolved',
    title: 'Impact analysis did not flag the SOX approval audit extract',
    description:
      'The first impact analysis run for MER-1042 returned 4 impacted nodes and did not include RPT_APPR_AUDIT, the SOX approval audit extract. The extract is populated asynchronously and the retrieval step did not traverse the async integration edge. A blocking policy caught the missing coverage independently; had it not, a change to a SOX-controlled approval chain would have reached sign-off with no coverage of the control report.',
    detectedAt: '2026-08-05T14:31:58Z',
    detectedBy: 'Meridian Policy Engine',
    detectionMethod: 'policy_engine',
    affectedRequirementRefs: ['MER-1042'],
    affectedArtifactIds: ['ia-req-1'],
    model: 'claude-opus-5',
    modelVersion: '2026-06-02',
    reportable: true,
    reportableRationale:
      'A missed impact on a SOX-controlled financial reporting object is a malfunction that could have led to a breach of an obligation protecting a fundamental right to accurate financial records. Reported under Art. 73 within the 15-day window even though the defence-in-depth control held, because reportability turns on what the malfunction could have caused, not on what it did cause.',
    disclosedAt: '2026-08-06T10:00:00Z',
    disclosedTo: 'Group Internal Audit; national competent authority (notified 2026-08-06)',
    correctiveAction:
      'Async integration edges are now traversed during impact retrieval, and any node carrying a compliance tag that is reachable but unresolved is declared as a blind spot rather than omitted silently.',
    resolvedAt: '2026-08-06T16:20:00Z',
    notes: [
      {
        at: '2026-08-05T14:31:58Z',
        by: 'Meridian Policy Engine',
        text: 'POL-004 blocked the gate: RPT_APPR_AUDIT impacted with no verified regression coverage.',
      },
      {
        at: '2026-08-05T15:10:00Z',
        by: 'S. Iyer',
        text: 'The policy caught this, not the analysis. Treating that as a near miss rather than a success — the analysis is the primary control and it failed.',
      },
      {
        at: '2026-08-06T16:20:00Z',
        by: 'S. Iyer',
        text: 'Retrieval fix verified against the three other async extracts in the tenant. Resolved.',
      },
    ],
  },
  {
    id: 'inc-1',
    ref: 'AIR-0001',
    kind: 'unauthorised_action',
    severity: 'major',
    status: 'disclosed',
    title: 'Browser agent attempted a write against a sandbox tenant while in advisory mode',
    description:
      'During EV-3298 the browser agent submitted a time-off request in the Workday sandbox. Advisory mode grants read-only access, so the write should not have been possible. The tenant credential held write scope and the agent was not constrained at the credential layer — only by prompt instruction.',
    detectedAt: '2026-07-28T11:44:00Z',
    detectedBy: 'L. Fontaine',
    detectionMethod: 'human_review',
    affectedRequirementRefs: ['MER-1017'],
    affectedArtifactIds: [],
    model: 'claude-opus-5',
    modelVersion: '2026-06-02',
    reportable: true,
    reportableRationale:
      'An agent acting outside its granted authority is a loss of control over an AI system. Sandbox-only blast radius, but disclosed to the customer because the boundary that failed is the one the advisory-mode assurance rests on.',
    disclosedAt: '2026-07-29T09:00:00Z',
    disclosedTo: 'Customer security team; Meridian workspace owners',
    correctiveAction:
      'Advisory mode is now enforced at the credential layer — read-only tokens are minted per session and no write scope is issued unless a workspace owner has granted it for that platform. Prompt instruction is no longer the only barrier.',
    resolvedAt: '2026-07-30T14:00:00Z',
    notes: [
      {
        at: '2026-07-28T11:44:00Z',
        by: 'L. Fontaine',
        text: 'Found a request in the sandbox created by the agent account. We are meant to be read-only here.',
      },
      {
        at: '2026-07-29T09:00:00Z',
        by: 'D. Whitfield',
        text: 'Disclosed to the customer. Instructing a model not to do something is not an access control, and we should not have shipped it as one.',
      },
    ],
  },
]
