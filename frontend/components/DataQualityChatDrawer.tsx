"use client";

import {
  ArrowUp,
  Loader2,
  MessageCircle,
  Sparkles,
  Square,
  Wrench,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import {
  api,
  ApiError,
  streamDqChat,
  type ChatMessage,
  type StreamEvent,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const STARTER_PROMPTS = [
  "Which columns have the worst data quality?",
  "Summarise the issues on the largest sheet.",
  "Suggest fixes for the highest-severity issues.",
  "Are there any orphan rows across sheets?",
];

type LocalMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  thinking?: string;
  toolCalls: Array<{ id: string; name: string; result?: string; isError?: boolean }>;
  status: "running" | "complete" | "error";
};

function fromPersisted(m: ChatMessage): LocalMessage {
  return {
    id: `db-${m.id}`,
    role: m.role,
    text: m.content,
    thinking: m.thinking ?? undefined,
    toolCalls: [],
    status: "complete",
  };
}

export default function DataQualityChatDrawer({
  projectId,
  datasetId,
}: {
  projectId: number;
  datasetId: number;
}) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);

  // Reload messages whenever the drawer is opened or the dataset switches.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api
      .listDqChat(projectId, datasetId)
      .then((rows) => {
        if (!cancelled) setMessages(rows.map(fromPersisted));
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : "Failed to load chat");
      });
    return () => {
      cancelled = true;
    };
  }, [open, projectId, datasetId]);

  // Auto-scroll on new content
  useEffect(() => {
    if (viewportRef.current) {
      viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
    }
  }, [messages]);

  // Escape closes
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent | globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey as never);
    return () => window.removeEventListener("keydown", onKey as never);
  }, [open]);

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isRunning) return;
      setInput("");
      setError(null);

      const userTempId = `local-user-${Date.now()}`;
      const assistantTempId = `local-asst-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        { id: userTempId, role: "user", text: trimmed, toolCalls: [], status: "complete" },
        { id: assistantTempId, role: "assistant", text: "", toolCalls: [], status: "running" },
      ]);
      setIsRunning(true);

      const controller = new AbortController();
      abortRef.current = controller;

      const updateAssistant = (mut: (m: LocalMessage) => LocalMessage) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantTempId ? mut(m) : m)),
        );
      };

      try {
        await streamDqChat(
          projectId,
          datasetId,
          trimmed,
          (ev: StreamEvent) => {
            switch (ev.type) {
              case "text_delta":
                updateAssistant((m) => ({ ...m, text: m.text + ev.data.text }));
                break;
              case "thinking_delta":
                updateAssistant((m) => ({
                  ...m,
                  thinking: (m.thinking ?? "") + ev.data.text,
                }));
                break;
              case "tool_call":
                updateAssistant((m) => ({
                  ...m,
                  toolCalls: [
                    ...m.toolCalls,
                    { id: ev.data.id, name: ev.data.name },
                  ],
                }));
                break;
              case "tool_result":
                updateAssistant((m) => ({
                  ...m,
                  toolCalls: m.toolCalls.map((tc) =>
                    tc.id === ev.data.tool_use_id
                      ? { ...tc, result: ev.data.preview, isError: ev.data.is_error }
                      : tc,
                  ),
                }));
                break;
              case "assistant_message":
                updateAssistant((m) => ({ ...m, status: "complete" }));
                break;
              case "error":
                setError(ev.data.message);
                updateAssistant((m) => ({ ...m, status: "error" }));
                break;
              default:
                break;
            }
          },
          controller.signal,
        );
      } catch (e: unknown) {
        const aborted = e instanceof DOMException && e.name === "AbortError";
        if (!aborted) {
          setError(e instanceof ApiError ? e.message : "Chat failed");
        }
        updateAssistant((m) => ({
          ...m,
          status: aborted ? "complete" : "error",
        }));
      } finally {
        setIsRunning(false);
        abortRef.current = null;
      }
    },
    [projectId, datasetId, isRunning],
  );

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    void sendMessage(input);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(input);
    }
  }

  function handleCancel() {
    abortRef.current?.abort();
  }

  return (
    <>
      {/* Floating opener */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open Data Quality chat"
        className={cn(
          "fixed bottom-6 right-6 z-30 inline-flex items-center gap-2 rounded-full bg-[var(--coral)] px-5 py-3 text-sm font-semibold text-white shadow-lg transition-all hover:brightness-95",
          open && "pointer-events-none opacity-0",
        )}
      >
        <MessageCircle className="h-5 w-5" />
        Chat with the dataset
      </button>

      <aside
        role="dialog"
        aria-label="Data Quality chat"
        aria-hidden={!open}
        className={cn(
          "fixed right-0 top-0 z-30 flex h-screen w-full max-w-[28rem] flex-col border-l border-[var(--geyser)] bg-white shadow-2xl transition-transform duration-200 ease-out sm:max-w-[32rem]",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <header className="flex items-center justify-between gap-2 border-b border-[var(--geyser)] px-4 py-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[var(--cerulean)]" />
            <h3 className="m-0 text-base font-semibold text-[var(--pickled-bluewood)]">
              Data Quality chat
            </h3>
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close chat"
            className="grid h-7 w-7 place-items-center rounded-md bg-transparent text-[var(--slate)] hover:bg-[var(--fog)] hover:text-[var(--pickled-bluewood)]"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div
          ref={viewportRef}
          className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-4"
        >
          {messages.length === 0 && (
            <div className="flex flex-col items-center gap-3 py-4 text-center text-sm text-[var(--slate)]">
              <p className="m-0 text-[var(--pickled-bluewood)]">
                Ask the agent about this dataset. It can read the profile,
                query rows, and cite specific sheet/column/value evidence.
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {STARTER_PROMPTS.map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => void sendMessage(p)}
                    className="max-w-xs rounded-full border border-[var(--geyser)] bg-white px-3 py-1.5 text-xs text-[var(--pickled-bluewood)] transition-colors hover:border-[var(--coral)] hover:text-[var(--coral)]"
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
        </div>

        {error && (
          <div
            role="alert"
            className="mx-4 rounded-md border border-[var(--watermelon)] bg-white px-3 py-2 text-xs text-[var(--watermelon)]"
          >
            {error}
          </div>
        )}

        <form
          onSubmit={handleSubmit}
          className="mt-2 flex flex-col gap-2 border-t border-[var(--geyser)] bg-white p-3"
          aria-label="data quality chat composer"
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={3}
            placeholder="Ask about a column, a sheet, or a specific row..."
            aria-label="Chat message"
            className="block w-full resize-none rounded-lg border border-[var(--geyser)] bg-white px-3 py-2 text-sm text-[var(--pickled-bluewood)] placeholder:text-[var(--heather)] focus:border-[var(--cerulean)] focus:outline-none focus:ring-2 focus:ring-[var(--cerulean)]/20"
          />
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] text-[var(--heather)]">
              Enter sends · Shift+Enter for a new line
            </span>
            {isRunning ? (
              <button
                type="button"
                onClick={handleCancel}
                aria-label="Stop generating"
                className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--watermelon)] text-white"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                aria-label="Send"
                className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--coral)] text-white shadow-sm transition-all hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <ArrowUp className="h-4 w-4" />
              </button>
            )}
          </div>
        </form>
      </aside>
    </>
  );
}

function MessageBubble({ message }: { message: LocalMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-[var(--coral)] px-4 py-2 text-sm text-white shadow-sm">
          {message.text}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {message.thinking && (
        <details className="rounded-md border border-dashed border-[var(--geyser)] bg-white px-3 py-2 text-xs text-[var(--slate)]">
          <summary className="cursor-pointer select-none font-medium">
            Thinking
          </summary>
          <div className="mt-2 whitespace-pre-wrap leading-relaxed">
            {message.thinking}
          </div>
        </details>
      )}
      {message.toolCalls.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {message.toolCalls.map((tc) => (
            <span
              key={tc.id}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border bg-white px-2 py-0.5 font-mono text-[10px]",
                tc.isError
                  ? "border-[var(--watermelon)] text-[var(--watermelon)]"
                  : "border-[var(--geyser)] text-[var(--slate)]",
              )}
              title={tc.result ?? "running..."}
            >
              <Wrench className="h-2.5 w-2.5" />
              {tc.name}
              {tc.result === undefined && (
                <Loader2 className="h-2.5 w-2.5 animate-spin" />
              )}
            </span>
          ))}
        </div>
      )}
      <div className="max-w-[95%] whitespace-pre-wrap rounded-2xl bg-[var(--fog)] px-4 py-2 text-sm leading-relaxed text-[var(--pickled-bluewood)]">
        {message.text || (message.status === "running" ? "..." : "(no response)")}
      </div>
      {message.status === "error" && (
        <div className="text-xs text-[var(--watermelon)]">
          Generation failed.
        </div>
      )}
    </div>
  );
}
