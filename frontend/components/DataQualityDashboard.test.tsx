/**
 * Dashboard tests focus on the layout + interactions we own. The Plotly
 * wrapper is dynamic-imported on mount; rather than try to render it in
 * jsdom (Plotly needs a real DOM), we mock the wrapper to a no-op span so
 * the surrounding KPI strip, tabs, table, drawer, and cross-table actions
 * can be asserted cleanly.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

// Mock PlotlyChart before the dashboard import so the lazy wrapper never
// touches the real Plotly bundle in jsdom.
vi.mock("./PlotlyChart", () => ({
  default: ({ ariaLabel }: { ariaLabel?: string }) => (
    <div data-testid="plotly-chart" aria-label={ariaLabel} />
  ),
}));

import DataQualityDashboard from "./DataQualityDashboard";

function json(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const ts = "2026-05-10T01:23:45Z";

const profile = [
  {
    id: 1,
    sheet_name: "customers",
    row_count: 3,
    column_count: 2,
    exact_duplicate_row_count: 0,
    completeness_pct: 100,
    rag: "green",
    engine_version: "1.0.0",
    computed_at: ts,
    columns: [
      {
        id: 11,
        name: "id",
        ordinal: 0,
        inferred_dtype: "object",
        semantic_type: "integer",
        type_mismatch_count: 0,
        null_count: 0,
        null_pct: 0,
        distinct_count: 3,
        distinct_pct: 100,
        top_values: [
          { value: "1", count: 1 },
          { value: "2", count: 1 },
          { value: "3", count: 1 },
        ],
        numeric_min: 1,
        numeric_max: 3,
        numeric_mean: 2,
        numeric_median: 2,
        numeric_std: 1,
        numeric_p25: 1.5,
        numeric_p75: 2.5,
        date_min: null,
        date_max: null,
        pattern_label: null,
        pattern_conformance_pct: null,
        outlier_iqr_count: 0,
        outlier_mad_count: 0,
        range_min: null,
        range_max: null,
        range_violation_count: null,
        rag: "green",
        computed_at: ts,
      },
      {
        id: 12,
        name: "email",
        ordinal: 1,
        inferred_dtype: "object",
        semantic_type: "string",
        type_mismatch_count: 0,
        null_count: 1,
        null_pct: 33.3,
        distinct_count: 2,
        distinct_pct: 66.7,
        top_values: [
          { value: "a@example.com", count: 1 },
          { value: "b@example.com", count: 1 },
        ],
        numeric_min: null,
        numeric_max: null,
        numeric_mean: null,
        numeric_median: null,
        numeric_std: null,
        numeric_p25: null,
        numeric_p75: null,
        date_min: null,
        date_max: null,
        pattern_label: "email",
        pattern_conformance_pct: 100,
        outlier_iqr_count: null,
        outlier_mad_count: null,
        range_min: null,
        range_max: null,
        range_violation_count: null,
        rag: "amber",
        computed_at: ts,
      },
    ],
  },
  {
    id: 2,
    sheet_name: "orders",
    row_count: 4,
    column_count: 3,
    exact_duplicate_row_count: 0,
    completeness_pct: 100,
    rag: "green",
    engine_version: "1.0.0",
    computed_at: ts,
    columns: [],
  },
];

const issues = [
  {
    id: 101,
    sheet_name: "customers",
    column_name: "email",
    dimension: "completeness",
    severity: "medium",
    description: "email is 33.3% null",
    sample_value_count: 0,
    sample_values: [],
    engine_version: "1.0.0",
    ai_narrative: "Missing emails will break the welcome flow.",
    ai_fix: "Backfill or remove rows without an email.",
    ai_status: "done",
    created_at: ts,
  },
];

const suggestedRelationship = {
  id: 901,
  parent_sheet: "customers",
  parent_column: "id",
  child_sheet: "orders",
  child_column: "customer_id",
  type_match: true,
  name_similarity: 0.5,
  subset_coverage: 1.0,
  cardinality: "many_to_one",
  confidence_pct: 87.5,
  status: "suggested",
  engine_version: "1.0.0",
  suggested_at: ts,
  confirmed_at: null,
  dismissed_at: null,
};

function makeFetch(overrides: Record<string, () => Response> = {}) {
  const defaults: Record<string, () => Response> = {
    "GET /api/projects/11/dq/datasets/7/profile": () => json(200, profile),
    "GET /api/projects/11/dq/datasets/7/issues": () => json(200, issues),
    "GET /api/projects/11/dq/datasets/7/functional-dependencies": () =>
      json(200, []),
    "GET /api/projects/11/dq/datasets/7/relationships": () =>
      json(200, [suggestedRelationship]),
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

describe("DataQualityDashboard", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders KPI strip, sheet tabs, and the columns table", async () => {
    vi.stubGlobal("fetch", makeFetch());
    render(<DataQualityDashboard projectId={11} datasetId={7} />);

    // KPI strip
    await waitFor(() =>
      expect(screen.getByText("Total rows")).toBeInTheDocument(),
    );
    expect(screen.getByText("7")).toBeInTheDocument(); // 3 + 4 rows
    expect(screen.getByText("5")).toBeInTheDocument(); // 2 + 3 cols

    // Sheet tabs both visible
    expect(
      screen.getByRole("button", { name: /customers green/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /orders green/i }),
    ).toBeInTheDocument();

    // Columns table shows the active sheet's columns by name
    expect(screen.getByText("id")).toBeInTheDocument();
    expect(screen.getByText("email")).toBeInTheDocument();
    // pattern label is appended after type
    expect(screen.getByText(/string · email/i)).toBeInTheDocument();
  });

  it("opens the column drawer when a row is clicked", async () => {
    vi.stubGlobal("fetch", makeFetch());
    const user = userEvent.setup();
    render(<DataQualityDashboard projectId={11} datasetId={7} />);

    await waitFor(() => expect(screen.getByText("email")).toBeInTheDocument());

    await user.click(screen.getByText("email"));
    // Drawer header carries the column name
    expect(
      screen.getByRole("dialog", { name: /column email details/i }),
    ).toBeInTheDocument();
    // Issues section shows the AI narrative when present
    expect(
      screen.getByText(/Missing emails will break the welcome flow/i),
    ).toBeInTheDocument();
  });

  it("switches to the Cross-table view and confirms a relationship", async () => {
    const fetchMock = makeFetch({
      "PATCH /api/projects/11/dq/datasets/7/relationships/901": () =>
        json(200, {
          ...suggestedRelationship,
          status: "confirmed",
          confirmed_at: ts,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<DataQualityDashboard projectId={11} datasetId={7} />);

    await waitFor(() =>
      expect(screen.getByText("Total rows")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /^cross-table$/i }));
    // Now the relationship row is visible
    expect(screen.getByText(/orders\.customer_id/i)).toBeInTheDocument();
    expect(screen.getByText(/customers\.id/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^confirm$/i }));

    const patch = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit)?.method === "PATCH",
    );
    expect(patch).toBeTruthy();
    expect(patch![0]).toBe(
      "/api/projects/11/dq/datasets/7/relationships/901",
    );
    expect(JSON.parse((patch![1] as RequestInit).body as string)).toEqual({
      status: "confirmed",
    });
  });

  it("switches to the Similarity view and renders the new tab", async () => {
    const fetchMock = makeFetch({
      "GET /api/projects/11/dq/datasets/7/similarity/runs": () => json(200, []),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<DataQualityDashboard projectId={11} datasetId={7} />);
    await waitFor(() =>
      expect(screen.getByText("Total rows")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /^similarity$/i }));
    await waitFor(() =>
      expect(screen.getByText(/no similarity runs yet/i)).toBeInTheDocument(),
    );
  });

  it("recomputes the profile when the Recompute button is clicked", async () => {
    const fetchMock = makeFetch({
      "POST /api/projects/11/dq/datasets/7/profile": () =>
        json(200, profile),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<DataQualityDashboard projectId={11} datasetId={7} />);
    await waitFor(() =>
      expect(screen.getByText("Total rows")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /^recompute$/i }));

    const recompute = fetchMock.mock.calls.find(
      ([url, init]) =>
        (init as RequestInit)?.method === "POST" &&
        (url as string) === "/api/projects/11/dq/datasets/7/profile",
    );
    expect(recompute).toBeTruthy();
  });
});
