import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

/**
 * Per-hour observation counts (per scanner) from `/stats/hourly`.
 *
 * Fuels the activity heatmap (5a) and streamgraph (5b). The endpoint returns a
 * flat list of recent hourly buckets; the chart components re-bucket as needed.
 */
export function useHourlyStats() {
  return useQuery({
    queryKey: ["stats", "hourly"],
    queryFn: async () => {
      const res = await api.GET("/stats/hourly");
      if (res.error) throw new Error("Failed to load hourly activity");
      return res.data;
    },
  });
}
