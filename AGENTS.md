# AGENTS.md

Guidance for coding agents working in this repository.

## Project Overview

RAPT Portal is a local dashboard for RAPT devices:

- `backend/` is a FastAPI service that authenticates against the RAPT API,
  periodically syncs device/session telemetry, stores it in SQLite through
  SQLAlchemy, and serves a small local JSON API.
- `frontend/` is a Vite React TypeScript SPA that reads the local API and
  renders device lists, session pages and charts.
- `docker-compose.yml` runs the backend plus an nginx frontend. nginx serves the
  SPA and proxies `/api` to the backend service.
- `data/` contains the local SQLite database and should be treated as runtime
  state, not source.

## Important Files

- `backend/app.py` - FastAPI app, CORS, router registration, background sync
  lifespan task.
- `backend/sync.py` - RAPT sync logic, session tracking, telemetry inserts,
  gravity estimation.
- `backend/rapt_client.py` - token cache and thin async client for upstream RAPT
  endpoints.
- `backend/db.py` - SQLAlchemy models and database initialization.
- `backend/routers/` - local API routes.
- `backend/serializers.py` - ORM row to API response helpers.
- `frontend/src/api.ts` - frontend API types and fetch helpers.
- `frontend/src/App.tsx` - SPA route map and navigation.
- `frontend/src/pages/` - page-level React views.
- `frontend/src/components/` - chart and shared UI components.

## RAPT API Context

Public OpenAPI spec:

`https://api.rapt.io/swagger/v1/swagger.json`

Authentication:

- Token URL: `https://id.rapt.io/connect/token`
- Form fields: `client_id=rapt-user`, `grant_type=password`,
  `username=$RAPT_USERNAME`, `password=$RAPT_SECRET`
- API base: `https://api.rapt.io`
- Auth scheme: Bearer JWT

Current upstream endpoints used by `backend/rapt_client.py`:

- `GET /api/Hydrometers/GetHydrometers`
- `GET /api/Hydrometers/GetTelemetry`
- `GET /api/BrewZillas/GetBrewZillas`
- `GET /api/BrewZillas/GetTelemetry`

Do not assume full session history comes from the public API. The app builds
history locally by observing active profile sessions during sync.

## Development Commands

Backend:

```bash
cd backend
uv sync
uv run uvicorn app:app --reload
uv run python rapt_client.py
uv run python scripts/test_gravities.py
```

Frontend:

```bash
cd frontend
npm install
npm run dev
npm run build
npm run lint
```

Docker:

```bash
docker compose up -d --build
docker compose logs -f backend
docker compose down
```

## Coding Notes

- Keep backend code compatible with Python 3.11+, even though the Docker image
  currently uses Python 3.13.
- Text files in this repo should be UTF-8 with LF endings. Respect the root
  `.editorconfig` and do not introduce cp1251/Windows-1252 encoded files.
- Prefer existing simple module-level helpers over adding abstractions.
- Keep local API response field names in snake_case; the frontend types in
  `frontend/src/api.ts` mirror those names.
- Preserve the append-only telemetry model and deduplication by timestamp.
- Keep timestamps normalized the same way as `sync._dt`: naive UTC in SQLite.
- Be careful around session close behavior. A session is closed when the active
  session id changes or disappears during a sync.
- Do not commit secrets. Runtime secrets belong in `backend/.env`, which is
  gitignored.
- `data/rapt.db` is local runtime data. Do not modify, delete, or include it in
  source changes unless the user explicitly asks for database work.
- Some existing UI strings appear to have encoding damage. Do not mass-rewrite
  unrelated text or encoding as part of narrow changes; fix only the files and
  strings required by the task.
- When reading or writing text in scripts/tools, pass `encoding="utf-8"`
  explicitly. For PowerShell text inspection/editing, prefer explicit UTF-8
  reads/writes. For Python console scripts on Windows, avoid printing raw
  non-ASCII device names unless stdout is known to be UTF-8; use a safe
  escaped/logging representation when needed.

## Git Workflow

- This repository uses a single-branch workflow on `main`.
- Do not create feature branches, agent branches, or PR branches unless the
  user explicitly asks for that workflow.
- Do not suggest PR creation by default. If the user asks to commit and push,
  commit to the current working branch and push that branch.
- Before pushing, verify which branch is checked out and keep the existing
  repository workflow intact.
- If a temporary branch is created by mistake, merge or fast-forward the work
  back to `main` and remove the temporary branch unless the user asks otherwise.

## Verification Expectations

For backend changes:

- Run `uv run python scripts/test_gravities.py` if gravity/session logic changed.
- Run or smoke-check `uv run uvicorn app:app --reload` when route wiring or app
  startup changes.
- Use `uv run python rapt_client.py` only when credentials/network access are
  available and the change touches upstream API behavior.

For frontend changes:

- Run `npm run build` for TypeScript and production build validation.
- Run `npm run lint` when changing TypeScript/React code.
- Check responsive layout manually for page or chart changes.

For Docker/deployment changes:

- Run `docker compose up -d --build` when practical.
- Verify `GET /health` through the backend and the nginx-served SPA through the
  published frontend port.
