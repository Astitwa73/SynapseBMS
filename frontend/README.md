# Dashboard

The operator-facing surface of the autonomous BMS. React 19 + TypeScript, Vite,
Tailwind 4, Recharts, Framer Motion.

It renders one thing: the agent's decision loop over a live building. Every
figure on screen is tagged **Measured**, **Derived** or **Estimated**, and
nothing is animated that the backend did not actually do.

## Develop

The backend must be running first — the dashboard has no mock data, by design.

```bash
python ../scripts/run_server.py --policy llm --speed 0.4 --decide-every 12
```

```bash
npm install
npm run dev
```

Vite serves on `:5173` and proxies `/api` and `/ws` to `:8000`, so the API origin
is identical in development and production and no base URL is configurable
anywhere in the client. See [vite.config.ts](vite.config.ts).

## Build

```bash
npm run build
```

Output goes to `../backend/api/static/`, which FastAPI mounts, so the demo runs
from one command and one URL: `http://localhost:8000`.

## Layout

| Path | Responsibility |
| --- | --- |
| `src/api/` | Hand-written mirror of the backend Pydantic schemas |
| `src/hooks/` | WebSocket stream, decision-cycle state machine, static fetches |
| `src/lib/` | Formatting, provenance labels, outcome measurement |
| `src/components/agent/` | Decision impact, safety layer, audit trail |
| `src/components/twin/` | Floor plan built from the real IDF geometry |
| `src/components/metrics/` | Trend chart, validated benchmark |
| `src/components/pipeline/` | Live system pipeline |
| `src/components/shell/` | Header, KPIs, health strip, architecture overlay |

Press `?` anywhere in the dashboard for the architecture overlay.
