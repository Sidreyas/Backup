import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * Vendor marks as inline SVG.
 *
 * Drawn rather than fetched: a strict CSP blocks external hosts, and hotlinking
 * a vendor CDN would make this page depend on someone else's uptime to render
 * its own chrome. Inline paths stay sharp at any size and cost no requests.
 *
 * These are simplified marks in each vendor's own brand colour — enough to be
 * recognised at 20px, which is the only job they have here.
 */

const MARKS: Record<string, { node: ReactNode; bg: string }> = {
  /*
   * Workday's mark is a stylised "W". Earlier art tried to spell the wordmark
   * and turned to mush below 32px — at this size a single bold letterform is
   * legible where a five-letter word is not.
   */
  workday: {
    bg: '#0875e1',
    node: (
      <path
        fill="#fff"
        d="M2.6 6.5h3.1l2.1 8.1 2.2-8.1h2.6l2.2 8.1 2.1-8.1h3.1l-3.6 11h-3.1L11 9.9l-1.7 7.6H6.2l-3.6-11Z"
      />
    ),
  },
  sap: {
    bg: '#0faaff',
    node: (
      // The SAP mark is a wordmark in a trapezoid. Rendered as three bold
      // letters, which survives the size reduction; the trapezoid does not.
      <text
        x="12"
        y="16"
        textAnchor="middle"
        fill="#fff"
        fontSize="9.5"
        fontWeight="700"
        fontFamily="Arial, Helvetica, sans-serif"
        letterSpacing="-0.3"
      >
        SAP
      </text>
    ),
  },
  jira: {
    bg: '#2684ff',
    node: (
      <path
        fill="#fff"
        d="M12.5 3 20 10.5a1 1 0 0 1 0 1.4l-7.5 7.5-2.6-2.6 5.5-5.5-5.5-5.6L12.5 3Zm-2.7 2.7L12.4 8.3 6.9 13.9l5.5 5.5-2.6 2.6L2.3 14.5a1 1 0 0 1 0-1.4l7.5-7.4Z"
        opacity=".95"
      />
    ),
  },
  github: {
    bg: '#181717',
    node: (
      <path
        fill="#fff"
        d="M12 2.2a9.8 9.8 0 0 0-3.1 19.1c.5.1.7-.2.7-.5v-1.7c-2.8.6-3.4-1.3-3.4-1.3-.4-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.3 1.1 2.9.8.1-.6.4-1.1.6-1.3-2.2-.3-4.6-1.1-4.6-5 0-1.1.4-2 1-2.7-.1-.3-.4-1.3.1-2.7 0 0 .8-.3 2.7 1a9.4 9.4 0 0 1 5 0c1.9-1.3 2.7-1 2.7-1 .5 1.4.2 2.4.1 2.7.6.7 1 1.6 1 2.7 0 3.9-2.4 4.7-4.6 5 .4.3.7.9.7 1.9v2.8c0 .3.2.6.7.5A9.8 9.8 0 0 0 12 2.2Z"
      />
    ),
  },
  gitlab: {
    bg: '#ffffff',
    node: (
      // The tanuki, as its five-plane fox head.
      <>
        <path fill="#e24329" d="m12 21.2-3.3-10.2h6.6L12 21.2Z" />
        <path fill="#fc6d26" d="M12 21.2 8.7 11H4.1L12 21.2Z" />
        <path fill="#fca326" d="M4.1 11 3.1 14.1a.7.7 0 0 0 .3.8L12 21.2 4.1 11Z" />
        <path fill="#e24329" d="m4.1 11 2-6.2c.1-.3.5-.3.6 0l2 6.2H4.1Z" />
        <path fill="#fc6d26" d="M12 21.2 15.3 11h4.6L12 21.2Z" />
        <path fill="#fca326" d="m19.9 11 1 3.1a.7.7 0 0 1-.3.8L12 21.2 19.9 11Z" />
        <path fill="#e24329" d="m19.9 11-2-6.2c-.1-.3-.5-.3-.6 0l-2 6.2h4.6Z" />
      </>
    ),
  },
  'azure-devops': {
    bg: '#0078d4',
    node: (
      <path
        fill="#fff"
        d="M21 6.3v11.2l-4.6 3.8-7.1-2.6v2.5l-4-5.3 11.8.9V6.9L21 6.3ZM17.2 7 10.4 3v2.7L4.2 7.5 3 9.1v6.6l2.4 1V8.9L17.2 7Z"
      />
    ),
  },
  slack: {
    bg: '#ffffff',
    node: (
      <>
        <path fill="#e01e5a" d="M6.2 14.9a1.8 1.8 0 1 1-1.8-1.8h1.8v1.8Zm.9 0a1.8 1.8 0 0 1 3.6 0v4.6a1.8 1.8 0 0 1-3.6 0v-4.6Z" />
        <path fill="#36c5f0" d="M8.9 6.2a1.8 1.8 0 1 1 1.8-1.8v1.8H8.9Zm0 .9a1.8 1.8 0 0 1 0 3.6H4.3a1.8 1.8 0 0 1 0-3.6h4.6Z" />
        <path fill="#2eb67d" d="M17.6 8.9a1.8 1.8 0 1 1 1.8 1.8h-1.8V8.9Zm-.9 0a1.8 1.8 0 0 1-3.6 0V4.3a1.8 1.8 0 0 1 3.6 0v4.6Z" />
        <path fill="#ecb22e" d="M14.9 17.6a1.8 1.8 0 1 1-1.8 1.8v-1.8h1.8Zm0-.9a1.8 1.8 0 0 1 0-3.6h4.6a1.8 1.8 0 0 1 0 3.6h-4.6Z" />
      </>
    ),
  },
  confluence: {
    bg: '#1868db',
    node: (
      <path
        fill="#fff"
        d="M3.3 16.6c-.3.5-.1 1.1.4 1.3l3.6 2c.5.3 1.1.1 1.4-.4 1.6-2.7 3.1-2.4 5.8-1.1l3.6 1.7c.5.2 1.1 0 1.3-.5l1.7-3.9c.2-.5 0-1-.5-1.3-1.5-.7-4.5-2.1-7.2-2.1-4.3 0-8 2.1-10.1 4.3Zm17.4-9.2c.3-.5.1-1.1-.4-1.3l-3.6-2c-.5-.3-1.1-.1-1.4.4-1.6 2.7-3.1 2.4-5.8 1.1L5.9 3.9c-.5-.2-1.1 0-1.3.5L2.9 8.3c-.2.5 0 1 .5 1.3 1.5.7 4.5 2.1 7.2 2.1 4.3 0 8-2.1 10.1-4.3Z"
      />
    ),
  },
  figma: {
    bg: '#ffffff',
    node: (
      <>
        <path fill="#0acf83" d="M8.5 22a3.5 3.5 0 0 0 3.5-3.5V15H8.5a3.5 3.5 0 0 0 0 7Z" />
        <path fill="#a259ff" d="M5 11.5A3.5 3.5 0 0 1 8.5 8H12v7H8.5A3.5 3.5 0 0 1 5 11.5Z" />
        <path fill="#f24e1e" d="M5 4.5A3.5 3.5 0 0 1 8.5 1H12v7H8.5A3.5 3.5 0 0 1 5 4.5Z" />
        <path fill="#ff7262" d="M12 1h3.5a3.5 3.5 0 0 1 0 7H12V1Z" />
        <path fill="#1abcfe" d="M19 11.5A3.5 3.5 0 0 1 15.5 15 3.5 3.5 0 0 1 12 11.5 3.5 3.5 0 0 1 15.5 8 3.5 3.5 0 0 1 19 11.5Z" />
      </>
    ),
  },
  microsoft: {
    bg: '#ffffff',
    node: (
      <>
        <path fill="#f25022" d="M3 3h8.5v8.5H3V3Z" />
        <path fill="#7fba00" d="M12.5 3H21v8.5h-8.5V3Z" />
        <path fill="#00a4ef" d="M3 12.5h8.5V21H3v-8.5Z" />
        <path fill="#ffb900" d="M12.5 12.5H21V21h-8.5v-8.5Z" />
      </>
    ),
  },
  sharepoint: {
    bg: '#036c70',
    node: (
      <path
        fill="#fff"
        d="M12.8 3a5.2 5.2 0 1 0 0 10.4A5.2 5.2 0 0 0 12.8 3ZM8.4 13.6a4.6 4.6 0 1 0 4.4 5.8 6.2 6.2 0 0 1-4.4-5.8Zm-3.1 5.6a2.4 2.4 0 1 0 2.4 2.4v-.2a5.5 5.5 0 0 1-2.4-2.2Z"
      />
    ),
  },
  servicenow: {
    bg: '#62d84e',
    node: (
      <path
        fill="#032d42"
        d="M12 3.5a8.5 8.5 0 0 0-6.6 13.9c.5.6 1.4.7 2 .2a7 7 0 0 1 9.2 0c.6.5 1.5.4 2-.2A8.5 8.5 0 0 0 12 3.5Zm0 12.2a3.7 3.7 0 1 1 0-7.4 3.7 3.7 0 0 1 0 7.4Z"
      />
    ),
  },
  oracle: {
    bg: '#ffffff',
    node: (
      <path
        fill="#c74634"
        d="M8.3 7.2h7.4a4.8 4.8 0 0 1 0 9.6H8.3a4.8 4.8 0 0 1 0-9.6Zm.1 2.5a2.3 2.3 0 0 0 0 4.6h7.2a2.3 2.3 0 0 0 0-4.6H8.4Z"
      />
    ),
  },
}

/** Which mark to draw for a vendor or product name. */
function markKey(name: string): string | null {
  const n = name.toLowerCase()
  if (n.includes('workday')) return 'workday'
  if (n.includes('sap')) return 'sap'
  if (n.includes('jira')) return 'jira'
  // GitLab before GitHub: neither contains the other, but keeping the git*
  // family adjacent makes the ordering constraint below easier to see.
  if (n.includes('gitlab')) return 'gitlab'
  if (n.includes('github')) return 'github'
  // Before the generic Microsoft check — Azure DevOps is a Microsoft product
  // and would otherwise collapse to the Windows squares.
  if (n.includes('azure') || n.includes('devops')) return 'azure-devops'
  if (n.includes('slack')) return 'slack'
  if (n.includes('confluence')) return 'confluence'
  if (n.includes('figma')) return 'figma'
  if (n.includes('sharepoint')) return 'sharepoint'
  if (n.includes('servicenow')) return 'servicenow'
  if (n.includes('oracle')) return 'oracle'
  // Checked after the specific Microsoft products so SharePoint and Dynamics
  // keep their own marks rather than all collapsing to the Windows squares.
  if (n.includes('dynamics') || n.includes('microsoft')) return 'microsoft'
  return null
}

/**
 * Deterministic fallback tint for anything without a drawn mark — chiefly
 * custom connectors, which by definition have no logo we could ship. Hashed
 * from the name so a given system keeps the same colour across sessions
 * rather than flickering between renders.
 */
const FALLBACK = ['#6d4bd8', '#0f766e', '#b45309', '#be123c', '#1d4ed8', '#4d7c0f']

function fallbackColor(name: string) {
  let h = 0
  for (let i = 0; i < name.length; i += 1) h = (h * 31 + name.charCodeAt(i)) | 0
  return FALLBACK[Math.abs(h) % FALLBACK.length]!
}

export function BrandIcon({
  name,
  size = 'md',
  className,
}: {
  name: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
}) {
  const key = markKey(name)
  const mark = key ? MARKS[key] : null

  const box = size === 'sm' ? 'size-6' : size === 'lg' ? 'size-11' : 'size-9'
  const glyph = size === 'sm' ? 'size-4' : size === 'lg' ? 'size-7' : 'size-6'

  if (!mark) {
    const tint = fallbackColor(name)
    return (
      <span
        className={cn(
          box,
          'flex shrink-0 items-center justify-center rounded-lg text-[13px] font-bold text-white',
          className,
        )}
        style={{ backgroundColor: tint }}
        aria-hidden="true"
      >
        {name.slice(0, 1).toUpperCase()}
      </span>
    )
  }

  /*
   * Marks on a white plate get a hairline border. Slack, Figma, Microsoft and
   * Oracle are multi-colour on white, and without the border they float on a
   * white card with no edge at all.
   */
  const onWhite = mark.bg.toLowerCase() === '#ffffff'

  return (
    <span
      className={cn(
        box,
        'flex shrink-0 items-center justify-center rounded-lg',
        onWhite && 'border border-[var(--border-subtle)]',
        className,
      )}
      style={{ backgroundColor: mark.bg }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 24" className={glyph} role="presentation">
        {mark.node}
      </svg>
    </span>
  )
}
