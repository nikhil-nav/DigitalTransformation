import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("./BcmSection", () => ({
  default: () => <div data-testid="bcm-section" />,
}));

import ProjectDetail from "./ProjectDetail";

const project = {
  id: 7,
  name: "Q3 Discovery",
  description: "kicking off",
  status: "draft" as const,
  project_type: {
    id: 1,
    code: "value_discovery",
    name: "Value Discovery",
    is_active: true,
  },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("ProjectDetail", () => {
  beforeEach(() => {
    mocks.push.mockReset();
    mocks.refresh.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads and renders the project, then edits and saves", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, project))
      .mockResolvedValueOnce(
        jsonResponse(200, { ...project, name: "Renamed", status: "active" }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<ProjectDetail projectId={7} />);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Q3 Discovery/i })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /^edit$/i }));

    const nameInput = screen.getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed");
    await user.selectOptions(screen.getByLabelText(/status/i), "active");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Renamed/i })).toBeInTheDocument(),
    );

    const patchCall = fetchMock.mock.calls.find(
      ([p, init]) => p === "/api/projects/7" && init?.method === "PATCH",
    );
    expect(patchCall).toBeTruthy();
    const patchBody = JSON.parse(patchCall![1]!.body as string);
    expect(patchBody).toEqual({
      name: "Renamed",
      description: "kicking off",
      status: "active",
    });
  });

  it("shows a confirm dialog and deletes the project", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(200, project))
        .mockResolvedValueOnce(
          { ok: true, status: 204, json: async () => ({}) } as Response,
        ),
    );

    const user = userEvent.setup();
    render(<ProjectDetail projectId={7} />);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Q3 Discovery/i })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(screen.getByRole("dialog", { name: /confirm delete/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /yes, delete/i }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/"));
  });

  it("can cancel out of the delete dialog", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(200, project)),
    );

    const user = userEvent.setup();
    render(<ProjectDetail projectId={7} />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Q3 Discovery/i })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("shows a not-found message when the project does not exist", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(404, { detail: "Project not found" })),
    );

    render(<ProjectDetail projectId={999} />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/not found/i),
    );
  });
});
