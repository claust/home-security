import type { components } from "@/api/schema";

/** One (hour, scanner) row from `/stats/hourly`. */
export type HourlyBucket = components["schemas"]["HourlyBucket"];

/** One hour-of-day x day-of-week cell for the activity heatmap (5a). */
export interface HeatCell {
  /** 0 = Sunday ... 6 = Saturday (UTC). */
  day: number;
  /** 0-23 (UTC). */
  hour: number;
  /** Mean observations seen in this weekday/hour slot (0 if never sampled). */
  observations: number;
  /** How many calendar days contributed to this cell. */
  samples: number;
}

/** One point in the activity streamgraph (5b): a scanner in a single hour. */
export interface StreamPoint {
  hour: Date;
  scanner: string;
  observations: number;
}

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Heatmap row order: Monday at the top, Sunday at the bottom. */
export const WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function weekdayLabel(day: number): string {
  return WEEKDAY_LABELS[day];
}

/** Distinct scanners present in the response, in first-seen order. */
export function scannersIn(buckets: HourlyBucket[]): string[] {
  const seen = new Set<string>();
  for (const b of buckets) seen.add(b.scanner_id);
  return [...seen];
}

/**
 * Re-bucket hourly rows into a complete 7x24 weekday/hour grid for the heatmap.
 *
 * Cells hold the *mean* observations per occurrence, not the sum: the archive
 * samples hours unevenly (outages leave gaps), so averaging keeps a slot that
 * happened to be recorded twice from looking artificially hotter. Times stay in
 * UTC (the form the archive stores) so the rhythm reads cleanly regardless of
 * the viewer's timezone. All 168 cells are emitted, even never-sampled ones.
 */
export function toHeatmapCells(buckets: HourlyBucket[]): HeatCell[] {
  const sums = new Map<string, number>();
  const counts = new Map<string, number>();
  for (const b of buckets) {
    const d = new Date(b.hour_utc);
    const key = `${d.getUTCDay()}-${d.getUTCHours()}`;
    sums.set(key, (sums.get(key) ?? 0) + b.observations);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  const cells: HeatCell[] = [];
  for (let day = 0; day < 7; day++) {
    for (let hour = 0; hour < 24; hour++) {
      const key = `${day}-${hour}`;
      const samples = counts.get(key) ?? 0;
      cells.push({
        day,
        hour,
        observations: samples ? Math.round((sums.get(key) ?? 0) / samples) : 0,
        samples,
      });
    }
  }
  return cells;
}

/**
 * Build a gap-aware, per-scanner hourly series for the streamgraph.
 *
 * Every hour from the first to the last bucket is emitted for every scanner,
 * filling absent (scanner, hour) pairs with 0. That keeps each band continuous
 * and makes an outage show up as the band pinching to nothing -- the health
 * signal called out in the brainstorm.
 */
export function toStreamSeries(buckets: HourlyBucket[]): StreamPoint[] {
  if (buckets.length === 0) return [];

  const scanners = scannersIn(buckets);
  const lookup = new Map<string, number>(); // `${ms}-${scanner}` -> observations
  let minMs = Infinity;
  let maxMs = -Infinity;

  for (const b of buckets) {
    const ms = new Date(b.hour_utc).getTime();
    minMs = Math.min(minMs, ms);
    maxMs = Math.max(maxMs, ms);
    lookup.set(`${ms}-${b.scanner_id}`, b.observations);
  }

  const HOUR = 3_600_000;
  const points: StreamPoint[] = [];
  for (let ms = minMs; ms <= maxMs; ms += HOUR) {
    for (const scanner of scanners) {
      points.push({
        hour: new Date(ms),
        scanner,
        observations: lookup.get(`${ms}-${scanner}`) ?? 0,
      });
    }
  }
  return points;
}
