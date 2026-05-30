# Web Frontend

Read-only dashboard over the home-security archive. React + Vite + TypeScript,
typed end-to-end from `../api/openapi.json`. See [`docs/web-frontend-stack.md`](../docs/web-frontend-stack.md).

## Run

Requires Node 24 (`.nvmrc`) and pnpm.

```sh
nvm use            # Node 24
pnpm install
```

Start the API first (separate terminal, from `../api`):

```sh
uv run home-security-api      # http://127.0.0.1:8002
```

Then the dev server:

```sh
pnpm dev                       # http://localhost:5173
```

The browser talks to same-origin `/api/*`; Vite proxies that to the API on
`:8002`, so there is no CORS to configure.

## Scripts

| Script           | Purpose                                                         |
| ---------------- | --------------------------------------------------------------- |
| `pnpm dev`       | Dev server + HMR on :5173                                       |
| `pnpm build`     | Type-check (tsgo), then bundle                                  |
| `pnpm preview`   | Serve the production build locally                              |
| `pnpm typecheck` | Type-check only                                                 |
| `pnpm check`     | Format (oxfmt) + lint with autofix (oxlint) — run after editing |
| `pnpm verify`    | `check` + `typecheck` — pre-push gate                           |
| `pnpm gen:api`   | Regenerate `src/api/schema.d.ts` from `../api/openapi.json`     |

## Layout

```text
src/
  main.tsx           React + Router + TanStack Query provider
  index.css          @import "tailwindcss"
  lib/utils.ts       cn() helper
  api/
    schema.d.ts      GENERATED from ../api/openapi.json — do not edit
    client.ts        typed openapi-fetch client
  routes/
    Overview.tsx     /stats/overview
```
