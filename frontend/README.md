# Frontend — control dashboard

React 18 + Vite + TypeScript + Tailwind + Recharts.

```bash
npm install
cp .env.example .env
npm run dev        # http://localhost:5173, proxies /api to :8000
npm run build
npm run typecheck
```

## Screens

| Route | Purpose |
|---|---|
| `/` | **Control Tower** — run a reconciliation, headline figures, exception mix, where the matches came from |
| `/exceptions` | **Exception queue** — filterable, ordered by money at risk, with a drill-in showing the arithmetic, the AI's reasoning, and the validation gate's verdict |
| `/chat` | **Finance chat** — questions over the run's aggregates, with the exact model context inspectable |
| `/benchmark` | **Benchmark** — throughput and accuracy across dataset sizes, chart and table |

## Colour and charts

Every colour is a CSS custom property declared once per mode in `src/index.css`;
components reference roles, never raw hex, so the light/dark swap happens in one
place.

The three categorical series slots are a **validated palette** — the ordering is
the colourblind-safety mechanism, not decoration. Both modes pass the lightness
band, chroma floor, CVD separation (adjacent ΔE 9.2 light / 9.4 dark) and
normal-vision floor checks. **Do not reorder or extend the slots without
re-validating.**

Chart rules that are deliberate, not stylistic:

- **No dual-axis charts.** Throughput and accuracy have different scales, so they
  are two charts. One plot with two y-axes is the most common charting mistake
  there is.
- **Single-series charts have no legend** — the title names the series.
- **Multi-series charts have both a legend and direct labels**, so identity is
  never carried by colour alone.
- **A table view is available** on every chart. Two light-mode series colours sit
  below 3:1 against the surface, and the rule for that is "relief required".
- Thin marks, 4px rounded data-ends anchored to the baseline, 2px lines, 2px gaps
  between adjacent fills, recessive grid and axes.

## Structure

```
src/
├── api/          client.ts (typed fetch), types.ts (wire shapes)
├── lib/          format.ts (money/count/pct), theme.ts
├── hooks/        useAsync, usePolling
├── components/   primitives.tsx, Layout, RunPicker, charts/
└── pages/        ControlTower, Exceptions, Chat, Benchmark
```

Amounts arrive as integer minor units and are formatted for display exactly once,
in `lib/format.ts`. They are never parsed back into arithmetic on the client.
