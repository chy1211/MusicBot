
## 2026-10-23 第二十七輪驗收校準

- 舊測試範圍仍記為 198 cases／808 assert calls；目前 round31 真瀏覽器 runner 有 64 cases，本次實跑 63 通過、1 失敗。
- 逐案映射表目前沒有連到可核對的新 runner 測試名稱或案例編號，因此**已明確對應的新測試：0/198；尚未明確對應：198/198**。這是逐案映射證據數，不代表合併式瀏覽器測試完全沒有覆蓋舊行為。
- PWA、offline、registration 另有 11 個舊 cases 保留於原套件，仍獨立驗收；不併入上述 198 個 Vue 移植範圍。
- runner 目前失敗案例：`queue empty state remains visible when the fixture has no queued tracks`。不得以 63/64 宣稱全部舊意圖已移植。

# Vue 測試移植 inventory 與 mapping

此檔由 `node tools/test_dashboard_round31_inventory.cjs` 從現有 CJS 案例產生。原基線記錄為 **211 tests / 856 textual asserts**；目前工作樹解析到 **209 test cases / 856 assert calls**，其中移植範圍 **198 / 808**。數字差異保留為待核對項，不以刪除或重複測試補數。PWA、offline、registration 三組按任務先保留。

驗收規則：映射後測試必須載入 Vite 建置輸出，使用 Playwright 對 rendered DOM 做互動，並在 API fixture 觀察結果；不得讀取／執行原 public JS，也不得用搜尋 TS 原始碼替代行為。重構無法在瀏覽器呈現的底層時序意圖，須以可觀察 UI/API 結果保留因果驗證。

## 各組數量

| 舊測試檔 | 案例 | assert calls | 狀態 |
|---|---:|---:|---|
| `test_web_dashboard_frontend.cjs` | 166 | 687 | 逐項映射，逐步換成瀏覽器互動 |
| `test_web_dashboard_i18n.cjs` | 4 | 7 | 逐項映射，逐步換成瀏覽器互動 |
| `test_web_dashboard_layout.cjs` | 8 | 44 | 逐項映射，逐步換成瀏覽器互動 |
| `test_web_dashboard_phone.cjs` | 3 | 9 | 逐項映射，逐步換成瀏覽器互動 |
| `test_web_dashboard_popular.cjs` | 8 | 27 | 逐項映射，逐步換成瀏覽器互動 |
| `test_web_dashboard_pwa.cjs` | 7 | 27 | 保留原套件 |
| `test_web_dashboard_round15_busy.cjs` | 4 | 15 | 逐項映射，逐步換成瀏覽器互動 |
| `test_web_dashboard_round27_covers.cjs` | 5 | 19 | 逐項映射，逐步換成瀏覽器互動 |
| `test_web_dashboard_round27_offline.cjs` | 2 | 15 | 保留原套件 |
| `test_web_dashboard_round27_registration.cjs` | 2 | 6 | 保留原套件 |

## 逐案映射

### `test_web_dashboard_frontend.cjs:210` — renders current track, progress, queue and safe untrusted titles

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L210: `assert.equal(app.element("bar-title").textContent, "First");`
  - L211: `assert.equal(app.element("progress").value, 30);`
  - L212: `assert.equal(app.element("queue-count").textContent, "2");`
  - L213: `assert.equal(app.element("queue").children[0].children[2].children[0].textContent, "<img onerror=evil>");`
  - L214: `assert.equal(app.element("enqueue").disabled, false);`
  - L215: `assert.ok(app.timers.some((timer) => timer[1] === 1000));`

### `test_web_dashboard_frontend.cjs:221` — control handlers send correct methods, body, guild and headers

- 舊意圖：8 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L221: `assert.equal(app.element("toggle").textContent.includes("繼續"), true);`
  - L230: `assert.deepEqual(mutations.map((r) => r.url), [`
  - L232: `assert.equal(mutations[1].data.volume, 65);`
  - L233: `assert.equal(mutations[2].data.mode, "all");`
  - L234: `assert.equal(mutations[3].data.query, "search words");`
  - L235: `assert.equal(mutations[4].data.query, "https://example.test/selected");`
  - L236: `assert.equal(mutations[4].headers["X-MusicBot-Dashboard"], "1");`
  - L237: `assert.equal(app.element("query").value, "");`

### `test_web_dashboard_frontend.cjs:243` — queue handlers retain observed revision and block invalid boundaries

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L243: `assert.equal(actions[1].disabled, true);`
  - L246: `assert.deepEqual(move.data, {from: 1, to: 2, revision: "revision-1"});`
  - L248: `assert.equal(app.requests.find((r) => r.method === "DELETE").url, "api/guilds/1/queue/1");`
  - L249: `assert.equal(app.element("queue-count").textContent, "1");`

### `test_web_dashboard_frontend.cjs:259` — failed focused volume control reconciles with actual server state

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L259: `assert.equal(app.element("volume").value, 15);`
  - L260: `assert.equal(app.element("notice").textContent, "denied");`
  - L261: `assert.equal(app.element("volume").disabled, false);`

### `test_web_dashboard_frontend.cjs:272` — guild switching clears previous content and rejects stale response

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L272: `assert.equal(app.element("bar-title").textContent, "Second");`
  - L275: `assert.equal(app.element("bar-title").textContent, "Second");`
  - L277: `assert.equal(app.requests.find((r) => r.url.endsWith("/skip")).url, "api/guilds/2/skip");`

### `test_web_dashboard_frontend.cjs:285` — failed guild switch clears old queue and disables controls

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L285: `assert.notEqual(app.element("bar-title").textContent, "First");`
  - L286: `assert.equal(app.element("queue").children.length, 0);`
  - L287: `assert.equal(app.element("toggle").disabled, true);`
  - L288: `assert.equal(app.element("enqueue").disabled, true);`

### `test_web_dashboard_frontend.cjs:296` — secret stays in headers and memory; clearing removes authorization

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L296: `assert.equal(app.requests.at(-1).headers.Authorization, "Bearer fake-fixture-secret");`
  - L297: `assert.ok(app.requests.every((r) => !r.url.includes("fake-fixture-secret")));`
  - L300: `assert.equal(app.requests.at(-1).headers.Authorization, undefined);`
  - L301: `assert.equal(app.element("secret").value, "");`

### `test_web_dashboard_frontend.cjs:310` — mutations block duplicate input and polling while in flight

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L310: `assert.equal(app.element("toggle").disabled, true);`
  - L311: `assert.equal(app.element("guild").disabled, true);`
  - L315: `assert.equal(app.requests.length, count);`
  - L318: `assert.equal(app.element("toggle").disabled, false);`

### `test_web_dashboard_frontend.cjs:326` — network errors preserve query and expose reconnect controls

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L326: `assert.equal(app.element("query").value, "keep this");`
  - L327: `assert.equal(app.element("notice").textContent, "network lost");`
  - L330: `assert.equal(app.element("auth").open, true);`
  - L331: `assert.equal(app.element("toggle").disabled, true);`

### `test_web_dashboard_frontend.cjs:345` — desktop pointer drag sends move with the observed revision

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L345: `assert.equal(app.run("drag.active"), true);`
  - L348: `assert.deepEqual(move.data, {from: 1, to: 2, revision: "revision-1"});`
  - L349: `assert.equal(grip.hasPointerCapture(7), false);`

### `test_web_dashboard_frontend.cjs:356` — touch drag requires long press and then uses the same move API

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L356: `assert.equal(app.run("drag.active"), false);`
  - L361: `assert.deepEqual(app.requests.find((r) => r.url.endsWith("queue/move")).data,`

### `test_web_dashboard_frontend.cjs:371` — touch tap or movement before long press cancels without moving

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Assert computed styles and browser geometry/accessibility on the built DOM at mobile/desktop and light/dark settings.
- 舊斷言逐行索引：
  - L371: `assert.equal(app.run("drag"), null);`
  - L372: `assert.equal(app.requests.some((r) => r.url.endsWith("queue/move")), false);`

### `test_web_dashboard_frontend.cjs:384` — Escape, pointercancel, lost capture and same-position drop send no mutations

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L384: `assert.equal(app.run("drag"), null);`
  - L385: `assert.equal(app.requests.some((r) => r.url.endsWith("queue/move")), false);`

### `test_web_dashboard_frontend.cjs:395` — changed queue revision cancels an active drag

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L395: `assert.equal(app.run("drag"), null);`
  - L396: `assert.equal(app.element("notice").textContent.includes("取消拖曳"), true);`
  - L398: `assert.equal(app.requests.some((r) => r.url.endsWith("queue/move")), false);`

### `test_web_dashboard_frontend.cjs:409` — stale drag response 409 refreshes state and retains the error notice

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L409: `assert.equal(app.element("notice").textContent, "stale queue");`
  - L410: `assert.equal(app.requests.at(-1).url, "api/guilds/1/state");`
  - L411: `assert.equal(handle(app).disabled, false);`

### `test_web_dashboard_frontend.cjs:418` — lookup never plays until the selected result is explicitly confirmed

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L418: `assert.equal(app.requests.some((r) => r.url.endsWith("/play")), false);`
  - L419: `assert.equal(app.element("preview-panel").hidden, false);`
  - L420: `assert.equal(app.element("preview-results").children[0].children[1].children[0].textContent, "Selected");`
  - L422: `assert.deepEqual(app.requests.find((r) => r.url.endsWith("/play")).data,`
  - L424: `assert.equal(app.element("preview-panel").hidden, true);`

### `test_web_dashboard_frontend.cjs:435` — denied results are visible with a disabled confirmation button

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L435: `assert.equal(card.children[2].disabled, true);`
  - L437: `assert.equal(app.requests.some((r) => r.url.endsWith("/play")), false);`

### `test_web_dashboard_frontend.cjs:447` — slow resolve permits playback controls and prevents duplicate lookups

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L447: `assert.equal(app.element("enqueue").disabled, true);`
  - L448: `assert.equal(app.element("toggle").disabled, false);`
  - L451: `assert.equal(app.requests.filter((r) => r.url.endsWith("/resolve")).length, 1);`

### `test_web_dashboard_frontend.cjs:469` — guild switching and clearing reject stale lookup responses

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L469: `assert.equal(app.element("preview-panel").hidden, true);`
  - L470: `assert.equal(app.element("preview-results").children.length, 0);`

### `test_web_dashboard_frontend.cjs:483` — duplicate confirm clicks are blocked and failed replies retain the same token

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L483: `assert.equal(app.requests.filter((r) => r.url.endsWith("/play")).length, 1);`
  - L486: `assert.equal(app.element("preview-panel").hidden, false);`
  - L487: `assert.equal(button.disabled, false);`
  - L491: `assert.deepEqual(plays[0].data, plays[1].data);`

### `test_web_dashboard_frontend.cjs:499` — edge dragging schedules scrolling and cancellation clears animation

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L499: `assert.deepEqual(app.scrolls.at(-1), [0, -10]);`
  - L501: `assert.equal(app.run("drag"), null);`

### `test_web_dashboard_frontend.cjs:512` — an old state poll cannot overwrite a completed mutation

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Observe rendered state transitions while fixture endpoints/stream change or fail; assert recovered/cleared UI and no stale content.
- 舊斷言逐行索引：
  - L512: `assert.equal(app.element("toggle").textContent.includes("繼續"), true);`
  - L515: `assert.equal(app.element("toggle").textContent.includes("繼續"), true);`

### `test_web_dashboard_frontend.cjs:529` — logged-out Discord page reads no guild or song APIs, including subsequent polls

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L529: `assert.deepEqual(app.requests.map((request) => request.url), ["/auth/session"]);`
  - L530: `assert.equal(app.element("dashboard").hidden, true);`
  - L531: `assert.equal(app.element("login-screen").hidden, false);`
  - L532: `assert.equal(app.element("discord-login").hidden, false);`
  - L533: `assert.equal(app.element("auth").hidden, true);`
  - L534: `assert.equal(app.element("enqueue").disabled, true);`
  - L536: `assert.equal(app.requests.length, 1);`

### `test_web_dashboard_frontend.cjs:541` — Discord session renders a safe profile and never sends shared-secret authorization

- 舊意圖：11 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L541: `assert.equal(app.requests[0].url, "/auth/session");`
  - L542: `assert.equal(app.requests[0].headers, undefined);`
  - L543: `assert.equal(app.requests[0].credentials, "same-origin");`
  - L544: `assert.equal(app.element("dashboard").hidden, false);`
  - L545: `assert.equal(app.element("login-screen").hidden, true);`
  - L546: `assert.equal(app.element("user-profile").hidden, false);`
  - L547: `assert.equal(app.element("user-name").textContent, "<img onerror=evil>");`
  - L548: `assert.equal(app.element("user-avatar").src, discordSession().user.avatar);`
  - L549: `assert.equal(app.element("auth").hidden, true);`
  - L553: `assert.ok(app.requests.every((request) => request.headers?.Authorization === undefined));`
  - L554: `assert.ok(app.requests.filter((request) => request.url.startsWith("api/")).every(`

### `test_web_dashboard_frontend.cjs:563` — Discord API 401 erases songs, guilds, preview, profile and query before stopping polling

- 舊意圖：15 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L563: `assert.equal(app.element("dashboard").hidden, true);`
  - L564: `assert.equal(app.element("login-screen").hidden, false);`
  - L565: `assert.equal(app.element("login-status").textContent, "session expired");`
  - L566: `assert.equal(app.element("guild").children.length, 0);`
  - L567: `assert.equal(app.element("queue").children.length, 0);`
  - L568: `assert.equal(app.element("preview-results").children.length, 0);`
  - L569: `assert.equal(app.element("preview-panel").hidden, true);`
  - L570: `assert.equal(app.element("query").value, "");`
  - L571: `assert.equal(app.element("user-name").textContent, "");`
  - L572: `assert.equal(app.element("user-avatar").getAttribute("src"), null);`
  - L573: `assert.notEqual(app.element("bar-title").textContent, "First");`
  - L574: `assert.notEqual(app.element("bar-title").textContent, "First");`
  - L575: `assert.equal(app.run("state"), null);`
  - L576: `assert.equal(app.run("selected"), "");`
  - L579: `assert.equal(app.requests.length, count);`

### `test_web_dashboard_frontend.cjs:592` — late state and lookup responses cannot restore content after session expiry

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L592: `assert.equal(app.element("dashboard").hidden, true);`
  - L593: `assert.equal(app.run("state"), null);`
  - L594: `assert.equal(app.element("queue").children.length, 0);`
  - L595: `assert.equal(app.element("preview-results").children.length, 0);`

### `test_web_dashboard_frontend.cjs:602` — mutation 401 stops reconciliation without exposing the old guild again

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L602: `assert.equal(app.requests.at(-1).url, "api/guilds/1/skip");`
  - L603: `assert.equal(app.element("dashboard").hidden, true);`
  - L604: `assert.equal(app.element("toggle").disabled, true);`

### `test_web_dashboard_frontend.cjs:611` — permission 403 displays the bot reason while retaining the Discord session

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L611: `assert.equal(app.element("notice").textContent, "you must join the bot voice channel");`
  - L612: `assert.equal(app.element("dashboard").hidden, false);`
  - L613: `assert.equal(app.element("user-profile").hidden, false);`
  - L614: `assert.equal(app.run("authenticated"), true);`
  - L615: `assert.equal(app.element("toggle").disabled, false);`

### `test_web_dashboard_frontend.cjs:627` — logout posts with the CSRF header, clears personal content and rejects a late lookup

- 舊意圖：11 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L627: `assert.equal(request.url, "/auth/logout");`
  - L628: `assert.equal(request.method, "POST");`
  - L629: `assert.equal(request.headers["X-MusicBot-Dashboard"], "1");`
  - L630: `assert.equal(request.credentials, "same-origin");`
  - L631: `assert.equal(request.headers.Authorization, undefined);`
  - L632: `assert.equal(app.element("user-name").textContent, "");`
  - L633: `assert.equal(app.element("guild").children.length, 0);`
  - L634: `assert.equal(app.element("queue").children.length, 0);`
  - L637: `assert.equal(app.element("preview-results").children.length, 0);`
  - L638: `assert.equal(app.element("dashboard").hidden, true);`
  - L641: `assert.equal(app.requests.length, count);`

### `test_web_dashboard_frontend.cjs:648` — a rejected logout retains login and gives a retryable error

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L648: `assert.equal(app.element("notice").textContent, "try logout again");`
  - L649: `assert.equal(app.element("dashboard").hidden, false);`
  - L650: `assert.equal(app.element("logout").disabled, false);`
  - L651: `assert.equal(app.run("authenticated"), true);`

### `test_web_dashboard_frontend.cjs:659` — session bootstrap failure and malformed responses fail closed without API reads

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L659: `assert.deepEqual(app.requests.map((request) => request.url), ["/auth/session"]);`
  - L660: `assert.equal(app.element("dashboard").hidden, true);`
  - L661: `assert.equal(app.element("login-screen").hidden, false);`
  - L662: `assert.equal(app.run("authenticated"), false);`
  - L664: `assert.equal(app.requests.length, 1);`

### `test_web_dashboard_frontend.cjs:671` — incomplete Discord identity is treated as logged out and unsafe avatar URLs are ignored

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L671: `assert.equal(loggedOut.requests.length, 1);`
  - L672: `assert.equal(loggedOut.element("dashboard").hidden, true);`
  - L675: `assert.equal(loggedIn.element("user-avatar").getAttribute("src"), null);`

### `test_web_dashboard_frontend.cjs:680` — owner retains connection settings and uses no Discord profile

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L680: `assert.equal(app.element("auth").hidden, false);`
  - L681: `assert.equal(app.element("user-profile").hidden, true);`
  - L684: `assert.equal(app.requests.length, count);`

### `test_web_dashboard_frontend.cjs:689` — initial HTML conceals the dashboard and provides a same-origin Discord login link

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L689: `assert.match(html, /<div id="dashboard" hidden>/);`
  - L690: `assert.match(html, /id="discord-login"[^>]*href="\/auth\/login"/);`
  - L691: `assert.match(html, /id="user-profile"[^>]*hidden/);`
  - L692: `assert.ok(html.indexOf('id="login-screen"') < html.indexOf('id="dashboard"'));`

### `test_web_dashboard_frontend.cjs:701` — a non-JSON API 401 still clears the Discord session and stops polling

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L701: `assert.equal(app.element("dashboard").hidden, true);`
  - L702: `assert.equal(app.run("authenticated"), false);`
  - L703: `assert.equal(app.element("queue").children.length, 0);`
  - L706: `assert.equal(app.requests.length, count);`

### `test_web_dashboard_frontend.cjs:716` — resolve spinner disables only lookup and resets after a failed response

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L716: `assert.equal(app.element("enqueue").getAttribute("aria-busy"), "true");`
  - L717: `assert.equal(app.element("enqueue").classes.has("is-loading"), true);`
  - L718: `assert.equal(app.element("enqueue").disabled, true);`
  - L719: `assert.equal(app.element("toggle").disabled, false);`
  - L722: `assert.equal(app.element("enqueue").getAttribute("aria-busy"), "false");`
  - L723: `assert.equal(app.element("enqueue").classes.has("is-loading"), false);`
  - L724: `assert.equal(app.element("enqueue").disabled, false);`

### `test_web_dashboard_frontend.cjs:736` — play spinner resets on client timeout and preserves its confirmation token

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Observe rendered state transitions while fixture endpoints/stream change or fail; assert recovered/cleared UI and no stale content.
- 舊斷言逐行索引：
  - L736: `assert.equal(button.dataset.loading, "1");`
  - L737: `assert.equal(button.getAttribute("aria-busy"), "true");`
  - L738: `assert.equal(button.disabled, true);`
  - L741: `assert.equal(button.dataset.loading, "0");`
  - L742: `assert.equal(button.disabled, false);`
  - L743: `assert.equal(app.element("preview-panel").hidden, false);`
  - L744: `assert.match(app.element("notice").textContent, /逾時/);`

### `test_web_dashboard_frontend.cjs:751` — toast expires automatically and an old timer cannot erase a new error

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Assert computed styles and browser geometry/accessibility on the built DOM at mobile/desktop and light/dark settings.
- 舊斷言逐行索引：
  - L751: `assert.equal(success[1], 4500);`
  - L752: `assert.equal(app.element("notice").classes.has("visible"), true);`
  - L755: `assert.equal(error[1], 10000);`
  - L757: `assert.equal(app.element("notice").textContent, "拒絕");`
  - L758: `assert.equal(app.element("notice").classes.has("error"), true);`
  - L760: `assert.equal(app.element("notice").textContent, "");`
  - L761: `assert.equal(app.element("notice").classes.has("visible"), false);`

### `test_web_dashboard_frontend.cjs:770` — current source link only exposes HTTP links and requester display names

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L770: `assert.equal(app.element("source-link").href, app.states[1].current.url);`
  - L771: `assert.equal(app.element("source-link").hidden, false);`
  - L772: `assert.match(app.element("source-link").textContent, /YouTube/);`
  - L773: `assert.equal(app.element("bar-status").textContent, "播放中 · 點播：<script>點播者</script>");`
  - L774: `assert.equal(app.element("queue").children[0].children[2].children[1].textContent, "點播：好友");`
  - L778: `assert.equal(app.element("source-link").hidden, true);`

### `test_web_dashboard_frontend.cjs:800` — playlist defaults to all eligible items and cannot select a blocked row

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L800: `assert.equal(list.children.length, 3);`
  - L801: `assert.equal(list.children[0].children[0].children[0].checked, true);`
  - L802: `assert.equal(list.children[1].children[0].children[0].checked, false);`
  - L803: `assert.equal(list.children[1].children[0].children[0].disabled, true);`
  - L804: `assert.equal(button.textContent, "加入佇列（2 首）");`
  - L806: `assert.deepEqual(app.requests.find((request) => request.url.endsWith("/play")).data, {`

### `test_web_dashboard_frontend.cjs:813` — playlist select none, select all and individual selection update the count and payload

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L813: `assert.equal(button.textContent, "加入佇列（0 首）");`
  - L814: `assert.equal(button.disabled, true);`
  - L816: `assert.equal(app.requests.some((request) => request.url.endsWith("/play")), false);`
  - L820: `assert.equal(button.textContent, "加入佇列（1 首）");`
  - L822: `assert.deepEqual(app.requests.find((request) => request.url.endsWith("/play")).data.selected_items, ["3"]);`

### `test_web_dashboard_frontend.cjs:831` — batch confirmation displays spinner, freezes selection and reports partial success toast

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Assert computed styles and browser geometry/accessibility on the built DOM at mobile/desktop and light/dark settings.
- 舊斷言逐行索引：
  - L831: `assert.equal(button.getAttribute("aria-busy"), "true");`
  - L832: `assert.equal(list.children[0].children[0].children[0].disabled, true);`
  - L833: `assert.equal(button.disabled, true);`
  - L837: `assert.match(app.element("notice").textContent, /已加入 1 首/);`
  - L838: `assert.equal(app.element("notice").classes.has("visible"), true);`

### `test_web_dashboard_frontend.cjs:848` — drag lifts the source, shifts neighbours, sends one move and animates rollback on 409

- 舊意圖：9 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L848: `assert.equal(rows[0].classes.has("dragging"), true);`
  - L849: `assert.match(rows[0].style.transform, /scale\(1.025\)/);`
  - L850: `assert.match(rows[1].style.transform, /translateY\(-110px\)/);`
  - L853: `assert.equal(rows[0].classes.has("settling"), true);`
  - L854: `assert.equal(app.requests.filter((request) => request.url.endsWith("queue/move")).length, 1);`
  - L857: `assert.equal(rows[0].style.transform, "");`
  - L858: `assert.equal(rows[1].style.transform, "");`
  - L859: `assert.equal(app.run("dragVisual"), null);`
  - L860: `assert.equal(app.element("notice").textContent, "隊列已更新");`

### `test_web_dashboard_frontend.cjs:872` — queue reorder uses FLIP frames and reduced motion skips transforms while retaining move

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L872: `assert.ok(app.element("queue").children.some((row) => row.animations.length > 0));`
  - L878: `assert.equal(reduced.element("queue").children[0].style.transform, undefined);`
  - L880: `assert.equal(reduced.requests.filter((request) => request.url.endsWith("queue/move")).length, 1);`

### `test_web_dashboard_frontend.cjs:886` — fixed accessible toast, safe source link and reduced motion CSS are present

- 舊意圖：9 個 assert calls；納入 Vue browser migration
- 新驗證：Assert computed styles and browser geometry/accessibility on the built DOM at mobile/desktop and light/dark settings.
- 舊斷言逐行索引：
  - L886: `assert.match(html, /id="notice"[^>]*role="status"[^>]*aria-live="polite"[^>]*aria-atomic="true"/);`
  - L887: `assert.match(html, /id="source-link"[^>]*target="_blank"[^>]*rel="noopener noreferrer"/);`
  - L888: `assert.match(css, /\.notice\{position:fixed/);`
  - L889: `assert.match(css, /prefers-reduced-motion:reduce/);`
  - L890: `assert.match(css, /\.is-loading::before\{display:none/);`
  - L892: `assert.ok(!html.includes(slogan) && !code.includes(slogan), slogan);`
  - L893: `assert.ok(!html.includes("sidebar-note"));`
  - L895: `assert.ok(!html.includes(slogan) && !code.includes(slogan), slogan);`
  - L896: `assert.ok(!html.includes("owner-badge") && !code.includes("owner-badge"));`

### `test_web_dashboard_frontend.cjs:910` — drop displacement uses unequal row heights without changing the move payload

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L910: `assert.equal(rows[0].style.transform, "translateY(74px)");`
  - L911: `assert.equal(rows[1].style.transform, "translateY(-120px)");`
  - L914: `assert.deepEqual(app.requests.find((request) => request.url.endsWith("queue/move")).data,`

### `test_web_dashboard_frontend.cjs:927` — both seek sliders preview a drag across polling and post only on release

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L927: `assert.equal(app.element("progress").value, 105);`
  - L928: `assert.equal(app.element("progress").value, 105);`
  - L929: `assert.equal(app.element("elapsed").textContent, "1:45");`
  - L930: `assert.equal(app.element("elapsed").textContent, "1:45");`
  - L931: `assert.equal(app.requests.filter((request) => request.url.endsWith("/seek")).length, 0);`
  - L934: `assert.deepEqual(app.requests.filter((request) => request.url.endsWith("/seek")).map((request) => request.data),`
  - L936: `assert.equal(app.element("progress").value, 105);`

### `test_web_dashboard_frontend.cjs:945` — touch seek and keyboard repeated arrows commit once at the end of interaction

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Operate the rendered seek range by pointer/touch/keyboard; inspect value/progress and the scoped seek request.
- 舊斷言逐行索引：
  - L945: `assert.deepEqual(app.requests.filter((request) => request.url.endsWith("/seek")).map((request) => request.data),`
  - L951: `assert.equal(app.requests.filter((request) => request.url.endsWith("/seek")).length, 1);`
  - L954: `assert.deepEqual(app.requests.filter((request) => request.url.endsWith("/seek")).map((request) => request.data),`

### `test_web_dashboard_frontend.cjs:961` — assistive input/change commits once and cancelled seek restores actual time

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Operate the rendered seek range by pointer/touch/keyboard; inspect value/progress and the scoped seek request.
- 舊斷言逐行索引：
  - L961: `assert.deepEqual(app.requests.find((request) => request.url.endsWith("/seek")).data, {position: 75});`
  - L964: `assert.equal(slider.value, 75);`
  - L965: `assert.equal(app.run("seekDrag"), null);`
  - L969: `assert.equal(app.requests.filter((request) => request.url.endsWith("/seek")).length, 1);`

### `test_web_dashboard_frontend.cjs:978` — track and guild changes cancel seek so release cannot target a new song

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L978: `assert.equal(slider.value, 0);`
  - L979: `assert.equal(app.requests.some((request) => request.url.endsWith("/seek")), false);`
  - L983: `assert.equal(slider.value, 30);`
  - L984: `assert.equal(app.requests.some((request) => request.url.endsWith("/seek")), false);`

### `test_web_dashboard_frontend.cjs:990` — live, empty and disconnected players disable seek and backend rejection reconciles

- 舊意圖：8 個 assert calls；納入 Vue browser migration
- 新驗證：Operate the rendered seek range by pointer/touch/keyboard; inspect value/progress and the scoped seek request.
- 舊斷言逐行索引：
  - L990: `assert.equal(app.element("progress").disabled, true);`
  - L993: `assert.equal(app.element("progress").disabled, true);`
  - L994: `assert.equal(app.element("progress").disabled, true);`
  - L996: `assert.equal(app.run("seekDrag"), null);`
  - L1002: `assert.equal(slider.value, 30);`
  - L1003: `assert.match(app.element("notice").textContent, /語音頻道/);`
  - L1005: `assert.equal(app.element("progress").disabled, true);`
  - L1006: `assert.equal(app.element("lyrics-toggle").disabled, true);`

### `test_web_dashboard_frontend.cjs:1013` — single preview has separate playnext confirmation using the same scoped token

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L1013: `assert.equal(card.children[2].textContent, "加入佇列");`
  - L1014: `assert.equal(card.children[3].textContent, "下一首播放");`
  - L1016: `assert.deepEqual(app.requests.find((request) => request.url.endsWith("/playnext")).data,`
  - L1018: `assert.equal(app.requests.some((request) => request.url.endsWith("/play")), false);`

### `test_web_dashboard_frontend.cjs:1025` — playnext-only users can query with playnext permission and receive actual command denial

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L1025: `assert.equal(app.requests.find((request) => request.url.endsWith("/resolve")).data.action, "playnext");`
  - L1027: `assert.equal(card.children[2].textContent, "下一首播放");`
  - L1028: `assert.equal(card.children[3].textContent, "加入佇列");`
  - L1031: `assert.match(app.element("notice").textContent, /play/);`
  - L1032: `assert.equal(app.element("preview-panel").hidden, false);`
  - L1034: `assert.equal(app.requests.filter((request) => request.url.endsWith("/playnext")).length, 1);`

### `test_web_dashboard_frontend.cjs:1039` — playlist preview retains ordered selection and offers no batch playnext control

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L1039: `assert.equal(card.children.length, 3);`
  - L1040: `assert.match(card.children[1].children.at(-3).textContent, /下一首播放目前只提供單曲/);`
  - L1041: `assert.match(button.textContent, /加入佇列/);`

### `test_web_dashboard_frontend.cjs:1055` — history renders at most fifty safe songs, requesters, times and source links

- 舊意圖：8 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L1055: `assert.equal(rows.length, 50);`
  - L1056: `assert.equal(rows[0].children[1].children[0].textContent, "<script>history</script>");`
  - L1057: `assert.match(rows[0].children[1].children[1].textContent, /點播：<img>朋友/);`
  - L1058: `assert.match(rows[0].children[1].children[1].textContent, /3 分鐘前/);`
  - L1060: `assert.equal(link.href, "https://example.test/replay-0");`
  - L1061: `assert.equal(link.rel, "noopener noreferrer");`
  - L1062: `assert.equal(app.run("playedTime(null)"), "播放時間未知");`
  - L1063: `assert.match(app.run("playedTime(1)"), /08:00/);`

### `test_web_dashboard_frontend.cjs:1072` — history replay only opens a play-permission preview until separately confirmed

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L1072: `assert.deepEqual(resolve.data, {query: "https://example.test/replay-0", action: "play"});`
  - L1073: `assert.equal(app.requests.some((request) => request.url.endsWith("/play")), false);`
  - L1074: `assert.equal(app.element("preview-panel").hidden, false);`

### `test_web_dashboard_frontend.cjs:1081` — history failures are isolated and late guild response cannot restore old records

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L1081: `assert.match(app.element("history-status").textContent, /成員/);`
  - L1082: `assert.equal(app.element("toggle").disabled, false);`
  - L1088: `assert.equal(app.element("history-list").children.length, 0);`
  - L1089: `assert.equal(app.element("bar-title").textContent, "Second");`

### `test_web_dashboard_frontend.cjs:1099` — synced lyrics highlight and scroll the current line as playback advances

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L1099: `assert.equal(app.element("lyrics-panel").hidden, false);`
  - L1100: `assert.equal(app.element("lyrics-toggle").getAttribute("aria-expanded"), "true");`
  - L1102: `assert.equal(rows[1].textContent, "<script>第一句</script>");`
  - L1103: `assert.equal(rows[1].getAttribute("aria-current"), "true");`
  - L1104: `assert.equal(app.element("lyrics-content").scrolled.behavior, "smooth");`
  - L1106: `assert.equal(rows[1].getAttribute("aria-current"), null);`
  - L1107: `assert.equal(rows[2].getAttribute("aria-current"), "true");`

### `test_web_dashboard_frontend.cjs:1117` — lyrics are not fetched every poll or on reopen and reduced motion scrolls instantly

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L1117: `assert.equal(app.requests.filter((request) => request.url.endsWith("/lyrics")).length, 1);`
  - L1118: `assert.equal(app.element("lyrics-content").scrolled.behavior, "auto");`

### `test_web_dashboard_frontend.cjs:1125` — plain lyrics render as safe text and missing lyrics expose a same-origin manual search

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L1125: `assert.equal(app.element("lyrics-content").textContent, "<img>\n第二行");`
  - L1126: `assert.equal(app.element("lyrics-content").classes.has("plain-lyrics"), true);`
  - L1129: `assert.equal(app.element("lyrics-status").textContent, "找不到這首的歌詞");`
  - L1130: `assert.equal(app.element("lyrics-search-form").hidden, false);`
  - L1133: `assert.ok(app.requests.some((request) => request.url === "api/guilds/1/lyrics?query=" + encodeURIComponent("歌名 Artist")));`
  - L1134: `assert.equal(app.requests.every((request) => !/^https?:\/\//.test(request.url)), true);`

### `test_web_dashboard_frontend.cjs:1141` — lyrics service errors and rate limits leave playback usable with manual retry

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L1141: `assert.match(app.element("lyrics-status").textContent, /暫時無法使用/);`
  - L1142: `assert.equal(app.element("toggle").disabled, false);`
  - L1145: `assert.match(app.element("lyrics-status").textContent, /太頻繁/);`
  - L1146: `assert.equal(app.element("lyrics-search-form").hidden, false);`
  - L1148: `assert.equal(app.element("toggle").textContent, "繼續");`

### `test_web_dashboard_frontend.cjs:1160` — late lyrics cannot overwrite a different track, different guild or expired session

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L1160: `assert.equal(app.element("lyrics-content").textContent, "new lyrics");`
  - L1166: `assert.equal(app.element("lyrics-panel").hidden, true);`
  - L1167: `assert.equal(app.element("lyrics-content").textContent, "");`
  - L1171: `assert.equal(app.element("lyrics-content").textContent, "");`
  - L1172: `assert.equal(app.element("dashboard").hidden, true);`

### `test_web_dashboard_frontend.cjs:1183` — manual lyrics query rejects an older slower response for the same track

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L1183: `assert.equal(app.element("lyrics-content").textContent, "manual result");`

### `test_web_dashboard_frontend.cjs:1190` — seek controls remain native keyboard/touch ranges and lyrics use no external script

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Operate the rendered seek range by pointer/touch/keyboard; inspect value/progress and the scoped seek request.
- 舊斷言逐行索引：
  - L1190: `assert.match(html, new RegExp('id="' + id + '"[^>]*type="range"[^>]*step="1"[^>]*aria-label='));`
  - L1191: `assert.match(html, /id="lyrics-toggle"[^>]*aria-controls="lyrics-panel"/);`
  - L1192: `assert.match(css, /progress-row input\[type=range\].*min-height:44px/);`
  - L1193: `assert.match(css, /@media\(prefers-reduced-motion:reduce\)/);`
  - L1194: `assert.ok(!html.includes("lrclib") && !code.includes("https://lrclib"));`

### `test_web_dashboard_frontend.cjs:1202` — seek sends the captured track token and reconciles a backend stale-track rejection

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Operate the rendered seek range by pointer/touch/keyboard; inspect value/progress and the scoped seek request.
- 舊斷言逐行索引：
  - L1202: `assert.equal(app.run("seekDrag.trackToken"), "track-at-drag-start");`
  - L1207: `assert.equal(JSON.parse(options.body).track_token, "track-at-drag-start"),`
  - L1211: `assert.equal(requests.length, 1);`
  - L1212: `assert.deepEqual(requests[0].data, {position: 110, track_token: "track-at-drag-start"});`
  - L1213: `assert.equal(slider.value, 4);`
  - L1214: `assert.equal(app.states[1].progress, 4);`
  - L1215: `assert.match(app.element("notice").textContent, /歌曲已更換/);`

### `test_web_dashboard_frontend.cjs:1225` — a changed track token cancels seek even when title URL and duration are unchanged

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Operate the rendered seek range by pointer/touch/keyboard; inspect value/progress and the scoped seek request.
- 舊斷言逐行索引：
  - L1225: `assert.equal(app.run("seekDrag"), null);`
  - L1226: `assert.equal(slider.value, 2);`
  - L1227: `assert.equal(app.requests.some((request) => request.url.endsWith("/seek")), false);`

### `test_web_dashboard_frontend.cjs:1238` — a blocked single-song preview disables both command confirmation buttons

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L1238: `assert.equal(card.children[2].disabled, true);`
  - L1239: `assert.equal(card.children[3].disabled, true);`
  - L1241: `assert.equal(app.requests.some((request) => /\/(?:play\|playnext)$/.test(request.url)), false);`

### `test_web_dashboard_frontend.cjs:1252` — native range lost capture preserves preview until document pointerup commits once

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L1252: `assert.equal(app.run("seekDrag.position"), 120);`
  - L1253: `assert.equal(slider.value, 120);`
  - L1254: `assert.equal(slider.capture, undefined);`
  - L1255: `assert.equal(app.requests.some((request) => request.url.endsWith("/seek")), false);`
  - L1257: `assert.equal(app.run("seekDrag.position"), 120);`
  - L1260: `assert.equal(app.requests.filter((request) => request.url.endsWith("/seek")).length, 1);`
  - L1261: `assert.deepEqual(app.requests.find((request) => request.url.endsWith("/seek")).data, {position: 120});`

### `test_web_dashboard_frontend.cjs:1268` — blurring a pointer seek cancels safely while keyboard blur commits its final preview

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Operate the rendered seek range by pointer/touch/keyboard; inspect value/progress and the scoped seek request.
- 舊斷言逐行索引：
  - L1268: `assert.equal(slider.value, 30);`
  - L1269: `assert.equal(app.requests.some((request) => request.url.endsWith("/seek")), false);`
  - L1272: `assert.deepEqual(app.requests.find((request) => request.url.endsWith("/seek")).data, {position: 180});`

### `test_web_dashboard_frontend.cjs:1277` — queue estimates add current remainder and previous durations

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L1277: `assert.equal(app.run("queueSchedule(state,30).total"), "共 0 小時 3 分");`
  - L1278: `assert.equal(app.run("queueSchedule(state,30).times.get(1)"), "約 3 分鐘後");`
  - L1279: `assert.equal(app.run("queueSchedule(state,30).times.get(2)"), "約 4 分鐘後");`
  - L1280: `assert.equal(app.element("queue").children[0].children[2].children[2].textContent, "約 3 分鐘後");`

### `test_web_dashboard_frontend.cjs:1287` — unknown duration makes subsequent estimates undetermined

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L1287: `assert.match(app.run("queueSchedule(state).total"), /已知.*含長度未知/);`
  - L1288: `assert.match(app.run("queueSchedule(state).times.get(1)"), /分鐘/);`
  - L1289: `assert.equal(app.run("queueSchedule(state).times.get(2)"), "時間未定");`
  - L1292: `assert.equal(app.run("queueSchedule(state).times.get(1)"), "時間未定");`

### `test_web_dashboard_frontend.cjs:1302` — paused stopped and single repeat never invent start times

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L1302: `assert.equal(app.run("queueSchedule(state).times.get(1)"), expected);`

### `test_web_dashboard_frontend.cjs:1310` — queue repeat shows first traversal and rounds long totals

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L1310: `assert.equal(app.run("queueSchedule(state).total"), "共 1 小時 4 分");`
  - L1311: `assert.match(app.element("queue-timing-note").textContent,/本輪/);`
  - L1312: `assert.match(app.run("queueSchedule(state).times.get(1)"),/分鐘/);`

### `test_web_dashboard_frontend.cjs:1318` — local progress advances only playing and caps at duration

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Operate the rendered seek range by pointer/touch/keyboard; inspect value/progress and the scoped seek request.
- 舊斷言逐行索引：
  - L1318: `assert.ok(app.run("localProgress()") >= 40);`
  - L1320: `assert.equal(app.run("localProgress()"),30);`
  - L1322: `assert.equal(app.run("localProgress()"),180);`
  - L1324: `assert.equal(app.run("localProgress()"),30);`

### `test_web_dashboard_frontend.cjs:1333` — my queue filter uses full positions for move and delete

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L1333: `assert.equal(row.dataset.position,"2");`
  - L1334: `assert.equal(app.element("queue").children.length,1);`
  - L1335: `assert.equal(app.element("queue-count").textContent,"2");`
  - L1336: `assert.equal(row.children[4].children[0].disabled,true);`
  - L1337: `assert.equal(app.element("shuffle").disabled,true);`
  - L1339: `assert.deepEqual(app.requests.find(r=>r.url.endsWith("queue/move")).data,`
  - L1342: `assert.equal(app.requests.find(r=>r.method==="DELETE").url,"api/guilds/1/queue/1");`

### `test_web_dashboard_frontend.cjs:1352` — my filter disables pointer sorting and reports empty selection

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L1352: `assert.equal(app.run("drag"),null);`
  - L1355: `assert.equal(app.element("queue").children.length,0);`
  - L1356: `assert.match(app.element("queue-empty").textContent,/沒有你點播/);`
  - L1358: `assert.equal(app.element("queue").children.length,2);`

### `test_web_dashboard_frontend.cjs:1367` — listeners fold above eight and render names as text

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L1367: `assert.equal(list.children.length,9);`
  - L1368: `assert.equal(list.children[0].children[1].textContent,"<script>unsafe</script>");`
  - L1369: `assert.equal(list.children[0].children[0].src,undefined);`
  - L1370: `assert.equal(list.children[8].tag,"details");`
  - L1371: `assert.match(list.children[8].children[0].textContent,/3/);`
  - L1374: `assert.match(app.element("listeners-status").textContent,/目前不在語音頻道/);`

### `test_web_dashboard_frontend.cjs:1383` — activity displays the configured time zone, source, result and safe song text

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L1383: `assert.equal(row.children[0].textContent,"Friend・點歌：<script>");`
  - L1384: `assert.match(row.children[1].textContent,/09:02:03.*Discord 斜線.*成功/);`

### `test_web_dashboard_frontend.cjs:1390` — SSE connects without headers and supersedes periodic fetches

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Observe rendered state transitions while fixture endpoints/stream change or fail; assert recovered/cleared UI and no stale content.
- 舊斷言逐行索引：
  - L1390: `assert.equal(app.streams[0].url,"/api/guilds/1/events?lang=zh-TW");`
  - L1394: `assert.equal(app.requests.length,count);`
  - L1395: `assert.equal(app.run("fallbackPolling"),false);`
  - L1396: `assert.equal(app.element("connection").textContent,"連線狀態");`

### `test_web_dashboard_frontend.cjs:1405` — SSE pushes community and history without optional REST polling

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Observe rendered state transitions while fixture endpoints/stream change or fail; assert recovered/cleared UI and no stale content.
- 舊斷言逐行索引：
  - L1405: `assert.equal(app.element("volume").value,72);`
  - L1406: `assert.equal(app.element("activity-list").children.length,1);`
  - L1407: `assert.equal(app.requests.length,count);`

### `test_web_dashboard_frontend.cjs:1418` — SSE reconnect backoff and repeated failure polling fallback

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L1418: `assert.equal(old.closed,true);`
  - L1421: `assert.equal(app.run("fallbackPolling"),true);`
  - L1424: `assert.equal(app.requests.length,count);`
  - L1428: `assert.deepEqual(delays,[1000,2000,4000,60000]);`
  - L1430: `assert.equal(app.run("eventFailures"),0);`
  - L1431: `assert.equal(app.run("fallbackPolling"),false);`

### `test_web_dashboard_frontend.cjs:1439` — SSE switch guild closes old stream ignores stale callbacks

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L1439: `assert.equal(old.closed,true);`
  - L1440: `assert.equal(app.streams.at(-1).url,"/api/guilds/2/events?lang=zh-TW");`
  - L1442: `assert.equal(app.element("bar-title").textContent,"Second");`
  - L1444: `assert.equal(app.element("connection").textContent,"連線狀態");`

### `test_web_dashboard_frontend.cjs:1453` — SSE hiding tab closes stream and showing resumes

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Observe rendered state transitions while fixture endpoints/stream change or fail; assert recovered/cleared UI and no stale content.
- 舊斷言逐行索引：
  - L1453: `assert.equal(old.closed,true);`
  - L1456: `assert.equal(app.requests.length,count);`
  - L1459: `assert.equal(app.streams.length,2);`

### `test_web_dashboard_frontend.cjs:1468` — SSE expiry clears all private UI and closes connection

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Observe rendered state transitions while fixture endpoints/stream change or fail; assert recovered/cleared UI and no stale content.
- 舊斷言逐行索引：
  - L1468: `assert.equal(stream.closed,true);`
  - L1469: `assert.equal(app.run("authenticated"),false);`
  - L1470: `assert.equal(app.element("queue").children.length,0);`
  - L1471: `assert.equal(app.element("activity-list").children.length,0);`
  - L1472: `assert.equal(app.element("dashboard").hidden,true);`

### `test_web_dashboard_frontend.cjs:1478` — SSE construction timeout and absent support retain polling

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Observe rendered state transitions while fixture endpoints/stream change or fail; assert recovered/cleared UI and no stale content.
- 舊斷言逐行索引：
  - L1478: `assert.ok(timeout);`
  - L1480: `assert.equal(app.streams[0].closed,true);`
  - L1481: `assert.equal(app.run("fallbackPolling"),true);`
  - L1483: `assert.equal(plain.run("fallbackPolling"),true);`

### `test_web_dashboard_frontend.cjs:1491` — legacy shared secret never enters EventSource URL

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L1491: `assert.equal(app.streams.length,1);`
  - L1492: `assert.equal(app.streams[0].closed,true);`
  - L1493: `assert.equal(app.run("fallbackPolling"),true);`
  - L1494: `assert.ok(app.streams.every(s=>!s.url.includes("fixture-secret")));`

### `test_web_dashboard_frontend.cjs:1501` — SSE wrong-guild data closes and reconnects safely

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L1501: `assert.equal(app.streams[0].closed,true);`
  - L1502: `assert.equal(app.element("bar-title").textContent,"First");`

### `test_web_dashboard_frontend.cjs:1534` — round7 general member sees playlists and no management entry

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L1534: `await flush();assert.equal(app.element("nav-admin").hidden,true);`
  - L1536: `assert.equal(app.element("play-view").hidden,true);assert.equal(app.element("library-panel").hidden,false);`
  - L1536: `assert.equal(app.element("play-view").hidden,true);assert.equal(app.element("library-panel").hidden,false);`
  - L1537: `assert.equal(app.element("library-list").children[0].children[2].children[0].textContent.startsWith("<img"),true);`
  - L1538: `assert.equal(app.element("library-rename").disabled,true);assert.equal(app.element("library-delete").disabled,true);`
  - L1538: `assert.equal(app.element("library-rename").disabled,true);assert.equal(app.element("library-delete").disabled,true);`

### `test_web_dashboard_frontend.cjs:1542` — owner capability reveals read/delete management

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L1542: `await flush();assert.equal(app.element("nav-admin").hidden,false);`
  - L1543: `assert.equal(app.element("autoplaylist-current").listeners.click, undefined);`
  - L1545: `assert.equal(app.element("admin-panel").hidden,false);`
  - L1546: `assert.equal(app.element("admin-apl-list").children.length,1);`
  - L1547: `assert.equal(app.element("admin-permissions").children[1].children[0].textContent,"Default");`

### `test_web_dashboard_frontend.cjs:1553` — round7 favorite sends only track metadata with revision

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L1553: `assert.deepEqual(request.data,{revision:"library-v1",track:{title:"Saved",url:"https://example.test/saved",duration:12}});`
  - L1554: `assert.equal(request.headers["X-MusicBot-Dashboard"],"1");`

### `test_web_dashboard_frontend.cjs:1559` — round7 playlist picker selects custom list and closes after save

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L1559: `assert.equal(app.element("library-save-dialog").open,true);`
  - L1562: `assert.ok(app.requests.some(r=>r.url==="/api/library/custom/tracks"));`
  - L1563: `assert.equal(app.element("library-save-dialog").open,false);`

### `test_web_dashboard_frontend.cjs:1572` — playlist row removal and rename send observed library revision

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L1572: `assert.equal(change.data.action,"remove");assert.equal(change.data.index,0);`
  - L1572: `assert.equal(change.data.action,"remove");assert.equal(change.data.index,0);`
  - L1573: `assert.equal(change.data.revision,"library-v1");`
  - L1575: `assert.ok(app.requests.some(r=>r.data?.name==="New name"));`

### `test_web_dashboard_frontend.cjs:1582` — round7 checked enqueue uses target guild and displays partial rejection

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L1582: `assert.equal(app.element("library-play-selected").disabled,false);`
  - L1585: `assert.deepEqual(request.data,{revision:"library-v1",selected_items:["1"]});`
  - L1586: `assert.equal(app.element("notice").textContent,"已加入 1 首，被拒 1 首。");`
  - L1587: `assert.ok(app.element("notice").classes.has("error"));`

### `test_web_dashboard_frontend.cjs:1592` — round7 enqueue all omits selection and empty checked selection stays disabled

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L1592: `assert.equal(app.element("library-play-selected").disabled,true);`
  - L1595: `assert.deepEqual(request.data,{revision:"library-v1"});`

### `test_web_dashboard_frontend.cjs:1602` — round7 permissions require old/new confirmation before PATCH

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-admin/#admin-panel; operate rendered setting controls and confirmation dialogs; assert capability gating and API payload.
- 舊斷言逐行索引：
  - L1602: `assert.equal(app.element("permission-confirm-dialog").open,true);`
  - L1603: `assert.ok(app.element("permission-confirm-text").textContent.includes("3 → 8"));`
  - L1604: `assert.equal(app.requests.filter(r=>r.method==="PATCH").length,0);`
  - L1607: `assert.deepEqual(request.data,{group:"Default",field:"MaxSongs",old_value:3,value:8});`

### `test_web_dashboard_frontend.cjs:1614` — round7 permissions cancel invalid values and guild changes send no edit

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L1614: `assert.equal(app.element("permission-confirm-dialog").open,undefined);`
  - L1617: `assert.equal(app.element("permission-confirm-dialog").open,false);`
  - L1620: `assert.equal(app.requests.filter(r=>r.method==="PATCH").length,0);`

### `test_web_dashboard_frontend.cjs:1625` — round7 logout clears private playlists and owner management

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L1625: `assert.ok(app.element("library-list").children.length);`
  - L1627: `assert.equal(app.element("library-list").children.length,0);`
  - L1628: `assert.equal(app.element("nav-admin").hidden,true);`
  - L1629: `assert.equal(app.element("admin-apl-list").children.length,0);`

### `test_web_dashboard_frontend.cjs:1644` — round8 shortcuts reuse playback buttons, seek tokens and request focus

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Operate the rendered seek range by pointer/touch/keyboard; inspect value/progress and the scoped seek request.
- 舊斷言逐行索引：
  - L1644: `assert.ok(seek.data.position >= 40 && seek.data.position < 41);`
  - L1645: `assert.equal(seek.data.track_token, "observed");`
  - L1648: `assert.equal(app.requests.filter(r => r.url.endsWith("/seek")).at(-1).data.position, 0);`
  - L1650: `assert.equal(app.element("query").focused, true);`
  - L1651: `assert.deepEqual(app.requests.filter(r => ["/pause","/resume","/skip"].some(s => r.url.endsWith(s))).map(r => r.url),`

### `test_web_dashboard_frontend.cjs:1668` — round8 shortcuts ignore input select textarea editable ancestors and menu

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Send real keyboard input to the rendered page; assert focus, dialog/command effects, and ignored editable/modifier cases.
- 舊斷言逐行索引：
  - L1668: `assert.equal(app.requests.length, before);`
  - L1669: `assert.notEqual(app.element("shortcuts-dialog").open, true);`

### `test_web_dashboard_frontend.cjs:1679` — round8 shortcuts ignore modifiers composing repeats and every open dialog

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L1679: `assert.notEqual(app.element("shortcuts-dialog").open, true);`
  - L1682: `assert.equal(app.requests.length, before);`

### `test_web_dashboard_frontend.cjs:1688` — round8 disabled capabilities stopped tracks busy disconnected and mobile do nothing

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Switch the rendered language selector; assert visible labels, placeholders, accessible names and parameterized messages.
- 舊斷言逐行索引：
  - L1688: `for (const id of ["toggle", "skip", "progress"]) assert.equal(app.element(id).disabled, true);`
  - L1691: `assert.equal(app.requests.length, before);`
  - L1697: `assert.equal(app.requests.length, count);`
  - L1701: `assert.equal(mobile.requests.length,count);`
  - L1702: `assert.notEqual(mobile.element("shortcuts-dialog").open,true);`

### `test_web_dashboard_frontend.cjs:1706` — round8 help opens from question mark or button and closes with Esc or close

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L1706: `assert.equal(shortcutEvent(app, "?").event.prevented, true);`
  - L1707: `assert.equal(app.element("shortcuts-dialog").open,true);`
  - L1709: `assert.equal(app.requests.length,before);`
  - L1710: `shortcutEvent(app, "Escape"); assert.equal(app.element("shortcuts-dialog").open,false);`
  - L1711: `app.element("shortcuts-help").click(); assert.equal(app.element("shortcuts-dialog").open,true);`
  - L1712: `app.element("shortcuts-close").click(); assert.equal(app.element("shortcuts-dialog").open,false);`
  - L1714: `assert.match(css,/\.desktop-shortcuts\{display:none\}/);`

### `test_web_dashboard_frontend.cjs:1727` — round8 queue search matches title or requester without case and combines with mine

- 舊意圖：8 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L1727: `assert.deepEqual(app.element("queue").children.map(r=>r.dataset.position),["1","3"]);`
  - L1729: `assert.deepEqual(app.element("queue").children.map(r=>r.dataset.position),["3"]);`
  - L1730: `assert.equal(app.element("queue-match-count").textContent,"顯示 1／4 首");`
  - L1734: `assert.deepEqual(move.data,{from:3,to:2,revision:"revision-1"});`
  - L1737: `assert.equal(app.requests.find(r=>r.method==="DELETE").url,"api/guilds/1/queue/2");`
  - L1738: `search("missing");assert.equal(app.element("queue-empty").hidden,false);`
  - L1740: `assert.equal(app.element("queue").children.length,3);`
  - L1741: `assert.equal(app.element("shuffle").disabled,false);`

### `test_web_dashboard_frontend.cjs:1747` — round8 any search disables dragging and shuffle with a reason then restores

- 舊意圖：9 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L1747: `assert.equal(handle.disabled,true);assert.equal(app.element("shuffle").disabled,true);`
  - L1747: `assert.equal(handle.disabled,true);assert.equal(app.element("shuffle").disabled,true);`
  - L1748: `assert.match(app.element("drag-help").textContent,/搜尋篩選中.*停用拖曳與洗牌/);`
  - L1750: `assert.equal(app.run("drag"),null);`
  - L1752: `assert.equal(app.requests.length,before);`
  - L1754: `assert.equal(app.element("shuffle").disabled,false);`
  - L1755: `assert.equal(app.element("queue").children[0].children[4].children[0].disabled,false);`
  - L1758: `assert.equal(app.element("queue-search").value,"");assert.equal(app.run("queueSearch"),"");`
  - L1758: `assert.equal(app.element("queue-search").value,"");assert.equal(app.run("queueSearch"),"");`

### `test_web_dashboard_frontend.cjs:1773` — round8 empty recommendations deduplicate skip current unsafe and cap at five

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L1773: `assert.equal(app.element("queue-recommendations").hidden,false);`
  - L1774: `assert.deepEqual(app.element("recommendation-list").children.map(r=>r.children[1].children[0].textContent),`
  - L1778: `assert.equal(app.element("queue-recommendations").hidden,true); // True empty only, not filtered empty.`
  - L1780: `assert.equal(app.element("queue-recommendations").hidden,true);`

### `test_web_dashboard_frontend.cjs:1788` — round8 recommendation add resolves and requires normal preview confirmation

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L1788: `assert.deepEqual(resolve.data,{query:"https://example.test/selected",action:"play"});`
  - L1789: `assert.equal(app.requests.filter(r=>r.url.endsWith("/play")).length,0);`
  - L1791: `assert.deepEqual(app.requests.find(r=>r.url.endsWith("/play")).data,`

### `test_web_dashboard_frontend.cjs:1800` — round8 recommendation rejection and stale guild button preserve existing boundaries

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L1800: `await add.click();assert.equal(app.element("notice").textContent,"權限拒絕");`
  - L1801: `assert.equal(app.requests.filter(r=>r.url.endsWith("/play")).length,0);`
  - L1804: `assert.equal(app.requests.length,count);assert.equal(app.element("queue-recommendations").hidden,true);`
  - L1804: `assert.equal(app.requests.length,count);assert.equal(app.element("queue-recommendations").hidden,true);`

### `test_web_dashboard_frontend.cjs:1820` — round8 YouTube identities unify watch short embed shorts live mobile and music links

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L1820: `app.context.testURL=url;assert.equal(app.run("songIdentity(testURL)"),"youtube:AbcDeFg1234",url);`
  - L1822: `assert.notEqual(app.run('songIdentity("https://youtube.com/watch?v=abcdefg1234")'),"youtube:AbcDeFg1234");`
  - L1823: `assert.notEqual(app.run('songIdentity("https://youtube.com.evil.test/watch?v=AbcDeFg1234")'),"youtube:AbcDeFg1234");`
  - L1824: `assert.equal(app.run('songIdentity("javascript:alert(1)")'),"");`

### `test_web_dashboard_frontend.cjs:1828` — round8 non YouTube normalization removes fragments tracking slash and orders query

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L1828: `assert.equal(app.run('songIdentity(" HTTPS://EXAMPLE.test:443/song/?b=2&a=1&utm_source=share#fragment ")'),`
  - L1830: `assert.notEqual(app.run('songIdentity("https://example.test/song?a=2")'),`
  - L1832: `assert.notEqual(app.run('songIdentity("https://example.test/Song")'),`
  - L1834: `assert.equal(app.run('songIdentity("https://user:pass@example.test/song")'),"");`

### `test_web_dashboard_frontend.cjs:1845` — round8 track duplicate warning is adjacent remains confirmable and follows live positions

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L1845: `assert.equal(note.textContent,"這首已經在佇列第 2 首");`
  - L1846: `assert.equal(note.hidden,false);assert.equal(button.disabled,false);`
  - L1846: `assert.equal(note.hidden,false);assert.equal(button.disabled,false);`
  - L1848: `assert.equal(note.textContent,"這首已經在佇列第 1 首");`
  - L1850: `assert.equal(app.requests.find(r=>r.url.endsWith("/play")).data.preview_id,"duplicate");`

### `test_web_dashboard_frontend.cjs:1857` — round8 currently playing reminder and removed duplicate update without rebuilding preview

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L1857: `assert.equal(note.textContent,"這首目前正在播放");`
  - L1859: `assert.equal(note.hidden,true);assert.equal(app.element("preview-results").children[0],card);`
  - L1859: `assert.equal(note.hidden,true);assert.equal(app.element("preview-results").children[0],card);`

### `test_web_dashboard_frontend.cjs:1868` — round8 playlist duplicate tags never change selected items and follow queue updates

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L1868: `assert.equal(first.children.at(-1).textContent,"已在佇列");`
  - L1869: `assert.equal(first.children[0].checked,true);`
  - L1872: `assert.equal(first.children.at(-1).hidden,true);assert.equal(button.textContent,selected);`
  - L1872: `assert.equal(first.children.at(-1).hidden,true);assert.equal(button.textContent,selected);`
  - L1873: `assert.equal(third.children[0].checked,true);`
  - L1875: `assert.ok(app.requests.find(r=>r.url.endsWith("/play")).data.selected_items.includes("1"));`

### `test_web_dashboard_frontend.cjs:1883` — round8 shortcuts respect busy disconnected and signed out control states

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L1883: `assert.equal(app.requests.length,before);`

### `test_web_dashboard_frontend.cjs:1890` — round10 mobile volume, selection locks and connection states

- 舊意圖：11 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L1890: `assert.equal(app.element("toggle").textContent,"暫停");`
  - L1892: `assert.equal(app.element("connection").textContent,"連線狀態");`
  - L1893: `assert.equal(app.element("connection").dataset.state,"reconnecting");`
  - L1895: `assert.ok(app.document.body.classes.has("no-selection"));`
  - L1897: `assert.ok(!app.document.body.classes.has("no-selection"));`
  - L1899: `assert.ok(!app.document.body.classes.has("no-selection"));`
  - L1901: `assert.match(html,/class="sr-only seek-hint"/);`
  - L1902: `assert.match(html,/id="drag-help" class="sr-only"/);`
  - L1903: `assert.doesNotMatch(html,/[⏸⏭]/);`
  - L1905: `assert.match(css,/playback-bar>\.volume-row\{display:none\}/);`
  - L1906: `assert.match(css,/-webkit-touch-callout:none/);`

### `test_web_dashboard_frontend.cjs:1914` — round10 favorite toggles pressed state and normalized identities

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L1914: `assert.equal(app.element("favorite").attributes["aria-pressed"],"true");`
  - L1915: `assert.match(app.element("favorite").textContent,/♥/);`
  - L1917: `assert.equal(app.element("favorite").attributes["aria-pressed"],"false");`
  - L1919: `assert.equal(app.element("favorite").disabled,true);`

### `test_web_dashboard_frontend.cjs:1925` — round10 song links canonicalize YouTube, reject scripts and suppress drag clicks

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L1925: `assert.equal(app.run('songLinkURL("https://youtu.be/video000001?t=3")'),"https://www.youtube.com/watch?v=video000001");`
  - L1927: `assert.equal(app.run("songLinkURL("+JSON.stringify(bad)+")"),"");`
  - L1930: `assert.equal(link.target,"_blank");assert.equal(link.rel,"noopener noreferrer");`
  - L1930: `assert.equal(link.target,"_blank");assert.equal(link.rel,"noopener noreferrer");`
  - L1934: `assert.equal(prevented,true);`
  - L1937: `assert.equal(prevented,false);`

### `test_web_dashboard_frontend.cjs:1944` — Spotify prefetch enables a real href without opening a popup

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L1944: `assert.equal(link.getAttribute("href"), "https://open.spotify.com/track/Fake0001");`
  - L1945: `assert.equal(link.getAttribute("aria-disabled"), "false");`
  - L1946: `assert.equal(link.classes.has("is-loading"), false);`

### `test_web_dashboard_frontend.cjs:1953` — Spotify ignores stale replies and disables clicks while loading

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L1953: `assert.equal(app.element("song-spotify").getAttribute("href"), null);`
  - L1956: `assert.equal(prevented, true);`
  - L1962: `assert.equal(app.element("song-spotify").getAttribute("href"), "https://open.spotify.com/track/New");`
  - L1964: `assert.equal(app.element("song-spotify").hidden, true);`
  - L1965: `assert.equal(app.element("song-spotify").getAttribute("href"), null);`

### `test_web_dashboard_frontend.cjs:1971` — Spotify lookup failure offers an encoded search URL

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L1971: `assert.equal(app.element("song-spotify").getAttribute("href"), "https://open.spotify.com/search/First");`

### `test_web_dashboard_frontend.cjs:1983` — maintenance renders owner metadata safely and discards stale replies

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L1983: `assert.ok(rows.some(row=>row.textContent.includes("剩餘 3 天")&&row.classes.has("maintenance-warning")));`
  - L1984: `assert.ok(rows.some(row=>row.textContent==="2 人（最近 45 秒）"));`
  - L1986: `assert.equal(app.element("maintenance-details").children.length,0);`

### `test_web_dashboard_frontend.cjs:1993` — owner empty-queue settings use guild-scoped JSON and validate ranges

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L1993: `assert.equal(app.element("empty-queue-mode").value,"autoplaylist");`
  - L1998: `assert.deepEqual(request.data,{empty_queue:"radio",radio_min_seconds:60,radio_max_seconds:600});`
  - L2002: `assert.equal(app.requests.length,count);`

### `test_web_dashboard_frontend.cjs:2008` — round11 library separates collection choices, compact actions and song columns

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L2008: `assert.equal(app.element("library-playlists").children.length,2);`
  - L2010: `assert.equal(app.element("library-panel").classes.has("detail-open"),true);`
  - L2011: `assert.equal(app.element("library-list").children[0].children.length,5);`
  - L2012: `assert.equal(app.element("library-detail-heading").textContent,"Study");`

### `test_web_dashboard_frontend.cjs:2018` — round11 mix defaults only seed and can save without sync source

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L2018: `assert.equal(list.children[0].children[0].children[0].checked,true);`
  - L2019: `assert.equal(list.children[1].children[0].children[0].checked,false);`

### `test_web_dashboard_frontend.cjs:2025` — round12 title opens two choices and Escape restores focus

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L2025: `assert.equal(app.element("song-choices").hidden,false);`
  - L2026: `assert.equal(app.element("bar-title").getAttribute("aria-expanded"),"true");`
  - L2028: `assert.equal(app.element("song-choices").hidden,true);`
  - L2029: `assert.equal(app.element("bar-title").focused,true);`

### `test_web_dashboard_frontend.cjs:2033` — round12 player has all controls and no expansion code or autoplaylist add UI

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L2033: `for (const id of ["favorite","toggle","skip","repeat","progress","volume","lyrics-toggle"]) assert.match(html,new RegExp('id="'+id+'"'));`
  - L2034: `assert.doesNotMatch(html,/player-dialog\|player-expand\|player-sheet-handle\|autoplaylist-current\|admin-apl-add\|spotify-link/);`
  - L2035: `assert.doesNotMatch(code,/openPlayerPanel\|closePlayerPanel\|playerSwipe\|panel-transport\|hero-progress/);`

### `test_web_dashboard_frontend.cjs:2040` — round11 logout all uses protected endpoint and clears private state

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L2040: `assert.ok(app.requests.some(r=>r.url==="/auth/logout-all"&&r.method==="POST"));`
  - L2041: `assert.equal(app.element("dashboard").hidden,true);`

### `test_web_dashboard_frontend.cjs:2048` — round12 lyrics default off sends no lyric or alignment requests across polls

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L2048: `assert.equal(app.requests.some(r=>r.url.includes("/lyrics")),false);`
  - L2049: `assert.equal(app.element("lyrics-panel").hidden,true);`
  - L2051: `assert.equal(app.requests.some(r=>r.url.includes("/lyrics")),false);`

### `test_web_dashboard_frontend.cjs:2057` — round12 lyric preference is scoped to authenticated viewer and storage can fail

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L2057: `assert.equal(store.get("musicbot-lyrics:user:123"),"on");`
  - L2059: `assert.equal(store.get("musicbot-lyrics:user:123"),"off");`
  - L2061: `assert.equal(second.requests.some(r=>r.url.includes("/lyrics")),false);`
  - L2064: `assert.equal(blocked.element("lyrics-panel").hidden,false);`

### `test_web_dashboard_frontend.cjs:2069` — round12 disabled server prevents queries and instrumental has no scroll controls

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L2069: `assert.equal(app.requests.some(r=>r.url.includes("/lyrics")),false);`
  - L2070: `assert.equal(app.element("lyrics-toggle").hidden,true);`
  - L2074: `assert.equal(app.element("lyrics-status").textContent,"純音樂");`
  - L2075: `assert.equal(app.element("lyrics-timing-controls").hidden,true);`

### `test_web_dashboard_frontend.cjs:2085` — round12 manual scroll pauses centering five seconds then seek realigns

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Operate the rendered seek range by pointer/touch/keyboard; inspect value/progress and the scoped seek request.
- 舊斷言逐行索引：
  - L2085: `assert.equal(rows[2].getAttribute("aria-current"),"true");`
  - L2086: `assert.equal(app.element("lyrics-content").scrollCalls.length,before);`
  - L2087: `assert.ok(app.run("lyricsUserScrollUntil-Date.now()")>4900);`
  - L2089: `assert.equal(app.element("lyrics-content").scrollCalls.length,before+1);`
  - L2091: `assert.equal(rows[0].getAttribute("aria-current"),"true");`

### `test_web_dashboard_frontend.cjs:2099` — round12 offset controls send small deltas and two-click sync position with token

- 舊意圖：14 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L2099: `assert.equal(app.element("lyrics-offset").textContent, "");`
  - L2102: `assert.deepEqual(added.data,{action:"adjust",track_token:"token",delta:.5});`
  - L2103: `assert.equal(app.element("lyrics-offset").textContent, "");`
  - L2106: `assert.equal(app.element("lyrics-sync-prompt").hidden,false);`
  - L2109: `assert.equal(app.requests.length,before+1);`
  - L2110: `assert.deepEqual(app.requests.at(-1).data,{action:"sync",track_token:"token",position:31.25});`
  - L2111: `assert.equal(app.element("lyrics-sync-prompt").hidden,true);`
  - L2114: `assert.equal(app.requests.length,count);`
  - L2155: `assert.equal(row.getAttribute("aria-current"),"true");`
  - L2156: `assert.ok(rect.top>=top-.01,JSON.stringify({rect,top}));`
  - L2157: `assert.ok(rect.bottom<=top+app.box.clientHeight+.01,JSON.stringify({rect,top,height:app.box.clientHeight}));`
  - L2158: `if(centered)assert.ok(Math.abs((rect.top+rect.bottom)/2-top-app.box.clientHeight/2)<.01);`
  - L2159: `assert.equal(row.scrolled,undefined,"never scroll an ancestor through scrollIntoView");`
  - L2160: `assert.equal(app.scrolls.length,0);`

### `test_web_dashboard_frontend.cjs:2171` — round14 rectangle centering ignores offsetParent with viewport height 

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L2171: `assert.equal(app.box.scrollTop,target,"existing scroll is not applied twice");`

### `test_web_dashboard_frontend.cjs:2188` — round14 reopening cached lyrics centers even if the active index is unchanged

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L2188: `assert.equal(app.requests.filter(r=>r.url.endsWith("/lyrics")).length,1);`

### `test_web_dashboard_frontend.cjs:2198` — round14 manual scrolling pauses centering and resumes on the same current line

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L2198: `assert.equal(app.box.scrollCalls.length,count);`
  - L2199: `assert.equal(app.box.scrollTop,0);`
  - L2200: `assert.equal(app.run("lyricsCenterPending"),true);`
  - L2205: `assert.ok(app.run("lyricsUserScrollUntil<Date.now()"),"programmatic scroll must not pause following");`

### `test_web_dashboard_frontend.cjs:2215` — round14 drag previews and committed forward/backward seeks center lyrics

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L2215: `assert.deepEqual(app.requests.filter(r=>r.url.endsWith("/seek")).map(r=>r.data.position),[75,25]);`

### `test_web_dashboard_frontend.cjs:1` — round14 offset changes recenter the newly highlighted line

- 舊意圖：0 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.

### `test_web_dashboard_frontend.cjs:2226` — round14 changing tracks reloads and centers the new active line

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L2226: `assert.equal(app.requests.filter(r=>r.url.endsWith("/lyrics")).length,2);`

### `test_web_dashboard_frontend.cjs:2232` — round14 hidden layout keeps a pending center until the lyric viewport is visible

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L2232: `assert.equal(app.box.scrollCalls.length,count);assert.equal(app.run("lyricsCenterPending"),true);`
  - L2232: `assert.equal(app.box.scrollCalls.length,count);assert.equal(app.run("lyricsCenterPending"),true);`

### `test_web_dashboard_frontend.cjs:2238` — round14 missing scrollTo falls back to the lyric box scrollTop only

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L2238: `visibleLyric(app,3);assert.equal(app.run("lyricsCenterPending"),false);`

### `test_web_dashboard_frontend.cjs:2242` — round14 reduced motion centers without smooth scrolling

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L2242: `visibleLyric(app,3);assert.equal(app.box.scrolled.behavior,"auto");`
  - L2251: `if (!el.children.length) assert.doesNotMatch(el.textContent, /\bm\d{4}\b/, el.id \|\| el.tag);`
  - L2253: `assert.doesNotMatch(String(el.getAttribute(attr) \|\| el[attr] \|\| ""), /\bm\d{4}\b/, (el.id \|\| el.tag) + ":" + attr);`

### `test_web_dashboard_frontend.cjs:2260` — playlist initializes before catalogs, then translates zh-TW and en without raw keys

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L2260: `assert.equal(app.requests.some(r => r.url === "/auth/session"), false);`
  - L2261: `assert.match(app.element("library-import-hint").textContent, /m0202/);`
  - L2268: `assert.equal(app.element("library-import-hint").textContent, catalog.m0202);`
  - L2269: `assert.equal(app.element("library-sync-slot").children[1].textContent, catalog.m0203);`
  - L2270: `assert.equal(app.element("library-sync-slot").children[0].textContent, catalog.m0204);`

### `test_web_dashboard_frontend.cjs:2277` — whole initialized DOM and accessible attributes contain no translation keys

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Switch the rendered language selector; assert visible labels, placeholders, accessible names and parameterized messages.
- 舊斷言逐行索引：
  - L2277: `assert.ok(app.requests.some(r => r.url === "/auth/session"));`
  - L2283: `assert.throws(() => assertNoTranslationKeys(app));`

### `test_web_dashboard_frontend.cjs:2294` — 429 transport errors back off, survive foreground changes, cap retry and recover

- 舊意圖：8 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L2294: `assert.equal(stream.closed,true);`
  - L2299: `assert.equal(app.streams.length,count);`
  - L2301: `assert.equal(app.streams.length,count+1);`
  - L2302: `assert.equal(app.streams.filter(s=>!s.closed).length,1);`
  - L2304: `assert.deepEqual(delays,[1000,2000,4000,60000,60000,60000,60000]);`
  - L2306: `assert.equal(app.run("fallbackPolling"),false);`
  - L2307: `assert.equal(app.run("eventFailures"),0);`
  - L2308: `assert.equal(app.run("connected"),true);`

### `test_web_dashboard_frontend.cjs:2316` — SSE fallback state reads are at least five seconds apart

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Observe rendered state transitions while fixture endpoints/stream change or fail; assert recovered/cleared UI and no stale content.
- 舊斷言逐行索引：
  - L2316: `assert.equal(count(),baseline);`
  - L2317: `now.value=105000; await app.run("poll()"); assert.equal(count(),baseline+1);`
  - L2318: `await app.run("poll()"); assert.equal(count(),baseline+1);`

### `test_web_dashboard_frontend.cjs:2330` — notification selector has translated default and safe text channel choices

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-admin/#admin-panel; operate rendered setting controls and confirmation dialogs; assert capability gating and API payload.
- 舊斷言逐行索引：
  - L2330: `assert.deepEqual(options.map(node=>node.value), ["","101"]);`
  - L2331: `assert.equal(options[0].textContent,t("notify.default"));`
  - L2332: `assert.equal(options[0].dataset.i18n,"notify.default");`
  - L2333: `assert.equal(options[1].textContent,"#<img onerror=evil>");`
  - L2334: `assert.equal(options[1].children.length,0);`
  - L2335: `assert.equal(app.element("admin-notify-channel").value,"");`
  - L2336: `assert.equal(app.element("admin-notify-warning").hidden,true);`

### `test_web_dashboard_frontend.cjs:2345` — notification selector restores setting and warns about inaccessible saved channel

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-admin/#admin-panel; operate rendered setting controls and confirmation dialogs; assert capability gating and API payload.
- 舊斷言逐行索引：
  - L2345: `assert.equal(select.value,"101");`
  - L2346: `assert.equal(select.children[1].disabled,true);`
  - L2347: `assert.equal(select.children[1].textContent,t("notify.unavailable"));`
  - L2348: `assert.equal(select.children[1].dataset.i18n,"notify.unavailable");`
  - L2349: `assert.equal(app.element("admin-notify-warning").hidden,false);`

### `test_web_dashboard_frontend.cjs:2359` — notification save posts selected text channel to selected guild

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L2359: `assert.equal(request.url,"/api/guilds/1/admin/notification-channel");`
  - L2360: `assert.deepEqual(request.data,{channel_id:"101"});`
  - L2361: `assert.equal(app.element("admin-notify-status").textContent,t("notify.saved"));`

### `test_web_dashboard_frontend.cjs:2369` — notification default option clears setting with JSON null

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-admin/#admin-panel; operate rendered setting controls and confirmation dialogs; assert capability gating and API payload.
- 舊斷言逐行索引：
  - L2369: `assert.deepEqual(request.data,{channel_id:null});`
  - L2370: `assert.equal(app.element("admin-notify-warning").hidden,true);`

### `test_web_dashboard_frontend.cjs:2382` — notification load discards reply after guild switch

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L2382: `assert.equal(app.element("admin-notify-channel").children.length,0);`

### `test_web_dashboard_frontend.cjs:2394` — notification clear removes private selection and discards pending save

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-admin/#admin-panel; operate rendered setting controls and confirmation dialogs; assert capability gating and API payload.
- 舊斷言逐行索引：
  - L2394: `assert.equal(app.element("admin-notify-channel").children.length,0);`
  - L2395: `assert.equal(app.element("admin-notify-warning").hidden,true);`
  - L2396: `assert.equal(app.element("admin-notify-status").textContent,"");`

### `test_web_dashboard_frontend.cjs:2404` — notification controls do not call API without Owner capability

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L2404: `assert.equal(app.requests.length,before);`

### `test_web_dashboard_frontend.cjs:2410` — opening management loads guild notification options with a translated form

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L2410: `assert.ok(app.requests.some(r=>r.url==="/api/guilds/1/admin/notification-channel"));`
  - L2412: `assert.match(html,/<label for="admin-notify-channel"><span data-i18n="notify.label">/);`
  - L2413: `assert.match(html,/<option value="" data-i18n="notify.default">/);`
  - L2414: `assert.match(html,/id="admin-notify-warning"[^>]+role="status"/);`

### `test_web_dashboard_frontend.cjs:2424` — vote skip management load restores server setting and accessible switch

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L2424: `assert.equal(app.element("admin-vote-skip-enabled").checked,false);`
  - L2425: `assert.equal(app.element("admin-vote-skip-enabled").disabled,false);`
  - L2427: `assert.match(html,/id="admin-vote-skip-enabled"[^>]+role="switch"/);`
  - L2428: `assert.match(html,/aria-describedby="admin-vote-skip-help"/);`
  - L2429: `assert.match(html,/data-i18n="vote_skip.help"/);`
  - L2430: `assert.ok(html.indexOf('id="admin-vote-skip-form"') < html.indexOf('id="admin-permissions"'));`

### `test_web_dashboard_frontend.cjs:2441` — vote skip save sends one boolean to selected server and can re-enable

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L2441: `assert.equal(request.url,"/api/guilds/1/admin/vote-skip");`
  - L2442: `assert.deepEqual(request.data,{enabled});`
  - L2443: `assert.equal(app.element("admin-vote-skip-status").textContent,t("vote_skip.saved"));`

### `test_web_dashboard_frontend.cjs:2451` — vote skip settings load independently after server switch

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L2451: `assert.equal(app.element("admin-vote-skip-enabled").checked,false);`
  - L2454: `assert.equal(app.element("admin-vote-skip-enabled").checked,true);`

### `test_web_dashboard_frontend.cjs:2462` — vote skip controls never call API for nonowner or before a successful read

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L2462: `assert.equal(app.requests.length,before);`
  - L2465: `assert.equal(app.requests.length,before);`
  - L2466: `assert.equal(app.element("admin-vote-skip-enabled").disabled,true);`

### `test_web_dashboard_frontend.cjs:2476` — vote skip late load cannot restore old server or logged-out state

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L2476: `assert.notEqual(app.element("admin-vote-skip-enabled").checked,false);`
  - L2477: `assert.equal(app.element("admin-vote-skip-enabled").disabled,true);`

### `test_web_dashboard_frontend.cjs:2490` — vote skip late save cannot overwrite new guild or logout controls

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L2490: `assert.equal(app.element("admin-vote-skip-enabled").checked,true);`
  - L2491: `assert.equal(app.element("admin-vote-skip-status").textContent,"");`

### `test_web_dashboard_frontend.cjs:2497` — vote skip load error keeps switch disabled and save error shows no success

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L2497: `await assert.rejects(()=>app.run("adminVoteSkipLoad()"));`
  - L2498: `assert.equal(app.element("admin-vote-skip-enabled").disabled,true);`
  - L2502: `assert.equal(app.element("admin-vote-skip-status").textContent,"");`

### `test_web_dashboard_frontend.cjs:2507` — vote skip catalogs explain immediate skipping and have English equivalents

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L2507: `assert.ok(en["vote_skip."+key]);assert.ok(zh["vote_skip."+key]);`
  - L2507: `assert.ok(en["vote_skip."+key]);assert.ok(zh["vote_skip."+key]);`
  - L2509: `assert.match(en["vote_skip.help"],/Skip permission.*immediately/);`
  - L2510: `assert.match(zh["vote_skip.help"],/\u95dc\u9589\u5f8c.*\u53ef\u76f4\u63a5\u8df3\u904e/);`

### `test_web_dashboard_frontend.cjs:2517` — unavailable lyrics retry at 45 seconds up to three times and manual retry can recover

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L2517: `assert.equal(app.element("lyrics-retry").hidden, false);`
  - L2522: `assert.equal(app.timers.filter(x=>x[1]===45000).length, 3);`
  - L2523: `assert.equal(app.requests.filter(x=>x.url.endsWith("/lyrics")).length, 4);`
  - L2526: `assert.equal(app.element("lyrics-retry").hidden, true);`
  - L2527: `assert.ok(app.element("lyrics-content").children.length);`

### `test_web_dashboard_frontend.cjs:2537` — a cancelled lyric retry cannot request the previous track or a closed panel

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L2537: `assert.equal(app.requests.length,before);`
  - L2542: `assert.equal(app.requests.length,count);`

### `test_web_dashboard_frontend.cjs:2549` — cover original lyrics are labelled in the panel

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L2549: `assert.equal(app.element("lyrics-status").textContent,t("m0610"));`

### `test_web_dashboard_frontend.cjs:2555` — round26 delayed automatic mobile scroll cannot suspend lyrics following

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L2555: `assert.equal(app.run("lyricsUserScrollUntil"),0);`
  - L2557: `assert.ok(app.box.children.some(row=>row.classes.has("active")));`
  - L2558: `assert.equal(app.run("lyricsCenterPending"),false);`

### `test_web_dashboard_frontend.cjs:2564` — round26 hidden song chooser retains pending center until restored

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L2564: `assert.equal(app.run("lyricsCenterPending"),true);`
  - L2565: `app.run("closeSongChoices()");assert.equal(app.run("lyricsCenterPending"),false);`

### `test_web_dashboard_frontend.cjs:2569` — round26 offset status row is absent from real shell

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L2569: `assert.doesNotMatch(html,/id="lyrics-offset"/);`
  - L2570: `assert.doesNotMatch(code,/\$\("lyrics-offset"\)/);`

### `test_web_dashboard_i18n.cjs:6` — catalogs have identical, complete keys and placeholder sets

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Switch the rendered language selector; assert visible labels, placeholders, accessible names and parameterized messages.
- 舊斷言逐行索引：
  - L6: `assert.deepEqual(Object.keys(en),Object.keys(zh));`
  - L8: `assert.ok(en[key].trim()&&zh[key].trim(),key);`
  - L9: `assert.deepEqual([...(en[key].match(/\{p\d+\}/g)\|\|[])].sort(),[...(zh[key].match(/\{p\d+\}/g)\|\|[])].sort(),key);`

### `test_web_dashboard_i18n.cjs:18` — language preference: saved selection, browser languages, server default, English

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L18: `Object.assign(c,{saved,languages,fallback});assert.equal(vm.runInContext("chooseLanguage(saved,languages,fallback)",c),want);`

### `test_web_dashboard_i18n.cjs:23` — translations substitute parameters once and fall back to English

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Switch the rendered language selector; assert visible labels, placeholders, accessible names and parameterized messages.
- 舊斷言逐行索引：
  - L23: `assert.equal(vm.runInContext('t("m0399",{p0:"{p1}",p1:0,p2:10})',c),"{p1} must be an integer between 0 and 10.");`

### `test_web_dashboard_i18n.cjs:27` — frontend contains no hardcoded CJK UI strings or missing translation keys

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Switch the rendered language selector; assert visible labels, placeholders, accessible names and parameterized messages.
- 舊斷言逐行索引：
  - L27: `const text=fs.readFileSync("musicbot/web/"+name,"utf8");assert.doesNotMatch(text,/[\u3400-\u9fff]/,name);`
  - L28: `for(const m of text.matchAll(/\bt\("([^"]+)"/g))assert.ok(en[m[1]],name+":"+m[1]);`

### `test_web_dashboard_layout.cjs:9` — brand centers icon and label as one flex group

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Switch the rendered language selector; assert visible labels, placeholders, accessible names and parameterized messages.
- 舊斷言逐行索引：
  - L9: `assert.match(html, /class="brand-icon"/); assert.match(html, /class="brand-label"/);`
  - L9: `assert.match(html, /class="brand-icon"/); assert.match(html, /class="brand-label"/);`
  - L10: `assert.match(css, /\.sidebar \.brand\{display:flex;align-items:center;justify-content:center/);`
  - L11: `assert.match(css, /\.brand \.brand-icon\{display:block;line-height:1/);`

### `test_web_dashboard_layout.cjs:14` — phone brand spans the full navigation row

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Assert computed styles and browser geometry/accessibility on the built DOM at mobile/desktop and light/dark settings.
- 舊斷言逐行索引：
  - L14: `assert.match(css, /\.sidebar \.brand\{grid-column:1\/-1;grid-row:1/);`

### `test_web_dashboard_layout.cjs:18` — page switches reserve scrollbar space and fixed tab geometry

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L18: `assert.match(css, /html\{overflow-y:scroll;scrollbar-gutter:stable\}/);`
  - L19: `assert.match(css, /\.page-tabs\{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);`
  - L20: `assert.match(css, /\.page-tabs button\{[^}]*height:44px;[^}]*white-space:nowrap/);`
  - L21: `assert.match(css, /\.page-tabs button:hover:enabled\{transform:none\}/);`

### `test_web_dashboard_layout.cjs:33` — loading a navigation page preserves its label without inserting a spinner

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Switch the rendered language selector; assert visible labels, placeholders, accessible names and parameterized messages.
- 舊斷言逐行索引：
  - L33: `assert.equal(button.textContent, "我的歌單"); assert.equal(active["is-loading"], false);`
  - L33: `assert.equal(button.textContent, "我的歌單"); assert.equal(active["is-loading"], false);`
  - L34: `assert.equal(attrs["aria-busy"], "true");`
  - L36: `assert.equal(button.textContent, "我的歌單");`

### `test_web_dashboard_layout.cjs:46` — initial server respects URL, recommendation, browser and first choice

- 舊意圖：7 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L46: `assert.equal(vm.runInContext("initialGuild(data)",c),"1");`
  - L48: `assert.equal(vm.runInContext("initialGuild(data)",c),"2");`
  - L50: `assert.equal(vm.runInContext("initialGuild(data)",c),"1");`
  - L52: `assert.equal(vm.runInContext("initialGuild(data)",c),"1");`
  - L54: `assert.doesNotThrow(()=>vm.runInContext('rememberGuild("2")',c));`
  - L56: `assert.equal(vm.runInContext("initialGuild(data)",c),"2");`
  - L58: `assert.equal(vm.runInContext("initialGuild(data)",c),"1");`

### `test_web_dashboard_layout.cjs:62` — glass provides both themes, prefixed blur and opaque accessibility fallbacks

- 舊意圖：15 個 assert calls；納入 Vue browser migration
- 新驗證：Assert computed styles and browser geometry/accessibility on the built DOM at mobile/desktop and light/dark settings.
- 舊斷言逐行索引：
  - L62: `assert.match(css, /backdrop-filter:blur\(var\(--glass-blur\)\) saturate\(160%\) brightness\(var\(--dim,1\)\)/);`
  - L63: `assert.match(css, /-webkit-backdrop-filter:blur\(var\(--glass-blur\)\) saturate\(160%\) brightness\(var\(--dim,1\)\)/);`
  - L64: `assert.match(css, /@media\(prefers-color-scheme:light\)/);`
  - L65: `assert.match(css, /@supports not \(backdrop-filter:blur\(1px\)\)/);`
  - L66: `assert.match(css, /@media\(prefers-reduced-transparency:reduce\)/);`
  - L67: `assert.match(css, /@media\(prefers-reduced-motion:reduce\)/);`
  - L68: `assert.match(css, /\.card,\.now-playing\{[^}]*backdrop-filter:none/);`
  - L69: `assert.doesNotMatch(css, /radial-gradient\([^)]*\)[^;]*var\(--bg\)/);`
  - L70: `assert.doesNotMatch(css, /#wallpaper/); assert.doesNotMatch(html, /wallpaper/);`
  - L70: `assert.doesNotMatch(css, /#wallpaper/); assert.doesNotMatch(html, /wallpaper/);`
  - L71: `assert.doesNotMatch(css, /box-shadow:[^;}]*rgba\((10,132,255\|100,210,255)[^;}]*\d+px[^;}]*-\d+px/);`
  - L72: `assert.match(css, /--bg:#0b0b0f/); assert.match(css, /--bg:#f2f2f7/);`
  - L72: `assert.match(css, /--bg:#0b0b0f/); assert.match(css, /--bg:#f2f2f7/);`
  - L73: `assert.match(css, /\.song-choices,[^{]*\{background:var\(--panel\)/);`
  - L75: `assert.match(css, /\.playback-bar:has\(#song-choices:not\(\[hidden\]\)\)\{z-index:21\}/);`

### `test_web_dashboard_layout.cjs:90` — clear glass foregrounds meet AA on white, black and saturated covers

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Assert computed styles and browser geometry/accessibility on the built DOM at mobile/desktop and light/dark settings.
- 舊斷言逐行索引：
  - L90: `assert.ok(ratio(rgb(fg),bg)>=4.5,JSON.stringify({light,pref,cover,fg,ratio:ratio(rgb(fg),bg)}));`
  - L92: `assert.doesNotMatch(html,/glass-appearance\|glass-preference/); assert.doesNotMatch(css,/glass-preference/);`
  - L92: `assert.doesNotMatch(html,/glass-appearance\|glass-preference/); assert.doesNotMatch(css,/glass-preference/);`
  - L93: `assert.match(fs.readFileSync(path.join(__dirname,"../musicbot/web/dashboard.js"),"utf8"),/root\.dataset\.glass = "clear"/); assert.match(css,/prefers-contrast:more/);`
  - L93: `assert.match(fs.readFileSync(path.join(__dirname,"../musicbot/web/dashboard.js"),"utf8"),/root\.dataset\.glass = "clear"/); assert.match(css,/prefers-contrast:more/);`

### `test_web_dashboard_layout.cjs:103` — explicit server survives the login redirect and is consumed after selection

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.
- 舊斷言逐行索引：
  - L103: `assert.equal(stored.size,1);`
  - L106: `assert.equal(vm.runInContext("initialGuild(data)",c),"2");`
  - L107: `vm.runInContext('rememberGuild("2")',c);assert.equal(stored.size,0);`
  - L108: `c.manualGuild="1";assert.equal(vm.runInContext("initialGuild(data)",c),"1");`

### `test_web_dashboard_phone.cjs:15` — segmented pill stays in padded container: three/four tabs, compact and rotated

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Assert computed styles and browser geometry/accessibility on the built DOM at mobile/desktop and light/dark settings.
- 舊斷言逐行索引：
  - L15: `assert.ok(g.x>=4&&g.y>=4&&g.x+g.w<=width-4&&g.y+g.h<=height-4);`
  - L16: `assert.ok(Math.abs(g.x-active.offsetLeft)<1);`

### `test_web_dashboard_phone.cjs:24` — bad transient offsets cannot escape either padded edge

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.
- 舊斷言逐行索引：
  - L24: `assert.ok(g.x>=6&&g.x+g.w<=341&&g.y>=4&&g.y+g.h<=42);}`

### `test_web_dashboard_phone.cjs:29` — all five player buttons share a fixed shape; first paint does not animate

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L29: `assert.match(html,new RegExp('<button id="'+id+'"[^>]*class="[^"]*player-control'));`
  - L30: `assert.match(css,/#playback-bar \.player-control\{[^}]*height:40px;[^}]*border-radius:20px/);`
  - L31: `assert.match(css,/\.page-tabs,\.queue-filters\{overflow:hidden\}/);`
  - L32: `assert.match(source,/document\.fonts\?\.ready\.then\(align\)/);`
  - L33: `assert.match(source,/orientationchange/);`
  - L34: `assert.match(css,/transition:transform 260ms cubic-bezier\(\.2,\.8,\.2,1\)/);`

### `test_web_dashboard_popular.cjs:31` — popular lists rank, count and duration through member API

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-popular/#popular-panel; assert ranked rows, count/duration, period empty/error states, and one-click resolved enqueue.
- 舊斷言逐行索引：
  - L31: `assert.equal(app.requests[0],"/api/guilds/1/popular?period=30");`
  - L33: `assert.equal(row.children[0].textContent,"1");`
  - L34: `assert.equal(row.children[1].children[0].textContent,"<img onerror=x>");`
  - L35: `assert.equal(row.children[1].children[1].textContent,"12 次 · 1:23");`
  - L36: `assert.equal(app.saved.length,1);`

### `test_web_dashboard_popular.cjs:41` — popular add resolves and confirms queue in one click

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.
- 舊斷言逐行索引：
  - L41: `assert.equal(button.textContent,t("m0612"));await button.listeners.click();`
  - L42: `assert.equal(app.requests.at(-1),"api/guilds/1/resolve");`
  - L43: `assert.deepEqual(JSON.parse(JSON.stringify(app.actions)),[["play",{query:"https://example.test/song",preview_id:"preview-one"}]]);`
  - L44: `assert.equal(app.previews.length,0);assert.equal(button.disabled,false);assert.equal(button.loading,false);`
  - L44: `assert.equal(app.previews.length,0);assert.equal(button.disabled,false);assert.equal(button.loading,false);`
  - L44: `assert.equal(app.previews.length,0);assert.equal(button.disabled,false);assert.equal(button.loading,false);`

### `test_web_dashboard_popular.cjs:50` — period changes discard obsolete responses

- 舊意圖：1 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L50: `assert.equal(app.node("popular-list").children.length,0);`

### `test_web_dashboard_popular.cjs:54` — popular failures show safe error without disconnecting playback

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.
- 舊斷言逐行索引：
  - L54: `await app.run("popularLoad()");assert.equal(app.ctx.connected,true);`
  - L55: `assert.equal(app.node("popular-status").textContent,"暫時無法取得熱門點播。");`

### `test_web_dashboard_popular.cjs:61` — reset clears popularity and invalidates stale buttons

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-popular/#popular-panel; assert ranked rows, count/duration, period empty/error states, and one-click resolved enqueue.
- 舊斷言逐行索引：
  - L61: `await button.listeners.click();assert.equal(app.previews.length,0);`
  - L62: `assert.equal(app.node("popular-list").children.length,0);`

### `test_web_dashboard_popular.cjs:66` — popular view uses top 20 and handles empty period

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-popular/#popular-panel; assert ranked rows, count/duration, period empty/error states, and one-click resolved enqueue.
- 舊斷言逐行索引：
  - L66: `assert.match(app.node("popular-status").textContent,/還沒有/);`
  - L67: `assert.match(code,/slice\(0, 20\)/);`

### `test_web_dashboard_popular.cjs:73` — popular pending resolve prevents duplicate clicks and stale guild enqueue

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.
- 舊斷言逐行索引：
  - L73: `const pending=button.listeners.click();assert.equal(button.loading,true);`
  - L74: `await button.listeners.click();assert.equal(app.requests.filter(u=>u.endsWith("/resolve")).length,1);`
  - L76: `assert.equal(app.actions.length,0);assert.equal(button.loading,false);assert.equal(button.disabled,true);`
  - L76: `assert.equal(app.actions.length,0);assert.equal(button.loading,false);assert.equal(button.disabled,true);`
  - L76: `assert.equal(app.actions.length,0);assert.equal(button.loading,false);assert.equal(button.disabled,true);`

### `test_web_dashboard_popular.cjs:82` — popular resolve rejection and unavailable tracks restore button and explain error

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L82: `assert.equal(app.actions.length,0);assert.equal(button.disabled,false);assert.equal(app.notices.length,1);assert.equal(app.notices[0][1],true);`
  - L82: `assert.equal(app.actions.length,0);assert.equal(button.disabled,false);assert.equal(app.notices.length,1);assert.equal(app.notices[0][1],true);`
  - L82: `assert.equal(app.actions.length,0);assert.equal(button.disabled,false);assert.equal(app.notices.length,1);assert.equal(app.notices[0][1],true);`
  - L82: `assert.equal(app.actions.length,0);assert.equal(button.disabled,false);assert.equal(app.notices.length,1);assert.equal(app.notices[0][1],true);`

### `test_web_dashboard_pwa.cjs:59` — install precaches injected public assets and activation removes old app caches

- 舊意圖：6 個 assert calls；既有真實 PWA/offline suite 暫保留
- 新驗證：Retain in the existing worker/offline/registration suite; no legacy assertion removed.
- 舊斷言逐行索引：
  - L59: `assert.ok(a.puts.includes("/")&&a.puts.includes("/icon-512.png"));`
  - L60: `assert.ok(a.puts.includes("/offline.html"));`
  - L61: `assert.ok(a.puts.every(key=>!key.startsWith("/api")&&!key.startsWith("/auth")&&!key.includes("events")&&!key.includes("secret")));`
  - L62: `assert.deepEqual(a.deleted,["musicbot-dashboard-old"]);assert.deepEqual(a.counts(),[1,1]);`
  - L62: `assert.deepEqual(a.deleted,["musicbot-dashboard-old"]);assert.deepEqual(a.counts(),[1,1]);`
  - L63: `assert.ok(a.fetches.every(r=>r.credentials==="omit"));`

### `test_web_dashboard_pwa.cjs:68` — never intercept API, auth, events, nonstatic, foreign origin, secrets or writes

- 舊意圖：6 個 assert calls；既有真實 PWA/offline suite 暫保留
- 新驗證：Retain in the existing worker/offline/registration suite; no legacy assertion removed.
- 舊斷言逐行索引：
  - L68: `assert.equal((await a.event("fetch",a.request(url))).intercept,false,url);`
  - L70: `assert.equal((await a.event("fetch",a.request("/assets/app.js",{method:"POST"}))).intercept,false);`
  - L71: `assert.equal((await a.event("fetch",a.request("/assets/app.js",{headers:{get:()=>"text/event-stream"}}))).intercept,false);`
  - L72: `assert.equal((await a.event("fetch",a.request("/assets/app.js",{url:"https://foreign.test/assets/app.js"}))).intercept,false);`
  - L73: `assert.equal(a.fetches.length,0);assert.equal(a.puts.length,0);`
  - L73: `assert.equal(a.fetches.length,0);assert.equal(a.puts.length,0);`

### `test_web_dashboard_pwa.cjs:78` — HTML network first and offline fallback is the installed offline page

- 舊意圖：2 個 assert calls；既有真實 PWA/offline suite 暫保留
- 新驗證：Retain in the existing worker/offline/registration suite; no legacy assertion removed.
- 舊斷言逐行索引：
  - L78: `assert.equal(await result.result.text(),"network");`
  - L80: `assert.equal(await result.result.text(),"currently offline");`

### `test_web_dashboard_pwa.cjs:85` — static stale while revalidate serves cache and refreshes versioned asset

- 舊意圖：3 個 assert calls；既有真實 PWA/offline suite 暫保留
- 新驗證：Retain in the existing worker/offline/registration suite; no legacy assertion removed.
- 舊斷言逐行索引：
  - L85: `assert.equal(await result.result.text(),"cached");`
  - L86: `assert.equal(await a.cache.get("/assets/app.js").text(),"network");`
  - L89: `assert.equal(await offline.result.text(),"offline css");`

### `test_web_dashboard_pwa.cjs:93` — failed install deletes the incomplete new cache and does not replace working version

- 舊意圖：3 個 assert calls；既有真實 PWA/offline suite 暫保留
- 新驗證：Retain in the existing worker/offline/registration suite; no legacy assertion removed.
- 舊斷言逐行索引：
  - L93: `await assert.rejects(a.event("install"),/network failure/);`
  - L94: `assert.ok(a.deleted.includes(version));`
  - L95: `assert.deepEqual(a.counts(),[0,0]);`

### `test_web_dashboard_pwa.cjs:100` — cache quota failures do not hide successful network responses

- 舊意圖：3 個 assert calls；既有真實 PWA/offline suite 暫保留
- 新驗證：Retain in the existing worker/offline/registration suite; no legacy assertion removed.
- 舊斷言逐行索引：
  - L100: `assert.equal(result.intercept,true);`
  - L101: `assert.equal(await result.result.text(),"network");`
  - L103: `assert.equal(await html.result.text(),"network");`

### `test_web_dashboard_pwa.cjs:121` — acknowledged cache sweep removes stale caches recreated after activation

- 舊意圖：4 個 assert calls；既有真實 PWA/offline suite 暫保留
- 新驗證：Retain in the existing worker/offline/registration suite; no legacy assertion removed.
- 舊斷言逐行索引：
  - L121: `assert.deepEqual(a.deleted,["musicbot-dashboard-old","musicbot-dashboard-r26-lyrics-popular"]);`
  - L122: `assert.equal(acknowledgement.type,"musicbot-cache-sweep-complete");`
  - L123: `assert.equal(acknowledgement.version,version);`
  - L124: `assert.ok(!a.cacheNames.some(name=>name.startsWith("musicbot-dashboard-")&&name!==version));`

### `test_web_dashboard_round15_busy.cjs:35` — query keeps its exact translation node through busy and language changes

- 舊意圖：6 個 assert calls；納入 Vue browser migration
- 新驗證：Switch the rendered language selector; assert visible labels, placeholders, accessible names and parameterized messages.
- 舊斷言逐行索引：
  - L35: `language("zh"); assert.equal(button.textContent, zh.m0248);`
  - L36: `run("buttonBusy(button,true)"); assert.equal(button.textContent, zh.m0044);`
  - L37: `language("en"); assert.equal(button.textContent, en.m0044);`
  - L38: `run("buttonBusy(button,false)"); assert.equal(button.children[0], label);`
  - L39: `assert.equal(button.textContent, en.m0248);`
  - L40: `language("zh"); assert.equal(button.textContent, zh.m0248);`

### `test_web_dashboard_round15_busy.cjs:46` — busy before translations arrive restores current language, never saved English

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Switch the rendered language selector; assert visible labels, placeholders, accessible names and parameterized messages.
- 舊斷言逐行索引：
  - L46: `assert.equal(button.textContent, zh.m0044);`
  - L47: `run("buttonBusy(button,false)"); assert.equal(button.textContent, zh.m0248);`
  - L48: `language("en"); assert.equal(button.textContent, en.m0248);`

### `test_web_dashboard_round15_busy.cjs:54` — dynamic preview, undo and library labels remain translatable and reentrant

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.
- 舊斷言逐行索引：
  - L54: `language("zh"); assert.equal(button.textContent, zh.m0044);`
  - L56: `assert.equal(button.textContent, zh[key]);`
  - L57: `language("en"); assert.equal(button.textContent, en[key]);`

### `test_web_dashboard_round15_busy.cjs:63` — playlist counts and busy text translate; navigation preserves its label

- 舊意圖：3 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L63: `language("zh"); assert.equal(button.textContent, zh.m0102+"3"+zh.m0103);`
  - L64: `run("buttonBusy(button,false)"); assert.equal(button.textContent, zh.m0088+"3"+zh.m0089);`
  - L66: `run("buttonBusy(button,true); buttonBusy(button,false)"); assert.equal(button.children[0], label);`

### `test_web_dashboard_round27_covers.cjs:19` — safe thumbnails and legacy YouTube URLs fill unique collage slots

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L19: `assert.deepEqual(Array.from(h.playlistCoverSources([{thumbnail:"https://img.example.test/a.jpg"},{url:"https://youtu.be/abcdefghijk"},{thumbnail:"https://img.example.test/c.jpg"},old,{thumbnail:"https://img.example.test/e.jpg"}])),["https://img.example.test/a.jpg","https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg","https://img.example.test/c.jpg","https://img.example.test/e.jpg"]);`
  - L20: `assert.equal(h.playlistCoverThumbnail(old),"https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg");`
  - L21: `assert.equal(h.playlistCoverElement([{thumbnail:"https://img.example.test/a.jpg"}]).getAttribute("data-count"),"1");`
  - L22: `assert.equal(h.playlistCoverElement([{thumbnail:"https://img.example.test/a.jpg"},{thumbnail:"https://img.example.test/b.jpg"}]).getAttribute("data-count"),"2");`

### `test_web_dashboard_round27_covers.cjs:26` — sources cap at four and no-image playlists show designed vinyl

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L26: `assert.equal(h.playlistCoverSources(many).length,4);`
  - L28: `assert.equal(none.getAttribute("data-count"),"0");assert.ok(none.classes.has("is-empty"));assert.match(none.style.background,/radial-gradient/);`
  - L28: `assert.equal(none.getAttribute("data-count"),"0");assert.ok(none.classes.has("is-empty"));assert.match(none.style.background,/radial-gradient/);`
  - L28: `assert.equal(none.getAttribute("data-count"),"0");assert.ok(none.classes.has("is-empty"));assert.match(none.style.background,/radial-gradient/);`

### `test_web_dashboard_round27_covers.cjs:32` — unsafe schemes and credential-bearing image or song URLs are rejected

- 舊意圖：2 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L32: `assert.deepEqual(Array.from(h.playlistCoverSources([`
  - L38: `assert.equal(h.playlistCoverThumbnail({thumbnail:"javascript:alert(1)",url:"https://example.test/x"}),"");`

### `test_web_dashboard_round27_covers.cjs:42` — failed images hide broken icons and reveal vinyl when every collage image fails

- 舊意圖：5 個 assert calls；納入 Vue browser migration
- 新驗證：Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.
- 舊斷言逐行索引：
  - L42: `assert.equal(images.length,2);images[0].onerror();assert.equal(images[0].hidden,true);assert.equal(images[0].style.display,"none");assert.equal(cover.classes.has("is-empty"),false);`
  - L42: `assert.equal(images.length,2);images[0].onerror();assert.equal(images[0].hidden,true);assert.equal(images[0].style.display,"none");assert.equal(cover.classes.has("is-empty"),false);`
  - L42: `assert.equal(images.length,2);images[0].onerror();assert.equal(images[0].hidden,true);assert.equal(images[0].style.display,"none");assert.equal(cover.classes.has("is-empty"),false);`
  - L42: `assert.equal(images.length,2);images[0].onerror();assert.equal(images[0].hidden,true);assert.equal(images[0].style.display,"none");assert.equal(cover.classes.has("is-empty"),false);`
  - L43: `images[1].onerror();assert.equal(cover.classes.has("is-empty"),true);`

### `test_web_dashboard_round27_covers.cjs:49` — playlist and favorite saves share the sanitized thumbnail field

- 舊意圖：4 個 assert calls；納入 Vue browser migration
- 新驗證：Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.
- 舊斷言逐行索引：
  - L49: `assert.ok(declaration);`
  - L54: `assert.equal(saved.thumbnail,"https://img.example.test/a.jpg");`
  - L55: `assert.match(library,/const track = libraryTrack\(song\)/);`
  - L56: `assert.match(library,/: \{track:libraryTrack\(song\)\}/);`

### `test_web_dashboard_round27_offline.cjs:102` — offline shell translates from cached catalogs only and keeps the canonical retry URL

- 舊意圖：10 個 assert calls；既有真實 PWA/offline suite 暫保留
- 新驗證：Retain in the existing worker/offline/registration suite; no legacy assertion removed.
- 舊斷言逐行索引：
  - L102: `assert.equal(await page.locator("#offline-heading").textContent(), expectedHeading);`
  - L103: `assert.equal(await page.locator("#offline-language").inputValue(), locale === "zh-TW" ? "zh-TW" : "en");`
  - L104: `assert.equal(await page.locator(".offline-retry").getAttribute("href"), "/");`
  - L105: `assert.equal(new URL(page.url()).pathname, "/offline.html");`
  - L106: `assert.equal(await page.locator("style").count(), 0);`
  - L107: `assert.equal(server.requests.i18n, i18nAtOfflineStart, "offline page must read catalogs only from Cache Storage");`
  - L108: `assert.equal(server.requests.uiConfig, 0);`
  - L110: `assert.ok(color.startsWith("rgb("));`
  - L115: `assert.equal(new URL(page.url()).pathname, "/offline.html", "language switching must not redirect");`
  - L121: `assert.notEqual(themeColors.light, themeColors.dark, "light and dark themes should use distinct card surfaces");`

### `test_web_dashboard_round27_offline.cjs:146` — offline layout honors simulated safe areas and keeps retry target at least 44px

- 舊意圖：5 個 assert calls；既有真實 PWA/offline suite 暫保留
- 新驗證：Retain in the existing worker/offline/registration suite; no legacy assertion removed.
- 舊斷言逐行索引：
  - L146: `assert.ok(layout.shellPaddingTop >= 87);`
  - L147: `assert.ok(layout.shellPaddingBottom >= 62);`
  - L148: `assert.ok(layout.retryHeight >= 44);`
  - L149: `assert.ok(layout.retryLeft >= 0 && layout.retryRight <= layout.width);`
  - L150: `assert.ok(layout.scrollWidth <= layout.width);`

### `test_web_dashboard_round27_registration.cjs:12` — already controlled PWA observes even an immediate registration update

- 舊意圖：3 個 assert calls；既有真實 PWA/offline suite 暫保留
- 新驗證：Retain in the existing worker/offline/registration suite; no legacy assertion removed.
- 舊斷言逐行索引：
  - L12: `const result=await run(true);assert.equal(result.observed,true);assert.equal(result.button.hidden,false);assert.deepEqual(result.messages,["m0222"]);`
  - L12: `const result=await run(true);assert.equal(result.observed,true);assert.equal(result.button.hidden,false);assert.deepEqual(result.messages,["m0222"]);`
  - L12: `const result=await run(true);assert.equal(result.observed,true);assert.equal(result.button.hidden,false);assert.deepEqual(result.messages,["m0222"]);`

### `test_web_dashboard_round27_registration.cjs:15` — first install does not show an unnecessary update prompt

- 舊意圖：3 個 assert calls；既有真實 PWA/offline suite 暫保留
- 新驗證：Retain in the existing worker/offline/registration suite; no legacy assertion removed.
- 舊斷言逐行索引：
  - L15: `const result=await run(false);assert.equal(result.observed,true);assert.equal(result.button.hidden,true);assert.deepEqual(result.messages,[]);`
  - L15: `const result=await run(false);assert.equal(result.observed,true);assert.equal(result.button.hidden,true);assert.deepEqual(result.messages,[]);`
  - L15: `const result=await run(false);assert.equal(result.observed,true);assert.equal(result.button.hidden,true);assert.deepEqual(result.messages,[]);`

## 執行矩陣

browser runner 將以 Node 啟動 credential-free `tools/dashboard_demo.py` fixture server，提供固定 guild、song、playlist、permission 與錯誤情境；Playwright 載入 build 後的頁面，逐項檢查 DOM 和 API request。視窗至少含 390px mobile、393px standalone safe-area、1440px desktop，並跑 light/dark。現有輪次 screenshot runner 的 demo API 可沿用；新測試不載入 legacy controller。
