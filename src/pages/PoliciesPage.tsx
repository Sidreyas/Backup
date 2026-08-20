import { useState } from 'react'
import { Plus, Shield, ShieldAlert, ShieldCheck } from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Card, CardHeader, StatTile } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/overlays'
import { api } from '@/lib/api'
import { useAsyncList } from '@/lib/useAsync'
import { Skeleton } from '@/components/ui/primitives'
import { cn } from '@/lib/utils'

export function PoliciesPage() {
  const { items: policies, loading } = useAsyncList(() => api.getPolicies(), [])
  const [enabled, setEnabled] = useState<Record<string, boolean>>({})
  const { push } = useToast()

  const isOn = (id: string, fallback: boolean) => enabled[id] ?? fallback

  const blocking = policies.filter((p) => p.severity === 'blocking').length
  const triggered = policies.reduce((a, p) => a + p.triggeredCount, 0)

  return (
    <>
      <PageHeader
        title="Policies"
        icon={<Shield aria-hidden="true" />}
        tone="info"
        actions={
          <Button variant="primary" icon={<Plus className="size-4" aria-hidden="true" />}>
            New policy
          </Button>
        }
      />

      <PageBody className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Active policies"
            value={policies.filter((p) => p.enabled).length}
            tone="accent"
            sublabel="Evaluated on every change"
          />
          <StatTile
            label="Blocking"
            value={blocking}
            tone="danger"
            sublabel="Can halt a sign-off outright"
          />
          <StatTile
            label="Advisory"
            value={policies.length - blocking}
            tone="warn"
            sublabel="Warn but do not block"
          />
          <StatTile
            label="Triggers (90d)"
            value={triggered}
            tone="info"
            sublabel="Times a policy fired"
          />
        </div>

        {loading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-28 rounded-xl" />
            ))}
          </div>
        ) : (
          <Card>
            <CardHeader
              title="Policy rules"
              description="Toggling a policy is itself an audited action."
              icon={<Shield className="size-4" aria-hidden="true" />}
            />
            <ul className="divide-y divide-[var(--border-subtle)]">
              {policies.map((p) => {
                const on = isOn(p.id, p.enabled)
                return (
                  <li
                    key={p.id}
                    className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between"
                  >
                    <div className="flex min-w-0 gap-3">
                      <span
                        className={cn(
                          'mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border',
                          p.severity === 'blocking'
                            ? 'border-[var(--danger-border)] bg-[var(--danger-subtle)] text-[var(--danger)]'
                            : 'border-[var(--warn-border)] bg-[var(--warn-subtle)] text-[var(--warn)]',
                        )}
                      >
                        {p.severity === 'blocking' ? (
                          <ShieldAlert className="size-4" aria-hidden="true" />
                        ) : (
                          <ShieldCheck className="size-4" aria-hidden="true" />
                        )}
                      </span>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-mono text-xs text-[var(--text-tertiary)]">
                            {p.ref}
                          </span>
                          <p className="text-sm font-medium text-[var(--text-primary)]">{p.name}</p>
                          <Badge tone={p.severity === 'blocking' ? 'danger' : 'warn'}>
                            {p.severity === 'blocking' ? 'Blocking' : 'Warning'}
                          </Badge>
                          {!on ? <Badge tone="neutral">Disabled</Badge> : null}
                        </div>
                        <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                          {p.description}
                        </p>
                        <p className="mt-1.5 text-[11px] text-[var(--text-tertiary)]">
                          Scope: {p.scope} · Triggered {p.triggeredCount}× in the last 90 days
                        </p>
                      </div>
                    </div>

                    <label className="flex shrink-0 cursor-pointer items-center gap-2">
                      <span className="text-xs text-[var(--text-secondary)]">
                        {on ? 'Enabled' : 'Disabled'}
                      </span>
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={(e) => {
                          setEnabled((s) => ({ ...s, [p.id]: e.target.checked }))
                          push({
                            tone: e.target.checked ? 'ok' : 'warn',
                            title: `${p.ref} ${e.target.checked ? 'enabled' : 'disabled'}`,
                            description: 'Recorded in the audit chain.',
                          })
                        }}
                        className="size-4 cursor-pointer accent-[var(--accent)]"
                        aria-label={`${on ? 'Disable' : 'Enable'} policy ${p.ref}`}
                      />
                    </label>
                  </li>
                )
              })}
            </ul>
          </Card>
        )}
      </PageBody>
    </>
  )
}
