import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

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
 * Overview page — proves the typed pipe end-to-end: TanStack Query → typed
 * openapi-fetch client → Vite proxy → FastAPI → SQLite archive.
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

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
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
    </main>
  );
}
