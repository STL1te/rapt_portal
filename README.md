# RAPT Portal

Self-hosted dashboard for [RAPT](https://app.rapt.io) brewing devices. The
backend signs in to the RAPT API, keeps device state, session history and
telemetry in PostgreSQL, and serves a local JSON API to a React frontend.

This is an unofficial project and is not affiliated with KegLand. The UI is in
Russian.

What it does:

- **Hydrometers (RAPT Pill)** - sessions, telemetry charts, estimated OG/FG, ABV
  and attenuation.
- **BrewZilla** - brew sessions with their profile and telemetry charts.
- **Profiles** - a local copy of the RAPT profile library with an editor;
  edited or new profiles are uploaded back to RAPT.
- **Recipe import** - BrewFather JSON, BeerXML and BeerJSON recipes are compiled
  into BrewZilla profiles by a deterministic compiler.
- **AI recipe wizard** - turns a free-text recipe into a BrewZilla profile: an
  LLM extracts a BeerJSON recipe, a judge checks it against the source, and the
  same compiler builds the profile.
- **AI assistant** - a chat attached to a brew session, a fermentation session
  or a profile, backed by any OpenAI-compatible API.
- **Yeast catalogue** synced from the RAPT inventory.
- **System Syncs** page - RAPT login, manual sync jobs and their history.

## Architecture

- `backend/` - FastAPI, SQLAlchemy, Alembic, PostgreSQL, httpx, OpenAI SDK.
  - `core/` - config, models, RAPT client and login, sync logic.
  - `features/<name>/` - one folder per feature (`hydrometers`, `brewzillas`,
    `profiles`, `recipes`, `yeasts`, `ai`, `system`), each with its routes and
    services.
  - `prompts/` - system prompts for the assistant and the recipe wizard.
- `frontend/` - Vite, React, TypeScript, React Router, TanStack Query, Recharts.
- `docker-compose.yml` - builds and runs the backend plus an nginx frontend that
  serves the SPA and proxies `/api` to the backend. PostgreSQL is not included;
  point `DATABASE_URL` at your own instance.

A background loop syncs devices and active-session telemetry every
`SYNC_INTERVAL_SECONDS` (60 by default). Every sync, scheduled or manual, runs
as a tracked job stored in the database; finished jobs are pruned after 3 days.

The local API has no authentication. Run it on a trusted network only.

## RAPT access

### Login

The portal signs in the same way the RAPT web app does: OAuth authorization
code with PKCE as the public `rapt-web` client. RAPT accepts only
`https://app.rapt.io/callback` as the redirect for that client, so the code
cannot be delivered to this app directly:

1. Open the System Syncs page (**Админ-панель -> Системные синки**) and press
   **Войти через RAPT**.
2. Sign in at RAPT. The address becomes
   `https://app.rapt.io/callback?code=...`; if the page has already moved on,
   go back with the browser's Back button.
3. Copy that address and paste it into the page.

The refresh token is stored in the database, encrypted with `APP_SECRET`. RAPT
replaces it on every refresh. In practice a login has stopped working about 30
days after it was made: sync jobs start failing with `invalid_grant` while
`GET /api/rapt_auth` still reports `connected`. Logging in again fixes it.

Without a login the backend falls back to the password grant
(`client_id=rapt-user`, `RAPT_USERNAME`, `RAPT_SECRET`). That covers the device
and telemetry endpoints only; the session-history, profile and yeast syncs then
need a portal bearer token in the `PORTAL_TOKEN` variable (outside Docker, a
`.portal_token` file in `backend/` also works).

### Upstream endpoints

OpenAPI spec: `https://api.rapt.io/swagger/v1/swagger.json`. API base:
`https://api.rapt.io`.

Devices and telemetry:

- `GET /api/Hydrometers/GetHydrometers`
- `GET /api/Hydrometers/GetTelemetry`
- `GET /api/BrewZillas/GetBrewZillas`
- `GET /api/BrewZillas/GetTelemetry`

Session history, profiles and yeasts:

- `GET /api/ProfileSessions/GetHydrometerProfileSessions`
- `GET /api/ProfileSessions/GetBrewZillaProfileSessions`
- `GET /api/Profiles/GetProfiles`
- `GET /api/ProfileTypes/GetAll`
- `POST /api/Profiles/AddOrUpdateProfile`
- `GET /api/Inventory/Yeasts/GetAll`

### Session history

A device response carries only its active profile session. The sync loop records
each active session as it sees it and closes it when the session id changes or
disappears, so a transition that happens while the service is down is missed.
The **portal data sync** job on the System Syncs page fills such gaps: it loads
past sessions and their telemetry from the session-history endpoints.

## Run with Docker

Create the environment files:

```bash
cp backend/.env.example backend/.env
cp .env.example .env
```

Edit `backend/.env`. The minimum is the database and the secret that encrypts
the RAPT login:

```env
APP_SECRET=<output of: python -c "import secrets; print(secrets.token_urlsafe(32))">
DATABASE_URL=postgresql://user:password@db-host/rapt_portal
```

Build, apply the database migrations and start the stack. Migrations are a
deploy step; the backend does not run them on startup.

```bash
docker compose build
docker compose run --rm backend uv run --no-dev alembic upgrade head
docker compose up -d
```

Open `http://localhost:8080` (or the port set by `FRONTEND_PORT` in the root
`.env`), open the System Syncs page and log in to RAPT.

Useful commands:

```bash
docker compose logs -f backend
docker compose ps
docker compose down
```

## Configuration

Root `.env`:

- `FRONTEND_PORT` - host port published by nginx. Default: `8080`.

`backend/.env`:

- `APP_SECRET` - encrypts the stored RAPT refresh token. Required for the RAPT
  login; changing it invalidates the stored login.
- `DATABASE_URL` - PostgreSQL URL, for example
  `postgresql://user:password@localhost/rapt_portal`.
- `SYNC_INTERVAL_SECONDS` - background sync interval. Default: `60`.
- `RAPT_USERNAME`, `RAPT_SECRET` - optional legacy password grant, used only
  when nobody has logged in through RAPT.

### LLM roles

Three roles are configured independently, each against an OpenAI-compatible
endpoint:

| Prefix           | Used for                              | Unset keys fall back to     |
| ---------------- | ------------------------------------- | --------------------------- |
| `WIZARD_LLM_`    | recipe extraction in the wizard       | `LLM_*`, then the defaults  |
| `ASSISTANT_LLM_` | the AI assistant chats                | `LLM_*`, then the defaults  |
| `VALIDATOR_LLM_` | the judge that checks the extraction  | the resolved `WIZARD_LLM_*` |

Keys, shown without the prefix:

- `BASE_URL` - chat-completions base URL. Default:
  `http://host.docker.internal:11434/v1` (Ollama on the Docker host).
- `API_KEY` - API key. Default: `not-needed`.
- `MODEL` - model name. Default: `local-model`.
- `TIMEOUT_SECONDS` - request timeout. Default: `900`, which leaves room for a
  local server to load the model first.
- `RESPONSE_FORMAT` - how structured output is requested: `auto`, `json_schema`,
  `json_object` or `none`. `auto` tries JSON Schema, then JSON mode, then no
  `response_format`. Default: `auto`.
- `SAMPLING` - `default` or `none`. `none` is for OpenAI reasoning models: no
  `temperature`/`top_p`, and `max_completion_tokens` instead of `max_tokens`.
- `EXTRA_BODY` - provider-specific request parameters, as a JSON object or a
  `key=value,key=value` list. For example, a fine-tuned model served by
  llama.cpp or Ollama needs `reasoning_effort=none`.

For `VALIDATOR_LLM_EXTRA_BODY`, an empty value means "send nothing extra" and an
unset one means "inherit from the wizard".

Temperature and `top_p` are fixed in `backend/core/config.py`.
`backend/.env.example` has a commented example for each role.

## Backend development

Requirements: Python 3.11 or newer, `uv`, a PostgreSQL database.

```bash
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app:app --reload
```

The backend runs at `http://localhost:8000`.

```bash
uv run pytest                      # tests; need no database or network
uv run ruff format .
uv run ruff check . --fix
uv run python -m core.rapt_client  # login and upstream API smoke test
```

## Frontend development

Requirements: Node.js 22 or newer, npm.

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173`. Vite proxies `/api` to
`http://localhost:8000`, so start the backend separately.

```bash
npm run build      # type check and production build
npm run fmt        # oxfmt
npm run lint       # oxlint
npm run lint:css   # stylelint
```

Source layout (`frontend/src`):

- `api/` - fetch client and per-domain endpoint modules; import from `@/api`.
- `types/` - API response types by domain; import from `@/types`.
- `lib/`, `hooks/` - formatting helpers and React hooks.
- `pages/`, `components/` - page views and shared UI.

Imports use the `@/` alias (`@` -> `src`) instead of relative `../` chains.

## Local API

System:

- `GET /health`
- `GET /api/rapt_auth` - whether a RAPT login is stored.
- `GET /api/rapt_auth/url` - the RAPT login address.
- `POST /api/rapt_auth` - completes the login; takes the callback address or the
  bare code.
- `POST /api/sync` - devices and active-session telemetry.
- `POST /api/portal_data_sync` - past sessions; `{"force": true}` reloads
  telemetry for every session.
- `POST /api/sync_yeasts`
- `POST /api/sync_profiles`
- `GET /api/system-jobs` - queued and running jobs.
- `GET /api/system-jobs/history?page=...&page_size=...`
- `GET /api/system-jobs/{job_id}`

The sync endpoints return `202` with a job to poll.

Hydrometers:

- `GET /api/hydrometers`
- `GET /api/hydrometers/{hydrometer_id}/sessions`
- `GET /api/hydrometer-sessions/{session_id}`
- `GET /api/hydrometer-sessions/{session_id}/telemetry?start=...&end=...`

BrewZillas:

- `GET /api/brewzillas`
- `GET /api/brewzillas/{brewzilla_id}/sessions?include_short=...`
- `GET /api/brew-sessions/{session_id}`
- `GET /api/brew-sessions/{session_id}/telemetry?start=...&end=...`

Profiles:

- `GET /api/profiles?type_id=...`
- `GET /api/profile-types`
- `GET /api/profiles/{profile_id}`
- `POST /api/profiles`
- `PUT /api/profiles/{profile_id}`
- `DELETE /api/profiles/{profile_id}`
- `POST /api/profiles/import` - compiles a recipe (`brewfather_json`, `beerxml`
  or `beerjson`) into an unsaved profile.
- `POST /api/profiles/{profile_id}/upload` - uploads the profile to RAPT as a
  job.

Yeasts:

- `GET /api/yeasts?q=...&type=...`

AI:

- `POST /api/ai/conversations/open` - opens the conversation for a subject
  (`brew_session`, `fermentation_session` or `profile`), creating it on first
  use.
- `POST /api/ai/conversations/{conversation_id}/messages`
- `POST /api/ai/conversations/{conversation_id}/reset`
- `POST /api/ai/recipe-wizard` - free-text recipe to profile.
- `POST /api/ai/recipe-wizard/stream` - the same as an NDJSON stream of progress
  events followed by the result.

Conversations are stored on the server, one per subject, and long ones are
summarized. In session chats the assistant can call read-only tools to list
brewing or fermentation sessions, search them by name and load a session's
context, so a user can ask to compare with an earlier batch by name. The model
never gets database credentials, SQL, arbitrary URLs or write access.

## Frontend routes

- `/` - dashboard.
- `/hydrometers`, `/hydrometers/:id` - hydrometers and the sessions of one.
- `/hydrometer-sessions/:id` - fermentation session chart and statistics.
- `/brewzillas`, `/brewzillas/:id` - BrewZillas and the sessions of one.
- `/brew-sessions/:id` - brew session profile and telemetry chart.
- `/profiles`, `/profiles/:id` - profile library and one profile.
- `/profiles/new`, `/profiles/:id/edit` - profile editor.
- `/profiles/import` - recipe file import.
- `/profiles/wizard` - AI recipe wizard.
- `/yeasts`, `/yeasts/:id` - yeast catalogue.
- `/admin/syncs` - RAPT login and system syncs.

## Recipe-wizard model tooling

`backend/scripts/` holds the tooling used to distil and evaluate a small local
model for the recipe wizard: running a teacher model over a recipe corpus,
building the fine-tuning dataset, rewriting sources into hand-typed drafts,
evaluating a student model and cutting quantized builds. The `.cmd` launchers
point at local corpus paths and need editing before use. The portal does not
need any of it to run.

Design notes and plans are in `docs/`.

## Data notes

- Telemetry is append-only and deduplicated by `(session_id, timestamp)`.
- Timestamps are stored as naive UTC.
- Hydrometer OG/FG are estimated from telemetry; the upstream API does not
  provide them.
- The only write to RAPT is the profile upload. The portal does not control
  devices.
