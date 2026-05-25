"use client";

import { useEffect, useRef } from "react";

import type {
  DqClusterTree,
  DqGoldenValue,
  DqMasterRecordSubtree,
  DqTreeBucket,
  DqTreeGroup,
  DqTreeLeaf,
} from "@/lib/api";

/**
 * Read-only Cytoscape visualization of the RESOLVED golden record.
 *
 * "Resolved" = leaves whose ``chosen_is_explicit`` is true. Auto-picked
 * leaves and unresolved conflicts are intentionally excluded so the
 * graph reflects only what the user has affirmatively picked.
 *
 * Layout:
 *   - Scalar root tree: shows the root only if the root itself has an
 *     explicit pick; otherwise the root still appears as the anchor so
 *     the user has somewhere to hang the picked leaves.
 *   - Master record: master + each variant pivot; under each variant
 *     only that subtree's explicit-pick leaves.
 *
 * Empty state: when nothing is picked, the graph isn't initialized;
 * the surrounding orchestrator renders a hint to use the Edit tab.
 */

const BUCKET_ICON: Record<DqTreeBucket, string> = {
  Important: "★",
  Identifiers: "#",
  Contact: "✉",
  Address: "⌂",
  Dates: "◷",
  Numeric: "Σ",
  Other: "·",
};

type CyNode = {
  data: {
    id: string;
    label: string;
    kind: "master" | "root" | "variant" | "bucket" | "leaf";
    arrayPick?: boolean;
  };
};
type CyEdge = { data: { id: string; source: string; target: string } };
type CyEle = CyNode | CyEdge;

export default function DataQualityTreeVisualizer({
  tree,
}: {
  tree: DqClusterTree;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const elements = buildVisualizerElements(tree);

  useEffect(() => {
    if (!containerRef.current) return;
    if (elements.length === 0) return;
    let cancelled = false;
    let cy: any = null;
    (async () => {
      const cytoscapeMod = await import("cytoscape");
      const dagreMod = await import("cytoscape-dagre");
      if (cancelled || !containerRef.current) return;
      const cytoscape = cytoscapeMod.default;
      try {
        cytoscape.use(dagreMod.default);
      } catch {
        // already registered
      }
      cy = cytoscape({
        container: containerRef.current,
        elements: elements as any,
        wheelSensitivity: 0.2,
        boxSelectionEnabled: false,
        autounselectify: true,
        style: VIS_STYLES,
        layout: VIS_LAYOUT as any,
      });
    })();
    return () => {
      cancelled = true;
      if (cy) cy.destroy();
    };
  }, [elements]);

  if (elements.length === 0) {
    return (
      <div className="grid h-[420px] place-items-center rounded-md border border-dashed border-[var(--geyser)] bg-white p-4 text-center text-sm text-[var(--heather)]">
        No golden values picked yet.
        <br />
        Use the <strong className="text-[var(--pickled-bluewood)]">Edit</strong>{" "}
        tab to pick attribute values; they'll appear here as they're saved.
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label="Resolved golden record"
      className="h-[420px] rounded-md border border-[var(--geyser)] bg-white"
    />
  );
}

// ---------------------------------------------------------------------------
// Element builder (filtered to explicit-pick leaves only)
// ---------------------------------------------------------------------------

const VIS_LAYOUT = {
  name: "dagre",
  rankDir: "TB",
  nodeSep: 28,
  rankSep: 56,
  edgeSep: 12,
  animate: false,
  fit: true,
  padding: 20,
};

const VIS_STYLES: any[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "font-family":
        '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      "text-valign": "center",
      "text-halign": "center",
      "text-wrap": "wrap",
      "text-max-width": "160px",
      "font-size": 10,
      "background-color": "#ffffff",
      color: "#33475B",
      "border-width": 1,
      "border-color": "#DFE3EB",
      shape: "round-rectangle",
      width: 140,
      height: 32,
      padding: "8px",
    },
  },
  {
    selector: "node[kind = 'master'], node[kind = 'root']",
    style: {
      "background-color": "#33475B",
      color: "#ffffff",
      "border-width": 0,
      "font-size": 12,
      "font-weight": 700,
      width: 180,
      height: 42,
    },
  },
  {
    selector: "node[kind = 'variant']",
    style: {
      "background-color": "#FFF1EE",
      color: "#33475B",
      "border-color": "#FF7A59",
      "border-width": 1.5,
      "font-weight": 600,
      width: 160,
      height: 36,
    },
  },
  {
    selector: "node[kind = 'bucket']",
    style: {
      "background-color": "#EAF0F6",
      color: "#516F90",
      "font-size": 10,
      "font-weight": 600,
      width: 130,
      height: 28,
    },
  },
  {
    selector: "node[kind = 'leaf']",
    style: {
      "background-color": "#ffffff",
      "border-color": "#00BDA5",
      "border-width": 2,
      "font-size": 10,
      width: 170,
      height: 36,
    },
  },
  {
    selector: "node[kind = 'leaf'][?arrayPick]",
    style: {
      "background-color": "#FFF1EE",
      "border-color": "#FF7A59",
    },
  },
  {
    selector: "edge",
    style: {
      width: 1.2,
      "line-color": "#8497ac",
      "curve-style": "taxi",
      "taxi-direction": "downward",
      "taxi-turn": 18,
      "target-arrow-shape": "none",
    },
  },
];

/**
 * Build the Cytoscape elements list filtered to ONLY explicit golden
 * picks. Returns an empty array when nothing is picked anywhere; the
 * caller uses that to switch to the empty-state placeholder.
 *
 * Exported for unit testing — Cytoscape itself doesn't render in jsdom.
 */
export function buildVisualizerElements(tree: DqClusterTree): CyEle[] {
  const explicitInScalarTree =
    !tree.master_record && countExplicit(tree) === 0;
  if (explicitInScalarTree) return [];

  if (tree.master_record) {
    // Count contributing subtrees first — if NONE contributes any
    // explicit pick, return empty so the orchestrator shows the empty
    // state instead of a lonely master node.
    const contributingSubtreesCount = tree.master_record.subtrees.reduce(
      (acc, st) => (countExplicit(st.subtree) > 0 ? acc + 1 : acc),
      0,
    );
    if (contributingSubtreesCount === 0) return [];

    const eles: CyEle[] = [];
    eles.push({
      data: { id: "master", label: tree.master_record.tag, kind: "master" },
    });
    tree.master_record.subtrees.forEach((st, i) => {
      const subExplicit = countExplicit(st.subtree);
      // Skip variant pivots that have no explicit picks under them.
      // The root of each subtree is auto-picked and excluded by design
      // (only EXPLICIT picks appear), so a subtree contributes only if
      // some non-root leaf was picked.
      if (subExplicit === 0) return;
      const variantId = `v${i}`;
      eles.push({
        data: { id: variantId, label: st.variant_raw, kind: "variant" },
      });
      eles.push({
        data: { id: `e-master-${variantId}`, source: "master", target: variantId },
      });
      appendExplicitGroupsAndLeaves(eles, st.subtree.groups, variantId, `v${i}::`);
    });
    return eles;
  }

  // Scalar root path: anchor with the root node (so picked leaves have
  // somewhere to hang), then only explicit-pick leaves.
  const eles: CyEle[] = [];
  eles.push({
    data: {
      id: "root",
      label: scalarRootLabel(tree),
      kind: "root",
    },
  });
  appendExplicitGroupsAndLeaves(eles, tree.groups, "root", "");
  return eles;
}

function appendExplicitGroupsAndLeaves(
  eles: CyEle[],
  groups: DqTreeGroup[],
  parentId: string,
  idPrefix: string,
): void {
  for (const g of groups) {
    const explicitLeaves = g.leaves.filter((l) => l.chosen_is_explicit);
    if (explicitLeaves.length === 0) continue;
    const bucketId = `${idPrefix}bucket::${g.bucket}`;
    eles.push({
      data: {
        id: bucketId,
        label: `${BUCKET_ICON[g.bucket]} ${g.bucket}`,
        kind: "bucket",
      },
    });
    eles.push({
      data: { id: `e-${parentId}-${bucketId}`, source: parentId, target: bucketId },
    });
    for (const l of explicitLeaves) {
      const leafId = `${idPrefix}leaf::${l.column_a}`;
      eles.push({
        data: {
          id: leafId,
          label: leafLabel(l),
          kind: "leaf",
          arrayPick: Array.isArray(l.chosen),
        },
      });
      eles.push({
        data: { id: `e-${bucketId}-${leafId}`, source: bucketId, target: leafId },
      });
    }
  }
}

function scalarRootLabel(tree: DqClusterTree): string {
  return `${tree.root_column_a}: ${formatGolden(tree.root_value)}`;
}

function leafLabel(leaf: DqTreeLeaf): string {
  return `${leaf.display_name}\n${formatGolden(leaf.chosen)}`;
}

function formatGolden(v: DqGoldenValue): string {
  if (v === null) return "(null)";
  if (Array.isArray(v)) {
    if (v.length === 0) return "(empty)";
    return v.join(" · ");
  }
  return v;
}

/**
 * Count leaves with explicit golden picks across one ClusterTree's
 * groups (does NOT recurse into nested master records — those are
 * handled by the caller).
 */
function countExplicit(tree: DqClusterTree): number {
  let n = 0;
  for (const g of tree.groups) {
    for (const l of g.leaves) {
      if (l.chosen_is_explicit) n++;
    }
  }
  return n;
}

// Re-export the helpers used by tests (countExplicit is also useful for
// orchestrator logic that decides whether to enable the Visualize tab).
export { countExplicit };
