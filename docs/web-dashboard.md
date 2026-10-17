# Web dashboard: round 8 (development only)

Optional aiohttp dashboard inside the bot event loop, without another Discord
client or dependency. The round-7 branch starts at dev 9af6f8d (round 6). This feature branch is not deployed. The public production
dashboard already uses Discord login. Each caller acts with their own guild
membership, permissions and voice state. Default AuthMode=owner preserves legacy
OwnerID behavior when the key is missing; owner mode requires external SSO.
This branch changes no production configuration, container, release tag, proxy,
firewall or system service.

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
return 401 without guild/song data. Authenticated APIs and logout require
X-MusicBot-Dashboard: 1, except the read-only GET events transport described below. No CORS. Supplied Origin must exactly equal PublicURL
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

Security headers on auth/API/static/errors include no-store (SSE uses no-cache), nosniff,
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
| GET /listeners | none; membership/blocklist | none | bot voice member cache, excludes bots |
| GET /activity | none; membership/blocklist | none | latest 100 guild memory records |
| GET /events | live session + membership/blocklist continuously | none | bounded SSE snapshots |
| POST /resolve | play or playnext (action), query first argument | none; never summons | extract_info, _do_song_blocklist_check, can_use_extractor, playlist/entry gates |
| POST /play | play, query first argument | same bot voice; absent bot needs caller voice + summonplay | cmd_play -> _cmd_play -> Playlist |
| POST /playnext | playnext, query first argument | same bot voice; absent bot needs caller voice + summonplay | cmd_playnext -> _cmd_play(head=True); single only |
| POST /seek | seek, absolute seconds | same bot voice | cmd_seek; observed track_token |
| GET /history | none; membership/blocklist | none | playback-start metadata + loaded guild URL history |
| GET /lyrics | none; membership/blocklist + separate 12/min | none | anonymous LRCLIB adapter |
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
Only play/playnext may create a player. Missing voice/bot returns 409; another voice
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

POST /resolve {query,action?} extracts metadata only (action defaults to play). Keywords return up to five choices,
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

State current and every queue track include requester: {name,avatar} and a
viewer-specific mine boolean; no requester ID, roles, channel, email or other
member data. Live guild display name wins,
then retained author/member metadata. Autoplay is 自動播放; a restored entry with
a channel but missing author is 點播者已離開或無法取得. Missing identity cannot
be reconstructed after the bot discarded it. Avatar and source URLs use
public_url: absolute HTTP(S) only, no userinfo/control characters or malformed
host/port. The current-track link uses target=_blank, rel="noopener noreferrer".

Move: {from,to,revision}, 1-based. Shuffle/remove: {revision}. Stale/concurrent
queue requests return 409. Volume: integer 1..100. Repeat: off/song/all.

Discord mode allows **12 combined resolve/play/playnext attempts per user per rolling
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
SSE replaces normal polling; progress is extrapolated locally. Failed/unsupported
streams fall back to one-second polling. Hidden tabs stop streams and reads.

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
The subsequent copy cleanup also removed 你的音樂空間, 此刻，聽點喜歡的,
讓旋律接下去 and 私人音樂室, plus the recent-play and lyrics taglines.
Round 6 keeps that cleanup. 一起聽音樂, 下一首，想聽什麼？ and 確認你的選擇 remain.
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


## Round 5: seek, playnext, recent plays and lyrics (not deployed)

New authenticated endpoints under /api/guilds/{id}:

| Method/path | Input | Output | Permission / voice / existing function |
| --- | --- | --- | --- |
| POST /seek | {"position":62.5,"track_token":"state current token"} absolute seconds, finite number, not boolean | {message,state} | seek; same bot voice; cmd_seek |
| POST /playnext | {"query":"https://example.test/song","preview_id":"..."} | {message,state} | playnext; same bot voice; cmd_playnext -> _cmd_play(head=True) |
| GET /history | none | {history:[track + played_at],source,resets_on_restart:true} | membership/blocklist only; no voice |
| GET /lyrics | optional ?query=artist%20song (manual keywords) | {status,title,artist,plain_lyrics,lines:[{time,text}],track_key} | membership/blocklist only; no voice |

POST /resolve accepts optional action="play" (default) or "playnext" and checks
that command's permission, including the URL/first argument. The query-use selector
supports callers with playnext permission but no play permission. A single-song
preview can be confirmed with either button; the chosen command's current
permissions are always checked again. A preview remains a single-use choice,
so switching action after completion never adds it twice. All normal queue/song,
blocklist, extractor and karaoke limits still apply.
Round 5 offers playnext for single tracks only. Playlist insertion is rejected
rather than reversing a list through repeated head insertions. Ordinary playlist
selection remains the round-4 play path.

State current adds seekable (boolean) and an opaque track_token tied to the
player and playback entry. The browser returns the observed track_token with
seek; an old token returns 409. Legacy position-only requests still compare the
entry before waiting for the guild lock/context and after any connection await,
rejecting a track change instead of moving the next song.

Seek accepts absolute 0..duration inclusive; unknown-duration/stream entries and
out-of-range values fail without modifying the queue. Only URL/local entries are
seekable. cmd_seek restarts the same entry via the existing ffmpeg seek mechanism,
which may have codec-dependent accuracy. Both now-playing and bottom-bar range
inputs support pointer, touch and arrow keys. Input previews both time displays;
only release/keyup/committed change submits. Polling updates state without replacing
an active drag. A changed guild/track, pointer cancel or Escape cancels the draft.

Recent plays are captured on playback-start events, including native Discord
requests with no browser open. The optional bot hook is synchronous, bounded and
exception-isolated; disabling/missing dashboard leaves native commands unchanged.
Every guild keeps at most 50 minimal records in memory. Names/avatar URLs are
resolved from the current guild member cache; only Discord user IDs are retained
internally, never sent as requester fields. Historical guild-history URLs can
supplement this view when already enabled; legacy URL-only entries have unknown
time/requester/length rather than invented metadata. Global-only history has no guild attribution, so it cannot safely backfill old
songs: this mode uses guild-scoped event metadata only and reports
source=dashboard_memory_global_history_unscoped. Shared global URLs are never
exposed as another guild's history. No options.ini change is needed.
Seeking restarts an entry and therefore can add another start record.
New metadata clears on process restart; existing enabled URL history follows the
bot's original persistence behavior. Replay uses a fresh play preview and the
logged-in caller's current restrictions. Times display in Asia/Taipei; old
URL-only entries explicitly show an unknown time.

Lyrics use the backend's LRCLIB metadata lookup and search fallback. The browser
only calls same-origin APIs and creates lyric text nodes, preserving CSP and
avoiding HTML injection. Synced LRC highlights and scrolls the current line with
playback progress; plain text displays as a paragraph. Missing lyrics and provider
errors retain manual search. Guild/track changes invalidate stale responses.
Reduced-motion disables smooth scrolling and decorative movement.

The provider boundary sends only song title, artist and duration (or manual song
keywords), with a project User-Agent, a dedicated unauthenticated HTTP session,
no redirects and no forwarded user/session/bot headers. The overall lookup budget
is eight seconds. Successful and not-found results are cached for one hour (at most 200 entries);
unavailable responses use a 30-second negative cache/cooldown. Each person gets
12 lyric requests per rolling minute across guilds, including cache hits. Provider
requests are serialized with a 200 ms minimum interval, honor Retry-After on
429/503, refuse redirects and non-JSON bodies, and cap responses at 512 KiB. Song metadata is cleaned before lookup: common Official/MV/video/
audio/lyrics/quality labels, bracket decorations, labeled video suffixes and featuring
suffixes; artist/title separators are recognized. Artist metadata is preferred
when available. Search candidates are checked for plausible title/duration
matches; manual search deliberately relaxes artist/duration matching. No requester
information is sent to LRCLIB.
Protocol reference: https://lrclib.net/docs (checked 2026-10-17).

### Round-5 isolated demo and tests

All Docker names/tags created for this round start musicbot-webtest-. The base
musicbot:ytdlp-base tag is only read. Build from a Git archive, never from the
operational directory. Run on the VPS after the feature commit:

~~~sh
ctx=$(mktemp -d /tmp/musicbot-webtest-r5.XXXXXX)
git -C "$HOME/musicbot" archive feature/dashboard-round5 | tar -x -C "$ctx"
printf '%s\n' 'FROM musicbot:ytdlp-base' 'WORKDIR /webtest' 'COPY . .' |
  docker build --network none -t musicbot-webtest-r5:demo -f - "$ctx"

docker run --rm --network none --name musicbot-webtest-r5-unit \
  --entrypoint python3 musicbot-webtest-r5:demo \
  -W 'error::DeprecationWarning:aiohttp.web_protocol' \
  -m unittest discover -s tests -p 'test_web_dashboard*.py'
docker run --rm --network none --name musicbot-webtest-r5-links \
  --entrypoint python3 musicbot-webtest-r5:demo -m tools.test_compound_link
(cd "$ctx" && node --check musicbot/web/dashboard.js &&
  node --test tests/test_web_dashboard_frontend.cjs)

docker run --rm -d --network none --name musicbot-webtest-r5-demo \
  --entrypoint python3 musicbot-webtest-r5:demo \
  -m tools.dashboard_demo --host 0.0.0.0 --port 8080 \
  --public-origin http://127.0.0.1:18080
python3 "$ctx/tools/dashboard_demo_relay.py" \
  --container musicbot-webtest-r5-demo --port 18080
~~~

Keep the relay running and open a Windows PowerShell SSH tunnel:

~~~powershell
ssh -N -L 127.0.0.1:18080:127.0.0.1:18080 -o ExitOnForwardFailure=yes your-vps
~~~

Open http://127.0.0.1:18080/ and choose the fake Owner:

1. Drag/click either progress slider, hold it while polling continues, release,
   then use keyboard arrows. The fake clock moves to the requested position.
2. Search any word or https://example.test/track/0, then choose 下一首播放.
   The current song continues and the new song appears first in the queue.
   A playlist offers ordinary selection only. Member/away/denied users show the
   same permission/voice denials as the authenticated API.
3. Open 最近播過: fake songs include Owner and 一般成員. Source links use
   example.test; 再點一次 opens a permission-checked play preview. Skipping records
   the next started song and the two demo guilds remain separate.
4. Open 歌詞 on 夜色慢行 for original synced demo lyrics. Seek to 45 seconds to
   see the highlight change. 窗邊的午後 (also guild 2's initial song) has original
   plain text. 島嶼來信 has no match; manually search 夜色慢行 to find fake lyrics.
   FakeLyricsClient replaces LRCLIB entirely; no provider request can occur.

Stop relay/tunnel with Ctrl+C, then remove only these named resources:

~~~sh
docker stop musicbot-webtest-r5-demo
docker image rm musicbot-webtest-r5:demo
case "$ctx" in /tmp/musicbot-webtest-r5.*) rm -rf -- "$ctx";; esac
~~~

No production container/configuration, service, proxy, firewall or network
configuration is changed by this workflow. Live Discord voice, actual LRCLIB
matching, external TLS and real-phone interaction still need a separately
authorized release/acceptance window.


### Round-5 validation (2026-10-17, no deployment)

Original baseline: backend 171/171, frontend 46/46, compound-link 16/16.
Final round-5 suites: backend 212/212 (35 API/provider regressions and six demo
cases added), frontend 69/69, compound-link 16/16; zero failures. Python runs with
aiohttp.web_protocol DeprecationWarning promoted to an error. JS syntax and
git diff --check pass.

Nine real headless Chromium checks passed against the fake-login demo through
the loopback relay: both seek inputs/history rendered; actual mouse drag held
across polling and release; keyboard hold/release; synced lyric highlighting;
playnext before existing songs while retaining current; recent replay preview;
390px viewport without horizontal overflow; emulated touch release; plain and
missing lyrics with manual fake search. No external requests occurred. Native
range capture behavior was exercised and fixed; the VM suite now includes it.

Independent review also reproduced and fixed full-duration playnext limits
(complete days and fractional seconds), stale seek during lock/context awaits,
and disabled alternate buttons on disallowed previews. No Discord client,
real voice, actual LRCLIB query or real-phone touchscreen was used. These remain
acceptance items for a separately authorized release.


## Round 6: shared listening and live updates (not deployed)

The root dashboard retains its existing style, Traditional Chinese controls,
mobile layout and prefers-reduced-motion behavior. No decorative copy is added.

The queue heading counts the complete queue and sums its known durations,
rounded up to minutes. If any duration is unknown it labels the sum as known
duration and warns that unknown tracks are included. Estimated starts use the
current remainder plus preceding track lengths, displayed as approximate minutes
from now. An unknown track can have a known start, but all tracks after it have
undetermined starts. Pausing labels every estimate as postponed. Single-track
repeat makes starts undetermined; queue repeat shows the first traversal only.
These estimates assume normal playback speed, no further skips/reordering and
no download/connection delay. No scheduling data is persisted or added to APIs.

All/mine filtering uses only the viewer-specific mine flag. It does not expose
the requester's ID. Mine mode disables drag sorting and shuffle, with visible
instructions. Up/down/delete retain original full-queue positions and revision.
The heading and duration remain totals for the complete queue.

### New and changed read APIs

All paths below use /api/guilds/{id}. Existing mutation inputs/permissions remain
unchanged. Guild reads require a current guild member and respect the user
blocklist, but do not require voice attendance or create a player.

| Method/path | Request | Response |
| --- | --- | --- |
| GET /state | no body, usual dashboard header | existing state + per-track mine + listeners + activity |
| GET /listeners | no body, usual dashboard header | {connected,channel,members:[{name,avatar}]} |
| GET /activity | no body, usual dashboard header | {activity:[{actor,action,source,detail,result,time}],limit:100,resets_on_restart:true} |
| GET /events | no body, cookie; no custom header required | text/event-stream; named snapshot and access events |

listeners.connected is false with empty channel/members when the bot is not in
voice. Members exclude MusicBot and every other bot; there are no member-ID
fields. The UI shows eight listeners, folding the rest in a details element.
Names and avatar URLs follow the same bounded text/validated URL rules as tracks.
Voice-channel names are visible to guild members, following the requested
guild-membership scope; this is not a per-channel member visibility API.

Each guild keeps its last 100 activity records in memory, newest first; restart
clears them. time is Unix seconds; the UI renders Asia/Taipei time. source is
web, discord_text or discord_slash. actor is a display name, never an ID.
detail contains fixed action labels and affected song titles, not search input,
command arguments, URLs or exception text. Large batches show at most eight
titles plus a count. result is success or a simplified denied/incomplete result.
Removed tracks are captured before mutation. Vote skip is distinguished from
instant skip using current-track/skip-state changes. Concurrent native commands
can make before/after attribution approximate; this is an activity feed rather
than a durable audit trail. Display names/song titles remain untrusted text.

Every web playback/queue mutation is observed, including authorized member
requests rejected by validation/permissions/revision. Login/read/resolve/lyrics
searches are not activity records. Unauthenticated or nonmember requests cannot
create records in another guild. Raw arguments/errors never enter this feed.

### Discord observation and unchanged command behavior

Text dispatcher coverage (after canonical alias resolution):
play, shuffleplay, playnext, playnow, stream, seek, repeat, move, pause, resume,
shuffle, clear, remove, skip (including vote skip), volume.
The same 15 slash callbacks have an isolated observer decorator.
No cmd_* body, argument mapping, permission test or response path is replaced.

bot.py changes are limited to an observer import, a guarded read-only queue
insertion observer at on_player_entry_added, a guarded capture before the
existing text permission/argument try block, a boolean after the original
handler returns, and a guarded finish in the existing finally block.
The entry observer only records object insertion order for notification-channel
selection; existing autoskip and serialization statements execute unchanged.
Observer errors log only their type and cannot replace a command error/result.

slash_commands.py adds the observer import, a guarded result observation before
the original _send reply, and decorators around the 15 callbacks. The decorator
awaits exactly the original callback, returns its exact value and propagates its
original exceptions. Task-local ContextVar state is restored in finally.
functools.wraps and evaluated original signatures preserve Discord registration,
parameter types, choices/defaults and names, including postponed annotations.
The observer never modifies response content, args, permissions or exceptions.

Not covered: interactive text/slash search result-selection UI (its later
callbacks are outside the safe dispatch scope), autoplay, and administrative or
unrelated commands such as speed/disconnect/config. Text requests silently
ignored before dispatch (unbound channel, blocked user, unknown command or bot
message) keep their original silent behavior and are not activity records.
A supported command returning a normal response without changing playback is
recorded as completed, matching its original result.

### SSE security, lifecycle and proxy behavior

GET /events is the only custom-header exception and does not mutate playback.
Discord mode still authenticates the same HttpOnly, Secure (HTTPS), SameSite=Lax,
host-scoped cookie. Public Host must match PublicURL and an Origin, if supplied,
must match its exact scheme/host/port. Sec-Fetch-Site must be same-origin or
absent; cross-site, same-site and none are rejected. Browsers set this header;
cross-site scripts cannot forge it. Older clients may omit it, but still require
a valid cookie and any supplied Origin must match; SameSite plus no CORS prevents
cross-site script access. No tokens, credentials or user IDs are put in event URLs.
No permissive CORS headers are emitted. HEAD/POST/OPTIONS do not acquire streams.
Normal APIs, including /state and logout, still require the custom header.
Legacy owner mode with a SharedSecret refuses SSE and retains Bearer polling;
it never bypasses a configured secret to accommodate EventSource.

Streams are reserved synchronously before any await: at most three per Discord
user across sessions/guilds, and 64 globally. Excess returns JSON 429. Every
one-second inspection revalidates cookie expiry/logout, live guild membership
and blocklist BEFORE writing data or a heartbeat. Revocation sends only a fixed
access event {status:401|403|404} and closes. Shutdown/not-ready closes streams;
app shutdown wakes idle waits, cancels overdue tasks, and releases all slots.
Writes have a five-second timeout; client disconnects/errors release slots.

The server inspects snapshots each second but sends only changed state, queue,
listeners, activity or recent history. A seek discontinuity also sends state;
ordinary progress does not generate per-second data. A snapshot is a full bundle
{state,listeners,activity,history}; state has the ordinary viewer-specific shape.
Heartbeats are SSE comment frames ": heartbeat" every 15 seconds. Headers sent
before prepare include Content-Type text/event-stream, Cache-Control no-cache,
X-Accel-Buffering no, nosniff, DENY and no-referrer. Traefik should preserve Host
and stream chunks immediately. Do not apply response buffering/compression
middlewares to this endpoint; X-Accel-Buffering mainly addresses nginx-compatible
proxies, so verify actual Traefik flush/idle-timeout behavior during release.
No proxy configuration is changed by this feature branch.

EventSource is explicitly closed on an error and recreated after 1s, 2s, 4s;
from the fourth consecutive failure it waits 60s and keeps ordinary polling.
An initial connection with no snapshot has a 20s watchdog. Failures also make
a normal authenticated state read to detect 401/403 that EventSource hides.
A valid snapshot resets failures and stops polling. Unsupported EventSource
and owner SharedSecret mode use polling. Switching guild closes/replaces the
stream; hidden tabs stop streams and reads, and showing the tab refreshes and
reconnects. Old callbacks and stale HTTP reads cannot overwrite another guild.
Progress and lyric highlighting advance locally, stopping during pause.

### Additional requirement 7: Discord notification channel

All web mutations share context/channel_for, including per-item playlist play,
playnext, seek, pause/resume, volume, skip/vote skip, repeat, remove, move and
shuffle. Candidate order is current entry.channel, most recently inserted queued
entry.channel, configured bound channels, system channel, remaining text channels,
then the caller's voice-channel chat. Candidates are deduplicated and must belong
to the guild, support messaging, satisfy BoundChannels/UnboundServers, and grant
both caller and bot view_channel plus send_messages. A failing candidate falls
through; no eligible candidate returns 403 instead of sending to a forbidden one.

Insertion order is observed in memory rather than inferred after move/shuffle.
For queues already present at dashboard startup without an insertion history,
the initial queue order is the fallback until new insertions are observed.
This limitation only affects the secondary candidate when there is no usable
current entry channel. No live configuration or native Discord routing changes.

### Round-6 isolated demo and test procedure

Run after the feature commit. Only a clean Git archive is copied into the build;
the base tag is read only. Every temporary image/container starts musicbot-webtest-.

~~~sh
ctx=$(mktemp -d /tmp/musicbot-webtest-r6.XXXXXX)
git -C "$HOME/musicbot" archive feature/dashboard-round6 | tar -x -C "$ctx"
printf '%s\n' 'FROM musicbot:ytdlp-base' 'WORKDIR /webtest' 'COPY . .' |
  docker build --network none -t musicbot-webtest-r6:demo -f - "$ctx"
docker run --rm --network none --name musicbot-webtest-r6-unit \
  --entrypoint python3 musicbot-webtest-r6:demo \
  -W 'error::DeprecationWarning:aiohttp.web_protocol' \
  -m unittest discover -s tests -p 'test_web_dashboard*.py'
docker run --rm --network none --name musicbot-webtest-r6-links \
  --entrypoint python3 musicbot-webtest-r6:demo -m tools.test_compound_link
(cd "$ctx" && node --check musicbot/web/dashboard.js &&
  node --test tests/test_web_dashboard_frontend.cjs)
docker run --rm -d --network none --name musicbot-webtest-r6-demo \
  --entrypoint python3 musicbot-webtest-r6:demo \
  -m tools.dashboard_demo --host 0.0.0.0 --port 8080 \
  --public-origin http://127.0.0.1:18080
python3 "$ctx/tools/dashboard_demo_relay.py" \
  --container musicbot-webtest-r6-demo --port 18080
~~~

Keep relay running; from Windows PowerShell open a tunnel:

~~~powershell
ssh -N -L 127.0.0.1:18080:127.0.0.1:18080 -o ExitOnForwardFailure=yes your-vps
~~~

Open http://127.0.0.1:18080/; select a fake user. The demo uses no Discord client,
OAuth provider, external lyric provider, downloader or real configuration.
Artwork and listener avatars are local SVGs. Every six seconds its local timer
alternates a fake Discord slash request and a fake web skip, exercising queue,
activity, recent history and SSE; the fake queue is bounded to 12 items.

1. Check known-duration total and estimates before/after the unknown-length song;
   pause and change single/queue repeat to inspect the labels.
2. Select Mine as Owner/member; try full-position arrows/delete and disabled
   drag/shuffle. Observe the eight visible listeners plus folded remaining three.
3. Inspect the three initial activity sources and new live records, skip voting
   as member, a denied deletion, and the other guild's separate feed.
4. In browser network tools check one events request and no per-second state
   requests while it works. Disconnect/reconnect it repeatedly to exercise polling;
   switch guild, hide/show tab, logout, and confirm the old stream closes.
5. Visit /dashboard/quota (302 to /); /api/missing retains JSON; favicon paths
   return locally. Use a 390px viewport and reduced motion.

Stop relay/tunnel with Ctrl+C and remove only the named temporary resources:

~~~sh
docker stop musicbot-webtest-r6-demo
docker image rm musicbot-webtest-r6:demo
case "$ctx" in /tmp/musicbot-webtest-r6.*) rm -rf -- "$ctx";; esac
~~~

Live Discord, real-phone gestures and actual public Traefik buffering remain
release acceptance items. This procedure does not deploy or change services.

### Round-6 validation (2026-10-17, no deployment)

Original backend 212, frontend 69 and compound-link 16 cases remain passing.
Final offline suites: backend 268/268 (56 added), frontend 87/87 (18 added),
compound-link 16/16; zero failures. Backend runs with aiohttp.web_protocol
DeprecationWarning promoted to error. JS syntax, Python compilation and
git diff --check pass. Test failure-injection warnings are expected assertions.

17 real headless Chromium checks passed through the loopback relay: anonymous
page without streams; fake Owner login and real EventSource; no per-second state
polling; unknown-duration queue estimates; mine filtering; folded listeners;
all three activity sources; timed fake additions; pause/resume local progress;
390px layout without overflow; reduced motion; guild switching; real stream
failure/backoff/polling; restored push; page redirect/API JSON/favicon; logout;
and zero external page requests or uncaught JavaScript exceptions. Queue,
listeners and activity were also visually inspected at 390px.

An AST comparison against dev confirms that removing only the explicit observer
imports, capture/result/finally blocks, queue-observer block and slash decorators
restores the exact original bot.py and slash_commands.py syntax trees. Real text
and slash volume callbacks were also executed with capture/finish/result failures
injected: original mutations/replies and original exception propagation remain.

Temporary containers/images use only musicbot-webtest- names and --network none.
The archive-based test image copies no real operational configuration. No live
Discord credentials, external providers or production services were used.

## Personal library (round 7)

Every authenticated, unblocked member of at least one bot guild owns one library,
shared across guilds. No client-supplied user ID or filename is accepted. Responses
contain no user ID. Storage: data/web_dashboard/user_playlists/<session-user>.json;
version 1 JSON contains playlists with opaque IDs, names and tracks. A track stores
only title (300 chars), http/https URL (2000 chars, no credentials/whitespace),
duration (finite nonnegative seconds or null), and added_at (Unix seconds).
Favorites plus 20 custom lists; names 1-60 characters; 200 tracks per list.
Limits and malformed values return 400 in Traditional Chinese.

Per-user asyncio locks serialize reads/mutations. A sibling temporary file is
flushed, fsynced and atomically replaced; the parent directory is fsynced.
Malformed JSON/schema is moved to .corrupt-<timestamp>, logged, and the request
returns 409 without writing a replacement. The next request may start a new library.
Files live under the persistent, ignored data bind mount.

All routes require existing session, header and same-origin guards:
- GET /api/library -> {version, playlists, revision, owner}.
- POST /api/library {name} -> updated library.
- PATCH /api/library/{opaque-id} {revision,name} or
  {revision,action:"remove",index} / {revision,action:"move",index,to}.
- DELETE /api/library/{opaque-id} {revision}. Favorites cannot be deleted/renamed.
- POST /api/library/{opaque-id}/tracks {revision,track:{title,url,duration}}.
- POST /api/guilds/{guild}/library/{opaque-id}/play {revision,selected_items?}.
  Index strings select tracks in saved order; omit to enqueue all. The target
  guild's live membership, command/voice permissions, AllowPlaylists, playlist
  length, MaxSongs, song length, extractor and blocklist checks apply via the
  existing play_selection and CONFIRMED_ENTRY_CHECK. Rate limit once per batch.
  Returns {added,skipped,results:[{item_id,title,added,reason}],message,state}.
  No cached saved duration authorizes enqueue; fresh extraction checks each song.

UI: favorite current track, save queue/history tracks via picker, create/rename/
delete lists, remove tracks, up/down ordering, enqueue all or checked tracks.
Revision conflicts return 409. The demo seeds separate fake libraries under a
TemporaryDirectory, cleaned at app shutdown; no real data directory is used.

## Owner autoplaylist administration (round 7)

Owner capability is reported by GET /api/library; the UI hides management and
the current-song autoplaylist button from all other users. Server authorization
always compares the session identity to bot.config.owner_id (403 otherwise),
then checks target guild membership and the existing guards.

GET /api/guilds/{guild}/admin/autoplaylist?q=<100-char-search>&page=1 returns
{total,matched,page,page_size:50,tracks:[{index,url,title}],revision}.
It uses the active server_data[guild].autoplaylist, not a separate copy or a
client-selected filename. Legacy local paths are hidden. Titles are not
automatically fetched; no extractor/network lookup occurs for browsing.

POST at the same path accepts {revision,url} or {revision,current:true}.
DELETE accepts {revision,index}. Invalid URLs/duplicates return 400; stale
revision returns 409. Each mutation first backs up the source to
data/web_dashboard/backups/autoplaylist/<filename>.<YYYYmmdd-HHMMSS>
(a random suffix resolves same-second collisions), retaining the newest 30 per
source file. Backups are fsynced, private mode 0600, outside config/.
Writes call only native AutoPlaylist.add_track / remove_track(delete_from_ap=True),
preserving their update lock, comments and removed log behavior. Memory is
immediately the native list; disk is checked afterward because native methods
swallow write errors. On mismatch the list is reloaded and an error returned.
Existing player autoplaylist shuffle-cycle copies keep native command behavior;
new selections use the updated source at the next refill. No bulk clear/overwrite.

The offline demo uses a real AutoPlaylist in TemporaryDirectory, fake URLs and
fake cache callbacks, shared by its fake guilds. No real config/data is accessed.

## Owner permissions page (round 7)

GET /api/guilds/{guild}/admin/permissions -> {groups,limits,activity}.
Only OwnerID in that target guild is authorized. The listed fields are MaxSongs,
MaxSongLength, MaxPlaylistLength, MaxSearchItems, AllowPlaylists, InstaSkip,
SkipLooped, Remove, SkipWhenAbsent, BypassKaraokeMode, SummonNoVoice, Extractors,
CommandWhitelist/CommandBlacklist, GrantToRoles/UserList. IDs in the latter two
are resolved in that guild to names; absent entries become 未知角色/未知成員.
Virtual groups are displayed read-only if absent from the file.

PATCH at the same path accepts exactly {group,field,old_value,value}.
Only the four fields MaxSongs (0-10000), MaxSongLength (0-86400 seconds),
MaxPlaylistLength (0-10000) and AllowPlaylists (JSON boolean) are editable in
existing disk groups. Zero retains native unlimited semantics. The confirmation
dialog shows the group, field and old/new values; stale old_value returns 409.

Transaction under the dashboard administration lock:
1. Validate caller, field/value and current value. Read original bytes.
2. Back up the original to data/web_dashboard/backups/permissions/
   permissions.ini.<YYYYmmdd-HHMMSS>, same-second suffix if necessary, newest 30.
3. Replace only the value span of the target line (or append the missing field
   at the end of that group). Preserve comments, ordering, spaces and line ends.
4. Write a sibling temporary file, flush/fsync, parse with native Permissions.
   Failed parsing removes the temp, returns 400 and leaves the original intact.
5. Recheck session, membership, disk bytes and live object identity. Atomically
   replace the original, fsync its directory.
6. Rebuild Permissions(bot._perms_file), set_owner_id(bot.config.owner_id),
   await async_validate(bot), then replace bot.permissions, matching native reload.
   Any failure after replacement atomically restores backup bytes and the original
   live object; no success is reported. A restore failure is reported explicitly.
7. Append 管理：修改權限 群組 欄位 舊值→新值 to a bounded owner-only management
   activity list (100, memory only). Shared guild activity/SSE does not include it.

No save command, config serializer or options.ini access is used. Existing
Discord commands and bot.py/permissions.py/autoplaylist.py are unchanged.
Concurrent external edits before replacement cause 409. Native Discord permission
editing is outside this web lock; avoid simultaneous administration from both UIs.
The demo uses a real Permissions parser on a fake permissions.ini located wholly
inside TemporaryDirectory and replaces its in-memory object through the same API.

## Install on a phone (PWA, round 7)

manifest.webmanifest names 音樂控制台, display standalone, start_url/scope "/", with
the existing #05060d theme. SVG favicon, 192/512 PNG and 180 apple-touch-icon PNG
are served locally; PNGs total under 5 KiB and can be regenerated with
python3 tools/dashboard_icons.py. iOS standalone/status/title meta tags are included.
In Safari use Share -> Add to Home Screen; on supporting Android browsers use
the browser installation menu. Real-device installation is a release acceptance item.

sw.js caches only its explicit static allowlist: root HTML shell, offline.html,
CSS, dashboard/library/admin/permissions/PWA JS, manifest and icons. Root HTML is
network-first with a simple offline page on network failure. Other static assets
use stale-while-revalidate. Version: musicbot-dashboard-r7-2; HTML asset references
carry ?v=r7-2. Increment both on every static release. Install uses skipWaiting;
activate deletes only older musicbot-dashboard-* caches and claims clients.
A controller change shows a refresh button so a playing/unsaved session is not
silently reloaded. Failed cache writes do not hide a successful HTML response.

GET only, same origin, explicit paths only. /api and /api/*, /auth and /auth/*,
event-stream Accept and events paths, unlisted routes, other origins, writes and
non-version query parameters bypass the worker completely. No session/identity,
API response, event or OAuth redirect/token is cached. Authentication and cookie
flows retain normal network behavior. SW install static fetches omit credentials.
The root HTML is a generic shell without embedded identity; offline.html has none.

## Round-7 isolated tests and demo (no deployment)

From a clean committed branch, on the test host:

~~~sh
ctx=$(mktemp -d /tmp/musicbot-webtest-r7.XXXXXX)
git -C "$HOME/musicbot" archive feature/dashboard-round7 | tar -x -C "$ctx"
printf '%s\n' 'FROM musicbot:ytdlp-base' 'WORKDIR /webtest' 'COPY . .' |
  docker build --network none -t musicbot-webtest-r7:demo -f - "$ctx"
docker run --rm --network none --name musicbot-webtest-r7-unit \
  --entrypoint python3 musicbot-webtest-r7:demo \
  -W 'error::DeprecationWarning:aiohttp.web_protocol' \
  -m unittest discover -s tests -p 'test_web_dashboard*.py'
docker run --rm --network none --name musicbot-webtest-r7-links \
  --entrypoint python3 musicbot-webtest-r7:demo -m tools.test_compound_link
(cd "$ctx" && node --test tests/test_web_dashboard_frontend.cjs tests/test_web_dashboard_pwa.cjs)
docker run --rm -d --network none --name musicbot-webtest-r7-demo \
  --entrypoint python3 musicbot-webtest-r7:demo \
  -m tools.dashboard_demo --host 0.0.0.0 --port 8080 \
  --public-origin http://127.0.0.1:18080
python3 "$ctx/tools/dashboard_demo_relay.py" \
  --container musicbot-webtest-r7-demo --port 18080
~~~

Keep the relay running and use a Windows tunnel:
ssh -N -L 127.0.0.1:18080:127.0.0.1:18080 -o ExitOnForwardFailure=yes your-vps
Then open http://127.0.0.1:18080/. network none containers require the existing
loopback relay; port publishing alone does not provide networking to them.

Fake Owner: favorite a song; create, rename, reorder, remove and enqueue tracks
from My Playlists; inspect owner-only management, search/page/add/remove the fake
autoplaylist, add current song, and confirm permission old/new values. Fake member:
management is hidden, private library differs, and playlist enqueue is denied until
Owner enables AllowPlaylists in the temporary Default group. Away/denied users
exercise voice/command denial. Switch guilds, logout, reconnect and inspect that
private views clear. DevTools offline mode exercises the offline page; reconnect
and refresh verifies the update prompt and normal login. Unit/VM tests simulate
fetch events and explicitly assert every excluded route bypasses respondWith.

The demo uses TemporaryDirectory for its private libraries, native AutoPlaylist,
fake permissions.ini and backups, with cleanup on app shutdown. It uses fake login,
fake extraction/lyrics/local art only; no real config/data, credentials or outbound
connections. All test containers have --network none and musicbot-webtest-* names.
Stop relay/tunnel, then clean only the named resources:

~~~sh
docker stop musicbot-webtest-r7-demo
docker image rm musicbot-webtest-r7:demo
case "$ctx" in /tmp/musicbot-webtest-r7.*) rm -rf -- "$ctx";; esac
~~~

Live Discord/OAuth, real-phone installation and production proxy behavior remain
unverified until a separately authorized deployment. Nothing in this procedure
changes dev, the production working tree/config/data, services or existing images.

## Round 8: keyboard shortcuts (development only)

Desktop shortcuts use the same enabled controls and click handlers as the page.
There is no separate skip path: N retains the existing skip/vote behavior.

| Key | Action |
| --- | --- |
| Space | Pause / resume |
| N | Skip / vote to skip |
| Left / Right | Seek -10 / +10 seconds, clamped to track bounds |
| / | Focus the request input (opens the playback view) |
| ? | Open keyboard help |
| Esc | Close help / cancel queue dragging |

Input, select, textarea, editable elements, menus and any open dialog suspend
shortcuts. Ctrl/Alt/Meta, composition and held-key repeats are ignored. Help can
also be closed with its button; its entry is hidden on phone/touch layouts.
No current playing/paused track, missing permission or disabled control means no
keyboard request is sent. Seeking retains the observed track token.

Existing state/SSE now includes only the viewer's four boolean capabilities
(pause, resume, skip, seek), using existing command, voice and channel checks.
These are display hints; every mutation still performs its original authorization.
No new endpoints, identity fields or other users' permissions are exposed.
The offline demo supports the same keys; fake away/denied users show disabled controls.

### Queue search

Search beside the queue heading filters titles and requester display names as you
type (case-insensitive). It combines with All / My requests and shows a match count.
Filtering never changes the queue or its numbering: up/down/delete still send the
complete-queue position and observed revision. Any search or My requests disables
dragging and shuffle, with a visible reason. Clear the search and choose All to
restore them. Switching guilds or signing out clears the search.
The demo's title/requester data can exercise both filters together.

### Empty queue: recent recommendations

Only an actually empty complete queue shows up to five recent tracks inside the
queue card. The client deduplicates source URLs (including YouTube video IDs),
skips the current track and unusable sources, and keeps newest-first order.
No history means no recommendation section; filtering to zero results does not
activate it. Add follows the existing request/resolve/preview/confirm flow, using
the caller's current permissions, rate/length/queue limits and existing APIs.

The offline demo has links above the request input: 示範空佇列 empties only fake
queues and pauses its automatic queue changes; 還原示範佇列 restores them. Choose
the empty example, inspect five distinct recommendations and click Add, then
confirm the normal preview. These demo-only switches make no outbound requests.

### Duplicate reminders

Track previews show a reminder beside confirmation when the source is already at
complete-queue position N, currently playing, or both. Playlist selection rows mark
queued tracks 已在佇列 (or 正在播放); allowed items stay checked. Warnings update
with received state without rebuilding the preview or changing selections. Users
can still confirm duplicates; this is advisory, not a new playback restriction.

Comparison stays in the browser and uses only existing current/queue/preview URLs.
YouTube watch, youtu.be, mobile/music, shorts, embed, live and nocookie forms compare
by case-sensitive 11-character video ID, ignoring playlist/time/share parameters.
Other HTTP(S) URLs normalize scheme/host/default port, trailing slash, fragment,
query order and common tracking parameters (utm_*, fbclid, gclid); meaningful query
values and path case remain distinct. Redirects, alternate non-YouTube source URLs
and the same recording uploaded under different IDs cannot be identified offline.

In the offline demo, 重複單曲範例 / 重複歌單範例 restore fake queues and fill the
request input; click 查詢 to inspect reminders and confirm normally. Manual empty/
filled examples keep automatic queue changes paused; 自動更新示範 resumes them.
All art, extraction, login, lyrics and example URLs remain local/fake.

### Round-8 isolated validation and demo

Run from the round-8 worktree. Archive only committed files; use a fresh tag:

~~~sh
ctx=$(mktemp -d /tmp/musicbot-webtest-r8.XXXXXX)
git archive HEAD | tar -x -C "$ctx"
printf '%s\n' 'FROM musicbot:ytdlp-base' 'WORKDIR /webtest' 'COPY . .' |
  docker build --network none -t musicbot-webtest-r8:final -f - "$ctx"
docker run --rm --network none --name musicbot-webtest-r8-unit \
  --entrypoint python3 musicbot-webtest-r8:final \
  -W 'error::DeprecationWarning:aiohttp.web_protocol' \
  -m unittest discover -s tests -p 'test_web_dashboard*.py'
docker run --rm --network none --name musicbot-webtest-r8-links \
  --entrypoint python3 musicbot-webtest-r8:final -m tools.test_compound_link
node --check musicbot/web/dashboard.js
node --test tests/test_web_dashboard_frontend.cjs tests/test_web_dashboard_pwa.cjs
docker run --rm -d --network none --name musicbot-webtest-r8-demo \
  --entrypoint python3 musicbot-webtest-r8:final \
  -m tools.dashboard_demo --host 0.0.0.0 --port 8080 \
  --public-origin http://127.0.0.1:18080
python3 tools/dashboard_demo_relay.py --container musicbot-webtest-r8-demo --port 18080
~~~

Use the existing loopback relay and the Windows tunnel documented above (your-vps).
No bridge, production mounts or credentials. Check desktop keys and help; search by
title/requester together with My requests; switch to empty recommendations; use
the two duplicate examples, then confirm a duplicate single/batch normally. Fake
away/denied users exercise voice/command restrictions. Browser/mobile tests use
only the demo. All new controls use existing reduced-motion rules and touch sizes.

After stopping the relay/tunnel, stop only musicbot-webtest-r8-demo and remove only
the new musicbot-webtest-r8:final tag and the specific /tmp/musicbot-webtest-r8.*
context. The main checkout, dev, existing tags, configuration and data stay untouched.

Round-8 validation (no deployment): backend 311 passed (original 306 + 5),
frontend 117 passed (original 101 + 16), compound links 16 passed, zero failures.
Node syntax checks and git diff --check passed. Chrome's credential-free demo
verified question-mark/Esc help, slash focus with N typed into input, Space pause,
+10-second seek, combined filters retaining positions 1/3, recommendation preview
then confirmation, duplicate position 1, and four batch duplicate tags with all
21 eligible items still checked. At width 390 the help entry was hidden and the
document had no horizontal overflow; denied-user pause/skip/seek stayed disabled.
Real Discord/OAuth, production proxy playback and physical-phone gestures were
not exercised. URL matching is advisory and does not resolve remote redirects.

## Round 9: feedback, public sources, popularity and Liquid Glass

Development only. This round does not deploy, push, change dev, read operational
credentials, or modify production configuration/data/services.

### Navigation, seek and recent playback

The complete brand uses one centered flex group with separate icon/text spans.
On phones it spans the navigation row. Navigation uses fixed-height, nonwrapping
grid buttons; a loading page retains its label instead of widening it with a
spinner. The document reserves its vertical scrollbar gutter, so switching
between the longer playback page and the shorter library does not change width.

Dashboard seek rounds nonnegative seconds half-up before the native command.
Both Discord feedback and shared activity use `跳轉：83 秒` for 83.456 or 82.5.
Out-of-range/NaN/infinite values and stale-track requests remain rejected.
Native Discord seek arguments retain their existing behavior.

Recent-history duplication came from observing every native audio-source play:
seek reinserts the same entry and emits play again; reconnect can restart or
reconstruct it. The dashboard observer executes before the native now-playing
message's reconnect suppression. Each entry now carries a runtime-only observer
marker, and consecutive same-URL events within 10 seconds are suppressed too.
Pause/resume emits resume rather than play; it was not the cause. Loaded guild
history already deduplicates fallback URLs. History stays bounded to 50 entries
and in memory; neither marker is added to serialized queue data.

GET /api/guilds adds only `recommended_guild_id: string | null`. It considers
only this viewer's visible guilds: same bot voice channel, then their own most
recent entry-added request from either Discord or web. Auto entries do not count.
The browser uses explicit `?guild=ID` (also `guild_id`), then the recommendation,
then its previous localStorage selection, then the first visible guild.
Storage reads/writes are guarded for private browsing. An explicit server also
survives the login redirect through a sessionStorage intent, consumed after the
first validated selection; the current page retains that entry preference.
Manual selection remains
in effect across reconnection in that page. The backend's bounded requester
preference cache is runtime only and resets on restart; it is never returned.

### Public Spotify / YouTube Music import (phase one)

My Playlists -> From Link -> Preview -> Import creates a new private playlist.
No account login or new application keys/settings are added. Spotify availability
comes from the running bot's existing spotify_enabled/provider object. Disabled
Spotify displays `目前無法讀取 Spotify 歌單` and disables the selector option.
The backend independently returns 503 if unavailable.

Allowed HTTP(S) input hosts are exactly open.spotify.com, youtube.com,
www.youtube.com, m.youtube.com, music.youtube.com and youtu.be. Credentials,
unexpected ports, control/space characters, lookalike domains and unsupported
paths are rejected. spotify.link is unsupported. Spotify accepts public albums
and playlists, including intl-prefixed links. YouTube inputs must contain one
playlist ID. YouTube Music is canonicalized to the equivalent YouTube playlist,
so an attached video cannot cause a compound-link prompt during import.

Spotify reads through the existing Spotify.get_album/get_playlist and bounded,
API_BASE-checked pagination. Tracks retain Spotify track URLs, artist-name
titles and duration seconds. YouTube uses the existing downloader/yt-dlp engine with
download=False/process=False and flat-in-playlist metadata. Its opt-in public_only
branch uses a fresh fixed-options client and the existing executor, with no
cookies, browser cookies, netrc, cache or ordinary authenticated headers. It
consumes at most 201 lazy entries inside the executor (200 plus overflow), then
returns directly without the normal authenticated extraction tail. WL, LL and LM
account-relative aliases are rejected before extraction; nonpublic availability
metadata is also rejected. Other native downloader calls never enter this branch.
Import reads metadata, never downloads media or adds queue entries.
Each source is capped to its first 200 entries; private/deleted/local/unsupported
entries are skipped. The preview states total count, usable import count, first
five tracks and an explicit truncation warning. A user's custom-list cap remains
20, plus favorites; no list exceeds 200 tracks.

Enqueue still uses the existing cmd_play/_cmd_play path and fresh permissions,
extractor/blocklist/duration/queue limits. A narrow compatibility check accepts
the existing Spotify downloader's flattened single-video search residue:
one nonnested child, parent type video and matching extractor; both parent and
child restrictions are checked. True playlists, multiple or nested children
remain rejected. No downloader, Spotify or native command mutation is used.

Imported records stay in
`data/web_dashboard/user_playlists/<server-session-user>.json`.
Version-1 library JSON remains compatible. Each imported playlist adds
`source_url` (canonical public URL) and `source_type` (spotify or youtube).
Tracks retain {title,url,duration,added_at}. Per-user locks, revision checks,
sibling temp files, fsync and atomic replacement are reused.
Resync fetches a preview and compares URL multisets, including duplicate tracks;
confirmation shows added/removed counts before replacing tracks. A source order,
title or duration update is still applied when the counts are both zero.
Manual edits to imported playlists are replaced on the next confirmed resync.

All new routes require the existing session, readiness, member/blocklist,
X-MusicBot-Dashboard: 1 and same-origin guards. Preview requires target-guild
membership; confirm rechecks source-guild membership after provider awaits and
inside the user storage lock. Tokens bind user, source, guild, target playlist,
revision and expiry, and are consumed on success. No client user ID/path is used.

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | /api/library/sources | none | {spotify,youtube,spotify_message} |
| GET | /api/library | existing | existing private library plus sources:{spotify,youtube} |
| POST | /api/guilds/{guild}/library/import/preview | {url} | preview below |
| POST | /api/library/import | {preview_id,revision,name} | updated private library, owner capability, message |
| POST | /api/guilds/{guild}/library/{playlist}/sync/preview | {revision} | preview with diff:{added,removed} |
| POST | /api/library/{playlist}/sync | {preview_id,revision} | updated private library, owner capability, message |

Preview fields: preview_id, revision, title, source_url, source_type, count,
import_count, tracks (first five), truncated, warning, diff (null for import),
expires_in. Confirm imports the validated server-side snapshot, not client tracks.
Resolve and source previews share the existing per-person 12/minute budget,
20-second timeout, per-guild active slot and global two-job cap. A timed-out
underlying extraction retains its slot until completion. Other playback controls
remain usable. Errors are safe Traditional Chinese: invalid 400, not allowed 403,
missing source 404, stale 409, busy/limited 429, provider failure 502,
Spotify unavailable 503, timeout 504.

Future private playlists / liked songs require a Spotify OAuth app, consent
scopes, secure per-user refresh-token storage and revocation handling. Private
YouTube data requires a Google OAuth app/consent/scopes and corresponding token
handling. Neither integration nor any user token storage is part of this round.

### Server popular requests

GET /api/guilds/{guild}/popular?period=7|30|all returns
{period,tracks:[{url,title,duration,count}]}, ranked by count, at most 20.
The default is 7; all means the retained 180 days. Live target-guild membership
is checked before and after the async read. Invalid periods return 400, storage
failures 503, inaccessible guilds follow existing member errors. Responses
contain no requester IDs/names, role IDs, filesystem paths or raw exceptions.

The native entry-added hook records each member-request entry once. Discord
text/slash commands and web requests share that event; every distinct batch entry
counts, including two intentional requests for the same song. Auto entries,
authorless entries and bot-authored entries are excluded. Resume, seek, queue
moves and repeated observer calls do not count. The hook is independently wrapped
in try/except and does not change queue mutation or normal serialization.

Storage: `data/web_dashboard/stats/<server-generated-guild-id>.json`.
No supplied filename is accepted. Schema:

~~~json
{"version":1,"tracks":{"https://www.youtube.com/watch?v=AbCdEfGhI01":{
  "url":"https://www.youtube.com/watch?v=AbCdEfGhI01",
  "title":"Example song","duration":180,
  "days":{"2026-10-17":3}
}}}
~~~

YouTube variants normalize by video ID; other public HTTP(S) URLs drop fragments
and common tracking parameters. Only media metadata and daily counts persist.
UTC dates retain today plus 179 previous days. Reads/records prune expired dates.
Each guild has its own asyncio lock/cache. Dirty buffers flush every 30 seconds
and during app cleanup; filesystem loading and atomic temp/fsync/replace writes
run in worker threads. Corrupt documents are preserved at
`.json.corrupt-<unique-time>` before starting a fresh document; existing recovery
copies are never overwritten. Failed writes retain dirty buffers for retry.
An abrupt process/host failure can lose counts since the last successful flush.

The Popular tab offers 7/30/all, rank/title/count/duration, Add and Save to
Playlist. Add reuses the normal resolve/preview/confirm path and permissions.
Server changes/signout invalidate outstanding popularity results and buttons.

### Discord enqueue notifications

Web single-track and playnext requests retain the native Response; only the
web-source note and logged-in display author are attached. The native command
title, translated templates, queue position/ETA, embed/text choice and
safe_send_message auto-delete behavior are shared with Discord commands.
Batch selections and saved playlists send one native playlist-format summary
using the first successful native response's position/ETA; retries do not resend.
There is no parallel custom enqueue notification.

channel_for keeps request/current-entry text channel priority, then allowed bound
and system/text channels; voice chat is last. Existing bound-channel, viewer and
bot send/view permissions are rechecked before sending. A failed notification
does not undo a successful enqueue or cause a duplicate request.

bot.py extracts only its existing two enqueue templates into a pure
build_play_response formatter; validation, queue insertion and ETA calculation
stay native. Runtime queue_position_text metadata is ignored by Discord.
Its other new block is the guarded entry-added popularity observer.
playlist.py and spotify.py are unchanged. downloader.py adds only the opt-in
credential-free public metadata branch; ordinary extraction, Spotify conversion,
header probing and playback use their existing path without changed options.

### Liquid Glass and accessibility

Large panels, sidebar, playback bar, dialogs and toasts use translucent surfaces,
blur+saturate with the WebKit prefix, bright top rims, soft shadows and round
corners. A fixed colorful radial-gradient wallpaper makes transparency visible.
System light/dark themes share contrast-safe text tokens. Static tests verify
normal/muted/accent text at AA against conservative wallpaper compositions;
primary button text also passes AA. No deleted decorative slogan is restored.

Unsupported backdrop-filter and prefers-reduced-transparency use opaque surfaces.
Existing prefers-reduced-motion disables animation/transitions. Phone cards do
not each blur; the sidebar/playback bar and temporary dialog/toast are the few
blurred surfaces. Queue rows never use backdrop blur. Static cache/version
references advance together; current round-9 assets use r9-7, including popular.js.

### Offline verification and demo

Use a fresh archive/context and only newly named test resources:

~~~sh
ctx=$(mktemp -d /tmp/musicbot-webtest-r9-demo.XXXXXX)
git archive feature/dashboard-round9 | tar -x -C "$ctx"
printf 'FROM musicbot:ytdlp-base\nWORKDIR /webtest\nCOPY . .\n' > "$ctx/Dockerfile.webtest"
docker build --network none -t musicbot-webtest-r9:demo -f "$ctx/Dockerfile.webtest" "$ctx"
docker run --rm --network none --name musicbot-webtest-r9-unit --entrypoint python3 musicbot-webtest-r9:demo -W error::DeprecationWarning:aiohttp.web_protocol -m unittest discover -s tests -p 'test_web_dashboard*.py'
docker run --rm --network none --name musicbot-webtest-r9-links --entrypoint python3 musicbot-webtest-r9:demo -m tools.test_compound_link
node --test tests/test_web_dashboard*.cjs
docker run --rm -d --network none --name musicbot-webtest-r9-demo --entrypoint python3 musicbot-webtest-r9:demo -m tools.dashboard_demo --host 0.0.0.0 --port 8080 --public-origin http://127.0.0.1:18090 --fake-login owner
python3 tools/dashboard_demo_relay.py --container musicbot-webtest-r9-demo --port 18090
~~~

Use a loopback tunnel `ssh -N -L 18090:127.0.0.1:18090 your-vps`.
Open http://127.0.0.1:18090/?demo-queue=filled. Compare desktop/phone brand and
switch Play/My Playlists several times while loading. System light/dark and
reduced transparency/motion exercise the glass alternatives. Popular contains
five fake tracks and different dated counts; try periods, Add and Save.
Spotify/YTM import examples (never contacted by this executable):
`https://open.spotify.com/playlist/DemoRound9`,
`https://music.youtube.com/playlist?list=DemoRound9`;
`DemoLarge` previews 205 source tracks, capped to 200. A second fetch from the
same fake source changes content to demonstrate +2/-1 resync confirmation.
Seek 83.456 in a test request demonstrates integer feedback.
`docker logs musicbot-webtest-r9-demo` includes fake Discord response objects
and channel names for seek, single, playnext and batch enqueue.

The demo uses TemporaryDirectory for all libraries, statistics, fake permissions,
autoplaylist and backups. It never initializes a Discord client or reads real
config/data; art, lyrics, login and both import providers remain fake/local.
Containers have --network none; the relay reaches only the demo loopback.
Stop only the named demo/relay/tunnel, remove only new musicbot-webtest-r9 tags,
and delete only the resolved /tmp/musicbot-webtest-r9-demo.* context afterward.
Screenshots/evidence can be preserved separately under /tmp/musicbot-webtest-shots/.
