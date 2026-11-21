# frontend/

React 18 + Vite + TypeScript + Tailwind + Recharts single-page app.

| Path | Contents |
|---|---|
| `src/App.tsx` | routing, auth context, shell |
| `src/api.ts`, `src/types.ts` | API client (CSRF header, cookie session) and types |
| `src/components/` | shared UI, evidence viewer (`EvidenceDrawer.tsx`) |
| `src/pages/` | dashboard, patients, document viewer, evaluation, review-time study, admin |
| `src/pages/patient/` | patient workspace tabs: overview, documents, timeline, medications, allergies, investigations, conditions & events, contradictions, duplicates, review centre, ask |

`npm install` · `npm run dev` (http://localhost:5173, proxies `/api` to :8000) · `npm run build` (output `dist/`, served by the backend).
