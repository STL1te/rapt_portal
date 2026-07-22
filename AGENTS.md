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
- `backend/core/` - cross-cutting infrastructure shared by all features:
  - `core/config.py` - env-driven settings.
  - `core/db.py` - SQLAlchemy models and database initialization.
  - `core/sync.py` - RAPT sync logic, session tracking, telemetry inserts,
    gravity estimation.
  - `core/rapt_client.py` - token cache and thin async client for upstream RAPT
    endpoints.
  - `core/serializers.py` - generic ORM row -> dict helper.
  - `core/db_migrations.py` - alembic upgrade runner used by `init_db`.
- `backend/features/<name>/` - one folder per feature, each with `router.py`
  (local API routes) and, where needed, `services.py` (feature logic and
  serialization): `hydrometers`, `brewzillas`, `yeasts`, `ai`, `system`.
- `backend/features/ai/services.py` - OpenAI-compatible LLM client,
  session-context builders and whitelisted tool-use loop.
- `backend/features/system/services.py` - DB-backed background sync jobs.
- `backend/prompts/` - UTF-8 Russian system prompts for brewing and fermentation.
- `frontend/src/api/` - fetch helpers (`client.ts`) plus one module per domain
  (`hydrometers`, `brew`, `yeasts`, `system`, `ai`); `index.ts` re-exports the
  endpoints and their types, so callers import from `@/api`.
- `frontend/src/types/` - API response types, split by domain, re-exported from
  `types/index.ts` (`@/types`).
- `frontend/src/lib/` - framework-agnostic helpers (`fmt.ts` formatting).
- `frontend/src/hooks/` - React hooks (`useTitle.ts`).
- `frontend/src/App.tsx` - SPA route map and navigation.
- `frontend/src/pages/` - page-level React views.
- `frontend/src/components/` - chart and shared UI components.
- Imports inside `frontend/src` use the `@/` alias (`@` -> `src`), configured in
  `vite.config.ts` and `tsconfig.app.json`. Prefer it over `../` chains.

## RAPT API Context

Public OpenAPI spec:

`https://api.rapt.io/swagger/v1/swagger.json`

Authentication:

- Token URL: `https://id.rapt.io/connect/token`
- Form fields: `client_id=rapt-user`, `grant_type=password`,
  `username=$RAPT_USERNAME`, `password=$RAPT_SECRET`
- API base: `https://api.rapt.io`
- Auth scheme: Bearer JWT

Current upstream endpoints used by `backend/core/rapt_client.py`:

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
uv run python -m core.rapt_client
uv run python scripts/test_gravities.py
```

Frontend:

```bash
cd frontend
npm install
npm run fmt
npm run fmt:check
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
- If a touched file already contains Cyrillic UI text, preserve it as UTF-8 and
  avoid edit paths that can mojibake the file; verify the saved file still shows
  readable Cyrillic before handoff.
- Prefer existing simple module-level helpers over adding abstractions.
- Keep local API response field names in snake_case; the frontend types in
  `frontend/src/types/` mirror those names.
- Preserve the append-only telemetry model and deduplication by timestamp.
- Keep timestamps normalized the same way as `sync._dt`: naive UTC in SQLite.
- Be careful around session close behavior. A session is closed when the active
  session id changes or disappears during a sync.
- Do not commit secrets. Runtime secrets belong in `backend/.env`, which is
  gitignored.
- Keep the AI backend OpenAI-compatible. Ollama-only controls belong in
  `LLM_EXTRA_BODY_JSON` or `LLM_KEEP_ALIVE`, so cloud providers can disable
  them through configuration.
- The LLM may only access local session data through the whitelisted tools in
  `backend/features/ai/services.py`; never expose SQL, arbitrary URLs, filesystem access or write
  operations to the model.
- Keep AI context focused on brewing: omit device-health fields such as battery
  and RSSI unless a feature explicitly needs them. Preserve UTF-8 Cyrillic in
  prompt files and require Russian answers there.
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
- The shell here is PowerShell. Do not use `&&` as a command separator; run
  commands separately or use PowerShell-valid control flow.
- Before committing code changes, run the project formatter for the touched
  stack:
  - frontend: `npm run fmt`
  - backend: `uv run ruff format .` and `uv run ruff check . --fix`
- Before build or final verification, run format checks for the touched stack:
  - frontend: `npm run fmt:check`
  - backend: `uv run ruff format --check .` and `uv run ruff check .`

## Git Workflow

- This repository uses a single-branch workflow on `main`.
- Do not create feature branches, agent branches, or PR branches unless the
  user explicitly asks for that workflow.
- Do not suggest PR creation by default. If the user asks to commit and push,
  commit to the current working branch and push that branch.
- Do not run `git` operations that mutate repository state in parallel. In
  particular, do not parallelize any combination of `git add`, `git commit`,
  `git merge`, `git rebase`, `git push`, or `git checkout` / `git switch`.
- Before pushing, verify which branch is checked out and keep the existing
  repository workflow intact.
- If a temporary branch is created by mistake, merge or fast-forward the work
  back to `main` and remove the temporary branch unless the user asks otherwise.

## Verification Expectations

For backend changes:

- Run `uv run ruff format --check .` and `uv run ruff check .` before commit
  and before handoff.
- Run `uv run python scripts/test_gravities.py` if gravity/session logic changed.
- Run or smoke-check `uv run uvicorn app:app --reload` when route wiring or app
  startup changes.
- Use `uv run python -m core.rapt_client` only when credentials/network access are
  available and the change touches upstream API behavior.
- Run `uv run python scripts/test_ai.py` when changing AI prompts, context,
  tools or the LLM client.

For frontend changes:

- Run `npm run fmt:check` before commit and before handoff.
- Run `npm run build` for TypeScript and production build validation.
- Run `npm run lint` when changing TypeScript/React code.
- Check responsive layout manually for page or chart changes.

For Docker/deployment changes:

- Run `docker compose up -d --build` when practical.
- Verify `GET /health` through the backend and the nginx-served SPA through the
  published frontend port.
