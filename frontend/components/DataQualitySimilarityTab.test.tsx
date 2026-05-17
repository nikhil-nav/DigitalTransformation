import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

import DataQualitySimilarityTab from "./DataQualitySimilarityTab";

function json(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const ts = "2026-05-18T12:00:00Z";

const sampleRun = {
  id: 42,
  dataset_id: 4,
  config_id: 1,
  sheet_a: "customers",
  sheet_b: "leads",
  threshold: 0.85,
  status: "done",
  candidate_pair_count: 16,
  passing_pair_count: 3,
  cluster_count: 2,
  blocking_column: "name|company",
  error: null,
  engine_version: "1.0.0",
  started_at: ts,
  finished_at: ts,
};

const sampleClusters = [
  {
    id: 100,
    run_id: 42,
    cluster_index: 0,
    a_member_count: 1,
    b_member_count: 1,
    top_score: 0.97,
    min_score: 0.97,
    canonical_key: { name: "Acme Robotics" },
    a_members: [0],
    b_members: [0],
  },
  {
    id: 101,
    run_id: 42,
    cluster_index: 1,
    a_member_count: 1,
    b_member_count: 2,
    top_score: 0.91,
    min_score: 0.88,
    canonical_key: { name: "Helix Pharmaceuticals" },
    a_members: [2],
    b_members: [2, 3],
  },
];

function makeFetch(overrides: Record<string, () => Response> = {}) {
  const defaults: Record<string, () => Response> = {
    "GET /api/projects/9/dq/datasets/4/similarity/runs": () =>
      json(200, [sampleRun]),
    "GET /api/projects/9/dq/datasets/4/similarity/runs/42/clusters": () =>
      json(200, sampleClusters),
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
  onEditConfig: () => {},
};

describe("DataQualitySimilarityTab", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the empty state when there are no runs", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetch({
        "GET /api/projects/9/dq/datasets/4/similarity/runs": () =>
          json(200, []),
      }),
    );
    render(<DataQualitySimilarityTab {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByText(/no similarity runs yet/i)).toBeInTheDocument(),
    );
  });

  it("renders the latest run summary and cluster rows", async () => {
    vi.stubGlobal("fetch", makeFetch());
    render(<DataQualitySimilarityTab {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByText(/customers/i)).toBeInTheDocument(),
    );
    // Counts from the run summary
    expect(screen.getByText("16")).toBeInTheDocument(); // candidate pairs
    expect(screen.getByText("3")).toBeInTheDocument(); // passing pairs
    // Canonical key for cluster 0
    expect(screen.getByText("Acme Robotics")).toBeInTheDocument();
    expect(screen.getByText("Helix Pharmaceuticals")).toBeInTheDocument();
    // View buttons (one per cluster)
    expect(screen.getAllByRole("button", { name: /view cluster/i })).toHaveLength(
      2,
    );
  });

  it("opens the cluster detail modal when View is clicked", async () => {
    const fetchMock = makeFetch({
      "GET /api/projects/9/dq/datasets/4/similarity/runs/42/clusters/100": () =>
        json(200, {
          cluster: sampleClusters[0],
          pairs: [
            {
              id: 1,
              cluster_id: 100,
              row_a_index: 0,
              row_b_index: 0,
              score: 0.97,
              per_column_scores: { "name|company": 0.97 },
            },
          ],
          a_rows: [{ _row_index: 0, name: "Acme Robotics" }],
          b_rows: [{ _row_index: 0, company: "ACME ROBOTICS INC" }],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<DataQualitySimilarityTab {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByText("Acme Robotics")).toBeInTheDocument(),
    );

    await user.click(
      screen.getAllByRole("button", { name: /view cluster/i })[0],
    );

    // Modal opened
    const dialog = await screen.findByRole("dialog", {
      name: /cluster detail/i,
    });
    expect(within(dialog).getByText("ACME ROBOTICS INC")).toBeInTheDocument();
    // Per-column score breakdown chip rendered inside the dialog (the same
    // value also appears on the cluster row behind the modal — scope to
    // the dialog to disambiguate).
    expect(within(dialog).getByText("0.970")).toBeInTheDocument();
  });

  it("triggers a re-run when Re-run is clicked", async () => {
    const fetchMock = makeFetch({
      "POST /api/projects/9/dq/datasets/4/similarity/run": () =>
        json(200, sampleRun),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<DataQualitySimilarityTab {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByText("Acme Robotics")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /^re-run$/i }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) =>
          (init as RequestInit)?.method === "POST" &&
          (url as string).endsWith("/similarity/run"),
      );
      expect(post).toBeTruthy();
    });
  });

  it("invokes onEditConfig when Edit config is clicked", async () => {
    vi.stubGlobal("fetch", makeFetch());
    const onEditConfig = vi.fn();
    const user = userEvent.setup();
    render(
      <DataQualitySimilarityTab {...baseProps} onEditConfig={onEditConfig} />,
    );
    await waitFor(() =>
      expect(screen.getByText("Acme Robotics")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /edit config/i }));
    expect(onEditConfig).toHaveBeenCalled();
  });
});
