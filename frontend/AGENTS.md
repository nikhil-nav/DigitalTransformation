# frontend/AGENTS.md

The Next.js frontend for the Digital Transformation Platform.

## Stack

- Next.js 16 (app router) with TypeScript and Turbopack
- React 19
- Vitest + React Testing Library for unit/integration tests
- Playwright for end-to-end tests

## Layout

```
frontend/
  app/
    layout.tsx                  Root layout, loads globals.css
    globals.css                 Design tokens + page/component styles
    login/page.tsx              Login page (server component); redirects to / if already signed in
    (app)/                      Route group for gated pages
      layout.tsx                Auth gate (redirects to /login) + header
      page.tsx                  Project list at /
      projects/new/page.tsx     New project form
      projects/[id]/page.tsx    Project detail / edit
  components/
    LoginForm.tsx + .test.tsx   POSTs /api/auth/login
    LogoutButton.tsx            POSTs /api/auth/logout
    ProjectList.tsx + .test.tsx List user's projects
    NewProjectForm.tsx + .test.tsx
    ProjectDetail.tsx + .test.tsx
  lib/
    session.ts                  getSessionUser() - server-side cookie validation
    api.ts                      Browser-side typed fetch helpers (Project, ProjectType, ApiError, api.*)
  tests/e2e/
    auth.spec.ts                Playwright: redirect, login, wrong creds, logout
    projects.spec.ts            Playwright: create -> edit -> reload -> delete
  next.config.ts                Sets output: "standalone" and rewrites /api/* to BACKEND_URL
  vitest.config.ts              jsdom env, @ alias, excludes tests/e2e
  playwright.config.ts
  Dockerfile                    Multi-stage; runs the standalone server as a non-root user
```

## Auth model

Session-cookie auth issued by the backend (httpOnly, SameSite=Lax, name `dt_session`). Gating is done in **server components** rather than middleware:

- `app/(app)/layout.tsx` calls `getSessionUser()` (`lib/session.ts`), which reads the request cookie and validates it by calling `BACKEND_URL/api/auth/me`. If invalid, it `redirect("/login")`. This protects every page under the `(app)` group in one place.
- `app/login/page.tsx` does the inverse: redirects to `/` if the cookie is already valid.
- `LoginForm` and `LogoutButton` POST to `/api/auth/login`/`/api/auth/logout`, then `router.push()` + `router.refresh()` to re-run the server component.
- The browser-side `lib/api.ts` helper redirects to `/login` on any 401 from the backend, catching the case where a session is invalidated mid-use (e.g. backend restart wiped the in-memory store).

## Routing model

The Next.js container is the only externally-exposed service. Browser requests for `/api/*` hit Next.js, which uses `rewrites()` in `next.config.ts` to proxy to the backend container at `http://backend:8000`. Everything else is served by Next.js. From component code, you call `fetch("/api/...")` and never think about the backend hostname.

`BACKEND_URL` is read at server boot:
- In `docker-compose.yml`: `BACKEND_URL=http://backend:8000` (Docker DNS)
- In local dev: defaults to `http://localhost:8000`

## Design tokens (from agents.md)

Defined as CSS custom properties on `:root` in `app/globals.css`: `--coral`, `--pickled-bluewood`, `--deep-bluewood`, `--cerulean`, `--jade`, `--marigold`, `--watermelon`, `--slate`, `--heather`, `--fog`, `--geyser`, `--forget-me-not`.

## Routes

- `/login` - login form
- `/` - project list (gated)
- `/projects/new` - create project (gated)
- `/projects/[id]` - project detail / edit (gated)

## Local development

```
npm install
npm run dev          # http://localhost:3000; needs uvicorn running on :8000 for /api/*
npm run test         # Vitest unit tests
npm run build        # production build (also runs tsc)
npm run start        # production server
npm run test:e2e     # Playwright; expects the docker compose stack to be up
```

## Container

`Dockerfile` is a four-stage build (`base`, `deps`, `builder`, `runner`). `next build` produces `.next/standalone` (a self-contained Node server) plus `.next/static` and `public/`; the runner stage copies just those and runs `node server.js` as the unprivileged `app` user on port 3000.

## Coding standards

Per agents.md: no emojis anywhere, keep it simple, no defensive code beyond system boundaries, root-cause fixes only.
