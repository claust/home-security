import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router";
import { Overview } from "@/routes/Overview";
import "@/index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // The archive API can return a transient 500 on the first request after
      // an idle period; retry a few times with a short backoff so the dashboard
      // recovers on its own instead of getting stuck on a one-off failure.
      retry: 4,
      retryDelay: (attempt) => Math.min(400 * 2 ** attempt, 3000),
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Overview />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
