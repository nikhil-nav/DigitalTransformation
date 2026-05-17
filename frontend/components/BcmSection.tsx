"use client";

import { GitBranch, KanbanSquare } from "lucide-react";
import { useEffect, useState } from "react";

import BcmGraph from "./BcmGraph";
import ChatDrawer from "./ChatDrawer";
import KanbanBoard from "./KanbanBoard";

import { cn } from "@/lib/utils";

type View = "board" | "graph";

const STORAGE_KEY_PREFIX = "dt-bcm-view:";

export default function BcmSection({ projectId }: { projectId: number }) {
  const storageKey = `${STORAGE_KEY_PREFIX}${projectId}`;
  const [refreshKey, setRefreshKey] = useState(0);
  const [view, setView] = useState<View>("board");
  const [hasMounted, setHasMounted] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(storageKey);
    if (stored === "graph" || stored === "board") setView(stored);
    setHasMounted(true);
  }, [storageKey]);

  useEffect(() => {
    if (!hasMounted || typeof window === "undefined") return;
    window.localStorage.setItem(storageKey, view);
  }, [view, hasMounted, storageKey]);

  return (
    <>
      <div className="mb-3 inline-flex rounded-md border border-[var(--geyser)] bg-white p-0.5">
        <TabButton
          icon={<KanbanSquare className="h-3.5 w-3.5" />}
          label="Board"
          active={view === "board"}
          onClick={() => setView("board")}
        />
        <TabButton
          icon={<GitBranch className="h-3.5 w-3.5" />}
          label="Graph"
          active={view === "graph"}
          onClick={() => setView("graph")}
        />
      </div>
      {view === "board" ? (
        <KanbanBoard projectId={projectId} refreshKey={refreshKey} />
      ) : (
        <BcmGraph projectId={projectId} refreshKey={refreshKey} />
      )}
      <ChatDrawer
        projectId={projectId}
        onChatComplete={() => setRefreshKey((k) => k + 1)}
      />
    </>
  );
}

function TabButton({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded border-0 px-3 py-1 text-sm font-medium transition-colors",
        active
          ? "bg-[var(--coral)] text-white"
          : "bg-transparent text-[var(--slate)] hover:bg-[var(--fog)] hover:text-[var(--pickled-bluewood)]",
      )}
      aria-pressed={active}
    >
      {icon}
      {label}
    </button>
  );
}
