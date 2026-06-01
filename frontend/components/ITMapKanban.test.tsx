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

import ITMapKanban from "./ITMapKanban";

function json(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const ts = "2026-05-18T10:00:00Z";

const caps = [
  { id: 1, project_id: 11, parent_id: null, level: 1, name: "Customer", description: null, position: 0, created_at: ts, updated_at: ts },
  { id: 2, project_id: 11, parent_id: 1, level: 2, name: "Sales", description: null, position: 0, created_at: ts, updated_at: ts },
  { id: 3, project_id: 11, parent_id: 1, level: 2, name: "Service", description: null, position: 1, created_at: ts, updated_at: ts },
  { id: 4, project_id: 11, parent_id: 2, level: 3, name: "Pricing", description: null, position: 0, created_at: ts, updated_at: ts },
];

function mapping(id: number, capId: number, status: "suggested" | "confirmed" | "dismissed") {
  return {
    id,
    capability_id: capId,
    confidence: 0.9,
    rationale: "agent rationale",
    status,
    engine_version: "it-map-agent/1.0.0",
    created_at: ts,
    updated_at: ts,
    confirmed_at: status === "confirmed" ? ts : null,
    dismissed_at: status === "dismissed" ? ts : null,
  };
}

const apps = [
  {
    id: 10,
    inventory_id: 7,
    sheet_name: "apps",
    row_index: 0,
    raw_row: { name: "Salesforce", owner: "Bob" },
    inferred_name: "Salesforce",
    inferred_description: "CRM SaaS",
    inferred_business_function: "Sales",
    inferred_technology: null,
    inferred_owner: "Bob",
    inferred_criticality: null,
    inferred_lifecycle: null,
    unmappable_reason: null,
    created_at: ts,
    mappings: [mapping(100, 2, "suggested"), mapping(101, 3, "confirmed")],
  },
  {
    id: 11,
    inventory_id: 7,
    sheet_name: "apps",
    row_index: 1,
    raw_row: { name: "?", owner: null },
    inferred_name: "Unknown Co",
    inferred_description: null,
    inferred_business_function: null,
    inferred_technology: null,
    inferred_owner: null,
    inferred_criticality: null,
    inferred_lifecycle: null,
    unmappable_reason: "No clear capability fit",
    created_at: ts,
    mappings: [],
  },
];

function makeFetch(overrides: Record<string, () => Response> = {}) {
  const defaults: Record<string, () => Response> = {
    "GET /api/projects/11/it-map/inventories/7/applications": () =>
      json(200, apps),
    "GET /api/projects/11/capabilities": () => json(200, caps),
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

describe("ITMapKanban", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders one column per L2 capability + an Unmapped column", async () => {
    vi.stubGlobal("fetch", makeFetch());
    render(<ITMapKanban projectId={11} inventoryId={7} />);
    await waitFor(() =>
      expect(
        screen.getByLabelText("Capability column: Sales"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByLabelText("Capability column: Service"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Capability column: Unmapped"),
    ).toBeInTheDocument();
    // L1 and L3 capabilities are NOT rendered as columns.
    expect(
      screen.queryByLabelText("Capability column: Customer"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Capability column: Pricing"),
    ).not.toBeInTheDocument();
  });

  it("places an app in EVERY column it has a non-dismissed mapping to", async () => {
    vi.stubGlobal("fetch", makeFetch());
    render(<ITMapKanban projectId={11} inventoryId={7} />);
    await waitFor(() =>
      expect(
        screen.getByLabelText("Capability column: Sales"),
      ).toBeInTheDocument(),
    );
    // Salesforce has mappings in both Sales (suggested) and Service (confirmed).
    const salesCol = screen.getByLabelText("Capability column: Sales");
    const serviceCol = screen.getByLabelText("Capability column: Service");
    expect(
      within(salesCol).getByRole("button", { name: /Application Salesforce/i }),
    ).toBeInTheDocument();
    expect(
      within(serviceCol).getByRole("button", { name: /Application Salesforce/i }),
    ).toBeInTheDocument();
  });

  it("places an app with no mappings in the Unmapped column with its reason", async () => {
    vi.stubGlobal("fetch", makeFetch());
    render(<ITMapKanban projectId={11} inventoryId={7} />);
    await waitFor(() =>
      expect(
        screen.getByLabelText("Capability column: Unmapped"),
      ).toBeInTheDocument(),
    );
    const unmapped = screen.getByLabelText("Capability column: Unmapped");
    expect(
      within(unmapped).getByRole("button", { name: /Application Unknown Co/i }),
    ).toBeInTheDocument();
    expect(
      within(unmapped).getByText(/No clear capability fit/i),
    ).toBeInTheDocument();
  });

  it("opens the drawer when an application card is clicked", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetch({
        "GET /api/projects/11/it-map/applications/10": () =>
          json(200, apps[0]),
      }),
    );
    const user = userEvent.setup();
    render(<ITMapKanban projectId={11} inventoryId={7} />);
    await waitFor(() =>
      expect(
        screen.getByLabelText("Capability column: Sales"),
      ).toBeInTheDocument(),
    );

    const salesCol = screen.getByLabelText("Capability column: Sales");
    await user.click(
      within(salesCol).getByRole("button", { name: /Application Salesforce/i }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: /application detail/i,
    });
    // "Salesforce" appears in the header, inferred fields, AND raw-row
    // table; use the heading to pin the unique one and rely on the
    // description text for the rest.
    expect(
      within(dialog).getByRole("heading", { name: "Salesforce" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("CRM SaaS")).toBeInTheDocument();
  });

  it("confirms a suggested mapping from the drawer and refetches", async () => {
    let confirmedReturned = false;
    const fetchMock = makeFetch({
      "GET /api/projects/11/it-map/applications/10": () => {
        if (!confirmedReturned) {
          return json(200, apps[0]);
        }
        // After PATCH, return the app with the first mapping flipped.
        const updated = {
          ...apps[0],
          mappings: [
            { ...apps[0].mappings[0], status: "confirmed", confirmed_at: ts },
            apps[0].mappings[1],
          ],
        };
        return json(200, updated);
      },
      "PATCH /api/projects/11/it-map/mappings/100": () => {
        confirmedReturned = true;
        return json(200, { ...apps[0].mappings[0], status: "confirmed" });
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ITMapKanban projectId={11} inventoryId={7} />);
    await waitFor(() =>
      expect(
        screen.getByLabelText("Capability column: Sales"),
      ).toBeInTheDocument(),
    );

    const salesCol = screen.getByLabelText("Capability column: Sales");
    await user.click(
      within(salesCol).getByRole("button", { name: /Application Salesforce/i }),
    );

    const dialog = await screen.findByRole("dialog");
    // Two Confirm buttons would only exist if both mappings were
    // confirm-eligible; the confirmed Service mapping has no Confirm
    // button (it's already confirmed). Click the only one.
    const confirmBtn = within(dialog).getByRole("button", { name: /confirm/i });
    await user.click(confirmBtn);

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          (init as RequestInit)?.method === "PATCH" &&
          (url as string).endsWith("/it-map/mappings/100"),
      );
      expect(patchCall).toBeTruthy();
      expect(JSON.parse((patchCall![1] as RequestInit).body as string)).toEqual({
        status: "confirmed",
      });
    });
  });

  it("creates a new mapping when the user picks an available L2 from the picker", async () => {
    // Unknown Co (app 11) has no mappings yet, so all L2 caps are available.
    const fetchMock = makeFetch({
      "GET /api/projects/11/it-map/applications/11": () => json(200, apps[1]),
      "POST /api/projects/11/it-map/mappings": () =>
        json(201, {
          id: 999,
          capability_id: 2,
          confidence: 1.0,
          rationale: "User-created mapping",
          status: "confirmed",
          engine_version: "user",
          created_at: ts,
          updated_at: ts,
          confirmed_at: ts,
          dismissed_at: null,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ITMapKanban projectId={11} inventoryId={7} />);
    await waitFor(() =>
      expect(
        screen.getByLabelText("Capability column: Unmapped"),
      ).toBeInTheDocument(),
    );

    const unmapped = screen.getByLabelText("Capability column: Unmapped");
    await user.click(
      within(unmapped).getByRole("button", { name: /Application Unknown Co/i }),
    );

    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getByRole("button", { name: /add mapping/i }),
    );
    // The picker should now show "Sales" and "Service" (both L2, both
    // unused). Click Sales.
    await user.click(within(dialog).getByRole("button", { name: /^Sales$/ }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) =>
          (init as RequestInit)?.method === "POST" &&
          (url as string).endsWith("/it-map/mappings"),
      );
      expect(post).toBeTruthy();
      expect(JSON.parse((post![1] as RequestInit).body as string)).toEqual({
        application_id: 11,
        capability_id: 2,
      });
    });
  });
});
