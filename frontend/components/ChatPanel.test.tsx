import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Mock streamChat so we don't try real network during ChatPanel mount.
const { mockStreamChat } = vi.hoisted(() => ({
  mockStreamChat: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, streamChat: mockStreamChat };
});

// Mock the assistant-ui Thread component so we don't drag the entire
// Radix/ResizeObserver tree into jsdom. ChatPanel's job is wiring
// (load history, manage runtime, expose LlmSettings) - that's what we test
// here. The Thread itself is exercised by Playwright in Phase 5.
vi.mock("./Thread", () => ({
  Thread: ({ disabled }: { disabled?: boolean }) => (
    <div
      data-testid="thread-mock"
      data-disabled={disabled ? "true" : "false"}
    />
  ),
}));

vi.mock("@assistant-ui/react", () => ({
  AssistantRuntimeProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="runtime-provider">{children}</div>
  ),
  useExternalStoreRuntime: () => ({}),
}));

import ChatPanel from "./ChatPanel";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const baseMessage = {
  thinking: null,
  model_provider: null,
  model_id: null,
  created_at: "2026-05-07T00:00:00Z",
};

const configuredKeys = {
  provider: "anthropic" as const,
  llm_configured: true,
};

const unconfiguredKeys = {
  provider: null,
  llm_configured: false,
};

type Handler = (init?: RequestInit) => Response | Promise<Response>;

function makeFetch(handlers: Record<string, Handler>) {
  return vi.fn(async (path: string, init?: RequestInit) => {
    for (const [prefix, handler] of Object.entries(handlers)) {
      if (
        path === prefix ||
        path.startsWith(`${prefix}?`) ||
        path.startsWith(`${prefix}/`)
      ) {
        return handler(init);
      }
    }
    throw new Error(`Unexpected fetch: ${path} ${init?.method ?? "GET"}`);
  });
}

describe("ChatPanel", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    mockStreamChat.mockReset();
  });

  it("loads chat history and renders the LlmSettings + Thread", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetch({
        "/api/auth/llm-keys": async () => jsonResponse(200, configuredKeys),
        "/api/projects/1/chat": async () =>
          jsonResponse(200, [
            { id: 1, role: "user", content: "hi", ...baseMessage },
            {
              id: 2,
              role: "assistant",
              content: "hello",
              ...baseMessage,
            },
          ]),
      }),
    );

    render(<ChatPanel projectId={1} threadId={1} />);

    // LlmSettings renders the configured badge.
    await waitFor(() =>
      expect(screen.getByText(/configured/i)).toBeInTheDocument(),
    );

    // Thread is mounted (not disabled because the key is configured).
    const thread = screen.getByTestId("thread-mock");
    expect(thread).toHaveAttribute("data-disabled", "false");
    expect(screen.getByTestId("runtime-provider")).toBeInTheDocument();
  });

  it("marks Thread as disabled when no LLM key is configured", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetch({
        "/api/auth/llm-keys": async () => jsonResponse(200, unconfiguredKeys),
        "/api/projects/1/chat": async () => jsonResponse(200, []),
      }),
    );

    render(<ChatPanel projectId={1} threadId={1} />);

    await waitFor(() =>
      expect(screen.getByText(/no llm key/i)).toBeInTheDocument(),
    );
    expect(screen.getByTestId("thread-mock")).toHaveAttribute(
      "data-disabled",
      "true",
    );
  });

  it("disables Export button when no LLM key", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetch({
        "/api/auth/llm-keys": async () => jsonResponse(200, unconfiguredKeys),
        "/api/projects/1/chat": async () =>
          jsonResponse(200, [
            { id: 1, role: "user", content: "hi", ...baseMessage },
          ]),
      }),
    );

    render(<ChatPanel projectId={1} threadId={1} />);
    const exportBtn = await screen.findByRole("button", {
      name: /export chat to bcm/i,
    });
    expect(exportBtn).toBeDisabled();
  });

  it("disables Export button when there are no messages yet", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetch({
        "/api/auth/llm-keys": async () => jsonResponse(200, configuredKeys),
        "/api/projects/1/chat": async () => jsonResponse(200, []),
      }),
    );

    render(<ChatPanel projectId={1} threadId={1} />);
    const exportBtn = await screen.findByRole("button", {
      name: /export chat to bcm/i,
    });
    await waitFor(() => expect(exportBtn).toBeDisabled());
  });

  it("clicking Export sends the export prompt via streamChat", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetch({
        "/api/auth/llm-keys": async () => jsonResponse(200, configuredKeys),
        "/api/projects/1/chat": async () =>
          jsonResponse(200, [
            { id: 1, role: "user", content: "hi", ...baseMessage },
            { id: 2, role: "assistant", content: "ok", ...baseMessage },
          ]),
      }),
    );

    mockStreamChat.mockImplementation(async () => {
      // no events; just resolve
    });

    render(<ChatPanel projectId={1} threadId={1} />);
    const exportBtn = await screen.findByRole("button", {
      name: /export chat to bcm/i,
    });
    await waitFor(() => expect(exportBtn).toBeEnabled());

    const userEvent = (await import("@testing-library/user-event")).default;
    const user = userEvent.setup();
    await user.click(exportBtn);

    await waitFor(() => expect(mockStreamChat).toHaveBeenCalledTimes(1));
    const [, prompt] = mockStreamChat.mock.calls[0];
    expect(String(prompt).toLowerCase()).toContain("business capability map");
    expect(String(prompt).toLowerCase()).toContain("set_capabilities");
  });

  it("surfaces a load-history error", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetch({
        "/api/auth/llm-keys": async () => jsonResponse(200, configuredKeys),
        "/api/projects/1/chat": async () =>
          jsonResponse(500, { detail: "DB exploded" }),
      }),
    );

    render(<ChatPanel projectId={1} threadId={1} />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/DB exploded/i),
    );
  });
});
