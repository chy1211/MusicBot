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

## 3. Operation log coverage

The previous last-path-segment allowlist omitted popular, Spotify, library
list/create/update/delete/tracks/play/import/sync/sources, both import preview
routes, queue undo, admin autoplaylist/permissions/maintenance/empty-queue,
lyrics offset, and logout-all. Admin lyrics was misleadingly called lyrics.
These registered API routes could log unknown (or misidentify the operation).
Static files, healthz, ui-config, language catalogs and auth/session were
already outside the logging condition, so they did not cause those 277 lines.
The summary does not identify how many came from each omitted route.

Canonical route-template mappings now name every registered API/auth operation;
an explicit no-operation set excludes static/bootstrap/health/session requests.
Tests enumerate every registered method, including automatic HEAD routes,
verify exact coverage and ensure query strings/cookies/Bearer values do not
enter the operation log. Unknown API paths are labeled unmatched; no raw path
or query is logged. Existing safe user/guild identifiers remain unchanged.

## 4. Autoplay disable: upstream behavior; one confirmed radio defect

Both warning strings and global auto_playlist=False assignments already exist
in local upstream/dev bot.py (Guild warning around line 1378, final warning
around line 1502). An initially empty configured in-memory list emits both
warnings in the same finish event. Exhaustion through upstream extraction or
playback failure/removal emits the final warning. Removal from memory occurs
even with remove_ap=False; that flag controls writing back to the source file.
Thus two warnings after a song are reproducible with an empty synthetic list,
without any dashboard or radio request. No upstream disable behavior is changed.

A separate defect in our radio integration is confirmed and fixed: radio entries
have author=None/channel=None, so from_auto_playlist is True. Upstream
on_player_error then removed the failed radio URL from the configured autoplaylist
if that same URL happened to be present there. The hook now excludes is_radio
entries, while native autoplay errors still prune their own list. This could
contribute to exhaustion in an overlapping list, but the supplied summary
cannot prove it caused the two production warnings. Synthetic regression tests
cover both the overlap defect and unchanged empty/failed/native success paths.

Normal web requests and playnext retain the requesting member/channel, and
change only the queue. Radio fill does not clear or mark the configured list;
radio off suppresses fallback without mutating global auto_playlist. Explicit
owner autoplaylist deletion is the only dashboard API that removes its tracks.
No production config/data contents were read, so actual production list length,
failed URLs and the trigger for each observed warning remain intentionally
unverified.

## 5. High-volume warning sources

Missing __input_subject is a valid invariant warning, not globally suppressed.
The ordinary extractor and credential-free public_only extractor already set
it. Our homepage playlist resolve adapter rebuilt imported YouTube/Spotify
metadata without this private field; constructing the root and every child
then warned. The adapter now stores the canonical source on the parent and
the canonical track URL on each child. Provenance tests cover both providers;
intentionally malformed metadata must still emit WARNING. The production
count cannot be split among this path and any other malformed callers from
the supplied summary alone.

Different cached extension comes from upstream URLPlaylistEntry._download and
AudioFileCache.get_if_cached(ignore_ext=True). yt-dlp may change the format;
a variant cache hit is expected, and size validation/re-download follows
immediately. Only that individual message moves to DEBUG. Tests exercise both
same-size reuse and size-mismatch re-download; no WARNING logger is disabled.
