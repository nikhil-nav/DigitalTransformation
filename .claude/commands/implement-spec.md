Implement a feature from an approved spec file.

$ARGUMENTS is the spec number or filename — e.g., `003` or `003-dq-email-format-check`.

## Pre-flight checks (run before writing any code)

1. **Find the spec file**: `ls specs/$ARGUMENTS*.md`
2. **Read the spec completely** — every section
3. **Verify status is `APPROVED`**: if status is `DRAFT` or `SCORED`, stop and tell the user the spec needs human approval before implementation
4. **Verify SCORE passed** (total ≥ 20/25): if the SCORE table is missing or below threshold, stop and run `/write-spec` to fix it first
5. **Read all files that will be changed** before touching them

If any check fails, halt and explain what needs to happen before implementation can proceed.

## Implementation order

### Backend first (if spec has API contract)
1. Add/update Pydantic schemas in `backend/app/schemas.py`
2. Add/update ORM models in `backend/app/models.py` if new DB columns needed
3. Implement the domain logic in the appropriate module (`bcm.py`, `data_quality/*.py`, etc.) — keep it thin and testable
4. Add the endpoint to the appropriate router — thin wrapper calling domain logic
5. Register new routers in `backend/app/main.py`
6. Write tests in `backend/tests/test_<module>.py` — one test per acceptance criterion
7. Run `cd backend && pytest` — must be green before touching frontend

### Frontend second
8. Implement the UI behaviour described in §5 of the spec
9. Use only what the API contract defines — no extra fields, no undocumented endpoints
10. Write a `ComponentName.test.tsx` for any new component
11. Run `cd frontend && npm run test`

## Constraints (enforce during implementation)
- **Implement only what the spec says** — no extra fields, no bonus features, no "while I'm here" improvements
- **API shape must exactly match §4** — no deviations; if a deviation is needed, stop and amend the spec first
- **No over-engineering**: if the spec says one endpoint, write one endpoint; if it needs a simple loop, no need for a strategy pattern
- **No new dependencies** unless the spec explicitly requires a capability the existing stack cannot provide

## When done
- Update spec status to `IN_PROGRESS` at start, `DONE` when all acceptance criteria in §7 are checked off
- Run both backend and frontend tests one final time
- Report which acceptance criteria passed and which (if any) need follow-up
