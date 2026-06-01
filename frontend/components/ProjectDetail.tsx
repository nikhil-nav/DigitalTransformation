"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import {
  api,
  ApiError,
  type Project,
  type ProjectStatus,
} from "@/lib/api";
import BcmSection from "./BcmSection";
import DataQualitySection from "./DataQualitySection";
import ITMapSection from "./ITMapSection";

export default function ProjectDetail({ projectId }: { projectId: number }) {
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("draft");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getProject(projectId)
      .then((p) => {
        setProject(p);
        setName(p.name);
        setDescription(p.description ?? "");
        setStatus(p.status);
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) {
          setLoadError("Project not found.");
          return;
        }
        const message =
          e instanceof ApiError ? e.message : "Failed to load project";
        setLoadError(message);
      });
  }, [projectId]);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await api.updateProject(projectId, {
        name: name.trim(),
        description: description.trim() ? description.trim() : null,
        status,
      });
      setProject(updated);
      setEditing(false);
    } catch (e: unknown) {
      setSaveError(e instanceof ApiError ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  function handleCancelEdit() {
    if (!project) return;
    setEditing(false);
    setName(project.name);
    setDescription(project.description ?? "");
    setStatus(project.status);
    setSaveError(null);
  }

  async function handleConfirmDelete() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteProject(projectId);
      router.push("/");
      router.refresh();
    } catch (e: unknown) {
      setDeleteError(e instanceof ApiError ? e.message : "Failed to delete");
      setDeleting(false);
    }
  }

  if (loadError) {
    return (
      <div className="stack">
        <Link href="/" className="back-link">
          &larr; All projects
        </Link>
        <div className="card">
          <div role="alert" className="status error">
            {loadError}
          </div>
        </div>
      </div>
    );
  }

  if (!project) {
    return <div className="status">Loading project...</div>;
  }

  return (
    <div className="stack">
      <Link href="/" className="back-link">
        &larr; All projects
      </Link>

      <div className="card">
        {editing ? (
          <form onSubmit={handleSave} aria-label="edit project form">
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
              Description
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
              />
            </label>
            <label>
              Status
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value as ProjectStatus)}
              >
                <option value="draft">Draft</option>
                <option value="active">Active</option>
                <option value="archived">Archived</option>
              </select>
            </label>
            {saveError && (
              <div role="alert" className="status error">
                {saveError}
              </div>
            )}
            <div className="form-actions">
              <button type="submit" disabled={saving}>
                {saving ? "Saving..." : "Save"}
              </button>
              <button
                type="button"
                className="link-button"
                onClick={handleCancelEdit}
                disabled={saving}
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <>
            <h1>{project.name}</h1>
            <p className="meta">
              {project.project_type.name} &middot; {project.status}
            </p>
            {project.description && <p>{project.description}</p>}
            <div className="form-actions">
              <button type="button" onClick={() => setEditing(true)}>
                Edit
              </button>
              <button
                type="button"
                className="link-button danger"
                onClick={() => {
                  setConfirmingDelete(true);
                  setDeleteError(null);
                }}
              >
                Delete
              </button>
            </div>
          </>
        )}
      </div>

      {project.project_type.code === "value_discovery" && (
        <>
          <BcmSection projectId={projectId} />
          <ITMapSection projectId={projectId} />
        </>
      )}

      {project.project_type.code === "data_quality_assessment" && (
        <DataQualitySection projectId={projectId} />
      )}

      {confirmingDelete && (
        <div
          role="dialog"
          aria-label="Confirm delete"
          aria-modal="true"
          className="modal"
        >
          <div className="card">
            <h2>Delete project?</h2>
            <p>
              This will remove &quot;{project.name}&quot; and any associated
              data.
            </p>
            {deleteError && (
              <div role="alert" className="status error">
                {deleteError}
              </div>
            )}
            <div className="form-actions">
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={deleting}
                className="danger"
              >
                {deleting ? "Deleting..." : "Yes, delete"}
              </button>
              <button
                type="button"
                className="link-button"
                onClick={() => setConfirmingDelete(false)}
                disabled={deleting}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
