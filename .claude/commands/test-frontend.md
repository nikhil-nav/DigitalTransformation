Run the frontend test suite.

If $ARGUMENTS is `e2e` or contains `e2e`, run Playwright E2E tests (`npm run test:e2e`). Otherwise run Vitest unit tests (`npm run test`).

Steps:
1. `cd frontend && npm run test` (or `npm run test:e2e`)
2. Report pass/fail counts and any failures with test name + error

Note: E2E tests require the full Docker stack to be running (`./scripts/start.sh`).
