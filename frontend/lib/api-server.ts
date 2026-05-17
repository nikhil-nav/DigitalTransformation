import { cookies } from "next/headers";

import { SESSION_COOKIE } from "./session";
import type { ProjectType } from "./api";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

async function authedHeaders(): Promise<HeadersInit> {
  const cookieStore = await cookies();
  const session = cookieStore.get(SESSION_COOKIE);
  return session ? { Cookie: `${SESSION_COOKIE}=${session.value}` } : {};
}

export async function listProjectTypesServer(): Promise<ProjectType[]> {
  const r = await fetch(`${BACKEND_URL}/api/project-types`, {
    headers: await authedHeaders(),
    cache: "no-store",
  });
  if (!r.ok) return [];
  return (await r.json()) as ProjectType[];
}
