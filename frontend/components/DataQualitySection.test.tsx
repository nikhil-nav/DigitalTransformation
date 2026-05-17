import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

import DataQualitySection from "./DataQualitySection";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const ts = "2026-05-10T01:23:45Z";

const sampleDataset = {
  id: 7,
  project_id: 11,
  original_filename: "biz.xlsx",
  file_sha256: "a".repeat(64),
  size_bytes: 12_345,
  sheets: [
    { name: "customers", row_count: 3, column_count: 2 },
    { name: "orders", row_count: 6, column_count: 3 },
  ],
  engine_version: "1.0.0",
  uploaded_at: ts,
  profiled_at: ts,
  annotation_status: "done",
  annotation_error: null,
  annotated_at: ts,
  // Epic 3: gate already cleared so existing list/render tests see the dashboard.
  config_completed_at: ts,
};

const emptyProfile: unknown[] = [];

/**
 * Build a URL-based fetch mock. The component fans out across several
 * endpoints (LlmSettings status, dataset list, profile, issues, FDs,
 * relationships) - matching on URL keeps the tests independent of call
 * order while still letting us override specific routes per test.
 */
function makeFetchMock(overrides: Record<string, () => Response>) {
  const defaults: Record<string, () => Response> = {
    "GET /api/auth/llm-keys": () =>
      jsonResponse(200, {
        provider: null,
        llm_configured: false,
        model: null,
        available_models: [],
      }),
    "GET /api/projects/11/dq/datasets": () => jsonResponse(200, []),
    "GET /api/projects/11/dq/datasets/7/profile": () =>
      jsonResponse(200, emptyProfile),
    "GET /api/projects/11/dq/datasets/7/issues": () =>
      jsonResponse(200, []),
    "GET /api/projects/11/dq/datasets/7/functional-dependencies": () =>
      jsonResponse(200, []),
    "GET /api/projects/11/dq/datasets/7/relationships": () =>
      jsonResponse(200, []),
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

describe("DataQualitySection", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows the empty state when the project has no datasets", async () => {
    vi.stubGlobal("fetch", makeFetchMock({}));

    render(<DataQualitySection projectId={11} />);
    await waitFor(() =>
      expect(screen.getByText(/no datasets yet/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /choose file/i }),
    ).toBeInTheDocument();
  });

  it("renders uploaded datasets with per-sheet row × column chips", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetchMock({
        "GET /api/projects/11/dq/datasets": () =>
          jsonResponse(200, [sampleDataset]),
      }),
    );

    render(<DataQualitySection projectId={11} />);
    await waitFor(() =>
      expect(screen.getByText("biz.xlsx")).toBeInTheDocument(),
    );
    expect(screen.getByText("customers")).toBeInTheDocument();
    expect(screen.getByText("orders")).toBeInTheDocument();
    // The "rows × cols" chip uses an unstyled "×" between the numbers
    expect(screen.getByText("3×2")).toBeInTheDocument();
    expect(screen.getByText("6×3")).toBeInTheDocument();
  });

  it("deletes a dataset and removes it from the list", async () => {
    const fetchMock = makeFetchMock({
      "GET /api/projects/11/dq/datasets": () =>
        jsonResponse(200, [sampleDataset]),
      "DELETE /api/projects/11/dq/datasets/7": () =>
        ({ ok: true, status: 204, json: async () => ({}) } as Response),
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<DataQualitySection projectId={11} />);
    await waitFor(() =>
      expect(screen.getByText("biz.xlsx")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /delete biz\.xlsx/i }));
    await waitFor(() =>
      expect(screen.queryByText("biz.xlsx")).not.toBeInTheDocument(),
    );

    const deleteCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit)?.method === "DELETE",
    );
    expect(deleteCall).toBeTruthy();
    expect(deleteCall![0]).toBe("/api/projects/11/dq/datasets/7");
  });

  it("mounts the config page when config_completed_at is null", async () => {
    const ungated = { ...sampleDataset, config_completed_at: null };
    vi.stubGlobal(
      "fetch",
      makeFetchMock({
        "GET /api/projects/11/dq/datasets": () =>
          jsonResponse(200, [ungated]),
        "GET /api/projects/11/dq/datasets/7/similarity/config": () =>
          jsonResponse(200, {
            saved: false,
            available_sheets: ["customers", "orders"],
            suggested_sheet_a: "customers",
            suggested_sheet_b: "orders",
            normalization: { case_fold: true },
            threshold: 0.85,
            mappings: [],
          }),
      }),
    );

    render(<DataQualitySection projectId={11} />);
    await waitFor(() =>
      expect(
        screen.getByLabelText(/profiling setup and configuration/i),
      ).toBeInTheDocument(),
    );
    // Dashboard heading should NOT be present — config page replaces it.
    expect(screen.queryByText(/Sheets summary/i)).not.toBeInTheDocument();
  });

  it("surfaces upload errors from the API", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetchMock({
        "POST /api/projects/11/dq/datasets": () =>
          jsonResponse(400, { detail: "Unsupported file extension '.csv'" }),
      }),
    );

    render(<DataQualitySection projectId={11} />);

    await waitFor(() =>
      expect(screen.getByText(/no datasets yet/i)).toBeInTheDocument(),
    );

    // The visible "Choose file" button proxies to a hidden <input type=file>;
    // fireEvent.change reliably triggers the handler regardless of visibility.
    const hiddenInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    expect(hiddenInput).toBeTruthy();
    const file = new File(["a,b\n1,2\n"], "data.csv", { type: "text/csv" });
    fireEvent.change(hiddenInput, { target: { files: [file] } });

    await waitFor(() =>
      expect(
        screen.getByText(/Unsupported file extension '\.csv'/),
      ).toBeInTheDocument(),
    );
  });
});
