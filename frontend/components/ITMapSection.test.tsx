import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

// Stub the kanban so ITMapSection tests don't need to mock its
// downstream fetches (capabilities + applications). The kanban itself
// is covered by ITMapKanban.test.tsx.
vi.mock("./ITMapKanban", () => ({
  default: () => <div data-testid="kanban-stub" />,
}));

import ITMapSection from "./ITMapSection";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const ts = "2026-05-18T01:23:45Z";

const sampleInventory = {
  id: 7,
  project_id: 11,
  original_filename: "apps.xlsx",
  file_sha256: "a".repeat(64),
  size_bytes: 12_345,
  sheets: [{ name: "applications", row_count: 28, column_count: 6 }],
  primary_sheet: "applications",
  engine_version: "1.0.0",
  uploaded_at: ts,
};

const doneRun = {
  id: 100,
  inventory_id: 7,
  status: "done" as const,
  tool_call_count: 12,
  application_count: 28,
  mapping_count: 41,
  unmappable_count: 2,
  error: null,
  engine_version: "it-map-agent/1.0.0",
  started_at: ts,
  finished_at: ts,
};

const runningRun = { ...doneRun, id: 101, status: "running" as const, finished_at: null };

function makeFetchMock(overrides: Record<string, () => Response>) {
  const defaults: Record<string, () => Response> = {
    "GET /api/projects/11/it-map/inventories": () => jsonResponse(200, []),
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

describe("ITMapSection", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows the empty state when no inventories exist", async () => {
    vi.stubGlobal("fetch", makeFetchMock({}));
    render(<ITMapSection projectId={11} />);
    await waitFor(() =>
      expect(screen.getByText(/no inventories yet/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /choose file/i }),
    ).toBeInTheDocument();
  });

  it("renders an inventory with its primary sheet highlighted and a done run summary", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetchMock({
        "GET /api/projects/11/it-map/inventories": () =>
          jsonResponse(200, [sampleInventory]),
        "GET /api/projects/11/it-map/inventories/7/runs": () =>
          jsonResponse(200, [doneRun]),
      }),
    );
    render(<ITMapSection projectId={11} />);
    await waitFor(() =>
      expect(screen.getByText("apps.xlsx")).toBeInTheDocument(),
    );
    expect(screen.getByText("applications")).toBeInTheDocument();
    // Chip text uses exact "Mapped"; the summary line uses lowercase
    // "mappings" so the regex would have matched both.
    expect(screen.getByText("Mapped")).toBeInTheDocument();
    // The summary line shows the three counts in one paragraph
    expect(
      screen.getByText(/28 applications · 41 mappings · 2 unmapped/),
    ).toBeInTheDocument();
    // The Run button label flips to "Re-run" once a run exists.
    expect(
      screen.getByRole("button", { name: /re-run/i }),
    ).toBeInTheDocument();
  });

  it("triggers POST /run when the Run agent button is clicked", async () => {
    const fetchMock = makeFetchMock({
      "GET /api/projects/11/it-map/inventories": () =>
        jsonResponse(200, [sampleInventory]),
      "GET /api/projects/11/it-map/inventories/7/runs": () =>
        jsonResponse(200, []),
      "POST /api/projects/11/it-map/inventories/7/run": () =>
        jsonResponse(200, runningRun),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ITMapSection projectId={11} />);
    await waitFor(() =>
      expect(screen.getByText("apps.xlsx")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /run agent/i }));

    const post = fetchMock.mock.calls.find(
      ([url, init]) =>
        (init as RequestInit)?.method === "POST" &&
        (url as string).endsWith("/it-map/inventories/7/run"),
    );
    expect(post).toBeTruthy();
    // After the response, the status badge flips to "Agent running".
    await waitFor(() =>
      expect(screen.getByText(/Agent running/i)).toBeInTheDocument(),
    );
  });

  it("starts polling when the latest run status is 'running'", async () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    vi.stubGlobal(
      "fetch",
      makeFetchMock({
        "GET /api/projects/11/it-map/inventories": () =>
          jsonResponse(200, [sampleInventory]),
        "GET /api/projects/11/it-map/inventories/7/runs": () =>
          jsonResponse(200, [runningRun]),
      }),
    );
    render(<ITMapSection projectId={11} />);
    await waitFor(() =>
      expect(screen.getByText(/Agent running/i)).toBeInTheDocument(),
    );
    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 5000);
    setIntervalSpy.mockRestore();
  });

  it("does NOT start polling when all runs are settled", async () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    vi.stubGlobal(
      "fetch",
      makeFetchMock({
        "GET /api/projects/11/it-map/inventories": () =>
          jsonResponse(200, [sampleInventory]),
        "GET /api/projects/11/it-map/inventories/7/runs": () =>
          jsonResponse(200, [doneRun]),
      }),
    );
    render(<ITMapSection projectId={11} />);
    await waitFor(() =>
      expect(screen.getByText("apps.xlsx")).toBeInTheDocument(),
    );
    const pollCalls = setIntervalSpy.mock.calls.filter(
      ([, ms]) => ms === 5000,
    );
    expect(pollCalls).toHaveLength(0);
    setIntervalSpy.mockRestore();
  });

  it("deletes an inventory and removes it from the list", async () => {
    const fetchMock = makeFetchMock({
      "GET /api/projects/11/it-map/inventories": () =>
        jsonResponse(200, [sampleInventory]),
      "GET /api/projects/11/it-map/inventories/7/runs": () =>
        jsonResponse(200, []),
      "DELETE /api/projects/11/it-map/inventories/7": () =>
        ({ ok: true, status: 204, json: async () => ({}) } as Response),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ITMapSection projectId={11} />);
    await waitFor(() =>
      expect(screen.getByText("apps.xlsx")).toBeInTheDocument(),
    );

    await user.click(
      screen.getByRole("button", { name: /delete apps\.xlsx/i }),
    );
    await waitFor(() =>
      expect(screen.queryByText("apps.xlsx")).not.toBeInTheDocument(),
    );
  });

  it("surfaces upload errors from the API", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetchMock({
        "POST /api/projects/11/it-map/inventories": () =>
          jsonResponse(400, {
            detail: "Unsupported file extension '.csv'",
          }),
      }),
    );
    render(<ITMapSection projectId={11} />);
    await waitFor(() =>
      expect(screen.getByText(/no inventories yet/i)).toBeInTheDocument(),
    );

    const hiddenInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File(["a"], "data.csv", { type: "text/csv" });
    fireEvent.change(hiddenInput, { target: { files: [file] } });

    await waitFor(() =>
      expect(
        screen.getByText(/Unsupported file extension '\.csv'/),
      ).toBeInTheDocument(),
    );
  });
});
