"use client";

import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { Download, Loader2, ScanSearch, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  api,
  ApiError,
  streamChat,
  type ChatMessage,
  type LlmKeysStatus,
  type StreamEvent,
} from "@/lib/api";

import AttachmentButton from "./AttachmentButton";
import AttachmentTray from "./AttachmentTray";
import LlmSettings from "./LlmSettings";
import SlashCommandMenu from "./SlashCommandMenu";
import { Thread } from "./Thread";

const EXPORT_PROMPT =
  "Review our conversation above and extract a complete Business Capability Map. " +
  "Identify all L1, L2, and L3 capabilities mentioned or implied, organise them into " +
  "a proper hierarchy, and immediately call the set_capabilities tool to write the full " +
  "tree to the project. If the conversation already produced a BCM, refine it based on " +
  "any subsequent discussion. If you don't have enough information to build a defensible " +
  "tree, briefly explain what's missing instead of guessing.";

const CRITIQUE_PROMPT =
  "Critique the Business Capability Map currently saved on this project. " +
  "Read the current capabilities (call list_capabilities by inspecting the conversation, or " +
  "rely on what was last set via set_capabilities), then assess: " +
  "(1) Capabilities that look like processes, systems, departments, or KPIs (anti-patterns); " +
  "(2) Missing supporting capabilities (e.g. compliance, HR, IT); " +
  "(3) Asymmetric depth (L1s with no L2s, or one L1 over-decomposed while peers are flat); " +
  "(4) Naming inconsistencies (verb-noun forms vs noun forms). " +
  "Score the map 1-10 with one-line justification, then list 3-5 concrete improvements as " +
  "bullets. Don't call set_capabilities unless I ask you to apply the changes.";

type AssistantContent = NonNullable<ThreadMessageLike["content"]>;
type ContentPart = Extract<AssistantContent, readonly unknown[]>[number];

function extractUserText(message: AppendMessage): string {
  const parts = message.content;
  if (!Array.isArray(parts)) return "";
  const out: string[] = [];
  for (const p of parts) {
    if (p && typeof p === "object" && (p as { type?: string }).type === "text") {
      const t = (p as { text?: string }).text;
      if (t) out.push(t);
    }
  }
  return out.join("");
}

function persistedToThreadMessage(m: ChatMessage): ThreadMessageLike {
  const parts: ContentPart[] = [];
  if (m.role === "assistant" && m.thinking) {
    parts.push({ type: "reasoning", text: m.thinking });
  }
  if (m.content) {
    parts.push({ type: "text", text: m.content });
  }
  const base: ThreadMessageLike = {
    id: `db-${m.id}`,
    role: m.role,
    content: parts.length > 0 ? parts : [{ type: "text", text: "" }],
    createdAt: m.created_at ? new Date(m.created_at) : undefined,
    status:
      m.role === "assistant"
        ? { type: "complete", reason: "stop" as const }
        : undefined,
  };
  if (m.role === "assistant" && m.citations && m.citations.length > 0) {
    return {
      ...base,
      metadata: {
        custom: { citations: m.citations },
      },
    };
  }
  return base;
}

function appendTextDelta(parts: ContentPart[], text: string): ContentPart[] {
  const out = parts.slice();
  const last = out[out.length - 1];
  if (last && (last as { type?: string }).type === "text") {
    out[out.length - 1] = {
      ...(last as { type: "text"; text: string }),
      text: ((last as { text: string }).text ?? "") + text,
    };
  } else {
    out.push({ type: "text", text });
  }
  return out;
}

function appendThinkingDelta(
  parts: ContentPart[],
  text: string,
): ContentPart[] {
  const out = parts.slice();
  const last = out[out.length - 1];
  if (last && (last as { type?: string }).type === "reasoning") {
    out[out.length - 1] = {
      ...(last as { type: "reasoning"; text: string }),
      text: ((last as { text: string }).text ?? "") + text,
    };
  } else {
    out.push({ type: "reasoning", text });
  }
  return out;
}

function addToolCallPart(
  parts: ContentPart[],
  id: string,
  name: string,
  args: Record<string, unknown>,
): ContentPart[] {
  const argsText = JSON.stringify(args);
  const out = parts.slice();
  out.push({
    type: "tool-call",
    toolCallId: id,
    toolName: name,
    // ThreadMessageLike's args wants ReadonlyJSONObject; we pass through the
    // raw input we received over the wire (which is JSON-serialisable).
    args: JSON.parse(argsText),
    argsText,
  });
  return out;
}

function setToolResultPart(
  parts: ContentPart[],
  toolCallId: string,
  result: string,
  isError: boolean,
): ContentPart[] {
  return parts.map((p) => {
    if (
      p &&
      (p as { type?: string }).type === "tool-call" &&
      (p as { toolCallId?: string }).toolCallId === toolCallId
    ) {
      return {
        ...(p as { type: "tool-call"; toolName: string }),
        result,
        isError,
      };
    }
    return p;
  });
}

export default function ChatPanel({
  projectId,
  threadId,
  onChatComplete,
  headerExtra,
  onClose,
}: {
  projectId: number;
  threadId?: number;
  onChatComplete?: () => void;
  headerExtra?: React.ReactNode;
  onClose?: () => void;
}) {
  const [keysStatus, setKeysStatus] = useState<LlmKeysStatus | null>(null);
  const [messages, setMessages] = useState<ThreadMessageLike[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFileIds, setSelectedFileIds] = useState<number[]>([]);
  const [attachmentRefresh, setAttachmentRefresh] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (threadId === undefined) {
      setMessages([]);
      return;
    }
    setMessages([]);
    api
      .listChat(projectId, threadId)
      .then((existing) =>
        setMessages(existing.map(persistedToThreadMessage)),
      )
      .catch((e: unknown) => {
        setError(
          e instanceof ApiError ? e.message : "Failed to load chat history",
        );
      });
  }, [projectId, threadId]);

  const llmConfigured = !!keysStatus?.llm_configured;

  const sendUserMessage = useCallback(
    async (text: string) => {
      if (!llmConfigured) return;
      const trimmed = text.trim();
      if (!trimmed) return;

      const userTempId = `local-user-${Date.now()}`;
      const assistantTempId = `local-asst-${Date.now()}`;

      setMessages((prev) => [
        ...prev,
        {
          id: userTempId,
          role: "user",
          content: [{ type: "text", text: trimmed }],
        },
        {
          id: assistantTempId,
          role: "assistant",
          content: [],
          status: { type: "running" as const },
        },
      ]);
      setIsRunning(true);
      setError(null);

      const controller = new AbortController();
      abortRef.current = controller;

      let reachedAssistant = false;

      const updateAssistant = (
        updater: (parts: ContentPart[]) => ContentPart[],
      ) => {
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== assistantTempId) return m;
            const current = Array.isArray(m.content)
              ? (m.content as ContentPart[])
              : [];
            return { ...m, content: updater(current) };
          }),
        );
      };

      const fileIdsForTurn = selectedFileIds.slice();
      // Clear selection so the next turn doesn't reattach the same files.
      setSelectedFileIds([]);

      try {
        await streamChat(
          projectId,
          trimmed,
          (event: StreamEvent) => {
            switch (event.type) {
              case "user_message":
                // Replace optimistic user with persisted id
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === userTempId
                      ? {
                          ...m,
                          id: `db-${event.data.id}`,
                          createdAt: event.data.created_at
                            ? new Date(event.data.created_at)
                            : undefined,
                        }
                      : m,
                  ),
                );
                break;
              case "text_delta":
                updateAssistant((p) => appendTextDelta(p, event.data.text));
                break;
              case "thinking_delta":
                updateAssistant((p) =>
                  appendThinkingDelta(p, event.data.text),
                );
                break;
              case "tool_call":
                updateAssistant((p) =>
                  addToolCallPart(
                    p,
                    event.data.id,
                    event.data.name,
                    event.data.input,
                  ),
                );
                break;
              case "tool_result":
                updateAssistant((p) =>
                  setToolResultPart(
                    p,
                    event.data.tool_use_id,
                    event.data.preview,
                    event.data.is_error,
                  ),
                );
                break;
              case "assistant_message":
                reachedAssistant = true;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantTempId
                      ? {
                          ...m,
                          id: `db-${event.data.id}`,
                          createdAt: event.data.created_at
                            ? new Date(event.data.created_at)
                            : undefined,
                          status: {
                            type: "complete",
                            reason: "stop" as const,
                          },
                        }
                      : m,
                  ),
                );
                break;
              case "error":
                setError(event.data.message);
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantTempId
                      ? {
                          ...m,
                          status: {
                            type: "incomplete",
                            reason: "error" as const,
                          },
                        }
                      : m,
                  ),
                );
                break;
              case "done":
              default:
                break;
            }
          },
          controller.signal,
          {
            fileIds:
              fileIdsForTurn.length > 0 ? fileIdsForTurn : undefined,
            threadId,
          },
        );
        if (reachedAssistant) {
          onChatComplete?.();
        }
      } catch (e: unknown) {
        const aborted =
          e instanceof DOMException && e.name === "AbortError";
        if (!aborted) {
          setError(e instanceof ApiError ? e.message : "Streaming failed");
        }
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantTempId
              ? {
                  ...m,
                  status: {
                    type: "incomplete" as const,
                    reason: aborted
                      ? ("cancelled" as const)
                      : ("error" as const),
                  },
                }
              : m,
          ),
        );
      } finally {
        setIsRunning(false);
        abortRef.current = null;
      }
    },
    [projectId, threadId, llmConfigured, onChatComplete, selectedFileIds],
  );

  const handleNew = useCallback(
    async (message: AppendMessage) => {
      const text = extractUserText(message);
      if (text.trim()) await sendUserMessage(text);
    },
    [sendUserMessage],
  );

  const handleExport = useCallback(async () => {
    await sendUserMessage(EXPORT_PROMPT);
  }, [sendUserMessage]);

  const handleCritique = useCallback(async () => {
    await sendUserMessage(CRITIQUE_PROMPT);
  }, [sendUserMessage]);

  const handleCancel = useCallback(async () => {
    abortRef.current?.abort();
  }, []);

  const runtime = useExternalStoreRuntime<ThreadMessageLike>({
    isDisabled: !llmConfigured,
    isRunning,
    messages,
    convertMessage: (m) => m,
    onNew: handleNew,
    onCancel: handleCancel,
  });

  const headerClass = useMemo(
    () =>
      "flex flex-wrap items-center justify-between gap-2 border-b border-[var(--geyser)] px-4 py-3",
    [],
  );

  const exportDisabled = !llmConfigured || isRunning || messages.length === 0;
  const critiqueDisabled = !llmConfigured || isRunning;
  const headerBtnClass =
    "inline-flex items-center gap-1.5 rounded-md border border-[var(--geyser)] bg-white px-2.5 py-1 text-xs font-medium text-[var(--pickled-bluewood)] shadow-sm transition-all hover:border-[var(--coral)] hover:text-[var(--coral)] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-[var(--geyser)] disabled:hover:text-[var(--pickled-bluewood)]";

  return (
    <section className="flex h-full min-h-0 flex-col bg-white">
      <header className={headerClass}>
        <div className="flex min-w-0 flex-1 items-center">
          {headerExtra ?? (
            <h2 className="m-0 text-base font-semibold text-[var(--pickled-bluewood)]">
              Chat
            </h2>
          )}
        </div>
        <div className="flex flex-shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={handleCritique}
            disabled={critiqueDisabled}
            aria-label="Critique BCM"
            title={
              !llmConfigured
                ? "Configure an LLM key first"
                : isRunning
                  ? "Wait for the current turn to finish"
                  : "Ask the agent to critique the current BCM"
            }
            className={headerBtnClass}
          >
            {isRunning ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <ScanSearch className="h-3.5 w-3.5" />
            )}
            <span>Critique</span>
          </button>
          <button
            type="button"
            onClick={handleExport}
            disabled={exportDisabled}
            aria-label="Export chat to BCM"
            title={
              !llmConfigured
                ? "Configure an LLM key first"
                : messages.length === 0
                  ? "Send at least one message first"
                  : isRunning
                    ? "Wait for the current turn to finish"
                    : "Ask the agent to extract a BCM from this conversation"
            }
            className={headerBtnClass}
          >
            {isRunning ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            <span>Export</span>
          </button>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close chat"
              title="Close chat"
              className="ml-0.5 grid h-7 w-7 flex-shrink-0 place-items-center rounded-md text-[var(--slate)] transition-colors hover:bg-[var(--fog)] hover:text-[var(--pickled-bluewood)]"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </header>
      <div className="px-4 pt-3">
        <LlmSettings onStatus={setKeysStatus} />
      </div>
      {keysStatus?.provider === "anthropic" && (
        <div className="px-4 pt-2">
          <AttachmentTray
            projectId={projectId}
            enabled={!!keysStatus?.llm_configured}
            selectedIds={selectedFileIds}
            onChange={setSelectedFileIds}
            refreshNonce={attachmentRefresh}
          />
        </div>
      )}
      {error && (
        <div
          role="alert"
          className="mx-4 mt-2 rounded-md border border-[var(--watermelon)] bg-white px-3 py-2 text-sm text-[var(--watermelon)]"
        >
          {error}
        </div>
      )}
      <div className="min-h-0 flex-1">
        <AssistantRuntimeProvider runtime={runtime}>
          <Thread
            disabled={!llmConfigured}
            composerLeading={
              <>
                <SlashCommandMenu
                  disabled={!llmConfigured || isRunning}
                  onSelect={(prompt) => {
                    void sendUserMessage(prompt);
                  }}
                />
                {keysStatus?.provider === "anthropic" && llmConfigured && (
                  <AttachmentButton
                    projectId={projectId}
                    disabled={isRunning}
                    onUploaded={(file) => {
                      setSelectedFileIds((prev) =>
                        prev.includes(file.id) ? prev : [...prev, file.id],
                      );
                      setAttachmentRefresh((n) => n + 1);
                    }}
                    onError={(message) => setError(message)}
                  />
                )}
              </>
            }
          />
        </AssistantRuntimeProvider>
      </div>
    </section>
  );
}
