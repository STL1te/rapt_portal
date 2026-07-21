# RAPT Portal — backend

FastAPI service that logs into the RAPT API, caches hydrometer telemetry into
SQLite, and serves it to the frontend. A background loop syncs every 60s.

## Run

```bash
cp .env.example .env      # fill RAPT_USERNAME + RAPT_SECRET
uv sync
uv run uvicorn app:app --reload
```

API on `http://localhost:8000`. Quick check: `uv run python rapt_client.py`.

## Endpoints

- `GET /api/hydrometers` — devices with latest readings
- `GET /api/hydrometers/{id}/sessions` — session history (with ABV/attenuation)
- `GET /api/sessions/{id}` — one session
- `GET /api/sessions/{id}/telemetry` — telemetry points
- `GET /health`, `POST /sync`

## Session history backfill

The public API exposes only the *active* session, so history is accumulated
locally. To import existing sessions, put a portal (rapt-web) bearer token in
`.portal_token` (from browser DevTools) and run:

```bash
uv run python backfill.py
```

Tests: `uv run python test_gravities.py` (OG/FG estimator).
