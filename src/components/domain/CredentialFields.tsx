/**
 * A credential form generated from what a connector declares.
 *
 * Nothing here knows about Workday, Jira or anything else. The backend says
 * which fields exist, which are secret, which apply to which authentication
 * method, and where to find each value — this renders that. A new connector
 * becomes connectable without a frontend change, and more importantly the help
 * text lives next to the code that knows why the field exists.
 *
 * The `authMethods` filter matters more than it looks. Workday accepts three
 * authentication methods and two of them have a field labelled "Integration
 * System User" meaning different things. Showing every field at once would put
 * that label on screen twice with no way to tell them apart.
 */
import { AlertCircle, Eye, EyeOff, KeyRound } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import type { CredentialField } from '@/lib/api-live'

const FIELD_CLASS =
  'w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-2.5 py-2 text-[13px] text-[var(--text-primary)] outline-none transition-colors focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--accent)]/10'

/** Which fields apply, given the chosen authentication method. */
export function visibleFields(
  fields: CredentialField[],
  method: string,
): CredentialField[] {
  return fields.filter((f) => !f.authMethods.length || f.authMethods.includes(method))
}

/** Required fields still empty, by label — matching the server's own check. */
export function missingFields(
  fields: CredentialField[],
  values: Record<string, string>,
  method: string,
): string[] {
  const missing = visibleFields(fields, method)
    .filter((f) => f.required && !(values[f.id] ?? '').trim())
    .map((f) => f.label)
  // De-duplicated: two methods can share a label, and the same requirement
  // listed twice reads as a bug rather than as emphasis.
  return Array.from(new Set(missing))
}

function SecretInput({
  field,
  value,
  onChange,
}: {
  field: CredentialField
  value: string
  onChange: (v: string) => void
}) {
  const [shown, setShown] = useState(false)

  /*
   * A stored secret comes back as a bullet string. Treating it as an ordinary
   * value would mean a user who edits any other field re-submits the bullets
   * as the new secret. It is therefore shown as a placeholder-like state that
   * clears the moment they type.
   */
  const isStoredMask = value.startsWith('••')

  return (
    <div className="relative">
      <input
        id={`cred-${field.id}`}
        type={shown && !isStoredMask ? 'text' : 'password'}
        value={value}
        placeholder={field.placeholder || undefined}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => {
          if (isStoredMask) onChange('')
        }}
        autoComplete="off"
        spellCheck={false}
        className={cn(FIELD_CLASS, 'pr-9 font-mono')}
      />
      {!isStoredMask && value ? (
        <button
          type="button"
          onClick={() => setShown((s) => !s)}
          aria-label={shown ? 'Hide value' : 'Show value'}
          className="absolute top-1/2 right-2 -translate-y-1/2 cursor-pointer text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
        >
          {shown ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      ) : null}
    </div>
  )
}

export function CredentialFieldsForm({
  fields,
  values,
  onChange,
  showMissing = false,
  secretsConfigured = true,
}: {
  fields: CredentialField[]
  values: Record<string, string>
  onChange: (id: string, value: string) => void
  /** Highlight empty required fields — only after a failed submit. */
  showMissing?: boolean
  /** False when the server cannot store credentials at all. */
  secretsConfigured?: boolean
}) {
  const method = values.method ?? ''
  const shown = visibleFields(fields, method)

  return (
    <div className="space-y-3">
      {!secretsConfigured ? (
        <p className="flex items-start gap-1.5 rounded-lg border border-[var(--danger-border)] bg-[var(--danger-subtle)] p-2.5 text-[12px] leading-relaxed text-[var(--danger)]">
          <AlertCircle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          <span>
            The server has no encryption key, so credentials cannot be stored. Set{' '}
            <code className="font-mono">MERIDIAN_SECRET_KEY</code> and restart the API.
            Nothing will be saved in plaintext.
          </span>
        </p>
      ) : null}

      {shown.map((field) => {
        const value = values[field.id] ?? ''
        const empty = showMissing && field.required && !value.trim()

        return (
          <div key={field.id}>
            <label
              htmlFor={`cred-${field.id}`}
              className="mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold text-[var(--text-primary)]"
            >
              {field.kind === 'password' ? (
                <KeyRound className="size-3 text-[var(--text-tertiary)]" aria-hidden="true" />
              ) : null}
              {field.label}
              {!field.required ? (
                <span className="font-normal text-[var(--text-tertiary)]">optional</span>
              ) : null}
            </label>

            {field.kind === 'select' ? (
              <div className="space-y-2">
                {field.options.map((option) => (
                  <label
                    key={option.id}
                    className={cn(
                      'flex cursor-pointer items-start gap-2.5 rounded-lg border p-2.5 transition-colors',
                      value === option.id
                        ? 'border-[var(--accent-border)] bg-[var(--accent-subtle)]'
                        : 'border-[var(--border-subtle)] hover:bg-[var(--bg-hover)]',
                    )}
                  >
                    <input
                      type="radio"
                      name={field.id}
                      checked={value === option.id}
                      onChange={() => onChange(field.id, option.id)}
                      className="mt-0.5 size-3.5 accent-[var(--accent)]"
                    />
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium text-[var(--text-primary)]">
                        {option.label}
                      </span>
                      <span className="block text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                        {option.description}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            ) : field.kind === 'password' ? (
              <SecretInput
                field={field}
                value={value}
                onChange={(v) => onChange(field.id, v)}
              />
            ) : field.kind === 'textarea' ? (
              <textarea
                id={`cred-${field.id}`}
                value={value}
                rows={4}
                placeholder={field.placeholder || undefined}
                onChange={(e) => onChange(field.id, e.target.value)}
                spellCheck={false}
                className={cn(FIELD_CLASS, 'font-mono text-[11px]', empty && 'border-[var(--danger-border)]')}
              />
            ) : (
              <input
                id={`cred-${field.id}`}
                value={value}
                placeholder={field.placeholder || undefined}
                onChange={(e) => onChange(field.id, e.target.value)}
                spellCheck={false}
                className={cn(FIELD_CLASS, empty && 'border-[var(--danger-border)]')}
              />
            )}

            {/* Where to find the value, in the source system's own words. This
                is the difference between a form someone can complete and one
                they have to ask an implementation partner about. */}
            {field.help ? (
              <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                {field.help}
              </p>
            ) : null}

            {empty ? (
              <p className="mt-1 text-[11px] text-[var(--danger)]">
                {field.label} is required.
              </p>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
