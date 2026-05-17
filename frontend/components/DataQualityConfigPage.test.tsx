import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

import DataQualityConfigPage from "./DataQualityConfigPage";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function draftBody(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    saved: false,
    available_sheets: ["customers", "leads"],
    suggested_sheet_a: "customers",
    suggested_sheet_b: "leads",
    normalization: { case_fold: true, collapse_whitespace: true },
    threshold: 0.85,
    mappings: [
      {
        column_a: "email",
        column_b: "contact_email",
        algorithm: "exact",
        weight: 1.0,
        is_important: false,
        parser: "email",
        recommended_by: "heuristic",
      },
    ],
    ...overrides,
  };
}

function makeFetchMock(overrides: Record<string, () => Response>) {
  const defaults: Record<string, () => Response> = {
    "GET /api/projects/9/dq/datasets/4/similarity/config": () =>
      jsonResponse(200, draftBody()),
  };
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url.split("?")[0]}`;
    const override = overrides[key];
    if (override) return override();
    const fallback = defaults[key];
    if (fallback) return fallback();
    throw new Error(`Unmocked fetch ${key}`);
  });
}

const baseProps = {
  projectId: 9,
  datasetId: 4,
  availableSheets: ["customers", "leads"],
  onComplete: () => {},
};

describe("DataQualityConfigPage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the draft mapping returned by GET /config", async () => {
    vi.stubGlobal("fetch", makeFetchMock({}));
    render(<DataQualityConfigPage {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByDisplayValue("email")).toBeInTheDocument(),
    );
    expect(screen.getByDisplayValue("contact_email")).toBeInTheDocument();
  });

  it("blocks Save & Run when no mapping is important", async () => {
    vi.stubGlobal("fetch", makeFetchMock({}));
    render(<DataQualityConfigPage {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByDisplayValue("email")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/at least one mapping as important/i),
    ).toBeInTheDocument();
    const runBtn = screen.getByRole("button", { name: /save & run/i });
    expect(runBtn).toBeDisabled();
  });

  it("calls PUT and POST /run when the user clicks Save & Run after marking important", async () => {
    const fetchMock = makeFetchMock({
      "PUT /api/projects/9/dq/datasets/4/similarity/config": () =>
        jsonResponse(200, {
          id: 1,
          sheet_a: "customers",
          sheet_b: "leads",
          normalization: { case_fold: true, collapse_whitespace: true },
          threshold: 0.85,
          engine_version: "1.0.0",
          created_at: "2026-05-10T00:00:00Z",
          updated_at: "2026-05-10T00:00:00Z",
          mappings: [],
        }),
      "POST /api/projects/9/dq/datasets/4/similarity/run": () =>
        jsonResponse(200, {
          id: 1,
          dataset_id: 4,
          config_id: 1,
          sheet_a: "customers",
          sheet_b: "leads",
          threshold: 0.85,
          status: "done",
          candidate_pair_count: 4,
          passing_pair_count: 1,
          cluster_count: 1,
          blocking_column: null,
          error: null,
          engine_version: "1.0.0",
          started_at: "2026-05-10T00:00:00Z",
          finished_at: "2026-05-10T00:00:01Z",
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const onComplete = vi.fn();
    const user = userEvent.setup();
    render(<DataQualityConfigPage {...baseProps} onComplete={onComplete} />);

    await waitFor(() =>
      expect(screen.getByDisplayValue("email")).toBeInTheDocument(),
    );
    const importantCheckbox = screen.getByLabelText(/Mapping 0 important/i);
    await user.click(importantCheckbox);

    const runBtn = screen.getByRole("button", { name: /save & run/i });
    expect(runBtn).not.toBeDisabled();
    await user.click(runBtn);

    await waitFor(() => expect(onComplete).toHaveBeenCalled());
    const calls = fetchMock.mock.calls.map(
      ([url, init]) => `${(init as RequestInit)?.method ?? "GET"} ${url}`,
    );
    expect(calls).toContain(
      "PUT /api/projects/9/dq/datasets/4/similarity/config",
    );
    expect(calls).toContain(
      "POST /api/projects/9/dq/datasets/4/similarity/run",
    );
  });

  it("calls POST /skip when Skip is clicked", async () => {
    const fetchMock = makeFetchMock({
      "POST /api/projects/9/dq/datasets/4/similarity/skip": () =>
        jsonResponse(200, { config_completed_at: "2026-05-10T00:00:00Z" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const onComplete = vi.fn();
    const user = userEvent.setup();
    render(<DataQualityConfigPage {...baseProps} onComplete={onComplete} />);
    await waitFor(() =>
      expect(screen.getByDisplayValue("email")).toBeInTheDocument(),
    );

    await user.click(
      screen.getByRole("button", { name: /skip similarity scoring/i }),
    );
    await waitFor(() => expect(onComplete).toHaveBeenCalled());
  });

  it("clamps weight input to [0, 1]", async () => {
    vi.stubGlobal("fetch", makeFetchMock({}));
    const user = userEvent.setup();
    render(<DataQualityConfigPage {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByDisplayValue("email")).toBeInTheDocument(),
    );
    const weightInput = screen.getByLabelText(/Mapping 0 weight/i) as HTMLInputElement;
    await user.clear(weightInput);
    await user.type(weightInput, "5");
    // Input is type=number with max=1; component clamps via clamp01.
    expect(Number(weightInput.value)).toBeLessThanOrEqual(1);
  });

  it("single-sheet workbook: shows one picker and auto-populates self-mappings", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetchMock({
        "GET /api/projects/9/dq/datasets/4/similarity/config": () =>
          jsonResponse(200, {
            saved: false,
            available_sheets: ["only_sheet"],
            suggested_sheet_a: "only_sheet",
            suggested_sheet_b: "only_sheet",
            normalization: { case_fold: true },
            threshold: 0.85,
            mappings: [
              {
                column_a: "name",
                column_b: "name",
                algorithm: "jaro_winkler",
                weight: 1.0,
                is_important: false,
                parser: null,
                recommended_by: "heuristic",
              },
            ],
          }),
      }),
    );
    render(
      <DataQualityConfigPage
        {...baseProps}
        availableSheets={["only_sheet"]}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /sheet to analyze/i })).toBeInTheDocument(),
    );
    // Only one picker should render — no Sheet B dropdown.
    expect(screen.queryByLabelText(/sheet b/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^sheet$/i)).toBeInTheDocument();
    // The self-mapping ("name" ↔ "name") is pre-populated.
    expect(screen.getAllByDisplayValue("name")).toHaveLength(2);
  });

  it("multi-sheet workbook: allows picking the same sheet for both (within-sheet dedup)", async () => {
    const fetchMock = makeFetchMock({
      "POST /api/projects/9/dq/datasets/4/similarity/recommend": () =>
        jsonResponse(200, {
          normalization: { case_fold: true },
          threshold: 0.85,
          mappings: [
            {
              column_a: "name",
              column_b: "name",
              algorithm: "jaro_winkler",
              weight: 1.0,
              is_important: false,
              parser: null,
              recommended_by: "heuristic",
            },
          ],
          llm_error: null,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<DataQualityConfigPage {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByDisplayValue("email")).toBeInTheDocument(),
    );

    // Initially: sheet_a = customers, sheet_b = leads (from draft). Now
    // set sheet_b = customers so both sides match → within-sheet dedup.
    await user.selectOptions(screen.getByLabelText(/sheet b/i), "customers");

    // The frontend re-fetches the heuristic and gets self-mappings back.
    await waitFor(() => {
      const recCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          (init as RequestInit)?.method === "POST" &&
          (url as string).endsWith("/similarity/recommend"),
      );
      expect(recCalls.length).toBeGreaterThan(0);
      const body = JSON.parse((recCalls[0][1] as RequestInit).body as string);
      expect(body.sheet_a).toBe("customers");
      expect(body.sheet_b).toBe("customers");
    });
  });

  it("refetches the recommendation when the user picks a new Sheet B", async () => {
    const fetchMock = makeFetchMock({
      "POST /api/projects/9/dq/datasets/4/similarity/recommend": () =>
        jsonResponse(200, {
          normalization: { case_fold: true },
          threshold: 0.85,
          mappings: [
            {
              column_a: "id",
              column_b: "ref",
              algorithm: "exact",
              weight: 1.0,
              is_important: false,
              parser: null,
              recommended_by: "heuristic",
            },
          ],
          llm_error: null,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <DataQualityConfigPage
        {...baseProps}
        availableSheets={["customers", "leads", "orders"]}
      />,
    );
    await waitFor(() =>
      expect(screen.getByDisplayValue("email")).toBeInTheDocument(),
    );

    await user.selectOptions(screen.getByLabelText(/sheet b/i), "orders");

    await waitFor(() =>
      expect(screen.getByDisplayValue("ref")).toBeInTheDocument(),
    );
  });
});
