import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

import KanbanBoard from "./KanbanBoard";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const ts = "2026-05-06T00:00:00Z";

const sampleTree = [
  {
    id: 1,
    project_id: 5,
    parent_id: null,
    level: 1,
    name: "Customer Management",
    description: null,
    position: 0,
    created_at: ts,
    updated_at: ts,
  },
  {
    id: 2,
    project_id: 5,
    parent_id: 1,
    level: 2,
    name: "Acquisition",
    description: null,
    position: 0,
    created_at: ts,
    updated_at: ts,
  },
  {
    id: 3,
    project_id: 5,
    parent_id: 2,
    level: 3,
    name: "Lead capture",
    description: null,
    position: 0,
    created_at: ts,
    updated_at: ts,
  },
];

describe("KanbanBoard", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the empty state when there are no capabilities", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(200, [])),
    );

    render(<KanbanBoard projectId={5} />);
    await waitFor(() =>
      expect(screen.getByText(/no capabilities yet/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /\+ add l1/i }),
    ).toBeInTheDocument();
  });

  it("renders a loaded tree with L1, L2, and the L3 visible after expanding", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(200, sampleTree)),
    );

    const user = userEvent.setup();
    render(<KanbanBoard projectId={5} />);

    await waitFor(() =>
      expect(screen.getByText("Customer Management")).toBeInTheDocument(),
    );
    expect(screen.getByText("Acquisition")).toBeInTheDocument();
    // L3 only visible after we expand the L2
    expect(screen.queryByText("Lead capture")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /expand l2/i }));
    expect(screen.getByText("Lead capture")).toBeInTheDocument();
  });

  it("creates an L1 via the + Add L1 inline form", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, []))
      .mockResolvedValueOnce(
        jsonResponse(201, {
          id: 10,
          project_id: 5,
          parent_id: null,
          level: 1,
          name: "Operations",
          description: null,
          position: 0,
          created_at: ts,
          updated_at: ts,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: 10,
            project_id: 5,
            parent_id: null,
            level: 1,
            name: "Operations",
            description: null,
            position: 0,
            created_at: ts,
            updated_at: ts,
          },
        ]),
      );
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<KanbanBoard projectId={5} />);

    await waitFor(() =>
      expect(screen.getByText(/no capabilities yet/i)).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /\+ add l1/i }));
    const input = screen.getByLabelText(/new l1 name/i);
    await user.type(input, "Operations{Enter}");

    await waitFor(() =>
      expect(screen.getByText("Operations")).toBeInTheDocument(),
    );

    const postCall = fetchMock.mock.calls.find(
      ([p, init]) =>
        p === "/api/projects/5/capabilities" && init?.method === "POST",
    );
    expect(postCall).toBeTruthy();
    expect(JSON.parse(postCall![1]!.body as string)).toEqual({
      level: 1,
      parent_id: null,
      name: "Operations",
    });
  });

  it("deletes an L1 through the confirm dialog", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, sampleTree))
      .mockResolvedValueOnce(
        { ok: true, status: 204, json: async () => ({}) } as Response,
      )
      .mockResolvedValueOnce(jsonResponse(200, []));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<KanbanBoard projectId={5} />);
    await waitFor(() =>
      expect(screen.getByText("Customer Management")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /delete l1/i }));
    await user.click(screen.getByRole("button", { name: /yes, delete/i }));

    await waitFor(() =>
      expect(
        screen.queryByText("Customer Management"),
      ).not.toBeInTheDocument(),
    );

    const deleteCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "DELETE",
    );
    expect(deleteCall).toBeTruthy();
    expect(deleteCall![0]).toBe("/api/projects/5/capabilities/1");
  });
});
