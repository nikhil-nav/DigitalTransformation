"use client";

import { useEffect, useState, type FormEvent } from "react";

import { api, ApiError, type LlmKeysStatus, type LlmProvider } from "@/lib/api";

const PROVIDER_LABEL: Record<LlmProvider, string> = {
  anthropic: "Claude (Anthropic)",
  openai: "OpenAI",
};

const KEY_PLACEHOLDER: Record<LlmProvider, string> = {
  anthropic: "sk-ant-...",
  openai: "sk-...",
};

const PROVIDER_NOTE: Record<LlmProvider, string> = {
  anthropic:
    "Full mode: server-side web search, extended thinking, file citations.",
  openai: "Lite mode: text + tools only. No web search, thinking, or citations.",
};

// Model variants offered per provider. Must match the backend's
// ALLOWED_MODELS_BY_PROVIDER in app/llm/session.py.
const MODELS_BY_PROVIDER: Record<LlmProvider, string[]> = {
  anthropic: [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
  ],
  openai: ["gpt-4o", "gpt-4o-mini"],
};
const DEFAULT_MODEL: Record<LlmProvider, string> = {
  anthropic: "claude-sonnet-4-6",
  openai: "gpt-4o",
};

export default function LlmSettings({
  onStatus,
}: {
  onStatus?: (status: LlmKeysStatus) => void;
}) {
  const [status, setStatus] = useState<LlmKeysStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState<LlmProvider>("anthropic");
  const [model, setModel] = useState<string>(DEFAULT_MODEL.anthropic);
  const [llmKey, setLlmKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getLlmKeysStatus()
      .then((s) => {
        setStatus(s);
        onStatus?.(s);
      })
      .catch(() => {
        // Status fetch silent-fail; user can still try to configure.
      });
  }, [onStatus]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (busy || llmKey.length < 10) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.setLlmKeys({
        provider,
        llm_api_key: llmKey,
        model,
      });
      setStatus(next);
      onStatus?.(next);
      setLlmKey("");
      setOpen(false);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to save keys");
    } finally {
      setBusy(false);
    }
  }

  async function handleClear() {
    setBusy(true);
    setError(null);
    try {
      const next = await api.clearLlmKeys();
      setStatus(next);
      onStatus?.(next);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to clear keys");
    } finally {
      setBusy(false);
    }
  }

  const configured = status?.llm_configured;

  return (
    <div className="llm-settings">
      <div className="llm-status-row">
        <span className={`badge${configured ? " badge-active" : ""}`}>
          {configured
            ? `${status?.provider ? PROVIDER_LABEL[status.provider] : ""} configured`
            : "No LLM key"}
        </span>
        <button
          type="button"
          className="link-button"
          onClick={() => setOpen((v) => !v)}
          disabled={busy}
        >
          {configured ? "Change" : "Configure"}
        </button>
        {configured && (
          <button
            type="button"
            className="link-button danger"
            onClick={handleClear}
            disabled={busy}
          >
            Clear
          </button>
        )}
      </div>

      {open && (
        <form onSubmit={handleSubmit} aria-label="llm settings form">
          <label>
            Provider
            <select
              value={provider}
              onChange={(e) => {
                const next = e.target.value as LlmProvider;
                setProvider(next);
                setModel(DEFAULT_MODEL[next]);
                setLlmKey("");
              }}
            >
              <option value="anthropic">Claude (Anthropic)</option>
              <option value="openai">OpenAI</option>
            </select>
          </label>
          <p className="meta llm-mode-note" data-testid="llm-mode-note">
            {PROVIDER_NOTE[provider]}
          </p>
          <label>
            Model
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              aria-label="LLM model"
            >
              {MODELS_BY_PROVIDER[provider].map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label>
            API key
            <input
              type="password"
              value={llmKey}
              onChange={(e) => setLlmKey(e.target.value)}
              autoComplete="off"
              required
              minLength={10}
              placeholder={KEY_PLACEHOLDER[provider]}
              aria-label="LLM API key"
            />
          </label>
          {error && (
            <div role="alert" className="status error">
              {error}
            </div>
          )}
          <div className="form-actions">
            <button type="submit" disabled={busy || llmKey.length < 10}>
              {busy ? "Saving..." : "Save"}
            </button>
            <button
              type="button"
              className="link-button"
              onClick={() => setOpen(false)}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
