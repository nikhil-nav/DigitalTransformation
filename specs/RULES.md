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

## Spec Versioning

Every spec file MUST maintain a **Changelog** section (§9) that records every change made after the file is first written.

### Rules

- **On creation:** Add a single entry — `v1.0 | YYYY-MM-DD | Created`.
- **On any edit:** Increment the version, record the date, and write a one-line description of exactly what changed. Never edit a previous entry.
- **Version format:** `vMAJOR.MINOR` — increment MINOR for wording fixes or additions within an existing section; increment MAJOR for requirement additions/removals, scope changes, or API contract changes.
- **Amendment after APPROVED:** A spec locked at APPROVED may only be changed by adding an `AMENDMENT` entry to the changelog explaining what changed and why. The amendment must be approved by a human before implementation resumes.

### Changelog entry format

```
| v1.0 | 2026-05-19 | Initial creation |
| v1.1 | 2026-05-20 | Clarified repository layer import rules in §6 |
| v2.0 | 2026-05-21 | AMENDMENT: Added requirement REQ-16 (logging middleware); approved by @nikhil |
```

The changelog lives at the bottom of every spec file, after the SCORE table (§9).

---

## Module File Naming Convention

All backend module files MUST follow the `{module}.{layer}.py` naming pattern inside the module's own folder:

```
auth/
├── __init__.py          # re-exports public surface (router, *Service, *Repository, schemas)
├── auth.router.py
├── auth.controller.py
├── auth.service.py
├── auth.repository.py
├── auth.models.py
└── auth.schemas.py
```

Because Python cannot import dot-named files via standard `import` syntax, each module's `__init__.py` MUST re-export the public surface using `importlib.import_module` so that all consumers import from the package, never from the dot-named file directly:

```python
# auth/__init__.py  — example
from importlib import import_module as _im
_r = _im("app.auth.auth.router")
router = _r.router
```

This applies to all modules: `auth`, `projects`, `bcm`, `files`, `threads`, `data_quality`, and any future module. The `common/` package follows the same convention (`common.db.py`, `common.exceptions.py`, etc.).

---

## Anti-Patterns (Forbidden)
- Writing code "temporarily" before a spec exists
- Specs that say "handle errors appropriately" (too vague — be specific)
- Specs that describe how code is structured internally (specs describe behaviour, not implementation)
- Adding fields to the contract "just in case"
- Changing a spec after `APPROVED` without creating an amendment note
