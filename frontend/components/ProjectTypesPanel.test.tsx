import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import ProjectTypesPanel from "./ProjectTypesPanel";

const types = [
  { id: 1, code: "value_discovery", name: "Value Discovery", is_active: true },
  {
    id: 2,
    code: "business_process_discovery",
    name: "Business Process Discovery",
    is_active: false,
  },
  { id: 3, code: "ai_assessment", name: "AI Assessment", is_active: false },
  {
    id: 4,
    code: "data_quality_assessment",
    name: "Data Quality Assessment",
    is_active: false,
  },
];

describe("ProjectTypesPanel", () => {
  afterEach(() => cleanup());

  it("lists all four types with Active and Coming soon badges", () => {
    render(<ProjectTypesPanel types={types} />);

    for (const t of types) {
      expect(screen.getByText(t.name)).toBeInTheDocument();
    }

    const active = screen.getByText("Value Discovery").closest("li")!;
    expect(within(active).getByText("Active")).toBeInTheDocument();
    expect(within(active).getByRole("link", { name: /start/i })).toHaveAttribute(
      "href",
      "/projects/new",
    );

    const inactive = screen.getByText("AI Assessment").closest("li")!;
    expect(within(inactive).getByText("Coming soon")).toBeInTheDocument();
    expect(within(inactive).queryByRole("link", { name: /start/i })).toBeNull();

    expect(screen.getByText(/1 active/i)).toBeInTheDocument();
    expect(screen.getByText(/3 coming soon/i)).toBeInTheDocument();
  });

  it("renders nothing when there are no types", () => {
    const { container } = render(<ProjectTypesPanel types={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
