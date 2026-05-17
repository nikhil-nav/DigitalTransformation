import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

import LlmSettings from "./LlmSettings";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const unconfigured = {
  provider: null,
  llm_configured: false,
  model: null,
  available_models: [],
};
const configuredAnthropic = {
  provider: "anthropic" as const,
  llm_configured: true,
  model: "claude-sonnet-4-6",
  available_models: [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
  ],
};
const configuredOpenAI = {
  provider: "openai" as const,
  llm_configured: true,
  model: "gpt-4o",
  available_models: ["gpt-4o", "gpt-4o-mini"],
};

describe("LlmSettings", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads the unconfigured status and shows the Configure button", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(200, unconfigured)),
    );

    render(<LlmSettings />);
    await waitFor(() =>
      expect(screen.getByText(/no llm key/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /configure/i }),
    ).toBeInTheDocument();
  });

  it("submits a Claude key and calls onStatus", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, unconfigured))
      .mockResolvedValueOnce(jsonResponse(200, configuredAnthropic));
    vi.stubGlobal("fetch", fetchMock);

    const onStatus = vi.fn();
    const user = userEvent.setup();
    render(<LlmSettings onStatus={onStatus} />);

    await waitFor(() =>
      expect(screen.getByText(/no llm key/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /configure/i }));
    await user.type(
      screen.getByLabelText(/^llm api key$/i),
      "sk-ant-test12345",
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(onStatus).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "anthropic",
          llm_configured: true,
        }),
      ),
    );

    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(postCall).toBeTruthy();
    expect(JSON.parse(postCall![1]!.body as string)).toEqual({
      provider: "anthropic",
      llm_api_key: "sk-ant-test12345",
      model: "claude-sonnet-4-6",
    });
  });

  it("submits an OpenAI key when the user picks OpenAI", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, unconfigured))
      .mockResolvedValueOnce(jsonResponse(200, configuredOpenAI));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<LlmSettings />);
    await waitFor(() =>
      expect(screen.getByText(/no llm key/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /configure/i }));

    const providerSelect = screen.getByLabelText(/provider/i);
    await user.selectOptions(providerSelect, "openai");
    await user.type(
      screen.getByLabelText(/^llm api key$/i),
      "sk-openai-test1234",
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(postCall).toBeTruthy();
    expect(JSON.parse(postCall![1]!.body as string)).toEqual({
      provider: "openai",
      llm_api_key: "sk-openai-test1234",
      model: "gpt-4o",
    });
  });

  it("lets the user pick a non-default Anthropic model and sends it", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, unconfigured))
      .mockResolvedValueOnce(jsonResponse(200, configuredAnthropic));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<LlmSettings />);
    await waitFor(() =>
      expect(screen.getByText(/no llm key/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /configure/i }));

    await user.selectOptions(
      screen.getByLabelText(/llm model/i),
      "claude-opus-4-7",
    );
    await user.type(
      screen.getByLabelText(/^llm api key$/i),
      "sk-ant-test12345",
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(JSON.parse(postCall![1]!.body as string)).toEqual({
      provider: "anthropic",
      llm_api_key: "sk-ant-test12345",
      model: "claude-opus-4-7",
    });
  });

  it("resets the model to the provider default when the provider changes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(200, unconfigured)),
    );
    const user = userEvent.setup();
    render(<LlmSettings />);
    await waitFor(() =>
      expect(screen.getByText(/no llm key/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /configure/i }));

    const modelSelect = screen.getByLabelText(/llm model/i) as HTMLSelectElement;
    expect(modelSelect.value).toBe("claude-sonnet-4-6");

    await user.selectOptions(screen.getByLabelText(/provider/i), "openai");
    expect(modelSelect.value).toBe("gpt-4o");

    await user.selectOptions(modelSelect, "gpt-4o-mini");
    expect(modelSelect.value).toBe("gpt-4o-mini");

    await user.selectOptions(screen.getByLabelText(/provider/i), "anthropic");
    expect(modelSelect.value).toBe("claude-sonnet-4-6");
  });

  it("shows a 'Lite mode' note when OpenAI is selected and 'Full mode' for Anthropic", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(200, unconfigured)),
    );

    const user = userEvent.setup();
    render(<LlmSettings />);
    await waitFor(() =>
      expect(screen.getByText(/no llm key/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /configure/i }));

    const note = screen.getByTestId("llm-mode-note");
    expect(note).toHaveTextContent(/full mode/i);

    await user.selectOptions(screen.getByLabelText(/provider/i), "openai");
    expect(note).toHaveTextContent(/lite mode/i);
  });

  it("clears the key field when the provider changes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(200, unconfigured)),
    );

    const user = userEvent.setup();
    render(<LlmSettings />);
    await waitFor(() =>
      expect(screen.getByText(/no llm key/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /configure/i }));

    const keyInput = screen.getByLabelText(/^llm api key$/i);
    await user.type(keyInput, "sk-ant-something");
    expect((keyInput as HTMLInputElement).value).toBe("sk-ant-something");

    await user.selectOptions(screen.getByLabelText(/provider/i), "openai");
    expect((keyInput as HTMLInputElement).value).toBe("");
  });

  it("clears the configured key", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, configuredAnthropic))
      .mockResolvedValueOnce(jsonResponse(200, unconfigured));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<LlmSettings />);
    await waitFor(() =>
      expect(screen.getByText(/configured/i)).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /^clear$/i }));
    await waitFor(() =>
      expect(screen.getByText(/no llm key/i)).toBeInTheDocument(),
    );

    const deleteCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "DELETE",
    );
    expect(deleteCall).toBeTruthy();
  });
});
