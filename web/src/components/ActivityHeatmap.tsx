import { useCallback, useMemo } from "react";
import * as Plot from "@observablehq/plot";
import { PlotFigure } from "@/components/PlotFigure";
import {
  type HeatCell,
  type HourlyBucket,
  toHeatmapCells,
  WEEKDAY_ORDER,
  weekdayLabel,
} from "@/lib/hourly";

// `tip` is absent from CellOptions in @observablehq/plot 0.6.17's type defs
// though it works at runtime -- derive the param type and widen for the cast.
type CellOpts = Parameters<typeof Plot.cell>[1];

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * Activity heatmap (brainstorm 5a): a weekday x hour-of-day grid where each
 * cell's colour is its mean observation volume. Reveals the rhythm of the area
 * -- the quiet small hours, the busy stretches, an odd hot cell.
 */
export function ActivityHeatmap({ buckets }: { buckets: HourlyBucket[] }) {
  const cells = useMemo(() => toHeatmapCells(buckets), [buckets]);

  const render = useCallback(
    (width: number) =>
      Plot.plot({
        width,
        height: 260,
        marginLeft: 44,
        marginRight: 0,
        marginTop: 8,
        marginBottom: 34,
        style: {
          background: "transparent",
          color: "#64748b",
          fontFamily: "inherit",
          fontSize: "11px",
        },
        x: {
          domain: Array.from({ length: 24 }, (_, i) => i),
          tickSize: 0,
          label: "Hour of day (UTC) →",
          labelAnchor: "right",
          tickFormat: (h: number) => (h % 3 === 0 ? pad(h) : ""),
        },
        y: {
          domain: WEEKDAY_ORDER,
          tickSize: 0,
          label: null,
        },
        color: {
          type: "sqrt",
          scheme: "YlGnBu",
          legend: true,
          label: "Avg observations / hour",
        },
        marks: [
          Plot.cell(cells, {
            x: "hour",
            y: (d: HeatCell) => weekdayLabel(d.day),
            fill: "observations",
            inset: 1.5,
            rx: 3,
            tip: {
              format: {
                x: (h: number) => `${pad(h)}:00-${pad((h + 1) % 24)}:00 UTC`,
                y: true,
                fill: (v: number) => `${v.toLocaleString()} obs/h (avg)`,
              },
            },
          } as unknown as CellOpts),
        ],
      }),
    [cells],
  );

  return <PlotFigure render={render} className="-ml-1" />;
}
