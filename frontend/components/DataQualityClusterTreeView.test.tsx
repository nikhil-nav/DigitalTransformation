import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

// Mock cytoscape + cytoscape-dagre BEFORE importing the visualizer.
// jsdom can't render the canvas Cytoscape needs; we only verify the
// component mounts. The pure element-builder is tested directly via
// the buildVisualizerElements export.
const cyInstance = { on: vi.fn(), destroy: vi.fn() };
const cytoscapeFactory = vi.fn(() => cyInstance);
(cytoscapeFactory as any).use = vi.fn();
vi.mock("cytoscape", () => ({
  __esModule: true,
  default: cytoscapeFactory,
}));
vi.mock("cytoscape-dagre", () => ({
  __esModule: true,
  default: { name: "dagre" },
}));

import DataQualityClusterTreeView, {
  buildExport,
} from "./DataQualityClusterTreeView";
import type { DqClusterTree } from "@/lib/api";

function json(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const sampleTree: DqClusterTree = {
  cluster_fingerprint: "abc",
  root_column_a: "name",
  root_column_b: "company",
  root_display_name: "name / company",
  root_value: "Acme Robotics",
  root_is_conflict: false,
  root_variants: [
    {
      normalized: "acme robotics",
      raw: "Acme Robotics",
      raw_examples: [],
      member_count: 2,
    },
  ],
  root_chosen_is_explicit: false,
  groups: [
    {
      bucket: "Contact",
      leaves: [
        {
          column_a: "email",
          column_b: "contact_email",
          display_name: "email / contact_email",
          bucket: "Contact",
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
          chosen: null,
          chosen_is_explicit: false,
        },
      ],
    },
    {
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
  resolved_conflict_count: 0,
  master_record: null,
  tree_version: "1.1.0",
};

const sampleTreeAfterPick: DqClusterTree = {
  ...sampleTree,
  groups: [
    {
      ...sampleTree.groups[0],
      leaves: [
        {
          ...sampleTree.groups[0].leaves[0],
          chosen: "ar2@example.com",
          chosen_is_explicit: true,
        },
      ],
    },
    sampleTree.groups[1],
  ],
  resolved_conflict_count: 1,
};

const TREE_URL =
  "/api/projects/9/dq/datasets/4/similarity/runs/42/clusters/100/tree";
const GOLDEN_URL = `${TREE_URL}/golden`;

function makeFetch(overrides: Record<string, () => Response> = {}) {
  const defaults: Record<string, () => Response> = {
    [`GET ${TREE_URL}`]: () => json(200, sampleTree),
  };
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url.split("?")[0]}`;
    const o = overrides[key];
    if (o) return o();
    const f = defaults[key];
    if (f) return f();
    throw new Error(`Unmocked fetch ${key}`);
  });
}

const baseProps = {
  projectId: 9,
  datasetId: 4,
  runId: 42,
  clusterId: 100,
};

describe("buildExport", () => {
  it("emits a flat object for a scalar-root tree", () => {
    const exp = buildExport(sampleTree) as Record<string, unknown>;
    expect(exp).toMatchObject({
      name: "Acme Robotics",
      email: null,
      city: "San Francisco",
    });
  });
});

describe("DataQualityClusterTreeView orchestrator", () => {
  beforeEach(() => {
    cytoscapeFactory.mockClear();
    cyInstance.on.mockClear();
    cyInstance.destroy.mockClear();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the header pill and defaults to the Edit sub-tab", async () => {
    vi.stubGlobal("fetch", makeFetch());
    render(<DataQualityClusterTreeView {...baseProps} />);
    await waitFor(() => {
      // Root value appears in both the header pill AND the root leaf body
      expect(screen.getAllByText("Acme Robotics").length).toBeGreaterThan(0);
    });
    // Edit sub-tab is selected by default
    const editTab = screen.getByRole("tab", { name: /^edit$/i });
    expect(editTab).toHaveAttribute("aria-selected", "true");
    // HTML picker is in the DOM (radio for the email conflict leaf)
    expect(
      screen.getByRole("group", { name: /pick golden value for email/i }),
    ).toBeInTheDocument();
  });

  it("switches to Visualize sub-tab and mounts Cytoscape on click", async () => {
    vi.stubGlobal("fetch", makeFetch({ [`GET ${TREE_URL}`]: () => json(200, sampleTreeAfterPick) }));
    const user = userEvent.setup();
    render(<DataQualityClusterTreeView {...baseProps} />);
    // Root value appears in the header pill AND the root-leaf body
    // (read-only single variant). Both are correct — use getAllByText.
    await waitFor(() =>
      expect(screen.getAllByText("Acme Robotics").length).toBeGreaterThan(0),
    );

    await user.click(screen.getByRole("tab", { name: /visualize/i }));
    // Visualizer container is in the DOM (role="img" with aria-label)
    expect(
      screen.getByRole("img", { name: /resolved golden record/i }),
    ).toBeInTheDocument();
    // Cytoscape factory was called now that we're on the visualize tab
    // and the tree has at least one explicit pick.
    await waitFor(() => expect(cytoscapeFactory).toHaveBeenCalled());
  });

  it("shows an empty state in Visualize when no explicit picks exist", async () => {
    vi.stubGlobal("fetch", makeFetch());
    const user = userEvent.setup();
    render(<DataQualityClusterTreeView {...baseProps} />);
    // Root value appears in the header pill AND the root-leaf body
    // (read-only single variant). Both are correct — use getAllByText.
    await waitFor(() =>
      expect(screen.getAllByText("Acme Robotics").length).toBeGreaterThan(0),
    );

    await user.click(screen.getByRole("tab", { name: /visualize/i }));
    expect(
      screen.getByText(/no golden values picked yet/i),
    ).toBeInTheDocument();
    // No Cytoscape canvas mounted
    expect(cytoscapeFactory).not.toHaveBeenCalled();
  });

  it("PUTs the golden value when a conflict radio is selected in Edit", async () => {
    const fetchMock = makeFetch({
      [`PUT ${GOLDEN_URL}`]: () => json(200, sampleTreeAfterPick),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<DataQualityClusterTreeView {...baseProps} />);
    // Root value appears in the header pill AND the root-leaf body
    // (read-only single variant). Both are correct — use getAllByText.
    await waitFor(() =>
      expect(screen.getAllByText("Acme Robotics").length).toBeGreaterThan(0),
    );

    const radio = screen.getByDisplayValue("ar2@example.com");
    await user.click(radio);

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, init]) =>
          (init as RequestInit)?.method === "PUT" &&
          (url as string) === GOLDEN_URL,
      );
      expect(put).toBeTruthy();
      const body = JSON.parse(
        ((put?.[1] as RequestInit).body as string) ?? "{}",
      );
      expect(body.column_name).toBe("email");
      expect(body.chosen_value).toBe("ar2@example.com");
    });
    // Counter updates from the response
    await waitFor(() =>
      expect(screen.getByText(/1 of 1 conflicts resolved/i)).toBeInTheDocument(),
    );
  });

  it("surfaces an error from the GET request", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(500, { detail: "boom" })),
    );
    render(<DataQualityClusterTreeView {...baseProps} />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
  });
});
