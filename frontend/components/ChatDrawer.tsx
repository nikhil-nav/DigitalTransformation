"use client";

import { MessageCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

import ChatPanel from "./ChatPanel";
import ThreadList from "./ThreadList";

const STORAGE_KEY_PREFIX = "dt-chat-drawer:";

export default function ChatDrawer({
  projectId,
  onChatComplete,
}: {
  projectId: number;
  onChatComplete?: () => void;
}) {
  const storageKey = `${STORAGE_KEY_PREFIX}${projectId}`;
  const [open, setOpen] = useState(false);
  const [hasMounted, setHasMounted] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState<number | undefined>(
    undefined,
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(storageKey);
    setOpen(stored === null ? true : stored === "true");
    setHasMounted(true);
  }, [storageKey]);

  useEffect(() => {
    if (!hasMounted || typeof window === "undefined") return;
    window.localStorage.setItem(storageKey, String(open));
  }, [open, hasMounted, storageKey]);

  // Reflect open state on body so layout CSS can reserve room on wide screens.
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.body.dataset.chatDrawer = open ? "open" : "closed";
    return () => {
      delete document.body.dataset.chatDrawer;
    };
  }, [open]);

  // Toggle with the Escape key when open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open chat"
        className={cn(
          "fixed bottom-6 right-6 z-40 inline-flex items-center gap-2 rounded-full bg-[var(--coral)] px-5 py-3 text-sm font-semibold text-white shadow-lg ring-1 ring-black/5 transition-all hover:brightness-95",
          open && "pointer-events-none opacity-0",
        )}
      >
        <MessageCircle className="h-5 w-5" />
        <span>Chat</span>
      </button>

      <aside
        aria-label="Chat panel"
        aria-hidden={!open}
        className={cn(
          "fixed right-0 top-0 z-30 flex h-screen w-full max-w-[28rem] flex-col border-l border-[var(--geyser)] bg-white shadow-2xl transition-transform duration-200 ease-out sm:max-w-[32rem]",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <div className="flex h-full min-h-0 flex-col">
          {open && (
            <ChatPanel
              projectId={projectId}
              threadId={activeThreadId}
              onChatComplete={onChatComplete}
              onClose={() => setOpen(false)}
              headerExtra={
                <ThreadList
                  projectId={projectId}
                  activeThreadId={activeThreadId}
                  onActiveChange={setActiveThreadId}
                />
              }
            />
          )}
        </div>
      </aside>
    </>
  );
}
