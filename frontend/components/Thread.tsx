"use client";

import {
  ActionBarPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useMessage,
  type ReasoningMessagePartProps,
  type TextMessagePartProps,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import {
  ArrowUp,
  Brain,
  Check,
  Copy,
  ExternalLink,
  Loader2,
  RefreshCw,
  Sparkles,
  Square,
  Wrench,
  X,
} from "lucide-react";

import type { Citation } from "@/lib/api";
import { cn } from "@/lib/utils";

const STARTER_PROMPTS = [
  "Build a BCM for a regional retailer; their site is https://example.com",
  "Build a BCM for a B2B SaaS company called Acme Corp",
  "Start from a financial services template and adapt for a community credit union",
  "What information do you need from me to draft a BCM?",
];

export function Thread({
  disabled,
  composerLeading,
}: {
  disabled?: boolean;
  composerLeading?: React.ReactNode;
}) {
  return (
    <ThreadPrimitive.Root className="flex h-full flex-col bg-white">
      <ThreadPrimitive.Viewport className="flex-1 overflow-y-auto px-4 py-4">
        <ThreadPrimitive.Empty>
          <ThreadEmpty disabled={disabled} />
        </ThreadPrimitive.Empty>
        <ThreadPrimitive.Messages
          components={{
            UserMessage,
            AssistantMessage,
          }}
        />
      </ThreadPrimitive.Viewport>
      <div className="px-4 pb-3">
        <Composer disabled={disabled} composerLeading={composerLeading} />
      </div>
    </ThreadPrimitive.Root>
  );
}

function ThreadEmpty({ disabled }: { disabled?: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center text-[var(--slate)]">
      <div className="grid h-12 w-12 place-items-center rounded-full bg-[var(--forget-me-not)] text-[var(--coral)]">
        <Sparkles className="h-6 w-6" />
      </div>
      <div className="text-base font-medium text-[var(--pickled-bluewood)]">
        Build a Business Capability Map
      </div>
      <div className="max-w-sm text-sm">
        Describe a company and the agent will research, propose, and write the
        L1 / L2 / L3 tree to the Kanban on the right.
      </div>
      {!disabled && (
        <div className="mt-2 flex flex-wrap justify-center gap-2">
          {STARTER_PROMPTS.map((p) => (
            <ThreadPrimitive.Suggestion
              key={p}
              prompt={p}
              send
              className="max-w-xs rounded-full border border-[var(--geyser)] bg-white px-3 py-1.5 text-xs text-[var(--pickled-bluewood)] transition-colors hover:border-[var(--coral)] hover:text-[var(--coral)]"
            >
              {p}
            </ThreadPrimitive.Suggestion>
          ))}
        </div>
      )}
    </div>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="mb-4 flex justify-end">
      <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-[var(--coral)] px-4 py-2 text-sm text-white shadow-sm">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="group/message mb-4 flex flex-col gap-2">
      <MessagePrimitive.Parts
        components={{
          Text: AssistantText,
          Reasoning: AssistantReasoning,
          tools: { Fallback: AssistantToolCall },
        }}
      />
      <CitationsFooter />
      <AssistantActionBar />
    </MessagePrimitive.Root>
  );
}

function CitationsFooter() {
  const message = useMessage();
  const citations = (message.metadata?.custom as { citations?: Citation[] } | undefined)?.citations;
  if (!citations || citations.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--slate)]">
        Sources
      </span>
      {citations.map((c, i) => (
        <a
          key={`${c.url}-${i}`}
          href={c.url}
          target="_blank"
          rel="noreferrer"
          title={c.cited_text ?? c.url}
          className="inline-flex max-w-full items-center gap-1 rounded-full border border-[var(--geyser)] bg-white px-2 py-0.5 text-xs text-[var(--cerulean)] hover:border-[var(--cerulean)] hover:bg-[var(--fog)]"
        >
          <span className="text-[10px] font-mono text-[var(--slate)]">
            [{i + 1}]
          </span>
          <span className="max-w-[16rem] truncate">
            {c.title || tryHostname(c.url)}
          </span>
          <ExternalLink className="h-3 w-3 shrink-0 opacity-60" />
        </a>
      ))}
    </div>
  );
}

function tryHostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function AssistantActionBar() {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      autohideFloat="single-branch"
      className="flex items-center gap-1 opacity-0 transition-opacity group-hover/message:opacity-100 data-[floating]:bg-white"
    >
      <ActionBarPrimitive.Copy
        aria-label="Copy message"
        className={iconButtonClass()}
      >
        <Copy className="h-3.5 w-3.5" />
      </ActionBarPrimitive.Copy>
      <ActionBarPrimitive.Reload
        aria-label="Regenerate"
        className={iconButtonClass()}
      >
        <RefreshCw className="h-3.5 w-3.5" />
      </ActionBarPrimitive.Reload>
    </ActionBarPrimitive.Root>
  );
}

function iconButtonClass() {
  return cn(
    "grid h-7 w-7 place-items-center rounded-md border border-transparent text-[var(--slate)]",
    "hover:border-[var(--geyser)] hover:bg-[var(--fog)] hover:text-[var(--pickled-bluewood)]",
    "disabled:cursor-not-allowed disabled:opacity-40",
  );
}

const AssistantText = ({ status }: TextMessagePartProps) => {
  const running = status?.type === "running";
  return (
    <div className="rounded-2xl bg-[var(--fog)] px-4 py-2 text-sm leading-relaxed text-[var(--pickled-bluewood)]">
      <MarkdownTextPrimitive
        smooth
        className="markdown-body"
        components={{
          a: (props) => (
            <a
              {...props}
              target="_blank"
              rel="noreferrer"
              className="text-[var(--cerulean)] underline hover:no-underline"
            />
          ),
          code: (props) => (
            <code
              {...props}
              className="rounded bg-[var(--geyser)] px-1 py-0.5 font-mono text-[0.85em] text-[var(--pickled-bluewood)]"
            />
          ),
          pre: (props) => (
            <pre
              {...props}
              className="my-2 overflow-x-auto rounded-md border border-[var(--geyser)] bg-white p-2 text-xs"
            />
          ),
          ul: (props) => (
            <ul {...props} className="my-2 list-disc pl-5 space-y-0.5" />
          ),
          ol: (props) => (
            <ol {...props} className="my-2 list-decimal pl-5 space-y-0.5" />
          ),
          h1: (props) => (
            <h3 {...props} className="my-2 text-base font-semibold" />
          ),
          h2: (props) => (
            <h4 {...props} className="my-2 text-sm font-semibold" />
          ),
          h3: (props) => (
            <h5 {...props} className="my-1 text-sm font-semibold" />
          ),
          blockquote: (props) => (
            <blockquote
              {...props}
              className="my-2 border-l-2 border-[var(--coral)] pl-3 italic text-[var(--slate)]"
            />
          ),
        }}
      />
      {running && (
        <span className="ml-1 inline-block h-3 w-1 animate-pulse bg-[var(--cerulean)] align-text-bottom" />
      )}
    </div>
  );
};

const AssistantReasoning = ({ text, status }: ReasoningMessagePartProps) => {
  const running = status?.type === "running";
  return (
    <details className="rounded-md border border-dashed border-[var(--geyser)] bg-white px-3 py-2 text-xs text-[var(--slate)]">
      <summary className="flex cursor-pointer select-none items-center gap-2 text-[var(--slate)]">
        <Brain className="h-3.5 w-3.5" />
        <span className="font-medium">
          {running ? "Reasoning..." : "Reasoning"}
        </span>
      </summary>
      <div className="mt-2 whitespace-pre-wrap pl-5 leading-relaxed">
        {text}
      </div>
    </details>
  );
};

const AssistantToolCall = ({
  toolName,
  args,
  argsText,
  result,
  isError,
  status,
}: ToolCallMessagePartProps) => {
  const running = status?.type === "running";
  const summary = summariseArgs(args, argsText);
  return (
    <div
      className={cn(
        "inline-flex max-w-full items-center gap-2 self-start rounded-full border px-3 py-1 font-mono text-xs transition-colors",
        isError
          ? "border-[var(--watermelon)] bg-white text-[var(--watermelon)]"
          : running
            ? "border-[var(--coral)] bg-[var(--forget-me-not)] text-[var(--pickled-bluewood)]"
            : "border-[var(--geyser)] bg-white text-[var(--pickled-bluewood)]",
      )}
      title={
        typeof result === "string"
          ? result
          : result
            ? JSON.stringify(result).slice(0, 400)
            : undefined
      }
    >
      <Wrench className="h-3 w-3 shrink-0 text-[var(--slate)]" />
      <span className="font-semibold">{toolName}</span>
      {summary && (
        <span className="max-w-[260px] truncate text-[var(--slate)]">
          {summary}
        </span>
      )}
      {running ? (
        <Loader2 className="h-3 w-3 shrink-0 animate-spin text-[var(--coral)]" />
      ) : isError ? (
        <X className="h-3 w-3 shrink-0" />
      ) : (
        <Check className="h-3 w-3 shrink-0 text-[var(--jade)]" />
      )}
    </div>
  );
};

function summariseArgs(args: unknown, argsText?: string): string {
  let parsed: Record<string, unknown> | undefined;
  if (args && typeof args === "object") parsed = args as Record<string, unknown>;
  else if (argsText) {
    try {
      parsed = JSON.parse(argsText);
    } catch {
      // ignore
    }
  }
  if (!parsed) return "";
  if (typeof parsed.url === "string") return parsed.url;
  if (typeof parsed.query === "string") return parsed.query;
  if (Array.isArray(parsed.tree)) {
    const n = (parsed.tree as unknown[]).length;
    return `tree of ${n} L1${n === 1 ? "" : "s"}`;
  }
  const keys = Object.keys(parsed);
  if (keys.length === 0) return "";
  if (keys.length === 1) return `${keys[0]}=...`;
  return `(${keys.join(", ")})`;
}

function Composer({
  disabled,
  composerLeading,
}: {
  disabled?: boolean;
  composerLeading?: React.ReactNode;
}) {
  return (
    <ComposerPrimitive.Root
      onSubmit={(e) => e.preventDefault()}
      className={cn(
        "mt-2 flex flex-col gap-2 rounded-2xl border bg-white px-3 py-2 transition-colors",
        "border-[var(--geyser)] focus-within:border-[var(--cerulean)] focus-within:ring-2 focus-within:ring-[var(--cerulean)]/20",
        disabled && "opacity-60",
      )}
    >
      <ComposerPrimitive.Input
        autoFocus
        disabled={disabled}
        rows={3}
        placeholder={
          disabled
            ? "Configure an LLM key above to start chatting"
            : "Type a message...  (Enter to send, Shift+Enter for newline)"
        }
        className="block w-full resize-none bg-transparent px-1 py-1 text-sm leading-relaxed text-[var(--pickled-bluewood)] outline-none placeholder:text-[var(--heather)] disabled:cursor-not-allowed"
      />
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {composerLeading}
        </div>
        <ThreadPrimitive.If running={false}>
          <ComposerPrimitive.Send
            disabled={disabled}
            aria-label="Send message"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[var(--coral)] text-white shadow-sm transition-all hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <ArrowUp className="h-4 w-4" />
          </ComposerPrimitive.Send>
        </ThreadPrimitive.If>
        <ThreadPrimitive.If running>
          <ComposerPrimitive.Cancel
            aria-label="Stop"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[var(--watermelon)] text-white shadow-sm transition-all hover:brightness-95"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
          </ComposerPrimitive.Cancel>
        </ThreadPrimitive.If>
      </div>
    </ComposerPrimitive.Root>
  );
}
