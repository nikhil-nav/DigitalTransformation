import Link from "next/link";

import type { ProjectType } from "@/lib/api";

const DESCRIPTIONS: Record<string, string> = {
  value_discovery:
    "Identify and prioritise opportunities, with estimated value and effort.",
  business_process_discovery:
    "Map current-state processes and surface friction points.",
  ai_assessment:
    "Evaluate where AI can add measurable value across the business.",
  data_quality_assessment:
    "Score data assets against fitness-for-use criteria.",
};

export default function ProjectTypesPanel({ types }: { types: ProjectType[] }) {
  if (types.length === 0) {
    return null;
  }

  return (
    <section className="card">
      <div className="row-between">
        <h2>Project types</h2>
        <span className="meta">
          {types.filter((t) => t.is_active).length} active &middot;{" "}
          {types.filter((t) => !t.is_active).length} coming soon
        </span>
      </div>
      <ul className="type-list">
        {types.map((t) => (
          <li
            key={t.code}
            className={`type-row${t.is_active ? "" : " disabled"}`}
            title={t.is_active ? undefined : "Not available in the MVP"}
          >
            <div className="type-row-main">
              <span className="type-row-name">{t.name}</span>
              <span className="type-row-desc">
                {DESCRIPTIONS[t.code] ?? ""}
              </span>
            </div>
            <span className={`badge${t.is_active ? " badge-active" : ""}`}>
              {t.is_active ? "Active" : "Coming soon"}
            </span>
            {t.is_active && (
              <Link href="/projects/new" className="link-button">
                Start &rarr;
              </Link>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
