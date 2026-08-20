import { useState } from 'react'
import { Bell, Building2, Cpu, Palette, Settings, User } from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import { Tabs } from '@/components/ui/overlays'
import {
  AgentsSection,
  AppearanceSection,
  NotificationsSection,
  ProfileSection,
  WorkspaceSection,
} from '@/components/settings/sections'

/**
 * Full-page settings, kept as a real destination for direct links and
 * bookmarks. The in-app route to settings is the overlay opened from the
 * account menu — this renders the same sections at page scale.
 */
export function SettingsPage() {
  const [tab, setTab] = useState('profile')

  return (
    <>
      <PageHeader
        title="Settings"
        icon={<Settings aria-hidden="true" />}
        tone="plain"
      />

      <PageBody className="space-y-4">
        <Tabs
          value={tab}
          onChange={setTab}
          items={[
            {
              id: 'profile',
              label: 'Profile',
              icon: <User className="size-3.5" aria-hidden="true" />,
            },
            {
              id: 'appearance',
              label: 'Appearance',
              icon: <Palette className="size-3.5" aria-hidden="true" />,
            },
            {
              id: 'workspace',
              label: 'Workspace',
              icon: <Building2 className="size-3.5" aria-hidden="true" />,
            },
            {
              id: 'agents',
              label: 'Agents & budget',
              icon: <Cpu className="size-3.5" aria-hidden="true" />,
            },
            {
              id: 'notifications',
              label: 'Notifications',
              icon: <Bell className="size-3.5" aria-hidden="true" />,
            },
          ]}
        />

        {tab === 'profile' ? <ProfileSection /> : null}
        {tab === 'appearance' ? <AppearanceSection /> : null}
        {tab === 'workspace' ? <WorkspaceSection /> : null}
        {tab === 'agents' ? <AgentsSection /> : null}
        {tab === 'notifications' ? <NotificationsSection /> : null}
      </PageBody>
    </>
  )
}
