import createClient from "openapi-fetch";
import type { paths } from "./schema";

// Same-origin "/api" — Vite proxies it to the FastAPI on :8002 (see vite.config.ts).
// Typed end-to-end: paths come from schema.d.ts, generated from api/openapi.json.
export const api = createClient<paths>({ baseUrl: "/api" });
