# RAPT Portal

Local dashboard for RAPT devices. The backend logs in to the public RAPT API,
stores device state and active-session telemetry in PostgreSQL, and exposes a
small read API for the React frontend.

The app currently supports:

- RAPT Pill / hydrometer devices, active sessions, telemetry charts, derived
  OG/FG, ABV and attenuation.
- BrewZilla devices, active brew sessions, profile metadata and telemetry
  charts.
- Docker Compose deployment with nginx serving the SPA and proxying `/api` to
  FastAPI.
- Alembic migrations for schema management.
- Local AI assistant for brewing and fermentation assessments through an
  OpenAI-compatible LLM API (Ollama by default).

## Architecture

- `backend/` - FastAPI, SQLAlchemy, Alembic, PostgreSQL, async RAPT API client.
- `frontend/` - Vite, React, TypeScript, React Router, TanStack Query, Recharts.
- `docker-compose.yml` - builds and runs backend plus nginx frontend.

The backend starts a background sync loop on application startup. By default it
runs every 60 seconds and can also be triggered manually with `POST /sync`.

## RAPT API

The upstream OpenAPI spec is published at:

`https://api.rapt.io/swagger/v1/swagger.json`

The spec describes `RAPT API` version `v1`, uses Bearer JWT auth, and serves API
routes from `https://api.rapt.io`. This project obtains tokens from
`https://id.rapt.io/connect/token` with:

- `client_id=rapt-user`
- `grant_type=password`
- `username=$RAPT_USERNAME`
- `password=$RAPT_SECRET`

Only these upstream endpoints are used by the app today:

- `GET /api/Hydrometers/GetHydrometers`
- `GET /api/Hydrometers/GetTelemetry`
- `GET /api/BrewZillas/GetBrewZillas`
- `GET /api/BrewZillas/GetTelemetry`

The public RAPT API exposes the active profile session on a device response, but
does not provide complete historical session rows for this portal. Session
history is therefore accumulated locally while the sync loop observes active
sessions. If the service is not running during a session change, that transition
may be missing from local history.

## Run With Docker

Create environment files:

```bash
cp backend/.env.example backend/.env
cp .env.example .env
```

Edit `backend/.env` and fill:

```env
RAPT_USERNAME=you@example.com
RAPT_SECRET=your-api-secret-here
DATABASE_URL=postgresql://user:password@db-host/rapt_portal
```

For the local Ollama assistant, leave the LLM defaults from `.env.example` or
configure them explicitly:

```env
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen3:8b
LLM_TIMEOUT_SECONDS=900
LLM_KEEP_ALIVE=30m
```

`LLM_TIMEOUT_SECONDS` allows the first request to wait while Ollama loads a
model into VRAM. `LLM_KEEP_ALIVE` keeps an Ollama model loaded; clear it when
using a cloud OpenAI-compatible provider.

Start the stack:

```bash
docker compose up -d --build
```

Open `http://localhost:8080`, or the port configured by `FRONTEND_PORT` in the
root `.env`.

Useful commands:

```bash
docker compose logs -f backend
docker compose ps
docker compose down
```

## Backend Development

Requirements:

- Python 3.11 or newer.
- `uv`.

Setup and run:

```bash
cd backend
cp .env.example .env
uv sync
uv run uvicorn app:app --reload
```

The backend runs at `http://localhost:8000`. On startup it applies Alembic
migrations to `DATABASE_URL`.

Useful commands:

```bash
uv run alembic upgrade head
uv run python rapt_client.py
uv run python scripts/test_gravities.py
uv run python -m scripts.portal_data_sync
```

`rapt_client.py` is a login/API smoke test. `scripts/test_gravities.py` checks
the gravity estimator. `scripts.portal_data_sync` imports historical hydrometer
sessions from the RAPT web portal API and expects a portal bearer token in
`backend/.portal_token`.

## Frontend Development

Requirements:

- Node.js 22 or newer.
- npm.

Setup and run:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173`. Vite proxies `/api` to
`http://localhost:8000`, so the backend should be running separately.

Useful commands:

```bash
npm run build
npm run lint
npm run preview
```

## Local API

System:

- `GET /health`
- `POST /sync`

Hydrometers:

- `GET /api/hydrometers`
- `GET /api/hydrometers/{hydrometer_id}/sessions`
- `GET /api/hydrometer-sessions/{session_id}`
- `GET /api/hydrometer-sessions/{session_id}/telemetry?start=...&end=...`

BrewZillas:

- `GET /api/brewzillas`
- `GET /api/brewzillas/{brewzilla_id}/sessions`
- `GET /api/brew-sessions/{session_id}`
- `GET /api/brew-sessions/{session_id}/telemetry?start=...&end=...`

AI:

- `POST /api/ai/assessments` - assesses a brewing or fermentation session.
  The request contains `kind`, `session_id`, `question` and recent chat
  `history`; the backend always rebuilds current local telemetry context.

The assistant can use read-only tools to list brewing or fermentation sessions,
search sessions by name and load a selected session's context. This lets a user
ask for a comparison by name, such as “сравни с предыдущей тропиканкой”, without
entering a session ID. The model never receives database credentials or direct
SQL access.

## Frontend Routes

- `/` - dashboard.
- `/hydrometers` - hydrometer list.
- `/hydrometers/:id` - sessions for one hydrometer.
- `/hydrometer-sessions/:id` - hydrometer session chart and statistics.
- `/brewzillas` - BrewZilla list.
- `/brewzillas/:id` - sessions for one BrewZilla.
- `/brew-sessions/:id` - brew session profile and telemetry chart.

## Configuration

Root `.env`:

- `FRONTEND_PORT` - host port published by nginx in Docker. Default: `8080`.

`backend/.env`:

- `RAPT_USERNAME` - RAPT account email.
- `RAPT_SECRET` - RAPT API secret/password used for token exchange.
- `DATABASE_URL` - SQLAlchemy database URL. Example: `postgresql://user:password@localhost/rapt_portal`.
- `SYNC_INTERVAL_SECONDS` - background sync interval. Default: `60`.
- `LLM_BASE_URL` - OpenAI-compatible chat-completions base URL. Default:
  Ollama at `http://host.docker.internal:11434/v1`.
- `LLM_API_KEY` - API key; Ollama accepts the placeholder `ollama`.
- `LLM_MODEL` - model name. Default: `qwen3:8b`.
- `LLM_TEMPERATURE`, `LLM_TOP_P` - standard generation controls.
- `LLM_EXTRA_BODY_JSON` - provider-specific request body; the default holds
  Ollama generation options.
- `LLM_TIMEOUT_SECONDS` - maximum LLM request time. Default: `900` seconds.
- `LLM_KEEP_ALIVE` - optional Ollama residency duration, for example `30m`.

## Data Notes

- Alembic migrations are applied automatically on backend startup.
- Telemetry rows are deduplicated by `(session_id, timestamp)`.
- Timestamps are normalized to naive UTC before storage.
- Hydrometer OG/FG are estimated from telemetry because the upstream API does
  not provide them for local historical sessions.
- The app currently reads from RAPT devices only. Upstream BrewZilla control
  endpoints exist in the public API, but this portal does not expose write
  controls.
