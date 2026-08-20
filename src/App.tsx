import { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from '@/components/layout/theme'
import { ScopeProvider } from '@/lib/workspace'
import { ToastProvider } from '@/components/ui/overlays'
import { AppShell } from '@/components/layout/AppShell'
import { DashboardPage } from '@/pages/DashboardPage'
import { Skeleton } from '@/components/ui/primitives'

/**
 * Routes are code-split so the initial load only pays for the shell and the
 * dashboard. Analytics in particular pulls in recharts, which is large.
 */
const SourcesPage = lazy(() =>
  import('@/pages/SourcesPage').then((m) => ({ default: m.SourcesPage })),
)
const IntegrationsPage = lazy(() =>
  import('@/pages/IntegrationsPage').then((m) => ({ default: m.IntegrationsPage })),
)
const RequirementsPage = lazy(() =>
  import('@/pages/RequirementsPage').then((m) => ({ default: m.RequirementsPage })),
)
const RequirementChatPage = lazy(() =>
  import('@/pages/RequirementChatPage').then((m) => ({ default: m.RequirementChatPage })),
)
const ImpactPage = lazy(() => import('@/pages/ImpactPage').then((m) => ({ default: m.ImpactPage })))
const TestPlanPage = lazy(() =>
  import('@/pages/TestPlanPage').then((m) => ({ default: m.TestPlanPage })),
)
const TestCasesPage = lazy(() =>
  import('@/pages/TestCasesPage').then((m) => ({ default: m.TestCasesPage })),
)
const TestRunsPage = lazy(() =>
  import('@/pages/TestRunsPage').then((m) => ({ default: m.TestRunsPage })),
)
const TestClosurePage = lazy(() =>
  import('@/pages/TestClosurePage').then((m) => ({ default: m.TestClosurePage })),
)
const EvidencePage = lazy(() =>
  import('@/pages/EvidencePage').then((m) => ({ default: m.EvidencePage })),
)
const ApprovalsPage = lazy(() =>
  import('@/pages/ApprovalsPage').then((m) => ({ default: m.ApprovalsPage })),
)
const AuditPage = lazy(() => import('@/pages/AuditPage').then((m) => ({ default: m.AuditPage })))
const IncidentsPage = lazy(() =>
  import('@/pages/IncidentsPage').then((m) => ({ default: m.IncidentsPage })),
)
const PoliciesPage = lazy(() =>
  import('@/pages/PoliciesPage').then((m) => ({ default: m.PoliciesPage })),
)
const SettingsPage = lazy(() =>
  import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
)
const SupportPage = lazy(() =>
  import('@/pages/SupportPage').then((m) => ({ default: m.SupportPage })),
)
const AnalyticsPage = lazy(() =>
  import('@/pages/AnalyticsPage').then((m) => ({ default: m.AnalyticsPage })),
)

/** Reserves the same shape the page will occupy, so there is no layout jump. */
function RouteFallback() {
  return (
    <div className="space-y-4 p-4 sm:p-6" role="status" aria-label="Loading page">
      <Skeleton className="h-16 w-full rounded-lg" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-80 w-full rounded-lg" />
      <span className="sr-only">Loading…</span>
    </div>
  )
}

export function App() {
  return (
    <ThemeProvider>
      <ScopeProvider>
        <ToastProvider>
          <BrowserRouter>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<DashboardPage />} />
                <Route
                  path="*"
                  element={
                    <Suspense fallback={<RouteFallback />}>
                      <Routes>
                        {/* Ingestion folded into Knowledge Sources — the drop
                            zone and the sources it produces now sit together.
                            Redirect so existing links keep working. */}
                        <Route path="/ingest" element={<Navigate to="/sources" replace />} />
                        <Route path="/sources" element={<SourcesPage />} />
                        <Route path="/integrations" element={<IntegrationsPage />} />
                        {/* Merged into Knowledge Sources as a view; keep the old link working */}
                        <Route
                          path="/graph"
                          element={<Navigate to="/sources?view=graph" replace />}
                        />
                        <Route path="/requirements" element={<RequirementsPage />} />
                        <Route path="/requirements/:id" element={<RequirementChatPage />} />
                        <Route path="/impact" element={<ImpactPage />} />
                        <Route path="/impact/:id" element={<ImpactPage />} />
                        {/* STLC — planning → design → execution → closure */}
                        <Route path="/test-plan" element={<TestPlanPage />} />
                        <Route path="/test-plan/:id" element={<TestPlanPage />} />
                        <Route path="/test-cases" element={<TestCasesPage />} />
                        <Route path="/test-runs" element={<TestRunsPage />} />
                        <Route path="/test-closure" element={<TestClosurePage />} />
                        <Route path="/evidence" element={<EvidencePage />} />
                        <Route path="/approvals" element={<ApprovalsPage />} />
                        <Route path="/audit" element={<AuditPage />} />
                        <Route path="/incidents" element={<IncidentsPage />} />
                        <Route path="/policies" element={<PoliciesPage />} />
                        <Route path="/analytics" element={<AnalyticsPage />} />
                        <Route path="/support" element={<SupportPage />} />
                        <Route path="/settings" element={<SettingsPage />} />
                        <Route path="*" element={<Navigate to="/" replace />} />
                      </Routes>
                    </Suspense>
                  }
                />
              </Route>
            </Routes>
          </BrowserRouter>
        </ToastProvider>
      </ScopeProvider>
    </ThemeProvider>
  )
}
