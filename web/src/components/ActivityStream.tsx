import { useCallback, useMemo } from "react";
import * as Plot from "@observablehq/plot";
import { PlotFigure } from "@/components/PlotFigure";
import { type HourlyBucket, scannersIn, toStreamSeries } from "@/lib/hourly";

// One saturated band per scanner, cohesive with the indigo UI.
const PALETTE = ["#6366f1", "#14b8a6", "#f59e0b", "#ec4899", "#0ea5e9"];

/**
 * Activity streamgraph (brainstorm 5b): ambient BLE volume over time, stacked
 * by scanner as flowing bands. Total height is overall activity; each band is
 * one scanner's share. A band thinning to nothing = that scanner went dark.
 */
export function ActivityStream({ buckets }: { buckets: HourlyBucket[] }) {
  const points = useMemo(() => toStreamSeries(buckets), [buckets]);
  const scanners = useMemo(() => scannersIn(buckets), [buckets]);

  const render = useCallback(
    (width: number) =>
      Plot.plot({
        width,
        height: 300,
        marginLeft: 8,
        marginRight: 8,
        marginTop: 12,
        marginBottom: 28,
        style: {
          background: "transparent",
          color: "#64748b",
          fontFamily: "inherit",
          fontSize: "11px",
        },
        x: {
          type: "utc",
          label: null,
          grid: true,
          ticks: 6,
        },
        y: { axis: null },
        color: {
          domain: scanners,
          range: PALETTE.slice(0, Math.max(scanners.length, 1)),
          legend: true,
        },
        marks: [
          Plot.areaY(points, {
            x: "hour",
            y: "observations",
            z: "scanner",
            fill: "scanner",
            offset: "wiggle",
            curve: "basis",
            fillOpacity: 0.9,
            tip: {},
          }),
        ],
      }),
    [points, scanners],
  );

  return <PlotFigure render={render} />;
}
