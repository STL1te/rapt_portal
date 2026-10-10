# AGENTS.md

Guidance for coding agents working in this repository.

## Project Overview

RAPT Portal is a self-hosted dashboard for RAPT devices:

- `backend/` is a FastAPI service that authenticates against the RAPT API,
  periodically syncs device/session telemetry, stores it in PostgreSQL through
  SQLAlchemy, and serves a local JSON API. It also keeps a local profile
  library, compiles recipes into BrewZilla profiles and runs the AI features.
- `frontend/` is a Vite React TypeScript SPA that reads the local API and
  renders devices, sessions, charts, the profile editor and the AI chat.
- `docker-compose.yml` runs the backend plus an nginx frontend. nginx serves the
  SPA and proxies `/api` to the backend service. PostgreSQL is external; the
  compose file does not start one.
- The repository is public. See the notes on secrets and personal data below.

## Important Files

- `backend/app.py` - FastAPI app, CORS, router registration, background sync
  lifespan task.
- `backend/core/` - cross-cutting infrastructure shared by all features:
  - `core/config.py` - env-driven settings, including the three LLM roles.
  - `core/db.py` - SQLAlchemy models, engine and session factory.
  - `core/sync.py` - RAPT sync logic, session tracking, telemetry inserts,
    gravity estimation.
  - `core/rapt_client.py` - token cache and thin async client for upstream RAPT
    endpoints.
  - `core/rapt_auth.py` - RAPT OAuth login (PKCE), encrypted refresh-token
    storage and the bearer token used by portal-only calls.
  - `core/serializers.py` - generic ORM row -> dict helper.
- `backend/alembic/` - migrations. They are a deploy step
  (`uv run alembic upgrade head`); the app does not run them on startup.
- `backend/features/<name>/` - one folder per feature, each with `router.py`
  (local API routes) and, where needed, `services.py` (feature logic and
  serialization): `hydrometers`, `brewzillas`, `profiles`, `yeasts`, `ai`,
  `system`. `recipes` has no routes: it is the shared recipe model, the
  importers and the profile compiler.
- `backend/features/recipes/` - `importers.py` (BrewFather JSON, BeerXML,
  BeerJSON -> `RecipeModel`), `brewzilla_compiler.py` (deterministic
  `RecipeModel` -> BrewZilla profile), `brewzilla_overrides.py` (device settings
  a recipe does not carry).
- `backend/features/profiles/services.py` - profile library sync from RAPT,
  local drafts and the upload back to RAPT.
- `backend/features/ai/services.py` - OpenAI-compatible LLM client,
  server-owned conversations, session-context builders and the whitelisted
  tool-use loop.
- `backend/features/ai/recipe_wizard.py` - free-text recipe -> BeerJSON
  extraction, semantic validation by a judge model, then the same compiler.
- `backend/features/system/services.py` - DB-backed background sync jobs;
  `portal_sync.py` - past-session backfill from the portal-only endpoints.
- `backend/prompts/` - English system prompts for the assistant, the recipe
  wizard and its validator, plus `default_questions.json` (localized default
  questions, `en` and `ru`).
- `backend/vendor/beerjson/` - vendored BeerJSON 1.0 schema. Do not edit.
- `backend/tests/` - pytest suite; `tests/data/` holds recipe export fixtures.
- `backend/scripts/` - distillation, dataset and evaluation tooling for the
  recipe-wizard model. Not part of the running app.
- `frontend/src/api/` - fetch helpers (`client.ts`) plus one module per domain
  (`hydrometers`, `brew`, `profiles`, `yeasts`, `system`, `ai`); `index.ts`
  re-exports the endpoints and their types, so callers import from `@/api`.
- `frontend/src/types/` - API response types, split by domain, re-exported from
  `types/index.ts` (`@/types`).
- `frontend/src/lib/` - framework-agnostic helpers (`fmt.ts` formatting).
- `frontend/src/hooks/` - React hooks (`useTitle.ts`).
- `frontend/src/App.tsx` - SPA route map and navigation.
- `frontend/src/pages/` - page-level React views, one folder per area
  (`hydrometers`, `brewzillas`, `profiles`, `yeasts`, `admin`).
- `frontend/src/components/` - chart and shared UI components.
- Imports inside `frontend/src` use the `@/` alias (`@` -> `src`), configured in
  `vite.config.ts` and `tsconfig.app.json`. Prefer it over `../` chains.
- `docs/` - design notes and plans. They record decisions at the time of
  writing and are not kept in sync with the code.

## RAPT API Context

Public OpenAPI spec:

`https://api.rapt.io/swagger/v1/swagger.json`

Authentication (`core/rapt_auth.py`, preferred):

- OAuth authorization code + PKCE as the `rapt-web` public client, the same one
  app.rapt.io uses. id.rapt.io accepts no other redirect than
  `https://app.rapt.io/callback`, so the code cannot land on this app: the user
  pastes the callback address into the System Syncs page once, and the refresh
  token (encrypted with `APP_SECRET`, stored in `app_settings`) keeps both the
  public API and the portal-only endpoints signed in.
- Authorize URL: `https://id.rapt.io/connect/authorize`; token URL:
  `https://id.rapt.io/connect/token`; client `rapt-web`; scope
  `openid profile rapt-api rapt-api.user IdentityServerApi offline_access`.
- Device code and client credentials are rejected for every public RAPT client,
  and only `app.rapt.io/callback` is a registered redirect — do not "fix" the
  flow by pointing it at localhost.
- RAPT rotates the refresh token on every use and the old one stops working.
  Always store the new one, and never clear the stored row because a refresh
  failed: another instance on the same database may have just rotated it.

Authentication (legacy fallback, used only when nobody has logged in):

- Token URL: `https://id.rapt.io/connect/token`
- Form fields: `client_id=rapt-user`, `grant_type=password`,
  `username=$RAPT_USERNAME`, `password=$RAPT_SECRET`
- Portal-only endpoints: `PORTAL_TOKEN` env var or a `.portal_token` file.
- API base: `https://api.rapt.io`
- Auth scheme: Bearer JWT

Upstream endpoints in use:

- `GET /api/Hydrometers/GetHydrometers`
- `GET /api/Hydrometers/GetTelemetry`
- `GET /api/BrewZillas/GetBrewZillas`
- `GET /api/BrewZillas/GetTelemetry`
- `GET /api/ProfileSessions/GetHydrometerProfileSessions`
- `GET /api/ProfileSessions/GetBrewZillaProfileSessions`
- `GET /api/Profiles/GetProfiles`
- `GET /api/ProfileTypes/GetAll`
- `POST /api/Profiles/AddOrUpdateProfile`
- `GET /api/Inventory/Yeasts/GetAll`

Do not assume full session history comes from the device endpoints: a device
response carries only its active session. The app builds history locally by
observing active profile sessions during sync, and the portal data sync job
backfills past sessions.

## Development Commands

Backend:

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app:app --reload
uv run pytest
uv run python -m core.rapt_client
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
npm run lint:css
```

Docker:

```bash
docker compose build
docker compose run --rm backend uv run --no-dev alembic upgrade head
docker compose up -d
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
- Keep timestamps normalized the same way as `sync._dt`: naive UTC in the
  database.
- Be careful around session close behavior. A session is closed when the active
  session id changes or disappears during a sync.
- A schema change needs a new revision in `backend/alembic/versions/`. Nothing
  applies it automatically.
- Do not commit secrets. Runtime secrets belong in `backend/.env`, which is
  gitignored.
- Do not commit personal data either. Recipe exports carry it: before adding a
  BrewFather or BeerXML file to `backend/tests/data/`, replace the author
  (`author`, `<BREWER>`) and the share id (`_share`). BeerXML writes non-ASCII
  names as numeric entities (`&#1050;...`), so a plain-text search misses them.
- Commit with the GitHub noreply address that `git config user.email` already
  holds; do not override it.
- Keep the AI backend OpenAI-compatible. Avoid Ollama-only request controls
  that break other providers; provider-specific parameters go through the
  `*_LLM_EXTRA_BODY` setting, not into code.
- The LLM may only access local session data through the whitelisted tools in
  `backend/features/ai/services.py`; never expose SQL, arbitrary URLs, filesystem access or write
  operations to the model.
- Keep AI context focused on brewing: omit device-health fields such as battery
  and RSSI unless a feature explicitly needs them.
- Prompt files are English. The reply language comes from the request `locale`
  (the browser locale, `ru` by default), not from the prompt text.
- The AI default questions live in `backend/prompts/default_questions.json`,
  keyed by language. The backend picks one and stores it as the first message
  of the conversation; the frontend keeps no copy.
- The recipe wizard and the file importers must produce profiles through the
  same `compile_brewzilla_profile`. Do not add a second path from a recipe to a
  profile.
- The database behind `DATABASE_URL` in `backend/.env` is live runtime data and
  may be shared with another running instance. Do not modify or delete its
  rows, and do not run migrations against it, unless the user explicitly asks
  for database work. Tests build their own SQLite databases and never touch it.
- When reading or writing text in scripts/tools, pass `encoding="utf-8"`
  explicitly. For PowerShell text inspection/editing, prefer explicit UTF-8
  reads/writes. For Python console scripts on Windows, avoid printing raw
  non-ASCII device names unless stdout is known to be UTF-8; use a safe
  escaped/logging representation when needed.
- Run backend scripts and tools through `uv run` (e.g. `uv run pytest`). Do not
  invoke a bare `python` or the `.venv` interpreter directly; `uv run` resolves
  the project environment.
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
- Run `uv run pytest`. The suite needs no database, network or LLM and takes a
  few seconds, so run all of it instead of picking files.
- Run or smoke-check `uv run uvicorn app:app --reload` when route wiring or app
  startup changes.
- Use `uv run python -m core.rapt_client` only when credentials/network access are
  available and the change touches upstream API behavior.

For frontend changes:

- Run `npm run fmt:check` before commit and before handoff.
- Run `npm run build` for TypeScript and production build validation.
- Run `npm run lint` when changing TypeScript/React code, and `npm run lint:css`
  when changing CSS.
- Check responsive layout manually for page or chart changes.

For Docker/deployment changes:

- Run `docker compose up -d --build` when practical.
- Verify `GET /health` through the backend and the nginx-served SPA through the
  published frontend port.
