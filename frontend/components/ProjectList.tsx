"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { api, type Project, ApiError } from "@/lib/api";

export default function ProjectList() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listProjects()
      .then(setProjects)
      .catch((e: unknown) => {
        const message =
          e instanceof ApiError ? e.message : "Failed to load projects";
        setError(message);
      });
  }, []);

  return (
    <div className="stack">
      <div className="row-between">
        <h1>Your projects</h1>
        <Link href="/projects/new" className="button-primary">
          + New Project
        </Link>
      </div>

      {error && (
        <div role="alert" className="status error">
          {error}
        </div>
      )}

      {projects === null && !error && (
        <div className="status">Loading projects...</div>
      )}

      {projects !== null && projects.length === 0 && (
        <div className="empty-state">
          No projects yet. Create your first to get started.
        </div>
      )}

      {projects !== null && projects.length > 0 && (
        <ul className="project-list">
          {projects.map((p) => (
            <li key={p.id}>
              <Link href={`/projects/${p.id}`} className="project-card">
                <span className="project-name">{p.name}</span>
                <span className="project-meta">
                  {p.project_type.name} &middot; {p.status}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
