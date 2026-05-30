import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useHourlyStats } from "@/api/hooks";
import { ActivityHeatmap } from "@/components/ActivityHeatmap";
import { ActivityStream } from "@/components/ActivityStream";

/** A single labelled metric card. */
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-sm font-medium text-slate-500">{label}</div>
      <div className="mt-1 text-3xl font-semibold tabular-nums text-slate-900">{value}</div>
    </div>
  );
}

function formatInstant(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

/**
 * A titled dashboard panel that hosts a chart, with its own loading / error
 * state so a slow chart query never blocks the metric cards above.
 */
function ChartCard({
  title,
  subtitle,
  status,
  children,
}: {
  title: string;
  subtitle: string;
  status: { isPending: boolean; isError: boolean };
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>
      <div className="mt-4 min-h-[260px]">
        {status.isPending && <p className="text-slate-400">Loading chart…</p>}
        {status.isError && <p className="text-red-600">Failed to load chart data.</p>}
        {children}
      </div>
    </section>
  );
}

/**
 * Overview page — proves the typed pipe end-to-end (TanStack Query → typed
 * openapi-fetch client → Vite proxy → FastAPI → SQLite archive) and turns the
 * static snapshot into a living dashboard with the activity heatmap (5a) and
 * streamgraph (5b).
 */
export function Overview() {
  const { data, error, isPending } = useQuery({
    queryKey: ["overview"],
    queryFn: async () => {
      const res = await api.GET("/stats/overview");
      if (res.error) throw new Error("Failed to load overview");
      return res.data;
    },
  });

  const hourly = useHourlyStats();

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="text-2xl font-bold text-slate-900">Home Security</h1>
      <p className="mt-1 text-slate-500">Archive overview</p>

      {isPending && <p className="mt-8 text-slate-500">Loading…</p>}
      {error && <p className="mt-8 text-red-600">{error.message}</p>}

      {data && (
        <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Stat label="Total observations" value={data.total_observations.toLocaleString()} />
          <Stat label="Distinct addresses" value={data.distinct_addresses.toLocaleString()} />
          <Stat label="Scanners" value={data.scanner_count.toLocaleString()} />
          <Stat label="First observed" value={formatInstant(data.first_observed_utc)} />
          <Stat label="Last observed" value={formatInstant(data.last_observed_utc)} />
          <Stat label="Last ingest" value={formatInstant(data.last_ingest_at_utc)} />
        </div>
      )}

      <div className="mt-10 grid grid-cols-1 gap-6">
        <ChartCard
          title="Activity rhythm"
          subtitle="Average observation volume by day of week and hour of day (UTC). Darker is busier."
          status={hourly}
        >
          {hourly.data && <ActivityHeatmap buckets={hourly.data} />}
        </ChartCard>

        <ChartCard
          title="Ambient BLE activity"
          subtitle="Hourly observations over time, stacked by scanner. A band thinning to nothing means that scanner went quiet."
          status={hourly}
        >
          {hourly.data && <ActivityStream buckets={hourly.data} />}
        </ChartCard>
      </div>
    </main>
  );
}
