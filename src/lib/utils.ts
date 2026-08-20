import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/*
 * The mock fixtures carry hardcoded dates around 2026-08-06, and rendering them
 * against the real clock would make a demo drift into "3mo ago" as time passes.
 * So fixture timestamps are still measured against that frozen instant.
 *
 * Real backend timestamps must not be: measuring a sync from three hours ago
 * against a date days in the past reported it as "just now", which is worse
 * than no timestamp at all. Anything at or after the fixture epoch is treated
 * as live and compared to the actual clock.
 */
const FIXTURE_EPOCH = new Date('2026-08-06T08:30:00Z')

function referenceNow(then: Date): number {
  const real = Date.now()
  return then.getTime() >= FIXTURE_EPOCH.getTime() ? real : FIXTURE_EPOCH.getTime()
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export function relativeTime(iso: string | null): string {
  if (!iso) return 'never'
  const then = new Date(iso)
  const diffMs = referenceNow(then) - then.getTime()
  // A clock skew of a few seconds should not render as "in the future".
  if (diffMs < 0) return 'just now'
  const mins = Math.round(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.round(days / 30)
  return `${months}mo ago`
}

export function daysSince(iso: string | null): number {
  if (!iso) return Infinity
  const then = new Date(iso)
  return Math.floor((referenceNow(then) - then.getTime()) / 86400000)
}

/**
 * Hours remaining until a deadline. Negative once it has passed.
 *
 * Fractional rather than floored so "9h 05m" is expressible — rounding to whole
 * hours here would make a deadline 55 minutes away read as "9h left".
 */
export function hoursUntil(iso: string | null): number {
  if (!iso) return Infinity
  const then = new Date(iso).getTime()
  /*
   * Deadlines are in the future, so `referenceNow`'s past/future split does not
   * apply. Fixture deadlines sit within a few weeks of the frozen epoch; a
   * live one is measured against the real clock. Beyond that window, treat it
   * as real — a demo deadline is never months out.
   */
  const withinFixtureWindow =
    then - FIXTURE_EPOCH.getTime() < 45 * 86400000 && then >= FIXTURE_EPOCH.getTime() - 45 * 86400000
  const ref = withinFixtureWindow ? FIXTURE_EPOCH.getTime() : Date.now()
  return (then - ref) / 3600000
}

/**
 * A countdown in the reference's idiom: "9h 05m left", "2d 4h left",
 * "6h 40m over".
 *
 * The sign is carried by the word, not a minus: "-6h 40m left" is a puzzle,
 * "6h 40m over" is a statement. Minutes are zero-padded so a column of these
 * stays aligned.
 */
export function formatCountdown(hours: number): string {
  if (!Number.isFinite(hours)) return '—'
  const over = hours < 0
  const total = Math.abs(hours)
  const d = Math.floor(total / 24)
  const h = Math.floor(total % 24)
  const m = Math.floor((total % 1) * 60)

  // Days dominate: at that range the minutes are noise, so show days and hours.
  const body = d > 0 ? `${d}d ${h}h` : `${h}h ${String(m).padStart(2, '0')}m`
  return over ? `${body} over` : `${body} left`
}

export function formatUsd(value: number, opts?: { precise?: boolean }): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: opts?.precise ? 2 : value < 10 ? 2 : 0,
    maximumFractionDigits: opts?.precise ? 2 : value < 10 ? 2 : 0,
  }).format(value)
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US').format(value)
}

export function formatCompact(value: number): string {
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(
    value,
  )
}

export function formatDuration(seconds: number): string {
  if (seconds === 0) return '—'
  if (seconds < 60) return `${seconds}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  if (mins < 60) return secs ? `${mins}m ${secs}s` : `${mins}m`
  const hours = Math.floor(mins / 60)
  return `${hours}h ${mins % 60}m`
}

export function formatHours(hours: number): string {
  if (hours < 24) return `${hours}h`
  const days = Math.round((hours / 24) * 10) / 10
  return `${days}d`
}

export function formatPct(value: number): string {
  return `${value > 0 ? '+' : ''}${value}%`
}

/** Title-case a snake_case enum for display. */
export function humanize(value: string): string {
  return value
    .split(/[_.]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}
