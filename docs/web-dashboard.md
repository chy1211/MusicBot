# Web dashboard: round 4 (implemented and tested, not deployed)

Optional aiohttp dashboard inside the bot event loop, without another Discord
client or dependency. Production dev ae9cc53 already uses Discord login. This round-4 branch is
not deployed. Default AuthMode=owner preserves legacy OwnerID behavior when
the key is missing. That mode still requires external SSO.
Removing SSO is appropriate only after separately deploying and verifying
AuthMode=discord over HTTPS. This branch changes no production configuration,
container, release tag, proxy, firewall or system service.

## Configuration and Discord Developer Portal

Only config/example_web_dashboard.ini is tracked. Never commit a real ini.

~~~ini
[WebDashboard]
Enabled = yes
Host = 0.0.0.0
Port = 8080
AuthMode = discord
PublicURL = https://music.example.com
DiscordClientID =
DiscordClientSecret = <OAUTH2_CLIENT_SECRET>
SessionSecret = <RANDOM_SECRET_AT_LEAST_32_BYTES_RECOMMENDED>
SessionHours = 168
SharedSecret =
~~~

PublicURL is an absolute root origin, without credentials, path, query or fragment.
A trailing slash is accepted. HTTPS is required except for local loopback demos.
A blank DiscordClientID uses the bot's application_id, cached application ID,
or bot user ID. DiscordClientSecret is required; it is not the bot token.
SessionHours must be positive and finite. Blank SessionSecret generates a random
key on startup. Sessions always live in process memory, so even a persistent
SessionSecret does not preserve logins across restarts. SharedSecret is ignored
in Discord mode; it remains optional Bearer protection in owner mode.

Missing/disabled configuration does not start a listener. Invalid or incomplete
enabled Discord configuration **does not start the dashboard**, logs only the
exception type, and lets MusicBot continue normally. This includes missing public
origin/client secret/application ID or invalid session duration. Read once after
the first successful on_ready; changing settings needs a separately approved
deployment/restart. close/logout/run_musicbot-finally clean up the listener,
session records and resolver tasks.

In https://discord.com/developers/applications select the bot application (or the
application matching DiscordClientID). Under **OAuth2**, copy **Client Secret**,
not the Bot page's Token. Under Redirects, add exactly and save:

~~~text
https://music.example.com/auth/callback
~~~

For an explicit DiscordClientID, copy **Application ID / Client ID** from that
same application. The flow requests only identify; no email, guilds, bot or
guilds.members.read scope. Guild membership/roles come from the existing bot cache.
Official protocol reference: https://discord.com/developers/docs/topics/oauth2

## Login and sessions

GET /auth/session returns {auth_mode, authenticated, user}, without guild/song
data. Unauthenticated user is null; owner reports authenticated with user=null.

GET /auth/login creates random state, a five-minute server record and a matching
browser cookie, then redirects to Discord's authorization code flow. Callback
requires the cookie plus unexpired record, consumes state before awaiting HTTP,
exchanges code and requests /users/@me. Missing/bad/replayed state, missing code,
cancellation and provider failures fail closed. HTTP uses a short-lived aiohttp
session, ten-second timeout, no redirects or environment proxy inheritance, and
16 KiB response limits. Only ID, display name and validated Discord avatar URL
survive. Access/refresh tokens and authorization codes are never saved.

Session cookies contain a random nonce plus HMAC-SHA256. The server stores only
the profile and absolute monotonic expiry (default seven days). Cookies are
HttpOnly, SameSite=Lax, path=/, no Domain; HTTPS also uses Secure and __Host-
names. Login rotates the session; POST /auth/logout revokes the server record
immediately, clears cookies and this browser's pending login. Replaying a logged
out cookie fails. GET never logs out. Logout requires a live session, custom
header and same-origin checks.

Pending states and sessions are capped at 1024 each; expired records are removed
during login/session creation. Login admission is capped at 60 per minute
globally (429), and new sessions fail at capacity (503). These are memory bounds,
not internet-edge DDoS protection.

The unauthenticated page only shows the login card and never requests guilds or
state. After login, avatar/name/logout appear at the upper right. A 401 clears
songs, guilds, query, preview and profile, stops sensitive polling and invalidates
stale replies; 403 shows the backend reason while retaining the session. Metadata
uses textContent, without external scripts/fonts/CDN.

## Request protection and TLS reverse proxies

In Discord mode, all /api/* requests require a live session **before** header,
readiness, route or guild checks. Missing/expired/tampered sessions uniformly
return 401 without guild/song data. Authenticated APIs and logout also require
X-MusicBot-Dashboard: 1. No CORS. Supplied Origin must exactly equal PublicURL
origin, including scheme/port. Missing Origin is permitted because cross-site
browser scripts cannot supply the custom header without a CORS preflight;
HTML forms cannot supply that header.

Auth/API Host must match PublicURL. Traefik must preserve the public Host, e.g.
music.example.com. The backend may receive HTTP plus
X-Forwarded-Proto=https: Secure cookies and Origin matching derive from PublicURL,
not request.scheme or client-controlled Forwarded headers. Forged forwarded
headers cannot change the accepted origin. Root hosting only, no subpaths.
Direct internal auth/API requests with another Host fail closed.

Owner mode retains the preceding Origin-versus-Host check, optional Bearer
SharedSecret and browser tab-memory secret input. Never expose owner mode
without an authenticated reverse proxy.

Security headers on auth/API/static/errors include no-store, nosniff,
no-referrer, X-Frame-Options=DENY and CSP with same-origin scripts/styles, no
objects/base override/framing. JSON request bodies are capped at 16 KiB. Access
logging is disabled to avoid callback codes/cookies in URL logs. Dashboard audit
lines (API, logout, login and callback) contain only user ID, guild ID, a fixed action and HTTP status for success
or rejection; no names, queries, provider body, cookies/tokens/secrets or exception
messages. Existing native command/downloader logging remains its original behavior.

## Identity, permissions and voice

Each guild request resolves the session ID with guild.get_member. Missing
members get 403; /api/guilds lists only available mutual guilds. User blocklist
matches the Discord dispatcher (OwnerID exempt). State requires membership only,
never creating a player or joining voice.

Commands use bot.permissions.for_user(member), including role-based groups and
Owner group. Nonowners pass can_use_command with the actual command and first
argument/subcommand, including advanced command lists. Owner's command-list
bypass matches Discord. Mutations queued behind the guild lock recheck session
and membership; connection awaits recheck current membership, permissions and
voice again before executing.

| API under /api/guilds/{id} | Command permission | Discord-mode voice | Existing implementation |
| --- | --- | --- | --- |
| GET /state | none; membership/blocklist | none | get_player_in |
| POST /resolve | play, query first argument | none; never summons | extract_info, _do_song_blocklist_check, can_use_extractor, playlist/entry gates |
| POST /play | play, query first argument | same bot voice; absent bot needs caller voice + summonplay | cmd_play -> _cmd_play -> Playlist |
| POST /pause | pause | same bot voice | cmd_pause |
| POST /resume | resume | same bot voice | cmd_resume |
| POST /skip | skip | same bot voice | cmd_skip, actual author, message=None, existing skip_state |
| POST /volume | volume, numeric argument | same bot voice | cmd_volume |
| POST /repeat | repeat, every on/off/all subcommand used | same bot voice | cmd_repeat |
| DELETE /queue/{position} | remove, position + ownership/remove flag | same bot voice | cmd_remove + serialize_queue |
| POST /queue/move | move, source position | same bot voice | Playlist delete/insert + serialize_queue |
| POST /queue/shuffle | shuffle | same bot voice | Playlist.shuffle + serialize_queue |

Every mutation requires same bot voice even with empty IgnoreNonVoice and even
for the logged-in Owner. Configured IgnoreNonVoice also calls the existing check.
Only play may create a player. Missing voice/bot returns 409; another voice
channel returns 403. Text responses follow bound-channel, UnboundServers and
member/bot view/send checks. Command author is the real caller; Discord messages
are sent by the bot with caller attribution, not by impersonating the user.
Notification failures do not repeat completed queue mutations.

Skip keeps the original configured voting/author-skip/InstaSkip/LegacySkip rules.
A nonprivileged caller votes; repeated clicks cannot add votes, and the API
message shows remaining votes. Remove follows ownership or permissions.remove.
InstaSkip alone does not grant remove in the current cmd_remove implementation,
despite its legacy error wording. Move also preserves cmd_move\'s active-entry requirement. Move/shuffle use equivalent Playlist primitives
without the Discord animation/await window but check move/shuffle permission first.
Owner mode preserves the preceding release's API and voice behavior.

## API payloads, limits and previews

Mutations return {message, state}; state contains track, progress seconds, volume
percent, repeat, queue and revision. Errors return {error}: 400 malformed/command,
401 login, 403 denial, 404 missing/no result, 409 voice/player/revision conflict,
429 admission limit, 502 provider failure, 504 resolver timeout. Denied preview
items may instead return allowed=false with a reason in a successful result list.

POST /resolve {query} extracts metadata only. Keywords return up to five choices,
bounded by MaxSearchItems. Playlist results now contain every extracted child up
to 200 entries, with a scrollable checklist, rather than a ten-song sample.

~~~json
{"results":[{"kind":"playlist","title":"Example","url":"https://example.test/list",
 "preview_id":"opaque-server-token","count":240,"checked_count":200,
 "eligible_count":190,"limit":200,"truncated":true,"allowed":true,"reason":"",
 "warning":"Only the first 200 entries are offered; actual UI text is zh-TW.",
 "entries":[{"item_id":"1","title":"Song","duration":180,
 "url":"https://example.test/song","thumbnail":"","allowed":true,"reason":"",
 "warning":""}]}],"expires_in":300}
~~~

count is the larger of extractor playlist_count and actual extracted entry count.
checked_count is the offered subset size; eligible_count is its eligible count.
Items beyond the cap cannot be selected. AllowPlaylists and MaxPlaylistLength
gate the entire original list, including a one-song selection. MaxSongs checks
the user's current queue before resolve; when slots remain, selection is
permitted even if the whole list would not fit. Actual enqueue checks MaxSongs
per song and returns partial success. Blocklist, extractor, MaxSongLength,
source enablement and karaoke gates remain. Unknown duration warns and is checked
again at play. Mixed YouTube links offer separate video/playlist choices.

POST /play confirms a choice. Singles keep {query:selected_url,preview_id}.
Playlist requests add a nonempty, unique list of string item IDs:

~~~json
{"query":"https://example.test/list","preview_id":"opaque-server-token",
 "selected_items":["1","3","12"]}
~~~

The server stores the offered URLs/eligibility in the preview record. IDs are
local to that preview; submitted URLs/unknown IDs, blocked items, duplicate IDs,
wrong types and an empty selection are rejected before enqueue (400/403).
Tokens bind user, guild and source URL for five minutes, at most 100 choices.
Selection without a preview is 400. Missing selected_items on a playlist selects
all eligible offered entries for compatibility. Singles reject selected_items.
The server restores playlist order regardless of submitted ID order.

Each selected item uses the original cmd_play -> _cmd_play -> Playlist path.
A task-local ContextVar check runs after fresh extraction, before mutation:
it rejects nested playlists and rechecks the live session/member, voice,
command permission, AllowPlaylists, MaxPlaylistLength, MaxSongs, full duration,
extractor and blocklist. The hook returns fresh permissions to _cmd_play.
Other tasks/native Discord commands see no check. The original command records
the actual enqueue before response work, so a failed reply does not miscount
other concurrent additions. Upstream English messages are unchanged.

The whole batch is one play rate-limit attempt; resolve is a separate attempt.
The guild mutation lock covers the batch, preserving source order among dashboard
mutations. Native Discord/round-robin behavior remains the bot's own. Each song
has a 20-second budget; the batch has a 120-second enqueue budget. Expired
remaining songs are reported as skipped. The UI shows a spinner with the selected
count throughout; no streaming per-song progress endpoint is added.

~~~json
{"message":"已加入 2 首，略過 1 首。已達到可排入佇列的歌曲數量上限。",
 "added":2,"skipped":1,
 "results":[{"item_id":"1","title":"Song","added":true,"reason":""},
            {"item_id":"3","title":"Another","added":true,"reason":""},
            {"item_id":"12","title":"Last","added":false,"reason":"佇列上限"}],
 "state":{"current":{},"queue":[]}}
~~~

A successful enqueue with failed response work has added=true plus a warning.
Repeating a completed preview with the same canonical selection returns saved
counts without enqueueing again. Changing a completed selection is 409. Once
submission starts, an interrupted/uncertain batch cannot restart with that token:
inspect the queue and resolve again. Session and membership are checked before
the response; revoked sessions never receive a state snapshot.
Legacy /play {query} still uses the original full-list behavior.

State current and every queue track add requester: {name,avatar} only; no requester
ID, roles, channel, email or other member data. Live guild display name wins,
then retained author/member metadata. Autoplay is 自動播放; a restored entry with
a channel but missing author is 點播者已離開或無法取得. Missing identity cannot
be reconstructed after the bot discarded it. Avatar and source URLs use
public_url: absolute HTTP(S) only, no userinfo/control characters or malformed
host/port. The current-track link uses target=_blank, rel="noopener noreferrer".

Move: {from,to,revision}, 1-based. Shuffle/remove: {revision}. Stale/concurrent
queue requests return 409. Volume: integer 1..100. Repeat: off/song/all.

Discord mode allows **12 combined resolve/play attempts per user per rolling
60 seconds**, across guilds and sessions; owner mode is unaffected. Additionally
one resolver per guild, two overall. Resolve deadlines are 20 seconds without
holding playback mutation locks; timed-out work retains its slot until finished.
Python cannot kill an executing yt-dlp worker thread.

Pointer sorting uses a lifted/scaled source, transformed neighbours and FLIP
reconciliation. A 409 animates back and retains the error toast before refreshing
authoritative state. API unchanged: one move with observed {from,to,revision}.
Touch hold is 420ms; Escape, lost capture, pointercancel and incoming revisions
cancel without mutation. Keyboard up/down/remove remain. Reduced motion disables
spinner rotation, FLIP and drag transforms; processing text remains.
Polling runs every second, ten seconds while hidden.

Query/confirm buttons expose aria-busy and CSS spinners, block duplicate submits,
and restore state after failure/timeout. Client deadlines: resolve 25s, selected
batch 150s, other requests 30s. Client timeout can follow a queue change: inspect
state before retrying. Fixed aria-live=polite/aria-atomic toasts last 4.5s normally
or 10s for errors. Old timers cannot erase newer messages. All-skipped batches use
the error duration. Common denials use existing _D translations then zh-TW
dashboard-only fallbacks for ownership, queue/playlist/song limits, karaoke,
voice and command permissions; upstream English sources/catalogs are untouched.

## Appearance and retained copy

Reference access was limited to personal-data-inventory/web/v2.html, v2.css
and build_v2_css.sh. No private data, APIs, databases, logs, other source files
or personal copy were read/copied. That project was never modified.

Shared tokens: background #05060d; text #f2f2f7; muted rgba(235,235,245,.6);
accent #64d2ff, secondary #bf5af2; rgba(255,255,255,.12) borders; 22px glass
panels, 16px secondary panels and capsule buttons. Glass uses the same 140deg
white sheen, dark translucent fill, 30px blur/saturation and bright inset rims.
Buttons use translucent #0a84ff with a top highlight. Sidebar, login, inputs,
selection rows and toast share these tokens and 8/12/16/24px spacing.

Differences: hand-written local CSS, without Tailwind tooling/CDN or Google Fonts;
system stack -apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI, PingFang TC,
Microsoft JhengHei, system-ui. Static radial wallpaper replaces animated colour
blobs. No refraction filter or pointer spotlight. The playback bar is solid
#1c1c22 for queue-text legibility. Functional sidebar/queue/control layout remains.

Removed exactly the requested groups: 讓音樂繼續陪你 plus sound-bar decoration;
sidebar-note including ◉ / 讓好歌 / 接著發生。 / 在 Discord 相聚，在這裡選歌。;
the hint 先看預覽，再加入佇列。搜尋結果可挑選一首。.
Retained for user decision: 你的音樂空間 (login/sidebar), 此刻，聽點喜歡的 (header),
讓旋律接下去 (queue), 私人音樂室 (owner badge). Potentially decorative headings
一起聽音樂, 下一首，想聽什麼？ and 確認你的選擇 also remain.
Functional empty-state, drag instructions and error messages remain.

## Offline tests and fake-login demo

Build from Git archive, never the operational directory containing credentials
and backups. Existing dependency tags are read only; all new test images and
containers start musicbot-webtest-. No production mounts.

~~~sh
ctx=$(mktemp -d /tmp/musicbot-webtest-r4.XXXXXX)
git -C "$HOME/musicbot" archive feature/dashboard-round4 | tar -x -C "$ctx"
printf '%s\n' 'FROM musicbot:ytdlp-base' 'WORKDIR /webtest' 'COPY . .' |
  docker build --network none -t musicbot-webtest-r4:demo -f - "$ctx"
docker run --rm --network none --name musicbot-webtest-r4-unit \
  --entrypoint python3 musicbot-webtest-r4:demo \
  -W 'error::DeprecationWarning:aiohttp.web_protocol' \
  -m unittest discover -s tests -p 'test_web_dashboard*.py'
docker run --rm --network none --name musicbot-webtest-r4-links \
  --entrypoint python3 musicbot-webtest-r4:demo -m tools.test_compound_link
(cd "$ctx" && node --check musicbot/web/dashboard.js &&
  node --test tests/test_web_dashboard_frontend.cjs)
~~~

Tests use real commands/Playlist, fake Discord boundaries and local OAuth mocks.
Node VM tests use a fake DOM with no network/dependencies. The base image's
git-version warning is expected in an archive (no .git); it does not fail tests.
No production configuration is mounted/copied.

The demo uses real Dashboard/assets/sessions and a fake-login picker, with no
Discord client, credentials, OAuth or downloads. Fake login exists only in the
demo executable. The queue includes Owner/member/autoplay. The fake playlist has
24 songs, three blocked. Owner can select all eligible songs. Member retains
210-second/three-song limits and AllowPlaylists=false, so cannot add even one
selected playlist item. Away reads only; denied has no command permissions.
Real cmd_skip/cmd_remove still implement demo vote/permission behavior.

Strict isolated browser demo, with relay in the foreground on the VPS:

~~~sh
docker run --rm -d --network none --name musicbot-webtest-r4-demo \
  --entrypoint python3 musicbot-webtest-r4:demo \
  -m tools.dashboard_demo --host 0.0.0.0 --port 8080 \
  --public-origin http://127.0.0.1:18080
python3 "$ctx/tools/dashboard_demo_relay.py" \
  --container musicbot-webtest-r4-demo --port 18080
~~~

The previous -p 127.0.0.1:18080:8080 demo needs Docker bridge networking;
it cannot forward into --network none. This task requires isolation, so a small
standard-library relay binds only 127.0.0.1:18080 and connects via docker exec
stdio to the demo container's loopback. It accepts only musicbot-webtest-*
container names and uses no production mounts or proxy changes. Every container
actually used for round-4 verification uses --network none.

Keep this Windows PowerShell tunnel open:

~~~powershell
ssh -N -L 127.0.0.1:18080:127.0.0.1:18080 -o ExitOnForwardFailure=yes your-vps
~~~

Open http://127.0.0.1:18080/, click login, choose Owner. Query
https://example.test/playlist: 24 rows, 21 eligible/selected, three disabled.
Try 全不選 (confirm disabled), 全選, then select only rows 3 and 5.
加入選取的 2 首 adds only these in source order. Logout and choose member for
whole-playlist denial and per-song length explanations. Try a keyword, HTTPS
single-song URL or blocked for other previews.

Stop relay/tunnel with Ctrl+C, then clean only these named resources:

~~~sh
docker stop musicbot-webtest-r4-demo
docker image rm musicbot-webtest-r4:demo
case "$ctx" in /tmp/musicbot-webtest-r4.*) rm -rf -- "$ctx";; esac
~~~

## Limits before a separately authorized release

Live Discord consent/redirects, real voice/yt-dlp, production TLS/Traefik and
real touch dragging remain live acceptance items. Mock proxy tests verify
HTTPS PublicURL, preserved Host, X-Forwarded-Proto=https and Secure cookies;
they are not a real proxy deployment. Member/role cache must be populated;
uncached users fail closed. Sessions are single-process, reset at restart, and
not shared across replicas. No admin per-session revocation UI is included.

Authenticated guild members retain the bot's existing downloader/network/cookie
capabilities, as through Discord play. OAuth does not make arbitrary yt-dlp or
internal HTTP URLs safe. Trust membership and permission/blocklists accordingly.
Many accounts can exhaust shared login/resolve quotas; edge DDoS/rate protection
is still needed for internet exposure. Remote track covers can contact image
hosts from the user's browser; no-referrer avoids sending the dashboard URL.
Protect backend reachability, TLS and secrets during the separate deployment.


## Round-4 validation (2026-10-17, no deployment)

Baseline archive before edits: backend 145/145, frontend 35/35.
Final suite: backend 171/171 (including 26 new round-4 cases), frontend 46/46
(including 11 new cases), tools.test_compound_link 16/16; zero failures.
Backend uses DeprecationWarning-as-error for aiohttp.web_protocol.
node --check and git diff --check also pass.

Chrome fake-data acceptance: login glass styling; 24-song preview with 21
selected and three blocked; select none/all and only rows 3/5; exactly these
two queued in source order; actual mouse drag first to third; member playlist
denial; removing another user's song gives a fixed zh-TW toast; 390px layout
has no horizontal overflow. Real phone long-press and live Discord/yt-dlp are
not exercised. Pointer touch/reduced-motion/409 recovery are offline tests.

Every test/demo container uses --network none. The browser reaches only the
fake demo via the loopback relay and SSH tunnel. No release commands or real
credentials were used. Worktree and temporary Docker resources are removed
after the commit; feature/dashboard-round4 remains for later review.
