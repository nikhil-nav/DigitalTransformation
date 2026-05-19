Scaffold a new FastAPI endpoint in the backend.

$ARGUMENTS describes the endpoint — e.g., "GET /api/projects/{id}/export returns project data as CSV".

Steps:
1. Read `backend/app/main.py` to see registered routers and decide which router file to add to
2. If a new Pydantic schema is needed, add it to `backend/app/schemas.py`
3. If a new ORM model is needed, add it to `backend/app/models.py`
4. Implement the endpoint — keep the router function thin; put logic in the domain module
5. If creating a new router file, register it in `main.py`
6. Add a test in the appropriate `backend/tests/test_*.py` file
7. Run `cd backend && pytest` to confirm nothing broke

Patterns to follow:
- Path prefix: `/api/`
- DB session: `Annotated[Session, Depends(get_session)]`
- Return typed Pydantic response models, not raw dicts
- LLM calls via `app/llm/provider.py` only
