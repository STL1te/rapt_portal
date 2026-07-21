# RAPT Portal — frontend

Vite + React + TypeScript dashboard for the RAPT Portal backend. TanStack Query
for data, Recharts for telemetry charts, light/dark theme.

## Run

```bash
npm install
npm run dev      # http://localhost:5173, proxies /api -> localhost:8000
```

`npm run build` for a production bundle.

## Pages

- `/` — dashboard (device cards)
- `/hydrometers` — device list
- `/hydrometers/:id` — session history for a device
- `/sessions/:id` — single session: OG/FG/ABV/attenuation + telemetry chart
  (zoom, click legend to toggle series)

The backend is reached via `/api` (Vite dev proxy locally, nginx in Docker).
