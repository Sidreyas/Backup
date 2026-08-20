import { useEffect, useMemo, useState } from 'react'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: Error | null
}

/** Stable empty array so `useList` consumers get a referentially stable fallback. */
const EMPTY: readonly never[] = Object.freeze([])

/**
 * Minimal data-fetch hook for the mock API. Deliberately tiny — when a real
 * backend lands this should be replaced with TanStack Query or similar.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, loading: true, error: null })

  useEffect(() => {
    let cancelled = false
    setState({ data: null, loading: true, error: null })
    fn()
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null })
      })
      .catch((error: Error) => {
        if (!cancelled) setState({ data: null, loading: false, error })
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return state
}

/**
 * Same as useAsync but for list endpoints: `items` is referentially stable
 * across renders while the data is unchanged, so downstream useMemo/useEffect
 * dependencies on it do not re-fire every render.
 */
export function useAsyncList<T>(
  fn: () => Promise<T[]>,
  deps: unknown[] = [],
): { items: T[]; loading: boolean; error: Error | null } {
  const { data, loading, error } = useAsync(fn, deps)
  const items = useMemo(() => data ?? (EMPTY as unknown as T[]), [data])
  return { items, loading, error }
}
