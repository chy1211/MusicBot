# Dashboard frontend

The current dashboard uses Vue 3 components and TypeScript composables under
`src/`. Public catalogs, icons, offline assets and installed-shell compatibility
stubs live under `public/`.

Node 22 or newer is required. Playwright exercises browser and offline behavior.

```sh
cd frontend
npm ci
npm run build
npx playwright install chromium
npm test
```

The build runs `vue-tsc --noEmit && vite build` and produces the ignored
`musicbot/web/dist` directory. Docker builds this distribution in its Node stage
and copies it into the Python runtime. Backend static routes serve only this
distribution. Without a built index, `/` returns HTTP 503 with
`dashboard frontend is not built`.

Production JavaScript and CSS are fingerprinted. Compatibility URLs redirect
old installed shells to `/`; keep the public `i18n.js`, `pwa.js` and
`dashboard.css` stubs. The generated service worker never caches auth/API/SSE.
Offline HTML/CSS/JS are independent of the compatibility entry points.

The shared base stylesheet is `src/base.css`. The historical service worker in
`tests/fixtures/` exists only for installed-worker upgrade regression tests.
