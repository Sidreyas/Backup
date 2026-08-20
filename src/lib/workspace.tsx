import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { PROJECTS, WORKSPACES } from './mock-data'
import type { Project, Workspace } from './types'

/**
 * Workspace/project scope.
 *
 * A workspace is a governance boundary (business unit, regulated entity); a
 * project scopes the working set inside it. Everything the user sees — sources,
 * requirements, evidence, spend — is filtered by the active project, so the
 * scope has to live above the router rather than in any one page.
 */
interface ScopeValue {
  workspaces: Workspace[]
  workspace: Workspace
  projects: Project[]
  project: Project
  setWorkspace: (id: string) => void
  setProject: (id: string) => void
  /**
   * Rename a workspace or project.
   *
   * Overrides are stored by id and layered over the fixtures, rather than
   * mutating them: the fixtures stand in for server data, and editing them in
   * place would make a rename look persisted while surviving only until the
   * module reloaded. An empty or whitespace-only name is ignored — a thing with
   * no name is unreachable in every menu that lists it.
   */
  renameWorkspace: (id: string, name: string) => void
  renameProject: (id: string, name: string) => void
}

const ScopeContext = createContext<ScopeValue | null>(null)

export function useScope(): ScopeValue {
  const ctx = useContext(ScopeContext)
  if (!ctx) throw new Error('useScope must be used inside <ScopeProvider>')
  return ctx
}

const STORAGE_KEY = 'meridian.scope'
/**
 * Renames, kept in their own key rather than inside `meridian.scope`.
 *
 * Scope is which workspace you are looking at — disposable, per-device state.
 * A rename is a change to the thing itself, and a corrupt scope blob should
 * never take the names down with it.
 */
const NAMES_KEY = 'meridian.names'

function readStored(): { workspaceId?: string; projectId?: string } {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}')
  } catch {
    return {}
  }
}

function readNames(): Record<string, string> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(NAMES_KEY) ?? '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    // Keep only string values: a malformed entry would otherwise render as
    // "[object Object]" in the sidebar with no way to fix it from the UI.
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        ([, v]) => typeof v === 'string' && v.trim().length > 0,
      ),
    ) as Record<string, string>
  } catch {
    return {}
  }
}

export function ScopeProvider({ children }: { children: ReactNode }) {
  const stored = readStored()

  const [workspaceId, setWorkspaceId] = useState<string>(
    () => WORKSPACES.find((w) => w.id === stored.workspaceId)?.id ?? WORKSPACES[0].id,
  )

  /** Renamed labels by entity id. Absent id ⇒ the fixture's own name stands. */
  const [names, setNames] = useState<Record<string, string>>(readNames)

  /*
   * The fixtures with renames applied. Everything downstream derives from
   * these, so a rename reaches the switcher, the settings page and every page
   * header at once — there is no second copy of a name to keep in step.
   */
  const workspaces = useMemo(
    () => WORKSPACES.map((w) => (names[w.id] ? { ...w, name: names[w.id] } : w)),
    [names],
  )
  const allProjects = useMemo(
    () => PROJECTS.map((p) => (names[p.id] ? { ...p, name: names[p.id] } : p)),
    [names],
  )

  const workspace = useMemo(
    () => workspaces.find((w) => w.id === workspaceId) ?? workspaces[0],
    [workspaces, workspaceId],
  )

  const projects = useMemo(
    () => allProjects.filter((p) => p.workspaceId === workspace.id),
    [allProjects, workspace.id],
  )

  const [projectId, setProjectId] = useState<string>(() => {
    const initialWs = WORKSPACES.find((w) => w.id === stored.workspaceId) ?? WORKSPACES[0]
    const inWs = PROJECTS.filter((p) => p.workspaceId === initialWs.id)
    return inWs.find((p) => p.id === stored.projectId)?.id ?? inWs[0]?.id ?? ''
  })

  // Switching workspace must land on a project that actually belongs to it.
  useEffect(() => {
    if (!projects.some((p) => p.id === projectId)) {
      setProjectId(projects[0]?.id ?? '')
    }
  }, [projects, projectId])

  const project = useMemo(
    () => projects.find((p) => p.id === projectId) ?? projects[0],
    [projects, projectId],
  )

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ workspaceId, projectId }))
    } catch {
      /* storage unavailable — scope simply won't persist */
    }
  }, [workspaceId, projectId])

  useEffect(() => {
    try {
      localStorage.setItem(NAMES_KEY, JSON.stringify(names))
    } catch {
      /* storage unavailable — renames simply won't persist */
    }
  }, [names])

  const setWorkspace = useCallback((id: string) => setWorkspaceId(id), [])
  const setProject = useCallback((id: string) => setProjectId(id), [])

  /*
   * One implementation for both: a rename is the same operation whichever kind
   * of thing is being renamed, and ids are unique across both sets.
   *
   * Trimmed, and rejected when empty. Renaming back to the fixture's own name
   * drops the override rather than storing a redundant copy, so "undo my
   * rename" leaves no trace behind.
   */
  const rename = useCallback((id: string, name: string) => {
    const next = name.trim()
    if (!next) return
    setNames((prev) => {
      const original = [...WORKSPACES, ...PROJECTS].find((e) => e.id === id)?.name
      if (next === original) {
        if (!(id in prev)) return prev
        const { [id]: _dropped, ...rest } = prev
        return rest
      }
      if (prev[id] === next) return prev
      return { ...prev, [id]: next }
    })
  }, [])

  const value = useMemo<ScopeValue>(
    () => ({
      workspaces,
      workspace,
      projects,
      project,
      setWorkspace,
      setProject,
      renameWorkspace: rename,
      renameProject: rename,
    }),
    [workspaces, workspace, projects, project, setWorkspace, setProject, rename],
  )

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>
}
