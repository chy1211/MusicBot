# Round 16 offline findings

Base: round 15, 5c73f76. No production data or logs consulted.

## 1. Translation startup audit

Round 15 already fixes the reported m0202 button and m0203 sync button:
`libraryButton(key)` retains a `data-i18n` span through `buttonLabel`.
The delayed-catalog test executes the real library bootstrap before either
catalog arrives, applies zh-TW then en, and scans all DOM text and
placeholder/title/aria-label values. Replacing the button with the old
one-shot `textContent = t(key)` makes that test fail.

Complete startup-reachable one-shot text inventory (including attributes):

| File / path | Text or attribute | Fix |
| --- | --- | --- |
| library.js libraryInitImports | hint m0202, sync m0203 | round-15 buttonLabel retained and regression tested |
| library.js libraryImportElement / libraryImportRender | source m0204 | key-based data-i18n element, including before first render |
| dashboard.js initialize / authDisplay / signedOut | identity note m0046-47; login/error m0048-55; connection m0049 | await dashboardI18nReady before session fetch or rendering |
| dashboard.js connect / refresh | connection/notice m0123-29 | same startup gate |
| dashboard.js resetView / render | source m0106-07; toggle m0108-09; title/status m0040-45,m0110-13; repeat text/aria-label m0114-19 | same startup gate |
| dashboard.js renderQueue / renderRecommendations | requester m0062; duration m0063,m0097; drag aria/title m0064-69; recommendation m0112,m0131-32 | same startup gate |
| dashboard.js drawProgress / resetHistory / resetLyrics | duration/aria-valuetext m0085,m0097,m0130; history m0133; lyrics heading/sync m0141-42 | same startup gate |
| dashboard.js setQueueFilter / updateQueueTimes / renderCommunity | drag help and shuffle title m0170-75; timing m0159-69; listeners/activity m0176-85 | same startup gate |
| library.js libraryLoad / libraryRender / favoriteRender | favorites/list metadata m0191-94,m0033; track aria/duration m0095,m0097; favorite title/aria m0200-01 | library load now follows startup gate |
| popular.js popularClear | empty status m0216 | resetView now follows startup gate |
| admin.js adminAplRender | remove m0004 | remove pre-translation passed to key-based libraryButton |
| permissions.js adminPermissionsRender | confirm m0214 | remove pre-translation passed to key-based libraryButton |

Other t() consumers in admin.js, permissions.js, popular.js, dashboard.js,
library.js and pwa.js run in user actions or their API callbacks after the
initialized application is visible (errors/confirm dialogs use the current
catalog); sw.js contains no t(). No other eager top-level text writes exist.
The language selector intentionally reloads the page, rebuilding all dynamic
state and localized server responses; this existing lifecycle is preserved.
Only retained bootstrap nodes need in-place data-i18n updates. No additional
translation registry or parallel translation mechanism was introduced.

## 2. SSE admission and recovery

Admission is per Discord member (across sessions/guilds), plus a global cap;
there is no IP or guild rate limiter. Three distinct users do not share the
per-user quota. The old cap was 3 streams per user, 64 globally. Idle closed
transports retained reservations until the next write (up to the 15-second
heartbeat), so quick reload/foreground cycles can reproduce the 429 bursts.
The summary alone cannot attribute each production 429 to a particular tab.

Admission now counts only live transports and the loop detects disconnection
on each inspection. Per-user cap 6 allows two tabs plus short reconnect/PWA
handover; global cap 64 and authentication/membership checks remain.
The service worker already excludes /events and API routes. Each page closes
its previous source and invalidates callbacks before constructing a new one.
Existing bounded backoff 1s/2s/4s/60s (then 60s) is retained, including across
visibility changes. A snapshot resets it; retries continue automatically.
EventSource hides the HTTP status, so all transport errors (including 429)
use this same recovery. Fallback state/probe reads are limited to one per
5 seconds per page; hidden pages do not poll. Explicit user actions may
still request immediate state. No production traffic was measured.
