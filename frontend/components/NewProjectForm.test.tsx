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

import NewProjectForm from "./NewProjectForm";

const types = [
  { id: 1, code: "value_discovery", name: "Value Discovery", is_active: true },
  {
    id: 2,
    code: "business_process_discovery",
    name: "Business Process Discovery",
    is_active: false,
  },
  { id: 3, code: "ai_assessment", name: "AI Assessment", is_active: false },
];

function makeFetch(
  responders: Record<string, (init?: RequestInit) => Promise<Response>>,
) {
  return vi.fn(async (path: string, init?: RequestInit) => {
    for (const [prefix, fn] of Object.entries(responders)) {
      if (path.startsWith(prefix)) return fn(init);
    }
    throw new Error(`Unexpected fetch: ${path}`);
  });
}

describe("NewProjectForm", () => {
  beforeEach(() => {
    mocks.push.mockReset();
    mocks.refresh.mockReset();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads types, disables inactive ones, submits and navigates to the new project", async () => {
    const fetchMock = makeFetch({
      "/api/project-types": async () =>
        ({ ok: true, status: 200, json: async () => types }) as Response,
      "/api/projects": async () =>
        ({
          ok: true,
          status: 201,
          json: async () => ({ id: 42 }),
        }) as Response,
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<NewProjectForm />);

    await waitFor(() =>
      expect(screen.getByLabelText("Value Discovery")).toBeInTheDocument(),
    );

    expect(screen.getByLabelText("Value Discovery")).not.toBeDisabled();
    expect(screen.getByLabelText("Business Process Discovery")).toBeDisabled();
    expect(screen.getByLabelText("AI Assessment")).toBeDisabled();

    await user.type(screen.getByLabelText(/^name$/i), "Q3 Discovery");
    await user.type(screen.getByLabelText(/description/i), "kicking off");
    await user.click(screen.getByRole("button", { name: /create project/i }));

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/projects/42"));

    const createCall = fetchMock.mock.calls.find(
      ([p, init]) => p === "/api/projects" && init?.method === "POST",
    );
    expect(createCall).toBeTruthy();
    expect(JSON.parse(createCall![1]!.body as string)).toEqual({
      name: "Q3 Discovery",
      description: "kicking off",
      project_type_code: "value_discovery",
    });
  });

  it("shows the API error message on a 400 from the backend", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetch({
        "/api/project-types": async () =>
          ({ ok: true, status: 200, json: async () => types }) as Response,
        "/api/projects": async () =>
          ({
            ok: false,
            status: 400,
            json: async () => ({ detail: "Project type 'x' is not active" }),
          }) as Response,
      }),
    );

    const user = userEvent.setup();
    render(<NewProjectForm />);
    await waitFor(() =>
      expect(screen.getByLabelText("Value Discovery")).toBeInTheDocument(),
    );

    await user.type(screen.getByLabelText(/^name$/i), "X");
    await user.click(screen.getByRole("button", { name: /create project/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/not active/i),
    );
    expect(mocks.push).not.toHaveBeenCalled();
  });
});
