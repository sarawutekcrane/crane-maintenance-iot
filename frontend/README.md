# Frontend — Thai Web Application

React + TypeScript + Vite. All user-facing content is Thai (internal
technical identifiers may stay English).

See the root `README.md` for local startup instructions. Quick reference:

```bash
npm install
npm run dev        # http://127.0.0.1:5173, proxies /api to the backend
npm run build       # type-check + production build
npm run test         # Vitest (component/unit tests)
npm run test:e2e      # Playwright (real-browser smartphone/tablet/desktop viewport tests)
npm run lint          # oxlint
```

`vite.config.ts` proxies `/api` to the local backend (`BACKEND_PORT`, default
`8000`) so the browser never talks to Google Sheets or any backend URL
directly — see `docs/architecture/API_CONVENTIONS.md`.

The UI shell is mobile-first and responsive (see
`docs/architecture/RESPONSIVE_UI.md`): reusable `Card`, `ResponsiveTable`,
and `FormField` patterns, a collapsible mobile nav, and a dialog that
always fits the viewport. `npm run test:e2e` starts the backend + frontend
automatically and checks the shell at smartphone, tablet, and desktop
widths.
