Re-evaluate and re-score an existing spec against the SCORE criteria.

$ARGUMENTS is the spec number or filename — e.g., `002` or `002-bcm-export`.

Use this when a spec was written manually, needs a quality check before approval, or was marked as needing revision.

## Steps

1. Read `specs/RULES.md`
2. Read the full spec file `specs/$ARGUMENTS*.md`
3. Evaluate each SCORE dimension honestly:

   **S — Simple (min 4/5)**
   - Does the solution scope exceed what the requirements strictly need?
   - Are any API fields added "for future use"?
   - Is the number of endpoints the minimum possible?

   **C — Complete (min 4/5)**
   - Does every requirement in §2 have a corresponding acceptance criterion in §7?
   - Are all error states (422, 404, 401, 500) accounted for in the contract?
   - Are edge cases (empty input, duplicate records, missing FK) specified?

   **O — Optimized (min 3/5)**
   - Does every request field get used in the response or stored?
   - Are there redundant endpoints that could be combined without losing clarity?
   - Is the response shape minimal for the frontend's actual needs?

   **R — Reviewable (min 4/5)**
   - Read each requirement: could a developer implement it without asking a question?
   - Are all terms defined (no assumed domain knowledge)?
   - Is the frontend behaviour described concretely (specific routes, specific messages)?

   **E — Executable (min 4/5)**
   - Does every "SHALL" statement map to a concrete, testable code action?
   - Is there any vague language like "handle appropriately", "validate correctly", "show an error"?
   - Can each acceptance criterion be written as a pytest or Vitest test?

4. Fill or update the SCORE table in the spec
5. If total < 20 or any dimension < minimum:
   - List every specific gap
   - Propose the exact text that would fix each gap
   - Ask the user to confirm before editing the spec
6. If total ≥ 20 and all minimums met:
   - Update status to `SCORED`
   - Print the SCORE table and confirm the spec is ready for human approval
