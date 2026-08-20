import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { DEFAULT_REQUIREMENT_ID } from './useStlc'
import type { Defect, DefectStatus, TestExecution } from './types'

/** A defect is settled when nothing further is expected of it. */
export const SETTLED_STATUSES: DefectStatus[] = ['closed', 'wont_fix', 'rejected']

export function isSettled(d: Defect) {
  return SETTLED_STATUSES.includes(d.status)
}

/**
 * A defect claimed fixed but never proven by a re-test.
 *
 * This is the state the closure gate exists to catch: "fixed" is a developer's
 * claim, and only a passing re-test turns it into evidence. Treating the two as
 * equivalent is how an unverified fix reaches sign-off.
 */
export function isUnverifiedFix(d: Defect) {
  return d.status === 'fixed' && d.verifiedByExecutionId === null
}

/** Defects that still block closure: anything not settled. */
export function blockingDefects(defects: Defect[]) {
  return defects.filter((d) => !isSettled(d))
}

/**
 * Defects for a requirement, with the mutations the re-test loop needs.
 *
 * State is held locally and updated in place rather than refetched, so raising
 * a defect or closing one by re-test is reflected immediately across every
 * screen that reads this hook.
 */
export function useDefects(requirementId: string = DEFAULT_REQUIREMENT_ID) {
  const [defects, setDefects] = useState<Defect[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let live = true
    setLoading(true)
    api.getDefects(requirementId).then((d) => {
      if (!live) return
      setDefects(d)
      setLoading(false)
    })
    return () => {
      live = false
    }
  }, [requirementId])

  const upsert = useCallback((next: Defect[]) => {
    setDefects((list) => {
      const byId = new Map(list.map((d) => [d.id, d]))
      for (const d of next) byId.set(d.id, d)
      return [...byId.values()]
    })
  }, [])

  const raise = useCallback(async (input: Parameters<typeof api.raiseDefect>[0]) => {
    const created = await api.raiseDefect(input)
    setDefects((list) => [created, ...list])
    return created
  }, [])

  const setStatus = useCallback(
    async (id: string, status: DefectStatus, note?: string) => {
      const updated = await api.setDefectStatus(id, status, note)
      if (updated) upsert([updated])
      return updated
    },
    [upsert],
  )

  const recordRetest = useCallback(
    async (execution: TestExecution, defectIds: string[]) => {
      const touched = await api.recordRetest(execution, defectIds)
      upsert(touched)
      return touched
    },
    [upsert],
  )

  return { defects, loading, raise, setStatus, recordRetest }
}
