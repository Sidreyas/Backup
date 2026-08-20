import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

type Theme = 'light' | 'dark'

const ThemeContext = createContext<{
  theme: Theme
  toggle: () => void
  /** Set a specific theme — needed by the appearance picker, which shows
      the current choice rather than just flipping it. */
  setTheme: (t: Theme) => void
}>({
  theme: 'light',
  toggle: () => {},
  setTheme: () => {},
})

export const useTheme = () => useContext(ThemeContext)

function readInitialTheme(): Theme {
  if (typeof document === 'undefined') return 'light'
  // index.html already resolved and applied this before paint.
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(readInitialTheme)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try {
      localStorage.setItem('meridian.theme', theme)
    } catch {
      /* storage unavailable — theme simply won't persist */
    }
  }, [theme])

  const toggle = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), [])
  const value = useMemo(() => ({ theme, toggle, setTheme }), [theme, toggle])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
