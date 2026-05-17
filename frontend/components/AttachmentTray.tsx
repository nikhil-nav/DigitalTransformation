"use client";

import { File as FileIcon, ImageIcon, Loader2, Paperclip, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, ApiError, type ProjectFile } from "@/lib/api";
import { cn } from "@/lib/utils";

const ACCEPT = "application/pdf,image/png,image/jpeg,image/gif,image/webp";

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

type Props = {
  projectId: number;
  /** Files the user has marked as attached to the next turn. */
  selectedIds: number[];
  /** Anthropic-mode only. */
  enabled: boolean;
  onChange: (ids: number[]) => void;
  /** Bump to force a re-fetch (e.g. after an external upload). */
  refreshNonce?: number;
};

export default function AttachmentTray({
  projectId,
  selectedIds,
  enabled,
  onChange,
  refreshNonce = 0,
}: Props) {
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!enabled) {
      setFiles([]);
      onChange([]);
      return;
    }
    api
      .listFiles(projectId)
      .then(setFiles)
      .catch((e: unknown) => {
        if (e instanceof ApiError) setError(e.message);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, enabled, refreshNonce]);

  async function uploadOne(file: File) {
    setBusy(true);
    setError(null);
    try {
      const row = await api.uploadFile(projectId, file);
      setFiles((prev) => [row, ...prev]);
      onChange([...selectedIds, row.id]);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function uploadMany(list: FileList) {
    for (const f of Array.from(list)) {
      await uploadOne(f);
    }
  }

  async function handleDelete(id: number) {
    setError(null);
    try {
      await api.deleteFile(projectId, id);
      setFiles((prev) => prev.filter((f) => f.id !== id));
      onChange(selectedIds.filter((i) => i !== id));
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Delete failed");
    }
  }

  function toggleSelected(id: number) {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((i) => i !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  }

  if (!enabled) {
    return null;
  }

  const dragHandlers = {
    onDragOver: (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(true);
    },
    onDragLeave: (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
    },
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (e.dataTransfer.files?.length) {
        void uploadMany(e.dataTransfer.files);
      }
    },
  };

  return (
    <div
      {...dragHandlers}
      className={cn(
        "rounded-lg border border-dashed px-3 py-2 transition-colors",
        dragging
          ? "border-[var(--coral)] bg-[var(--forget-me-not)]"
          : "border-[var(--geyser)] bg-white",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-[var(--slate)]">
          Attachments
        </span>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="inline-flex items-center gap-1 rounded-md border border-[var(--geyser)] bg-white px-2 py-0.5 text-xs text-[var(--pickled-bluewood)] transition-all hover:border-[var(--coral)] hover:text-[var(--coral)] disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Paperclip className="h-3 w-3" />
          )}
          <span>{busy ? "Uploading..." : "Add file"}</span>
        </button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            const list = e.target.files;
            if (list?.length) void uploadMany(list);
            e.target.value = "";
          }}
        />
      </div>
      {error && (
        <div role="alert" className="mt-1 text-xs text-[var(--watermelon)]">
          {error}
        </div>
      )}
      {files.length === 0 ? (
        <p className="mt-1 text-xs text-[var(--heather)]">
          Drag a PDF or image here, or click <em>Add file</em>. Tick the ones
          you want the agent to read on your next message.
        </p>
      ) : (
        <ul className="mt-2 flex flex-wrap gap-2">
          {files.map((f) => {
            const Icon = f.kind === "pdf" ? FileIcon : ImageIcon;
            const checked = selectedIds.includes(f.id);
            return (
              <li
                key={f.id}
                className={cn(
                  "group inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
                  checked
                    ? "border-[var(--coral)] bg-[var(--forget-me-not)]"
                    : "border-[var(--geyser)] bg-white",
                )}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleSelected(f.id)}
                  aria-label={`Attach ${f.original_filename}`}
                  className="h-3 w-3 accent-[var(--coral)]"
                />
                <Icon className="h-3 w-3 shrink-0 text-[var(--slate)]" />
                <span
                  className="max-w-[200px] truncate"
                  title={f.original_filename}
                >
                  {f.original_filename}
                </span>
                <span className="text-[10px] text-[var(--heather)]">
                  {fmtSize(f.size_bytes)}
                </span>
                <button
                  type="button"
                  onClick={() => handleDelete(f.id)}
                  aria-label={`Remove ${f.original_filename}`}
                  className="grid h-4 w-4 place-items-center rounded text-[var(--slate)] hover:bg-[var(--fog)] hover:text-[var(--watermelon)]"
                >
                  <X className="h-3 w-3" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
