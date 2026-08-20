# Meridian — frontend base

The system of record for enterprise change. This repository currently contains
the **frontend only**, built against a mock data layer. No backend exists yet.

> Every change to your systems — who asked for it, what it actually means
> against your real configuration, what evidence proves it works, who signed
> off, and what it cost — in one auditable chain.

## Running it

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # typecheck + production build
npm run lint
```

## What is real and what is fake

| Layer | State |
|---|---|
| Screens, navigation, routing | Real, complete |
| Components, theming, a11y | Real, complete |
| Filtering, sorting, tabs, drawers, modals, toasts | Real, working client-side |
| Data | **Mock** — static fixtures in `src/lib/mock-data.ts` |
| Network | **Mock** — `src/lib/api.ts` resolves promises after a short delay |
| Auth, persistence, agents, ingestion | Not built |

The mock API deliberately delays so loading skeletons, empty states and error
paths are exercised rather than decorative.

## Swapping in a backend

Every component talks to `src/lib/api.ts` and nothing else. To go live, replace
the bodies of those functions with real calls. Component code should not change.

```
src/lib/types.ts      ← the contract. Backend responses must match these shapes.
src/lib/api.ts        ← the only place that knows how data is fetched.
src/lib/mock-data.ts  ← delete once the backend exists.
```

`useAsync` / `useAsyncList` in `src/lib/useAsync.ts` are intentionally minimal.
When a real backend lands, replace them with TanStack Query for caching,
retries and invalidation.

## Product concepts encoded in the UI

The interface is opinionated about a few things. These are deliberate and worth
preserving if the design changes.

**Verified vs asserted evidence.** `EvidenceGrade` in `types.ts` distinguishes a
deterministic, replayable test with attached artifacts (`verified`) from an
agent's one-off claim (`asserted`). An approval gate carrying
`requiresEvidenceGrade: 'verified'` cannot be satisfied by an assertion, and the
UI shows the two with different icons and words, never colour alone.

**Links are hypotheses.** Graph edges carry a `LinkConfidence` and are drawn with
distinct dash patterns as well as colours. Nothing inferred is presented as
fact, and confirming a link is a recorded action that improves later analysis.

**Blind spots are declared.** Impact analyses list what Meridian *could not*
reason about, and every evidence run carries an environment fingerprint
including data coverage, so nobody mistakes a sandbox pass for production proof.

**No unfalsifiable metrics.** The analytics screen reports measured values only
and explicitly documents which metrics are excluded and why. There is no
"hours saved" headline, because the counterfactual cannot be observed.

**Advisory mode.** The UI states throughout that Meridian holds read-only access.
Write access is a per-platform grant and itself an audited change.

**Ingestion is staged, not binary.** `IngestJob.stage` runs queued → uploading →
parsing → extracting → linking → ready, because each step can partially fail: a
PDF may parse but yield no requirements, a repo may index but resolve no links
to the business layer. Surfacing the stage — plus `parseCoverage` and per-file
warnings — is what lets someone see *why* the graph looks thin instead of
assuming it is complete.

**Workspaces and projects.** A workspace is a governance boundary — a business
unit or regulated entity — and carries the compliance regime that its policies
and approval gates enforce. A project sits inside one and scopes the working
set: connected sources, in-flight requirements, spend. Scope lives in
`src/lib/workspace.tsx` above the router, because every screen is filtered by
it; the switcher is in the sidebar and the full view is at `/projects`.

## Structure

```
src/
  components/
    domain/status.tsx      status pills — the single source of truth for how
                           grades, confidence and decisions are rendered
    layout/                AppShell (nav + topbar), ScopeSwitcher, PageHeader,
                           theme provider
    ui/                    primitives (Button, Card, StatTile, Sparkline,
                           Segmented, SearchInput …), DataTable, overlays
  lib/
    api.ts  types.ts  mock-data.ts  useAsync.ts  utils.ts  workspace.tsx
  pages/                   one file per route
```

Routes are code-split; the initial bundle is ~344 kB (107 kB gzip), with recharts
isolated to the analytics route.

## Design system

Data-dense dashboard style, driven from a reference the product owner supplied.
Its defining traits, all encoded in `src/index.css`:

- **One typeface.** Inter, and nothing else. Technical strings (ids, paths,
  hashes) use `font-mono`, which still resolves to Inter but switches on tabular
  figures and slightly open tracking — a texture change, not a second family.
- **Near-black primary.** The interactive colour is `#1c1c1c` (inverted to
  near-white in dark mode) rather than a brand hue. That frees the entire
  chromatic range to mean status and nothing else, which is what a governance
  console needs — orange can only ever mean "warning".
- **Canvas vs surface.** `--bg-base` is a light grey and `--bg-surface` is
  white, so cards read as raised panels. Keeping them the same value makes the
  page collapse into one flat sheet.
- **Borders, not shadows.** Hierarchy comes from `--border-subtle` and tonal
  steps; shadows are reserved for genuinely floating layers (popovers, modals).
- **Full-bleed shell.** The app fills the viewport; sidebar and top bar are
  white chrome, the scrolling content area is the grey canvas.

Components reference semantic tokens (`--accent`, `--ok`, `--warn`, …) defined
per theme. Light and dark are authored as separate palettes, not inverted values.

The original generated system is kept at
[docs/design-system/MASTER.md](docs/design-system/MASTER.md) for reference.

### Two traps worth knowing

1. Do not define named `--spacing-<name>` keys in the `@theme` block. In
   Tailwind v4 that namespace also backs the named width utilities, so a token
   like `--spacing-2xl: 3rem` silently makes `max-w-2xl` resolve to 48px. The
   container scale is declared explicitly in `src/index.css` for this reason.
2. A `*/` inside a CSS comment in `@theme` terminates the comment early and
   corrupts the whole block — the build error points at the wrong line.

## Accessibility

Verified in-browser across all routes in light, dark and at 375px:

- Skip link, visible focus rings, logical tab order
- Focus trap and restore in modals and drawers, Escape to close
- `aria-sort` on sortable columns, arrow-key navigation on tab lists
- Toasts announced via `aria-live="polite"` without stealing focus
- Status conveyed by icon and text, never colour alone
- `prefers-reduced-motion` honoured globally
- No horizontal scroll at mobile width

## Known gaps

- The graph layout is a hand-written force simulation in
  `src/lib/useForceLayout.ts`. It settles once on mount and is fine for tens of
  nodes; past a few hundred it needs d3-force in a worker plus canvas rendering
  and viewport culling.
- Uploads are simulated. `api.uploadArtifact` streams staged progress but never
  touches the network, and no file content is read.
- Search in the topbar is decorative.
- The chat composer returns a canned reply from `api.sendMessage`.
- No tests. The verification described above was done by driving the built app
  with Playwright, not by a committed suite.
