"use client";

import { AlertTriangle, CheckCircle2, Inbox, Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  api,
  ApiError,
  type Capability,
  type ItMapApplication,
  type ItMapMapping,
} from "@/lib/api";
import { cn } from "@/lib/utils";

import ITMapAppDrawer from "./ITMapAppDrawer";

export default function ITMapKanban({
  projectId,
  inventoryId,
}: {
  projectId: number;
  inventoryId: number;
}) {
  const [apps, setApps] = useState<ItMapApplication[] | null>(null);
  const [caps, setCaps] = useState<Capability[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drawerAppId, setDrawerAppId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [a, c] = await Promise.all([
        api.listItMapApplications(projectId, inventoryId),
        api.listCapabilities(projectId),
      ]);
      setApps(a);
      setCaps(c);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to load kanban");
    }
  }, [projectId, inventoryId]);

  useEffect(() => {
    void load();
  }, [load]);

  // L2 capabilities are the only valid mapping targets (enforced both
  // in the agent and the user-driven endpoints). Anything else is
  // ignored by the kanban.
  const l2 = useMemo(
    () => (caps ?? []).filter((c) => c.level === 2),
    [caps],
  );

  // Pre-compute card placement: for each L2, the apps with a
  // non-dismissed mapping pointing at it; plus the Unmapped column
  // (apps with zero non-dismissed mappings OR an unmappable_reason).
  const placement = useMemo(() => {
    const byCap = new Map<number, Array<{ app: ItMapApplication; mapping: ItMapMapping }>>();
    const unmapped: ItMapApplication[] = [];
    for (const cap of l2) byCap.set(cap.id, []);
    for (const app of apps ?? []) {
      const active = app.mappings.filter((m) => m.status !== "dismissed");
      if (active.length === 0 || app.unmappable_reason) {
        unmapped.push(app);
        continue;
      }
      // Many-to-many: a single app can appear in every column it's
      // mapped to. Group by capability_id.
      for (const m of active) {
        if (!byCap.has(m.capability_id)) continue; // mapping to non-L2: shouldn't happen
        byCap.get(m.capability_id)!.push({ app, mapping: m });
      }
    }
    // Stable sort within each column: confirmed first, then suggested by
    // descending confidence.
    for (const list of byCap.values()) {
      list.sort((a, b) => {
        if (a.mapping.status !== b.mapping.status) {
          return a.mapping.status === "confirmed" ? -1 : 1;
        }
        return b.mapping.confidence - a.mapping.confidence;
      });
    }
    return { byCap, unmapped };
  }, [apps, l2]);

  if (apps === null || caps === null) {
    return (
      <div className="flex items-center gap-2 px-4 text-sm text-[var(--slate)]">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading kanban...
      </div>
    );
  }
  if (error) {
    return (
      <div role="alert" className="px-4 text-sm text-[var(--watermelon)]">
        {error}
      </div>
    );
  }
  if (l2.length === 0) {
    return (
      <div className="px-4 text-sm text-[var(--heather)]">
        No L2 capabilities defined for this project yet. Use the BCM
        section above to add some, then re-run the IT Map agent.
      </div>
    );
  }

  return (
    <div
      className="flex gap-3 overflow-x-auto px-4 pb-4"
      aria-label="IT Map kanban"
    >
      {l2.map((cap) => {
        const items = placement.byCap.get(cap.id) ?? [];
        return (
          <Column
            key={cap.id}
            title={cap.name}
            count={items.length}
            tone="capability"
          >
            {items.map(({ app, mapping }) => (
              <ApplicationCard
                key={`${cap.id}:${app.id}`}
                app={app}
                mapping={mapping}
                onClick={() => setDrawerAppId(app.id)}
              />
            ))}
            {items.length === 0 && (
              <p className="text-[10px] italic text-[var(--heather)]">
                No applications mapped here yet.
              </p>
            )}
          </Column>
        );
      })}

      <Column
        title="Unmapped"
        count={placement.unmapped.length}
        tone="unmapped"
      >
        {placement.unmapped.map((app) => (
          <ApplicationCard
            key={`u:${app.id}`}
            app={app}
            mapping={null}
            onClick={() => setDrawerAppId(app.id)}
          />
        ))}
        {placement.unmapped.length === 0 && (
          <p className="text-[10px] italic text-[var(--heather)]">
            All applications have at least one mapping.
          </p>
        )}
      </Column>

      {drawerAppId !== null && (
        <ITMapAppDrawer
          projectId={projectId}
          applicationId={drawerAppId}
          l2Capabilities={l2}
          onClose={() => setDrawerAppId(null)}
          onMutated={() => void load()}
        />
      )}
    </div>
  );
}

function Column({
  title,
  count,
  tone,
  children,
}: {
  title: string;
  count: number;
  tone: "capability" | "unmapped";
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "flex w-64 shrink-0 flex-col gap-2 rounded-md border bg-white p-2",
        tone === "unmapped"
          ? "border-[var(--watermelon)]/40"
          : "border-[var(--geyser)]",
      )}
      aria-label={`Capability column: ${title}`}
    >
      <header className="flex items-center justify-between gap-2 border-b border-[var(--geyser)] pb-1">
        <h3 className="m-0 truncate text-sm font-semibold text-[var(--pickled-bluewood)]">
          {tone === "unmapped" && (
            <Inbox className="mr-1 inline h-3 w-3 text-[var(--watermelon)]" />
          )}
          {title}
        </h3>
        <span className="text-[10px] text-[var(--slate)]">{count}</span>
      </header>
      <div className="flex flex-col gap-1.5">{children}</div>
    </section>
  );
}

function ApplicationCard({
  app,
  mapping,
  onClick,
}: {
  app: ItMapApplication;
  mapping: ItMapMapping | null;
  onClick: () => void;
}) {
  const name = app.inferred_name ?? `Row ${app.row_index}`;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Application ${name}`}
      className="flex flex-col gap-1 rounded border border-[var(--geyser)] bg-white px-2 py-1.5 text-left text-xs transition-colors hover:border-[var(--cerulean)]"
    >
      <span className="truncate font-medium text-[var(--pickled-bluewood)]">
        {name}
      </span>
      {mapping ? (
        <span className="flex items-center justify-between gap-1 text-[10px]">
          <StatusBadge status={mapping.status} />
          <span className="font-mono text-[var(--slate)]">
            {mapping.confidence.toFixed(2)}
          </span>
        </span>
      ) : app.unmappable_reason ? (
        <span
          className="line-clamp-2 text-[10px] italic text-[var(--watermelon)]"
          title={app.unmappable_reason}
        >
          {app.unmappable_reason}
        </span>
      ) : (
        <span className="text-[10px] italic text-[var(--heather)]">
          Awaiting review
        </span>
      )}
    </button>
  );
}

function StatusBadge({ status }: { status: ItMapMapping["status"] }) {
  const map = {
    suggested: {
      cls: "bg-[var(--marigold)]/20 text-[var(--pickled-bluewood)]",
      icon: null,
      text: "suggested",
    },
    confirmed: {
      cls: "bg-[var(--jade)]/20 text-[var(--pickled-bluewood)]",
      icon: <CheckCircle2 className="h-2.5 w-2.5" />,
      text: "confirmed",
    },
    dismissed: {
      cls: "bg-[var(--watermelon)]/20 text-[var(--pickled-bluewood)]",
      icon: <AlertTriangle className="h-2.5 w-2.5" />,
      text: "dismissed",
    },
  } as const;
  const { cls, icon, text } = map[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 rounded px-1 py-0.5 uppercase tracking-wide",
        cls,
      )}
    >
      {icon}
      {text}
    </span>
  );
}
