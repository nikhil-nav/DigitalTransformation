"use client";

import {
  AlertTriangle,
  ChevronRight,
  Loader2,
  RotateCcw,
} from "lucide-react";
import { useState } from "react";

import type {
  DqClusterTree,
  DqGoldenValue,
  DqMasterRecordSubtree,
  DqTreeBucket,
  DqTreeGroup,
  DqTreeLeaf,
  DqTreeVariant,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * HTML form-based golden record editor. Replaces clicking-on-Cytoscape-
 * nodes for selection — the user picks per-leaf golden values inline.
 *
 * Layout:
 *   - Scalar root: root leaf prominently, then bucket groups underneath.
 *   - Master Record (US 3.8): the master tag at top + N <details>
 *     subtrees, each with its own root + bucket groups + leaves.
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

const NULL_SENTINEL = "__dq_tree_null__";
const KEEP_ALL_SENTINEL = "__dq_tree_keep_all__";

function variantOptionValue(v: DqTreeVariant): string {
  if (v.raw == null && v.normalized == null) return NULL_SENTINEL;
  return v.raw ?? NULL_SENTINEL;
}

function allVariantRaws(variants: DqTreeVariant[]): Array<string | null> {
  const out = new Set<string | null>();
  for (const v of variants) {
    if (v.raw == null && v.normalized == null) out.add(null);
    else {
      if (v.raw != null) out.add(v.raw);
      for (const r of v.raw_examples) out.add(r);
    }
  }
  return Array.from(out);
}

function keepAllRawList(variants: DqTreeVariant[]): string[] {
  return variants.filter((v) => v.raw != null).map((v) => v.raw as string);
}

function isGoldenArray(v: DqGoldenValue): v is string[] {
  return Array.isArray(v);
}

function renderGoldenValue(v: DqGoldenValue) {
  if (v === null) return <span className="text-[var(--heather)]">(null)</span>;
  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="text-[var(--heather)]">(empty)</span>;
    return <span>{v.join(" · ")}</span>;
  }
  return <span>{v}</span>;
}

export default function DataQualityTreeEditor({
  tree,
  savingColumn,
  onSet,
  onClear,
}: {
  tree: DqClusterTree;
  savingColumn: string | null;
  onSet: (column: string, v: DqGoldenValue) => void;
  onClear: (column: string) => void;
}) {
  if (tree.master_record) {
    return (
      <div className="flex flex-col gap-3">
        {tree.master_record.subtrees.map((st) => (
          <SubtreeBlock
            key={st.variant_raw}
            subtree={st}
            savingColumn={savingColumn}
            onSet={onSet}
            onClear={onClear}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <RootLeaf
        tree={tree}
        saving={savingColumn === tree.root_column_a}
        onSet={(v) => onSet(tree.root_column_a, v)}
        onClear={() => onClear(tree.root_column_a)}
      />
      {tree.groups.map((g) => (
        <Group
          key={g.bucket}
          group={g}
          savingColumn={savingColumn}
          onSet={onSet}
          onClear={onClear}
        />
      ))}
    </div>
  );
}

function SubtreeBlock({
  subtree,
  savingColumn,
  onSet,
  onClear,
}: {
  subtree: DqMasterRecordSubtree;
  savingColumn: string | null;
  onSet: (column: string, v: DqGoldenValue) => void;
  onClear: (column: string) => void;
}) {
  return (
    <details open className="rounded-md border border-[var(--coral)] bg-white">
      <summary className="flex cursor-pointer items-center gap-1 border-b border-[var(--geyser)] bg-[var(--forget-me-not,_#FFF1EE)] px-2 py-1.5 text-xs font-semibold text-[var(--pickled-bluewood)] hover:brightness-95">
        <ChevronRight className="h-3 w-3" />
        <span>Variant:</span>
        <span className="font-mono">{subtree.variant_raw}</span>
      </summary>
      <div className="flex flex-col gap-2 p-2">
        <RootLeaf
          tree={subtree.subtree}
          saving={savingColumn === subtree.subtree.root_column_a}
          onSet={(v) => onSet(subtree.subtree.root_column_a, v)}
          onClear={() => onClear(subtree.subtree.root_column_a)}
        />
        {subtree.subtree.groups.map((g) => (
          <Group
            key={g.bucket}
            group={g}
            savingColumn={savingColumn}
            onSet={onSet}
            onClear={onClear}
          />
        ))}
      </div>
    </details>
  );
}

function RootLeaf({
  tree,
  saving,
  onSet,
  onClear,
}: {
  tree: DqClusterTree;
  saving: boolean;
  onSet: (v: DqGoldenValue) => void;
  onClear: () => void;
}) {
  const synthetic: DqTreeLeaf = {
    column_a: tree.root_column_a,
    column_b: tree.root_column_b,
    display_name: tree.root_display_name,
    bucket: "Important",
    is_important: true,
    weight: 1.0,
    is_conflict: tree.root_is_conflict,
    variants: tree.root_variants,
    auto_pick: null,
    chosen: tree.root_value,
    chosen_is_explicit: tree.root_chosen_is_explicit,
  };
  return (
    <div className="rounded-md border border-[var(--pickled-bluewood)] bg-white p-2">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-[var(--pickled-bluewood)]">
        Root · highest-weight important column
      </div>
      <Leaf leaf={synthetic} saving={saving} onSet={onSet} onClear={onClear} />
    </div>
  );
}

function Group({
  group,
  savingColumn,
  onSet,
  onClear,
}: {
  group: DqTreeGroup;
  savingColumn: string | null;
  onSet: (column: string, v: DqGoldenValue) => void;
  onClear: (column: string) => void;
}) {
  return (
    <details open className="rounded-md border border-[var(--geyser)] bg-white">
      <summary className="flex cursor-pointer items-center gap-1 px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--slate)] hover:bg-[var(--fog)]">
        <ChevronRight className="h-3 w-3" />
        <span aria-hidden="true">{BUCKET_ICON[group.bucket]}</span>
        <span>{group.bucket}</span>
        <span className="ml-auto text-[var(--heather)]">
          {group.leaves.length}
        </span>
      </summary>
      <ul className="flex flex-col divide-y divide-[var(--geyser)]">
        {group.leaves.map((l) => (
          <li key={`${l.column_a}|${l.column_b}`} className="px-2 py-2">
            <Leaf
              leaf={l}
              saving={savingColumn === l.column_a}
              onSet={(v) => onSet(l.column_a, v)}
              onClear={() => onClear(l.column_a)}
            />
          </li>
        ))}
      </ul>
    </details>
  );
}

function Leaf({
  leaf,
  saving,
  onSet,
  onClear,
}: {
  leaf: DqTreeLeaf;
  saving: boolean;
  onSet: (v: DqGoldenValue) => void;
  onClear: () => void;
}) {
  const [customInput, setCustomInput] = useState("");
  const variantValues = allVariantRaws(leaf.variants);

  if (!leaf.is_conflict) {
    return (
      <div>
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-xs font-medium text-[var(--pickled-bluewood)]">
            {leaf.display_name}
            {leaf.is_important && (
              <span
                className="ml-1 rounded-full bg-[var(--marigold)] px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-[var(--pickled-bluewood)]"
                title="important column"
              >
                imp
              </span>
            )}
          </span>
          <span className="text-[10px] text-[var(--heather)]">
            {leaf.variants[0]?.member_count ?? 0} members
          </span>
        </div>
        <div className="mt-0.5 font-mono text-sm">
          {renderGoldenValue(leaf.chosen)}
        </div>
      </div>
    );
  }

  const currentValue = leaf.chosen_is_explicit
    ? isGoldenArray(leaf.chosen)
      ? KEEP_ALL_SENTINEL
      : (leaf.chosen ?? NULL_SENTINEL)
    : "";
  const keepAllList = keepAllRawList(leaf.variants);
  const showKeepAll = keepAllList.length >= 2;

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-[var(--pickled-bluewood)]">
          {leaf.display_name}
          {leaf.is_important && (
            <span
              className="ml-1 rounded-full bg-[var(--marigold)] px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-[var(--pickled-bluewood)]"
              title="important column"
            >
              imp
            </span>
          )}
          <span
            className="ml-1 inline-flex items-center gap-0.5 rounded-full bg-[var(--watermelon)] px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-white"
            title="conflict — pick a golden value"
          >
            <AlertTriangle className="h-2.5 w-2.5" />
            conflict
          </span>
        </span>
        {leaf.chosen_is_explicit && (
          <button
            type="button"
            onClick={onClear}
            disabled={saving}
            className="inline-flex items-center gap-1 rounded text-[10px] text-[var(--slate)] hover:text-[var(--watermelon)] disabled:opacity-50"
          >
            <RotateCcw className="h-3 w-3" /> Reset
          </button>
        )}
      </div>
      {isGoldenArray(leaf.chosen) && (
        <div className="mt-1 flex flex-wrap gap-1 rounded-md bg-[var(--fog)] px-1.5 py-1">
          <span className="text-[10px] uppercase tracking-wide text-[var(--slate)]">
            Keeping {leaf.chosen.length}:
          </span>
          {leaf.chosen.map((v) => (
            <span
              key={v}
              className="rounded-full border border-[var(--geyser)] bg-white px-1.5 py-0.5 font-mono text-[10px] text-[var(--pickled-bluewood)]"
            >
              {v}
            </span>
          ))}
        </div>
      )}
      <fieldset
        className="mt-1 flex flex-col gap-1"
        aria-label={`Pick golden value for ${leaf.display_name}`}
      >
        {leaf.variants.map((v) => {
          const value = variantOptionValue(v);
          return (
            <label
              key={value}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded px-1.5 py-0.5 text-xs hover:bg-[var(--fog)]",
                currentValue === value && "bg-[var(--fog)]",
              )}
            >
              <input
                type="radio"
                name={`golden-${leaf.column_a}`}
                value={value}
                checked={currentValue === value}
                disabled={saving}
                onChange={() =>
                  onSet(value === NULL_SENTINEL ? null : value)
                }
                className="accent-[var(--pickled-bluewood)]"
              />
              <span className="font-mono">
                {v.raw ?? <span className="text-[var(--heather)]">(null)</span>}
              </span>
              <span className="text-[10px] text-[var(--heather)]">
                ({v.member_count})
              </span>
              {v.raw_examples.length > 0 && (
                <span
                  className="text-[9px] text-[var(--heather)]"
                  title={v.raw_examples.join(", ")}
                >
                  +{v.raw_examples.length} similar
                </span>
              )}
            </label>
          );
        })}
        {showKeepAll && (
          <label
            className={cn(
              "flex cursor-pointer items-center gap-2 rounded border border-dashed border-[var(--geyser)] px-1.5 py-0.5 text-xs hover:bg-[var(--fog)]",
              currentValue === KEEP_ALL_SENTINEL && "border-solid bg-[var(--fog)]",
            )}
          >
            <input
              type="radio"
              name={`golden-${leaf.column_a}`}
              value={KEEP_ALL_SENTINEL}
              checked={currentValue === KEEP_ALL_SENTINEL}
              disabled={saving}
              onChange={() => onSet(keepAllList)}
              className="accent-[var(--pickled-bluewood)]"
            />
            <span className="font-medium text-[var(--pickled-bluewood)]">
              Keep all {keepAllList.length} variants
            </span>
          </label>
        )}
      </fieldset>
      <div className="mt-1 flex items-center gap-1">
        <input
          type="text"
          aria-label={`Custom value for ${leaf.display_name}`}
          value={customInput}
          onChange={(e) => setCustomInput(e.target.value)}
          placeholder="Custom value..."
          disabled={saving}
          className="flex-1 rounded border border-[var(--geyser)] bg-white px-1.5 py-0.5 text-xs font-mono"
        />
        <button
          type="button"
          onClick={() => {
            const v = customInput.trim();
            if (v === "") return;
            if (!variantValues.includes(v)) {
              alert(
                `"${v}" is not one of the cluster's variants. Pick from the radios above.`,
              );
              return;
            }
            onSet(v);
            setCustomInput("");
          }}
          disabled={saving || customInput.trim() === ""}
          className="rounded border border-[var(--geyser)] bg-white px-2 py-0.5 text-[10px] text-[var(--pickled-bluewood)] hover:border-[var(--pickled-bluewood)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          Save
        </button>
      </div>
      {saving && (
        <p className="mt-1 flex items-center gap-1 text-[10px] text-[var(--slate)]">
          <Loader2 className="h-3 w-3 animate-spin" /> Saving...
        </p>
      )}
    </div>
  );
}
