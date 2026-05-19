# Spec-Driven Development Rules

## The Prime Rule
**No spec. No code.**

Every feature, endpoint, component, or behaviour change starts with a spec file.
No implementation file is created or modified until the spec exists, is complete,
and has passed its SCORE self-assessment (minimum 20/25).

---

## Spec Numbering
Specs live in `specs/` and are numbered sequentially, zero-padded to three digits:

```
specs/
  001-user-authentication.md
  002-bcm-capability-export.md
  003-dq-email-format-check.md
```

The next spec number = highest existing number + 1.
Never reuse or skip numbers. Never rename a spec file after it is approved.

---

## SCORE Principle

Every spec self-scores itself on five dimensions before it is considered complete.
The agent fills this table honestly — it does not inflate scores to pass.

| Dimension | What it measures | Min to pass |
|-----------|-----------------|-------------|
| **S — Simple** | Is this the minimum solution that satisfies the requirement? No future-proofing, no abstraction for its own sake. | 4 |
| **C — Complete** | Are all requirements, error states, and edge cases explicitly written? Nothing left to "figure out later". | 4 |
| **O — Optimized** | Is the API contract lean? No redundant endpoints, no over-fetching, no unnecessary fields. | 3 |
| **R — Reviewable** | Can any developer on the team implement this without asking a single clarifying question? | 4 |
| **E — Executable** | Does every requirement map directly to a concrete code action? No vague language. | 4 |

**Total minimum: 20 / 25**

If any single dimension is below its minimum, or the total is below 20, the spec
must be revised before implementation begins. The agent states what it must fix.

---

## Spec Lifecycle

```
DRAFT → SCORED → CONTRACT → APPROVED → IN_PROGRESS → DONE
```

| Status | Meaning |
|--------|---------|
| `DRAFT` | Being written; not ready for review |
| `SCORED` | SCORE table filled; total ≥ 20; ready for review |
| `CONTRACT` | API contract section is defined and agreed |
| `APPROVED` | A human has approved — implementation may begin |
| `IN_PROGRESS` | Implementation underway; spec is locked |
| `DONE` | Implemented and tested |

**Spec is locked at `APPROVED`** — requirements cannot change. If scope changes,
open a new spec or explicitly mark sections as amended with a reason.

---

## Contract Rules

Every spec that involves both frontend and backend must have an **API Contract**
section that defines:
- HTTP method + path
- Request body shape (typed, not "object")
- Response body shape (typed, with all possible status codes)
- Who owns each side (Frontend / Backend / Both)

The contract is the single source of truth. Frontend and backend implement to it
independently. No contract means no split work.

---

## Anti-Patterns (Forbidden)
- Writing code "temporarily" before a spec exists
- Specs that say "handle errors appropriately" (too vague — be specific)
- Specs that describe how code is structured internally (specs describe behaviour, not implementation)
- Adding fields to the contract "just in case"
- Changing a spec after `APPROVED` without creating an amendment note
