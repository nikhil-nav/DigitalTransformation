# Digital Transformation Platform - Implementation Plan

A 7-part plan. The user must explicitly approve each completed part before the next begins.

## Canonical architecture (from agents.md, with decisions confirmed in Part 1)

- Two Docker containers managed by `docker compose`: a Next.js frontend container (Node process running `next start`) and a FastAPI backend container.
- FastAPI serves the API under `/api`; Next.js serves all other routes. Routing between the two is handled at the compose level (single ingress port).
- SQLite database stored on a named Docker volume; created on first run if missing.
- `uv` is the Python package manager inside the backend container.
- Auth: httpOnly session cookie issued by FastAPI, in-memory session store. Acceptable for the MVP because there is a single backend instance and only the hardcoded `user`/`password`.

## Test stack

- Backend: pytest
- Frontend unit/integration: Vitest + React Testing Library
- End-to-end: Playwright (drives the running compose stack)

---

## Part 1 - Plan

Goal: Produce this document and a forward-looking `frontend/AGENTS.md`. Get user approval.

Checklist:
- [x] Move root `plan.md` to `docs/PLAN.md` and expand into a detailed plan
- [x] Create `frontend/AGENTS.md` describing the planned frontend
- [ ] User approves Part 1

Tests / success criteria:
- `docs/PLAN.md` covers Parts 1-7, each with a checklist, tests, and success criteria.
- `frontend/AGENTS.md` exists and describes the planned stack, routes, auth model, and testing approach.
- User signs off explicitly before Part 2 begins.

---

## Part 2 - Scaffolding

Goal: `docker compose up` brings up FastAPI and serves a static "hello world" HTML page that calls a real API endpoint and renders the response.

Checklist:
- [ ] Create `backend/` with a FastAPI project managed by `uv` (`pyproject.toml`, `uv.lock`).
- [ ] Implement `app/main.py` exposing `GET /api/health` returning `{"status": "ok"}`.
- [ ] Add a single static HTML page (served by FastAPI in this part only) that fetches `/api/health` and renders the result.
- [ ] Write `backend/Dockerfile` using `uv` for dependency install and a non-root runtime user.
- [ ] Write `docker-compose.yml` defining the backend service and a `dt-data` named volume mounted where the SQLite file will live.
- [ ] Write start/stop scripts: `scripts/start.sh`, `scripts/stop.sh` (POSIX) and `scripts/start.ps1`, `scripts/stop.ps1` (Windows).
- [ ] Configure pytest in the backend; add a test for `/api/health`.

Tests:
- `pytest` in `backend/` passes (`/api/health` returns 200 and `{"status":"ok"}`).
- `scripts/start.ps1` (Windows) and `scripts/start.sh` (Mac/Linux) bring the stack up; visiting the home URL shows the hello-world page.
- The hello-world page renders the live API response, not a hardcoded string (verify by stopping the backend - the page should show an error state).

Success criteria:
- Single command brings the stack up and down cleanly on Mac, Linux, and Windows.
- No errors in `docker compose logs`.
- User approval.

---

## Part 3 - Add Next.js frontend

Goal: Replace the static HTML with a real Next.js app served from its own container. The hello-world call to `/api/health` still works.

Checklist:
- [ ] Create `frontend/` Next.js app (latest stable, TypeScript, app router).
- [ ] Apply the agents.md color palette and Enterprise theme as CSS custom properties / design tokens.
- [ ] Add `frontend/Dockerfile` (production build, `next start`).
- [ ] Add the frontend service to `docker-compose.yml`; configure routing so `/api/*` reaches FastAPI and everything else reaches Next.js.
- [ ] Configure Vitest + React Testing Library; add at least one component test.
- [ ] Configure Playwright with one E2E test that loads `/` and asserts the live API value is rendered.
- [ ] Remove the static HTML that FastAPI served in Part 2.
- [ ] Update `frontend/AGENTS.md` to describe the actual code that now exists.

Tests:
- Vitest unit tests pass.
- Playwright E2E: visiting `/` shows the live `/api/health` value.
- `pytest` in `backend/` still passes.

Success criteria:
- `docker compose up` brings up two containers; the home page renders via Next.js and reads the live API.
- All test suites green.
- User approval.

---

## Part 4 - Fake login

Goal: Visiting `/` redirects to `/login` until the user signs in with `user`/`password`. Logged-in users see a homepage and can log out.

Checklist:
- [ ] Backend: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`. In-memory session store; httpOnly, SameSite=Lax session cookie.
- [ ] Frontend: `/login` page; route gating that redirects unauthenticated visitors to `/login`; a logout action visible on the homepage.
- [ ] Wrong credentials show an inline error and do not create a session.
- [ ] Backend tests: success and failure paths for all three endpoints.
- [ ] Vitest tests for the login form (validation, submission, error display).
- [ ] Playwright test: full flow login -> homepage -> logout -> redirected back to `/login`.

Tests:
- `pytest` covers login (200 + cookie set), wrong creds (401, no cookie), `/me` (with and without cookie), logout (clears session).
- Playwright flow above passes.

Success criteria:
- Unauthenticated users cannot reach the homepage.
- Sessions survive a page reload but not a backend container restart (in-memory store is acceptable for MVP).
- User approval.

---

## Part 5 - Database modeling

Goal: Design the SQLite schema for users, projects, project types, and the Value Discovery payload. Ship the schema as JSON and an architecture doc. Design only - no code in this part.

Checklist:
- [ ] Propose `docs/db-schema.json` covering: `users`, `projects`, `project_types` (Value Discovery active; Business Process Discovery, AI Assessment, Data Quality Assessment seeded as inactive), and the Value Discovery entity (fields proposed in this part, finalized with user).
- [ ] Write `docs/database.md` describing: table-by-table rationale, indices, foreign keys, where the SQLite file lives in the container and on the named volume, how the DB is created on first run, and the migration approach (e.g. Alembic vs. plain SQL on startup).
- [ ] No code changes in this part.

Tests:
- `docs/db-schema.json` is valid JSON.
- `docs/database.md` answers: where the DB file lives, how it is created on first run, how schema changes will be handled, and how multi-user isolation is enforced (foreign key on `user_id`).

Success criteria:
- User approves the schema and the doc.

---

## Part 6 - Backend CRUD

Goal: Real CRUD over Projects (and the Value Discovery payload) for the logged-in user. SQLite created on first run if missing.

Checklist:
- [ ] Implement the schema from Part 5 in code (SQLAlchemy 2.x or equivalent).
- [ ] On startup, create the DB file and tables if missing; seed project types (Value Discovery active, three others inactive).
- [ ] `GET /api/projects`, `POST /api/projects`, `GET /api/projects/{id}`, `PATCH /api/projects/{id}`, `DELETE /api/projects/{id}` - all scoped to the current user.
- [ ] Endpoints for the Value Discovery payload as defined in Part 5.
- [ ] All endpoints require an authenticated session.
- [ ] Backend unit tests: happy paths, validation errors, 401 without session, 404 for projects belonging to another user.

Tests:
- `pytest` covers the matrix above with a fresh in-memory or temp-file SQLite per test.
- DB file is created on first start when missing (verified by deleting the volume and starting clean).

Success criteria:
- All backend tests green.
- User approval.

---

## Part 7 - Wire frontend to backend

Goal: The UI uses the real API. A signed-in user can create, open, edit, and delete a Value Discovery project, with persistence across container restarts.

Checklist:
- [ ] Project list page (uses `GET /api/projects`).
- [ ] New project flow: only Value Discovery is selectable; the other three project types are visible but disabled with a tooltip explaining they are not in the MVP.
- [ ] Project detail / edit page wired to `PATCH`.
- [ ] Delete with confirmation dialog.
- [ ] Loading and error states on every async call.
- [ ] Vitest tests for the new UI.
- [ ] Playwright E2E: login -> create project -> edit -> reload page -> verify persisted -> delete -> verify gone.

Tests:
- All previous test suites still green.
- New Vitest and Playwright tests green.

Success criteria:
- Restarting the stack (`docker compose down && docker compose up`) preserves projects (named volume works).
- A second user (created directly in the DB for now) cannot see the first user's projects.
- User approval - project complete.
