# RAPT Portal

Dashboard for RAPT hydrometers: a FastAPI backend caches telemetry from the
RAPT API into SQLite, a React frontend shows devices, sessions and charts.

## Run (Docker)

```bash
cp backend/.env.example backend/.env   # fill RAPT_USERNAME + RAPT_SECRET
docker compose up -d --build
```

App on `http://localhost:8080` (nginx serves the frontend and proxies `/api` to
the backend). The DB lives in `./data/`.

## Backend (dev)

```bash
cd backend
cp .env.example .env      # RAPT_USERNAME + RAPT_SECRET
uv sync
uv run uvicorn app:app --reload      # http://localhost:8000
```

Background loop syncs every 60s. Quick check: `uv run python rapt_client.py`.
Tests: `uv run python test_gravities.py` (OG/FG estimator).

### Endpoints

- `GET /api/hydrometers` — devices with latest readings
- `GET /api/hydrometers/{id}/sessions` — session history (with ABV/attenuation)
- `GET /api/sessions/{id}` — one session
- `GET /api/sessions/{id}/telemetry` — telemetry points
- `GET /health`, `POST /sync`

### Session history backfill

The public API exposes only the *active* session, so history is accumulated
locally. To import existing sessions, put a portal (rapt-web) bearer token in
`backend/.portal_token` (from browser DevTools) and run:

```bash
cd backend && uv run python backfill.py
```

## Frontend (dev)

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173, proxies /api -> localhost:8000
```

Vite + React + TS, TanStack Query, Recharts, light/dark theme.

### Pages

- `/` — dashboard (device cards)
- `/hydrometers` — device list
- `/hydrometers/:id` — session history for a device
- `/sessions/:id` — single session: OG/FG/ABV/attenuation + telemetry chart
  (zoom, click legend to toggle series)
