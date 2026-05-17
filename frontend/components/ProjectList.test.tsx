import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

import ProjectList from "./ProjectList";

const sampleProject = {
  id: 1,
  name: "Q3 Discovery",
  description: null,
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

describe("ProjectList", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows loading then renders projects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [sampleProject],
      } as Response),
    );

    render(<ProjectList />);
    expect(screen.getByText(/loading projects/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/Q3 Discovery/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Value Discovery/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /\+ New Project/i })).toHaveAttribute(
      "href",
      "/projects/new",
    );
  });

  it("renders an empty state when there are no projects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [],
      } as Response),
    );

    render(<ProjectList />);
    await waitFor(() =>
      expect(screen.getByText(/no projects yet/i)).toBeInTheDocument(),
    );
  });

  it("renders an error when the API fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({ detail: "boom" }),
      } as Response),
    );

    render(<ProjectList />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/boom/i),
    );
  });
});
