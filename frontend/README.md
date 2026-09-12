# Frontend — Thai Web Application

React + TypeScript + Vite. All user-facing content is Thai (internal
technical identifiers may stay English).

See the root `README.md` for local startup instructions. Quick reference:

```bash
npm install
npm run dev        # http://127.0.0.1:5173, proxies /api to the backend
npm run build       # type-check + production build
npm run test         # Vitest
npm run lint          # oxlint
```

`vite.config.ts` proxies `/api` to the local backend (`BACKEND_PORT`, default
`8000`) so the browser never talks to Google Sheets or any backend URL
directly — see `docs/architecture/API_CONVENTIONS.md`.
