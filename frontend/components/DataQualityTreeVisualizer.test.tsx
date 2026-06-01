import { describe, expect, it } from "vitest";

import {
  buildVisualizerElements,
  countExplicit,
} from "./DataQualityTreeVisualizer";
import type { DqClusterTree } from "@/lib/api";

const baseLeaf = {
  bucket: "Contact" as const,
  is_important: false,
  weight: 0.5,
  is_conflict: true,
  variants: [
    {
      normalized: "ar@example.com",
      raw: "ar@example.com",
      raw_examples: [],
      member_count: 1,
    },
    {
      normalized: "ar2@example.com",
      raw: "ar2@example.com",
      raw_examples: [],
      member_count: 1,
    },
  ],
  auto_pick: null,
};

function scalarTree(emailChosenExplicit: boolean): DqClusterTree {
  return {
    cluster_fingerprint: "fp",
    root_column_a: "name",
    root_column_b: "company",
    root_display_name: "name / company",
    root_value: "Acme Robotics",
    root_is_conflict: false,
    root_variants: [],
    root_chosen_is_explicit: false,
    groups: [
      {
        bucket: "Contact",
        leaves: [
          {
            ...baseLeaf,
            column_a: "email",
            column_b: "contact_email",
            display_name: "email / contact_email",
            chosen: emailChosenExplicit ? "ar@example.com" : null,
            chosen_is_explicit: emailChosenExplicit,
          },
        ],
      },
      {
        // City leaf — auto-picked, never appears in the explicit-only graph.
        bucket: "Other",
        leaves: [
          {
            column_a: "city",
            column_b: "city",
            display_name: "city",
            bucket: "Other",
            is_important: false,
            weight: 0.3,
            is_conflict: false,
            variants: [
              {
                normalized: "san francisco",
                raw: "San Francisco",
                raw_examples: [],
                member_count: 2,
              },
            ],
            auto_pick: "San Francisco",
            chosen: "San Francisco",
            chosen_is_explicit: false,
          },
        ],
      },
    ],
    conflict_count: 1,
    resolved_conflict_count: emailChosenExplicit ? 1 : 0,
    master_record: null,
    tree_version: "1.1.0",
  };
}

describe("buildVisualizerElements (scalar root)", () => {
  it("returns an empty list when no leaf has an explicit pick", () => {
    expect(buildVisualizerElements(scalarTree(false))).toEqual([]);
  });

  it("includes ONLY the explicit-pick leaf and its bucket, plus the root anchor", () => {
    const els = buildVisualizerElements(scalarTree(true));
    const ids = els.map((e) => (e.data as any).id);
    // Root anchor + explicit Contact bucket + email leaf + 2 edges = 5
    expect(ids).toEqual(
      expect.arrayContaining(["root", "bucket::Contact", "leaf::email"]),
    );
    // Auto-picked city must NOT appear in the visualization
    expect(ids).not.toContain("leaf::city");
    expect(ids).not.toContain("bucket::Other");
  });

  it("flags array-pick leaves so the visualizer can style them differently", () => {
    const tree = scalarTree(true);
    // Re-shape the email leaf as an array pick
    tree.groups[0].leaves[0].chosen = ["ar@example.com", "ar2@example.com"];
    const els = buildVisualizerElements(tree);
    const emailNode = els.find(
      (e) => (e.data as any).id === "leaf::email",
    ) as any;
    expect(emailNode.data.arrayPick).toBe(true);
  });
});

describe("buildVisualizerElements (master record)", () => {
  function masterTree(opts: {
    acmeExplicit: boolean;
    brightExplicit: boolean;
  }): DqClusterTree {
    const sub = (
      label: string,
      email: string,
      explicit: boolean,
    ): DqClusterTree => ({
      cluster_fingerprint: "fp-sub",
      root_column_a: "name",
      root_column_b: "name",
      root_display_name: "name",
      root_value: label,
      root_is_conflict: false,
      root_variants: [],
      root_chosen_is_explicit: false,
      groups: [
        {
          bucket: "Contact",
          leaves: [
            {
              column_a: "email",
              column_b: "email",
              display_name: "email",
              bucket: "Contact",
              is_important: false,
              weight: 0.5,
              is_conflict: false,
              variants: [
                {
                  normalized: email,
                  raw: email,
                  raw_examples: [],
                  member_count: 1,
                },
              ],
              auto_pick: email,
              chosen: email,
              chosen_is_explicit: explicit,
            },
          ],
        },
      ],
      conflict_count: 0,
      resolved_conflict_count: explicit ? 1 : 0,
      master_record: null,
      tree_version: "1.1.0",
    });
    return {
      cluster_fingerprint: "fp",
      root_column_a: "name",
      root_column_b: "name",
      root_display_name: "name",
      root_value: ["Acme", "Brightlight"],
      root_is_conflict: true,
      root_variants: [],
      root_chosen_is_explicit: true,
      groups: [],
      conflict_count: 0,
      resolved_conflict_count: 0,
      master_record: {
        tag: "<name-Parent>",
        root_column_a: "name",
        subtrees: [
          { variant_raw: "Acme", subtree: sub("Acme", "a@acme.com", opts.acmeExplicit) },
          {
            variant_raw: "Brightlight",
            subtree: sub("Brightlight", "b@bright.com", opts.brightExplicit),
          },
        ],
      },
      tree_version: "1.1.0",
    };
  }

  it("returns empty when no subtree has an explicit pick", () => {
    expect(
      buildVisualizerElements(
        masterTree({ acmeExplicit: false, brightExplicit: false }),
      ),
    ).toEqual([]);
  });

  it("includes only variant pivots whose subtree has at least one explicit pick", () => {
    const els = buildVisualizerElements(
      masterTree({ acmeExplicit: true, brightExplicit: false }),
    );
    const ids = els.map((e) => (e.data as any).id);
    expect(ids).toContain("master");
    expect(ids).toContain("v0"); // Acme variant
    expect(ids).toContain("v0::leaf::email");
    expect(ids).not.toContain("v1"); // Brightlight skipped (no explicit picks)
  });

  it("namespaces ids per variant so multiple subtrees don't collide", () => {
    const els = buildVisualizerElements(
      masterTree({ acmeExplicit: true, brightExplicit: true }),
    );
    const ids = els.map((e) => (e.data as any).id);
    expect(ids).toContain("v0::leaf::email");
    expect(ids).toContain("v1::leaf::email");
  });
});

describe("countExplicit", () => {
  it("counts only leaves where chosen_is_explicit is true", () => {
    expect(countExplicit(scalarTree(false))).toBe(0);
    expect(countExplicit(scalarTree(true))).toBe(1);
  });
});
