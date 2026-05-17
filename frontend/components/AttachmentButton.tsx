"use client";

import { Loader2, Paperclip } from "lucide-react";
import { useRef, useState } from "react";

import { api, ApiError, type ProjectFile } from "@/lib/api";

const ACCEPT = "application/pdf,image/png,image/jpeg,image/gif,image/webp";

export default function AttachmentButton({
  projectId,
  disabled,
  onUploaded,
  onError,
}: {
  projectId: number;
  disabled?: boolean;
  onUploaded: (file: ProjectFile) => void;
  onError?: (message: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  async function handleFiles(list: FileList) {
    setBusy(true);
    try {
      for (const f of Array.from(list)) {
        const row = await api.uploadFile(projectId, f);
        onUploaded(row);
      }
    } catch (e: unknown) {
      onError?.(e instanceof ApiError ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={disabled || busy}
        aria-label="Attach a PDF or image"
        title="Attach a PDF or image"
        className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-[var(--geyser)] bg-white text-[var(--slate)] transition-all hover:border-[var(--coral)] hover:text-[var(--coral)] disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Paperclip className="h-4 w-4" />
        )}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          const list = e.target.files;
          if (list?.length) void handleFiles(list);
          e.target.value = "";
        }}
      />
    </>
  );
}
