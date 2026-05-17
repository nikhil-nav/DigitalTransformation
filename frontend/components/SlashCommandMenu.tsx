"use client";

import { ChevronUp, Slash } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

export type SlashCommand = {
  /** What the user types after the slash, e.g. "critique". */
  name: string;
  /** Short user-facing label. */
  label: string;
  /** One-line description shown in the menu. */
  description: string;
  /** The expanded prompt text that gets sent. */
  prompt: string;
};

export const DEFAULT_COMMANDS: SlashCommand[] = [
  {
    name: "critique",
    label: "/critique",
    description: "Score the current BCM and list improvements",
    prompt:
      "Critique the Business Capability Map currently saved on this project. " +
      "Score it 1-10 with one-line justification, then list 3-5 concrete improvements.",
  },
  {
    name: "export",
    label: "/export",
    description: "Extract a BCM from this conversation and write it to the Kanban",
    prompt:
      "Review our conversation above and extract a complete Business Capability Map. " +
      "Identify all L1, L2, and L3 capabilities, organise them into a proper hierarchy, " +
      "and call set_capabilities to write the full tree to the project.",
  },
  {
    name: "research",
    label: "/research",
    description: "Research a company URL and update the BCM",
    prompt:
      "Please research the company at this URL: <paste URL here>. " +
      "Use fetch_url and web_search as needed; then update the BCM via set_capabilities.",
  },
  {
    name: "refine",
    label: "/refine",
    description: "Refine the current BCM based on the discussion",
    prompt:
      "Refine the current Business Capability Map based on what we have discussed. " +
      "Tighten naming, fix any anti-patterns, and call set_capabilities with the updated tree.",
  },
  {
    name: "template-retail",
    label: "/template retail",
    description: "Start from a Retail industry template",
    prompt:
      "Build a starter Business Capability Map using a Retail industry template " +
      "(merchandising, supply chain, sales channels, customer management, finance, people). " +
      "Call set_capabilities with the tree, then ask which area to deepen.",
  },
  {
    name: "template-saas",
    label: "/template saas",
    description: "Start from a B2B SaaS industry template",
    prompt:
      "Build a starter Business Capability Map using a B2B SaaS template " +
      "(product development, customer acquisition, customer success, billing, infrastructure, " +
      "people, finance & risk). Call set_capabilities with the tree, then ask which area to deepen.",
  },
  {
    name: "template-finserv",
    label: "/template finserv",
    description: "Start from a Financial Services template",
    prompt:
      "Build a starter Business Capability Map using a Financial Services template " +
      "(client onboarding, products & services, transactions & payments, lending & credit, " +
      "risk & compliance, treasury, finance, people, IT). Call set_capabilities with the tree, " +
      "then ask which area to deepen.",
  },
];

export default function SlashCommandMenu({
  disabled,
  onSelect,
}: {
  disabled?: boolean;
  onSelect: (prompt: string, command: SlashCommand) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-label="Slash commands"
        title="Slash commands"
        className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-[var(--geyser)] bg-white text-[var(--slate)] transition-all hover:border-[var(--coral)] hover:text-[var(--coral)] disabled:cursor-not-allowed disabled:opacity-50"
      >
        {open ? (
          <ChevronUp className="h-4 w-4" />
        ) : (
          <Slash className="h-4 w-4" />
        )}
      </button>
      {open && (
        <div
          className={cn(
            "absolute bottom-full left-0 z-50 mb-2 w-80 rounded-lg border border-[var(--geyser)] bg-white p-1 shadow-lg",
          )}
        >
          <div className="border-b border-[var(--geyser)] px-2 py-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
            Slash commands
          </div>
          <ul className="max-h-72 overflow-y-auto py-1">
            {DEFAULT_COMMANDS.map((cmd) => (
              <li key={cmd.name}>
                <button
                  type="button"
                  onClick={() => {
                    onSelect(cmd.prompt, cmd);
                    setOpen(false);
                  }}
                  className="flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[var(--fog)]"
                >
                  <span className="font-mono text-xs font-semibold text-[var(--coral)]">
                    {cmd.label}
                  </span>
                  <span className="text-xs text-[var(--slate)]">
                    {cmd.description}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
