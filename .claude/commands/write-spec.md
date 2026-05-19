Create a new spec file for a feature using spec-driven development.

$ARGUMENTS is the feature description — e.g., "export BCM capability map as CSV" or "add email domain validation to the DQ profile module".

## What this command does

1. **Finds the next spec number** by scanning `specs/*.md` for the highest NNN prefix, then incrementing
2. **Reads** `specs/RULES.md` and `specs/SPEC_TEMPLATE.md` before writing anything
3. **Reads relevant existing code** to understand the current state (models, endpoints, components) — never spec in a vacuum
4. **Writes** `specs/NNN-kebab-case-title.md` filling every section of the template:
   - Problem Statement (the WHY)
   - Requirements (SHALL statements, numbered, atomic)
   - Out of Scope (explicit exclusions)
   - API Contract (typed request/response for every new/changed endpoint)
   - Frontend Behaviour (state transitions, loading, error display)
   - Backend Behaviour (server logic, not internal structure)
   - Acceptance Criteria (one checkbox per requirement)
5. **Self-scores** using the SCORE table:
   - S — Simple (min 4/5): No gold-plating, no future-proofing
   - C — Complete (min 4/5): All requirements and error states defined
   - O — Optimized (min 3/5): Lean contract, no unused fields
   - R — Reviewable (min 4/5): No verbal explanation needed
   - E — Executable (min 4/5): Every SHALL maps to a concrete code action
6. **If total < 20/25 or any dimension below minimum**: revise the spec, fix the gaps, re-score
7. **Sets status to `SCORED`** and prints the spec path + SCORE summary

## Rules enforced
- No implementation code is written — only the spec file
- Spec must pass SCORE (≥ 20/25) before this command completes
- Every new endpoint must have a full typed API contract in §4
- No vague language: no "handle errors appropriately", no "returns the object"

## After this command
- A human reviews and approves the spec (changes status to `APPROVED`)
- Then run `/implement-spec NNN` to build it
