import { cookies } from "next/headers";

export const SESSION_COOKIE: string = "dt_session";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export type SessionUser = { username: string };

/**
 * Read the session cookie from the incoming request and validate it against
 * the backend. Returns the user on success, or null if the cookie is missing
 * or rejected.
 */
export async function getSessionUser(): Promise<SessionUser | null> {
  const cookieStore = await cookies();
  const session = cookieStore.get(SESSION_COOKIE);
  if (!session) return null;

  const r = await fetch(`${BACKEND_URL}/api/auth/me`, {
    headers: { Cookie: `${SESSION_COOKIE}=${session.value}` },
    cache: "no-store",
  });
  if (!r.ok) return null;
  return (await r.json()) as SessionUser;
}
