"use client";

/**
 * Dynamic-import wrapper around react-plotly.js.
 *
 * Plotly is ~300KB even with the basic-dist bundle, so we never want it in
 * the initial JS payload. Components that need a chart render this wrapper;
 * it lazy-loads the bundle on first mount and shows a small spinner placeholder
 * during the swap. The same pattern is used for cytoscape in BcmGraph.
 */

import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState, type ComponentType } from "react";
import type { Data, Layout, Config } from "plotly.js";
import type { PlotParams } from "react-plotly.js";

export type PlotlyChartProps = {
  data: Data[];
  layout?: Partial<Layout>;
  config?: Partial<Config>;
  className?: string;
  ariaLabel?: string;
};

type LazyPlot = ComponentType<PlotParams>;

export default function PlotlyChart({
  data,
  layout,
  config,
  className,
  ariaLabel,
}: PlotlyChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [PlotComp, setPlotComp] = useState<LazyPlot | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // The basic bundle covers bar, pie, line, scatter, histogram - plenty
      // for this dashboard; switch to the full dist only when we need
      // 3d/maps/etc.
      const [plotly, factoryMod] = await Promise.all([
        import("plotly.js-basic-dist-min"),
        import("react-plotly.js/factory"),
      ]);
      if (cancelled) return;
      const createPlotlyComponent = factoryMod.default;
      const Plot = createPlotlyComponent(
        plotly.default as unknown as object,
      ) as unknown as LazyPlot;
      setPlotComp(() => Plot);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const baseLayout: Partial<Layout> = {
    autosize: true,
    margin: { l: 36, r: 8, t: 8, b: 32 },
    font: {
      family: '-apple-system, "Segoe UI", Roboto, sans-serif',
      color: "#1e3a52",
      size: 11,
    },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    ...layout,
  };
  const baseConfig: Partial<Config> = {
    displayModeBar: false,
    responsive: true,
    ...config,
  };

  return (
    <div
      ref={containerRef}
      className={className}
      aria-label={ariaLabel}
      role="img"
    >
      {PlotComp ? (
        <PlotComp
          data={data}
          layout={baseLayout}
          config={baseConfig}
          style={{ width: "100%", height: "100%" }}
          useResizeHandler
        />
      ) : (
        <div className="grid h-full w-full place-items-center text-[var(--slate)]">
          <Loader2 className="h-4 w-4 animate-spin" />
        </div>
      )}
    </div>
  );
}
