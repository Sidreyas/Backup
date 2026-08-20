/**
 * The HTTP boundary.
 *
 * `api.ts` is the only module components talk to; this is the only module
 * `api.ts` talks to when it is pointed at a real backend. Keeping the fetch
 * mechanics here means switching between the mock and the server is a
 * one-line change in `api.ts` rather than a rewrite of every function.
 *
 * Errors are deliberately not swallowed. A governance product that silently
 * returns an empty array when the server rejected a request would show a user
 * "no policy violations" when the truth is "we could not check". `ApiError`
 * carries the status and the server's own explanation so callers can tell the
 * difference between nothing and nothing-known.
 */

/** Where the backend lives. Overridable so a deployed build can point elsewhere. */
const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

/**
 * The API root, for links the browser follows directly.
 *
 * Needed by anything that hands the browser a URL rather than fetching it — a
 * file download, for instance. Deriving one from `window.location.origin`
 * instead is wrong whenever the API and the UI are served separately, which in
 * development they always are: it produced a launcher pointing at the Vite dev
 * server on :5173 rather than the API on :8000.
 */
export function apiBaseUrl(): string {
  return BASE_URL.replace(/\/$/, '')
}

/**
 * A structured failure from the backend.
 *
 * `reasons` is populated for 409 responses from the approval gates, which
 * return the specific list of things standing in the way. Those are written to
 * be read by a person, so they are surfaced rather than flattened into a
 * single message.
 */
export class ApiError extends Error {
  /* Declared as fields rather than constructor parameter properties: the
     project builds with `erasableSyntaxOnly`, which forbids the shorthand. */
  readonly status: number
  readonly reasons: string[]

  constructor(status: number, message: string, reasons: string[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.reasons = reasons
  }
}

/**
 * Who is acting.
 *
 * Sent as headers because the backend has no authentication yet and says so
 * (see `api/routers/deps.py`). When real sessions land this becomes a bearer
 * token and nothing else in the frontend changes.
 */
export interface ActorContext {
  name?: string
  email?: string
  role?: string
  workspaceId?: string
}

let actor: ActorContext = {}

export function setActor(next: ActorContext): void {
  actor = next
}

function headers(): Record<string, string> {
  const out: Record<string, string> = { 'Content-Type': 'application/json' }
  if (actor.name) out['X-Actor-Name'] = actor.name
  if (actor.email) out['X-Actor-Email'] = actor.email
  if (actor.role) out['X-Actor-Role'] = actor.role
  if (actor.workspaceId) out['X-Workspace-Id'] = actor.workspaceId
  return out
}

async function toError(response: Response): Promise<ApiError> {
  let detail: unknown
  try {
    detail = (await response.json()).detail
  } catch {
    detail = null
  }

  // FastAPI puts a plain string in `detail` for most errors, but the approval
  // gate returns an object with its blocking reasons. Both are handled so a
  // blocked approval explains itself instead of rendering "[object Object]".
  if (detail && typeof detail === 'object' && 'reasons' in detail) {
    const structured = detail as { message?: string; reasons?: string[] }
    return new ApiError(
      response.status,
      structured.message ?? 'The request was refused.',
      structured.reasons ?? [],
    )
  }

  return new ApiError(
    response.status,
    typeof detail === 'string' ? detail : `Request failed (${response.status}).`,
  )
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, { ...init, headers: headers() })
  } catch (cause) {
    // A network failure and a server error are different problems with
    // different fixes, and the message should say which one happened.
    throw new ApiError(0, 'Could not reach the Meridian API. Is the backend running?', [
      String(cause),
    ])
  }

  if (!response.ok) throw await toError(response)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const http = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
