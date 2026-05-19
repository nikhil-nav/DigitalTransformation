Review the current uncommitted or recently committed changes for correctness, security, and consistency with the platform's architecture.

If $ARGUMENTS specifies a commit hash or file path, scope the review to that. Otherwise review `git diff HEAD`.

Steps:
1. Run `git diff HEAD` (or `git show $ARGUMENTS`) to get the diff
2. For each changed file, read the surrounding context if needed
3. Check against these platform-specific concerns:
   - Backend: thin routers, LLM calls via `app/llm/provider.py`, `uv` for deps
   - Frontend: server components by default, CSS custom properties for colors, `/api/*` proxy
   - Security: no secrets in code, ORM-only DB access, file type validation on uploads
   - Tests: new modules/components should have corresponding test files
4. Report findings grouped by: **Critical** (security/data-loss), **Issues** (bugs/broken patterns), **Suggestions** (minor style/consistency)

Provide file:line references for each finding.
