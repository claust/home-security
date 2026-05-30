# Web Frontend — Tech Stack Proposal

> Status: **finalized — ready to implement**. Last updated 2026-05-30.
> This document describes the agreed stack for a small, locally-running
> website that presents the home-security archive: queries, drill-downs, and
> dashboards. All stack decisions are settled (see §7); nothing is built yet.

## 1. Goal & scope

A polished, **read-only dashboard** over the existing FastAPI
(`api/`, loopback `:8002`). It is a *curated presentation layer*, not a
general query tool.

- **In scope:** opinionated views — overview/health, device explorer with
  search, per-device timeline + RSSI chart, vendor/service breakdowns,
  "new devices" feed.
- **Out of scope:** ad-hoc SQL and raw table browsing. That is already
  covered by **Datasette** (`tools/home-security-datasette`, `:8001`). We do
  not duplicate it.

Stays loopback-only, consistent with the rest of the stack.

## 2. Architecture

```text
browser ──/api/*──►  Vite dev server (:5173)  ──proxy──►  FastAPI (:8002)
   │                       │
   └── React SPA           └── serves static build in "preview"/prod
```

- The browser talks to **same-origin `/api/*`**; Vite proxies that to
  `127.0.0.1:8002`. This sidesteps CORS entirely. (The API's existing
  `5173` CORS allowlist remains a fallback for direct calls.)
- The SPA is built from **`api/openapi.json`** — types are generated from the
  committed schema, so the frontend cannot drift from the API.

## 3. Stack at a glance

| Concern | Choice | Status | Notes |
| --- | --- | --- | --- |
| Runtime | **Node.js 24** (LTS) | stable | Pinned via `.nvmrc`, `engines`, and `packageManager`. |
| Package manager | **pnpm** | stable | Fast, strict, disk-efficient. Lockfile `pnpm-lock.yaml`. |
| Build tool / dev server | **Vite** | stable | Transpiles via esbuild; HMR; dev proxy to the API. |
| UI library | **React + TypeScript** | stable | |
| Type checker | **tsgo** (`@typescript/native-preview`) | **beta (TS 7.0)** | Type-check only (`tsgo --noEmit`); stable `tsc` kept as fallback. |
| Linter | **oxlint** | stable (v1+) | Rust, ~50–100× ESLint; React + import rules built in. |
| Formatter | **oxfmt** | **alpha** | Rust, Prettier-compatible (~95%); version pinned against churn. |
| Styling | **Tailwind CSS v4** | stable | Utility-first; first-class Vite plugin, no runtime cost. |
| Data fetching | **TanStack Query** | stable | `useInfiniteQuery` maps onto cursor pagination. |
| Typed API client | **openapi-typescript** + **openapi-fetch** | stable | Generates `schema.d.ts` from `api/openapi.json`. |
| Routing | **React Router** | stable | Small surface; a handful of routes, one with an `{address}` param. |
| Component library | **shadcn/ui** | stable | Copy-in Radix + Tailwind components; we own the source; pulled on-demand. |
| Charts | **Observable Plot** | stable | Concise for time-series / RSSI / breakdowns; wrapped in a small React component. (shadcn is used for UI chrome only, not charts.) |

## 4. Proposed layout (`web/`)

```text
web/
  .nvmrc                  # 24
  package.json            # scripts + engines.node>=24 + packageManager (pnpm)
  pnpm-lock.yaml
  vite.config.ts          # :5173, proxy /api -> 127.0.0.1:8002, @tailwindcss/vite
  tsconfig.json
  components.json         # shadcn/ui config (style, aliases, baseColor)
  .oxlintrc.json
  .oxfmtrc.json
  index.html
  README.md               # run instructions (matches hub/ & pi/ convention)
  src/
    main.tsx              # React + Router + TanStack Query provider
    index.css             # @import "tailwindcss"; + optional @theme
    lib/
      utils.ts            # cn() = clsx + tailwind-merge (shadcn helper)
    api/
      schema.d.ts         # GENERATED from ../api/openapi.json — do not edit
      client.ts           # openapi-fetch typed client + query hooks
    routes/
      Overview.tsx        # /stats/overview, /scanners, hourly sparkline
      Devices.tsx         # /addresses — search, sort, infinite scroll
      DeviceDetail.tsx    # /addresses/{addr} + observations timeline + RSSI chart
      Vendors.tsx         # /stats/vendors bar chart
    components/
      ui/                 # shadcn/ui components (copied in, owned by us)
      ...                 # app-specific: chart wrappers, layout
```

## 5. package.json scripts (proposed)

| Script | Command | Purpose |
| --- | --- | --- |
| `dev` | `vite` | Dev server + HMR on :5173 |
| `build` | `tsgo --noEmit && vite build` | Type-check, then bundle |
| `preview` | `vite preview` | Serve the production build locally |
| `typecheck` | `tsgo --noEmit` | Type-check only |
| `fmt` | `oxfmt` | Format (write) |
| `lint` | `oxlint` | Lint (report only) |
| **`check`** | **`oxfmt && oxlint --fix`** | **One-shot: format + lint-with-autofix. The command to run after editing.** |
| `gen:api` | `openapi-typescript ../api/openapi.json -o src/api/schema.d.ts` | Regenerate the typed client from the committed schema |

### 5.1 `pnpm check` — the one command to validate changes

**`pnpm check`** is the single, simple command for both humans and the LLM to
run after touching any code in `web/`. It formats the tree with oxfmt and then
runs oxlint with `--fix`, so one invocation cleans up formatting, auto-fixes
what it can, and prints anything left to resolve. Both tools are Rust-fast, so
it returns near-instantly even on the whole tree.

(Type-checking stays a separate `pnpm typecheck` because tsgo is a different
tool with different output; run it too before a commit, or use a combined
`pnpm verify` = `pnpm check && pnpm typecheck` if we want a single
pre-push gate.)

### 5.2 Git commit hooks

Commits must not introduce format or lint errors. We **extend the repo's
existing `pre-commit` framework** (`.pre-commit-config.yaml`) rather than add a
second hook manager (husky/lint-staged) — one system for the whole repo,
already installed. A `local` hook scoped to `web/` mirrors the mutate-then-fail
pattern the ruff hooks already use:

```yaml
  - repo: local
    hooks:
      - id: web-check
        name: web format + lint (oxfmt + oxlint)
        entry: pnpm -C web check
        language: system
        files: ^web/
        pass_filenames: false
      - id: web-typecheck
        name: web typecheck (tsgo)
        entry: pnpm -C web typecheck
        language: system
        files: ^web/
        pass_filenames: false
```

As with ruff today, if `check` reformats or auto-fixes a file the hook fails
and the change is left staged for review + re-commit. `pnpm` and Node 24 must
be on `PATH` for the `language: system` hooks to run.

## 6. Build milestones

1. **Scaffold + prove the typed pipe** — `web/` skeleton, `gen:api`, Vite
   proxy, and a working **Overview** page rendering live `/stats/overview` +
   `/scanners`. End-to-end typed data on screen.
2. **Device explorer** — paginated, searchable, sortable address table.
3. **Device detail** — observation timeline + RSSI-over-time chart.
4. **Breakdowns** — vendor bar chart, hourly-activity chart, "new devices"
   (recent first-seen) feed.
5. **Docs + a `just`/make target** to run API + web together.

## 7. Decisions (resolved)

All open questions are settled; the stack above is final for v1.

| Question | Decision |
| --- | --- |
| Node runtime | **Node.js 24 (LTS)**, pinned (`.nvmrc` / `engines` / `packageManager`) |
| Formatter | **oxfmt** (no Prettier), version pinned |
| Styling | **Tailwind CSS v4** |
| Component library | **shadcn/ui** (copy-in, on-demand) |
| Charts | **Observable Plot** (shadcn used for chrome only, not charts) |
| Routing | **React Router** |
| `web/` location | **Standalone `web/`** (its own `package.json`, like `api/`/`hub/`/`pi/`) |
| First view to build | **Overview** (proves the typed pipe end-to-end) |
| Type checking | **tsgo** (`--noEmit`), with stable `tsc` retained as fallback |
| Validate command | **`pnpm check`** = `oxfmt && oxlint --fix` (one shot; §5.1) |
| Git hooks | **Extend the existing `pre-commit` framework** with a `web/`-scoped local hook (§5.2) — no husky |

## Sources

- [TypeScript Native Previews announcement](https://devblogs.microsoft.com/typescript/announcing-typescript-native-previews/)
- [`@typescript/native-preview` on npm](https://www.npmjs.com/package/@typescript/native-preview)
- [TypeScript 7.0 Beta Arrives on Go-Based Foundation (Visual Studio Magazine)](https://visualstudiomagazine.com/articles/2026/04/21/typescript-7-0-beta-arrives-on-go-based-foundation-with-10x-speed-claim.aspx)
- [Oxfmt: Migrate from Prettier](https://oxc.rs/docs/guide/usage/formatter/migrate-from-prettier.html)
- [VoidZero Announces Oxfmt Alpha (InfoQ)](https://www.infoq.com/news/2026/01/oxfmt-rust-prettier/)
- [shadcn/ui — Tailwind v4](https://ui.shadcn.com/docs/tailwind-v4)
- [shadcn/ui — React 19](https://ui.shadcn.com/docs/react-19)
</content>
