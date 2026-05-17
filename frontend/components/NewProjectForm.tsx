"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { api, ApiError, type ProjectType } from "@/lib/api";

export default function NewProjectForm() {
  const router = useRouter();
  const [types, setTypes] = useState<ProjectType[] | null>(null);
  const [selectedCode, setSelectedCode] = useState<string>("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api
      .listProjectTypes()
      .then((ts) => {
        setTypes(ts);
        const active = ts.find((t) => t.is_active);
        if (active) setSelectedCode(active.code);
      })
      .catch((e: unknown) => {
        const message =
          e instanceof ApiError ? e.message : "Failed to load project types";
        setError(message);
      });
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!selectedCode) return;
    setSubmitting(true);
    setError(null);
    try {
      const project = await api.createProject({
        name: name.trim(),
        description: description.trim() || null,
        project_type_code: selectedCode,
      });
      router.push(`/projects/${project.id}`);
      router.refresh();
    } catch (e: unknown) {
      const message =
        e instanceof ApiError ? e.message : "Failed to create project";
      setError(message);
      setSubmitting(false);
    }
  }

  return (
    <div className="stack">
      <Link href="/" className="back-link">
        &larr; All projects
      </Link>
      <div className="card">
        <h1>New project</h1>
        {types === null && !error && <div className="status">Loading...</div>}

        {types !== null && (
          <form onSubmit={handleSubmit} aria-label="new project form">
            <fieldset>
              <legend>Project type</legend>
              <div className="type-grid">
                {types.map((t) => {
                  const tooltip = t.is_active
                    ? undefined
                    : "Not available in the MVP";
                  return (
                    <label
                      key={t.code}
                      className={
                        t.is_active ? "type-option" : "type-option disabled"
                      }
                      title={tooltip}
                    >
                      <input
                        type="radio"
                        name="project_type_code"
                        value={t.code}
                        checked={selectedCode === t.code}
                        onChange={() => setSelectedCode(t.code)}
                        disabled={!t.is_active}
                      />
                      <span>{t.name}</span>
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <label>
              Name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={200}
              />
            </label>

            <label>
              Description (optional)
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
              />
            </label>

            {error && (
              <div role="alert" className="status error">
                {error}
              </div>
            )}

            <div className="form-actions">
              <button type="submit" disabled={submitting || !selectedCode}>
                {submitting ? "Creating..." : "Create project"}
              </button>
              <Link href="/" className="link-button">
                Cancel
              </Link>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
