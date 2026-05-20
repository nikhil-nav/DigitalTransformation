SESSION_COOKIE = "dt_session"

# In-memory session store. Reset on backend restart - acceptable for MVP.
sessions: dict[str, str] = {}
