# API Software

Read-only HTTP API over `~/.local/state/home-security/archive.sqlite3`.

## Run

```sh
uv run home-security-api
```

Defaults to `http://127.0.0.1:8002`. OpenAPI docs at `/docs`, schema at `/openapi.json`.

## Configuration

Environment variables (all prefixed `HOME_SECURITY_API_`):

| Variable | Default | Notes |
| --- | --- | --- |
| `HOME_SECURITY_API_ARCHIVE_PATH` | `~/.local/state/home-security/archive.sqlite3` | Read-only sqlite path |
| `HOME_SECURITY_API_HOST` | `127.0.0.1` | Bind address — keep loopback unless you know what you're doing |
| `HOME_SECURITY_API_PORT` | `8002` | |
| `HOME_SECURITY_API_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated. Empty disables CORS. |

## Endpoints

| Group | Path |
| --- | --- |
| Meta | `GET /health`, `GET /stats/overview` |
| Scanners | `GET /scanners`, `GET /scanners/{scanner_id}` |
| Addresses | `GET /addresses`, `GET /addresses/{address}`, `GET /addresses/{address}/observations` |
| Observations | `GET /observations` |
| Stats | `GET /stats/hourly`, `GET /stats/vendors` |
| Search | `GET /search` |

The OpenAPI schema is the source of truth — point a typed client generator at `/openapi.json`.

A generated copy is committed at [`openapi.json`](openapi.json). Regenerate it
without running the server (or having an archive present) with:

```sh
uv run home-security-api-openapi openapi.json
```

Omit the path argument to write the schema to stdout instead.
