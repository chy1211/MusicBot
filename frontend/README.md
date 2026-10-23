# Dashboard framework migration checkpoint

This branch is not a release-ready full Vue migration. Vue 3 SFCs render the
workspace and page templates; TypeScript owns router, typed API transport,
reactive now-playing state, and the lifecycle bridge. `vite.config.ts` bundles
the existing JavaScript auth, gesture, SSE, library, administration and lyrics
controllers into a single lexical compatibility adapter. Dynamic lists and
several forms still use imperative DOM updates. Porting those state machines and
renderers to typed Vue composables/components remains an acceptance blocker.

Node 22 or newer is required. The dependency list matches the reference stack,
with one optional test dependency: Playwright, used for real offline/browser
regressions instead of simulated layout assertions.

```sh
cd frontend
npm ci
npm run build
npx playwright install chromium
npm test
```

The build runs `vue-tsc --noEmit && vite build` and produces
`musicbot/web/dist`. The repository Dockerfile builds this directory in a Node
stage and copies only the distribution into the Python runtime; node_modules is
excluded. The Python static routes prefer a built distribution and retain a
source fallback for original contract fixtures. Production JavaScript and CSS
are fingerprinted, while compatibility paths hand old installed shells to `/`.
The worker is generated with vite-plugin-pwa injectManifest; auth/API/SSE are
never cached. Offline HTML/CSS/JS are independent of compatibility entry points.

The typed router bridge keeps legacy page navigation and hash URLs synchronized.
The compatibility adapter is a singleton. Complete teardown of its legacy
observers/timers and complete migration of its dynamic DOM are still pending.
Do not describe this checkpoint as a complete TypeScript/Vue reconstruction.
