# SPEC-NNN: Title

**Status:** DRAFT
**Created:** YYYY-MM-DD
**Author:** (agent or human)
**Touches:** Backend | Frontend | Both

---

## 1. Problem Statement

One paragraph. What user problem or system gap does this solve?
No solution language here — just the problem.

---

## 2. Requirements

Numbered, atomic, and testable. Each line must be independently verifiable.

1. The system SHALL ...
2. The system SHALL ...
3. When X occurs, the system SHALL return Y.
4. If Z is missing, the system SHALL respond with HTTP 422 and message "...".

> **Rule:** No "should", "might", or "appropriately". Use SHALL (mandatory) or MAY (optional).

---

## 3. Out of Scope

Explicitly list what this spec does NOT cover. This prevents scope creep.

- ...
- ...

---

## 4. API Contract

> Skip this section if the spec is frontend-only or backend-only with no new endpoints.

### 4.1 Endpoint: METHOD /api/path

**Owner:** Backend implements. Frontend consumes.

**Request**
```json
{
  "field": "string",
  "count": 0
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| field | string | yes | ... |
| count | integer | no | Default: 0 |

**Response — 200 OK**
```json
{
  "id": "uuid",
  "result": "string"
}
```

**Response — 422 Unprocessable Entity**
```json
{ "detail": "human-readable error message" }
```

**Response — 404 Not Found**
```json
{ "detail": "Resource not found" }
```

---

## 5. Frontend Behaviour

Describe what the UI does — state transitions, loading states, error display.
Reference specific components if they already exist.

- On submit: show loading spinner, disable button
- On 200: navigate to /projects/[id]
- On 422: display `detail` message inline below the form field
- On network error: show toast "Something went wrong. Try again."

---

## 6. Backend Behaviour

Describe the server-side logic without prescribing code structure.

- Validate that `field` is non-empty
- Check that referenced resource exists; return 404 if not
- Persist to DB via SQLAlchemy; return the created record

---

## 7. Acceptance Criteria

Checkbox list. Each item maps to a requirement in §2.
Implementation is DONE only when all boxes can be checked.

- [ ] AC-1: Given valid input, endpoint returns 200 with correct shape
- [ ] AC-2: Given missing required field, endpoint returns 422 with descriptive message
- [ ] AC-3: UI displays loading state while request is in flight
- [ ] AC-4: UI navigates to the correct route on success

---

## 8. SCORE Self-Assessment

| Dimension | Score (1–5) | Notes |
|-----------|-------------|-------|
| **S — Simple** | ? | Is this the minimum solution? |
| **C — Complete** | ? | All requirements and errors specified? |
| **O — Optimized** | ? | Lean contract, no redundant fields? |
| **R — Reviewable** | ? | Any dev can implement without questions? |
| **E — Executable** | ? | Every requirement maps directly to code? |
| **Total** | **?/25** | Minimum to proceed: 20/25 |

**Revision needed:** (list gaps if total < 20 or any dimension < minimum)
- ...
