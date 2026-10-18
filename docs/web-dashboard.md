# Web dashboard

For a new Docker installation, follow [Install MusicBot](install.md) or
[繁體中文安裝](install.zh-TW.md). Language and time-zone configuration is documented
in [Dashboard languages](dashboard-languages.md). The sections below describe
the dashboard API and existing features.

The optional aiohttp dashboard runs inside the bot event loop. Discord mode
authenticates members individually and keeps existing permission and voice-channel
checks. The new Docker installer starts the login page before Discord connects;
protected APIs remain unavailable until the bot is ready. Owner mode remains
available for existing installations with external authentication.

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
SharedSecret =
~~~

PublicURL is an absolute root origin, without credentials, path, query or fragment.
A trailing slash is accepted. HTTPS is required except for local loopback demos.
A blank DiscordClientID uses the bot's application_id, cached application ID,
or bot user ID. DiscordClientSecret is required; it is not the bot token.
Logins persist across restarts with a fixed 30-day inactivity window.
Legacy SessionSecret/SessionHours may remain in existing configuration; the new
opaque-session mechanism does not use either to sign tokens or shorten/extend
the 30-day lifetime (legacy duration syntax is still validated).
SharedSecret remains optional Bearer protection only in owner mode.

Missing/disabled configuration does not start a listener. Invalid or incomplete
enabled Discord configuration **does not start the dashboard**, logs only the
exception type, and lets MusicBot continue normally. This includes missing public
origin/client secret/application ID or invalid session duration. Read once after
the first successful on_ready; changing settings needs a separately approved
deployment/restart. close/logout/run_musicbot-finally clean up the listener,
in-memory session cache and resolver tasks; persisted sessions remain valid.

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

Session cookies contain 32 random bytes encoded as an opaque URL-safe token.
Only SHA-256(token), minimal profile (ID/name/avatar), creation time, last renewal
and expiry are persisted in data/web_dashboard/sessions/sessions.json. Writes use
a 0600 temporary sibling, flush/fsync and atomic replacement; the directory is
created 0700. No raw token, OAuth access/refresh token or authorization code is
stored. No signing/encryption key is needed; SessionSecret is unused.

Cookies have Max-Age=2592000 (30 days), HttpOnly, SameSite=Lax, Path=/, no Domain;
HTTPS retains Secure and __Host- names. A successful same-origin request renews
server expiry and cookie at most once per rolling day. The maximum inactivity is
30 days after the last persisted renewal. Active browser pages also check the
session daily, including when using a long-lived SSE stream. No per-request disk
write. Startup and daily cleanup remove expired records; max 10 sessions/person
(evict oldest) and max 1024 globally. Missing/corrupt files start with no sessions.
Each use checks bot-cached membership and blocklist; removal/blocking revokes the
session, and protected operations continue checking the target guild/permissions.

POST /auth/logout revokes the current server record immediately and clears
cookies/pending OAuth state. POST /auth/logout-all revokes every session for the
authenticated user (other users remain signed in), then clears this browser's
cookies. Both accept an empty JSON object and return {message}, require a live
Discord session, X-MusicBot-Dashboard: 1 and the existing host/origin checks.
Owner mode returns 404, unauthenticated 401, bad CSRF/origin 403, wrong method 405.
GET never logs out. POST /auth/logout-all is available in the account menu.

To force everyone to sign in again: stop the dashboard/bot through your normal
maintenance procedure, delete only data/web_dashboard/sessions/sessions.json,
then restart. Do not edit configuration or OAuth credentials. Deleting the file
while a process is running does not revoke its in-memory sessions; restart is
required. Deletion discards only login state, not playlists or settings.

Pending states and sessions are capped at 1024 each; expired records are removed
at startup, daily and during session validation. Login admission is capped at 60 per minute
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
Microsoft JhengHei, system-ui. Round 12c uses a plain solid page background (no wallpaper). No refraction filter or pointer spotlight. The playback bar is solid
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
five tracks and an explicit truncation warning. If a bounded source omits its total,
count_is_minimum labels the count as at least that many, rather than an exact total. A user's custom-list cap remains
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
import_count, tracks (first five), count_is_minimum, truncated, warning, diff (null for import),
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
corners. Round 12c: the page is a plain solid colour; transparency comes from content scrolling under the floating layers.
System light/dark themes share contrast-safe text tokens. Static tests verify
normal/muted/accent text at AA against conservative wallpaper compositions;
primary button text also passes AA. No deleted decorative slogan is restored.

Unsupported backdrop-filter and prefers-reduced-transparency use opaque surfaces.
Existing prefers-reduced-motion disables animation/transitions. Phone cards do
not each blur; the sidebar/playback bar and temporary dialog/toast are the few
blurred surfaces. Queue rows never use backdrop blur. Static cache/version
references advance together; current round-9 assets use r9-8, including popular.js.

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

## Round 10: Spotify button

GET /api/guilds/{guild_id}/spotify is read-only, with the existing session,
membership/blocklist, custom-header and origin checks; no voice requirement.
It returns {url, mode: "track" | "search", query, track_token}. No request body.
It uses the current entry's Spotify URL when present, otherwise the existing
Spotify client searches one track. Cleaned artist/title, conservative similarity
thresholds and a 12-second duration tolerance gate direct links; uncertain,
unconfigured, timed-out or failed lookups return an encoded Spotify search URL.
The timeout is eight seconds, cache TTL one hour (256 entries), failure cooldown
30 seconds and per-member admission 12 requests/minute. Provider errors stay internal.
The frontend prefetches on track changes and enables the actual link only after
the result arrives, so normal target=_blank navigation avoids blocked popups.
Late results for old tracks/guilds are discarded. The demo provider always
returns a fake Spotify track without making any outbound request.

## Round 10: read-only maintenance

GET /api/guilds/{guild_id}/admin/maintenance requires OwnerID himself and guild
membership, with the standard session/header/origin/blocklist checks. No body
and no write action. Returns cookie metadata, loaded versions, optional sanitized
host status, process started_at, last_stop {time, classification}, SW version,
and viewer count (unique members seen by guild APIs/SSE in the last 45 seconds).
Disk inspection is off the event loop and cached 15 seconds; live identity is
rechecked after waiting. No cookie values, raw log text, paths or IDs are returned.

Cookie parsing opens the container's data/cookies.txt read-only, bounds its
size to 4 MiB and memory-maps separators; only expiry and name column slices are
decoded. The value column is never materialized as a field/line, persisted or
logged. The earliest positive expiry among known login-cookie names is shown
with file mtime; within seven days (including expired) warns. Session-only
cookies have no known expiry. A missing file says 未使用 cookie.
Last stop selects logs/musicbot.ended-*.log, examines at most 16 KiB/40 tail
lines internally, classifies explicit clean-shutdown markers versus failure or
uncertain endings, and returns only UTC mtime and 正常/異常. mtime avoids the
legacy rotation filename's month/minute formatting ambiguity. No ended file
means no last-stop record; this is an inference, not a process-exit database.

The host may optionally supply data/web_dashboard/host_status.json, max 32 KiB:
~~~json
{
  "written_at": "2026-10-17T06:00:00Z",
  "ytdlp_update": {
    "updated": "2026-10-17T04:30:00Z",
    "channel": "stable",
    "yt-dlp": "2026.10.14",
    "yt-dlp-ejs": "0.3.1",
    "bgutil-plugin": "1.2.2"
  },
  "cookie_sync": {
    "last_run": "2026-10-17T03:58:00Z",
    "next_run": "2026-10-18T03:58:00Z",
    "result": "success"
  }
}
~~~
Use timezone-aware ISO timestamps; channel is stable/nightly; result is
success/failure/running. Unknown fields are discarded, invalid fields become
null/unknown. Missing host file hides that section; malformed/oversize data shows
a read-only unavailable state. The dashboard creates no host script or timer.
The demo uses a self-generated fake cookie in TemporaryDirectory, never the
real config/data/logs. Test fixtures also create only temporary fake files.

## Round 10: per-guild empty-queue behavior / radio

GET and POST /api/guilds/{guild_id}/admin/empty-queue are OwnerID-only,
with existing session/member/blocklist/header/origin checks. GET returns:
~~~json
{"empty_queue":"autoplaylist","radio_min_seconds":0,"radio_max_seconds":0,
 "radio_failures":0,"radio_suspended_seconds":0}
~~~
POST takes exactly the first three fields. empty_queue is autoplaylist (default),
radio or off. Seconds are integers >= 0, max 31536000; max=0 means unlimited,
otherwise min <= max. Writes use the shared fsync+atomic-replace helper and a
store lock at data/web_dashboard/settings/{guild_id}.json, preserving existing
ownership/mode. Missing or invalid files use the legacy autoplaylist default;
corrupt files are not overwritten by reads. Responses contain no server/user IDs.

The native bot's on_player_finished_playing wrapper loads the policy and
delegates to the original body (now _on_player_finished_playing). Default mode
uses that original path with no radio fetch and no change to AutoPlaylist flags.
For radio/off only, a per-guild lock covers the entire finished event, radio lookup,
original fallback and play scheduling. Concurrent finished events are coalesced.
The actual fill hook is directly before the original empty-queue/autoplay block.
All observation/lookup hooks have try/except; unexpected failures allow the old
path. off skips automatic filling, without changing the global AutoPlaylist flag
or preventing manually requested songs. Radio works even when the global list
is disabled; fallback still respects the original global switch.

Playback-start observation retains the most recent 50 played URLs and the last
YouTube seed in memory, independently of browser polling/dashboard enablement.
Repeated seek events for the same entry do not add history. Radio asks the
existing credential-free flat playlist extractor for
https://www.youtube.com/watch?v=<ID>&list=RD<ID>, timeout 20 seconds. Up to 200
flat candidates are considered; add up to three known, positive-duration
YouTube tracks outside the recent 50 and within the server's radio min/max,
checking the native blocklist against title and canonical URL. Native autoplay
has no duration range of its own: both new radio limits default to 0 (no extra
bound), and the Owner may set them per server without changing native lists.
Live/unknown durations are skipped. Policy/voice/user queue are checked again
after extraction; a user request or off policy takes precedence.

Entries have author=None/channel=None (native autoplay semantics), plus a radio
metadata marker. The dashboard shows 電台 in current/queue/history; popularity
ignores these entries. No available tracks, no seed or provider error logs a
generic fallback warning and uses the old AutoPlaylist path. Partial success
does not also fill from that list. Three consecutive failures pause radio for
600 seconds, using native fallback during cooldown; a new attempt after cooldown
may recover. State/history/cooldown reset on restart; policy persists on disk.

Offline tests cover default/off, native fallback, the shared fallback lock,
recent-50 boundary, blocklist/length filters, stats exclusion, timeout and
three-failure cooldown, using only mock YouTube Mixes. The browser demo stores
policy only in its TemporaryDirectory.

## Remaining round-10 changes and API compatibility

* Seek: cmd_seek temporarily requeues the current entry and restarts its audio
  source. Previously the dashboard exposed that entry as an additional queued
  song and combined the old frame counter with its new start offset; repeat
  modes could requeue it twice. A pending transition now supplies the true
  position/paused state and excludes that technical requeue from visible queue
  and ETA calculations. Resume reinstates normal frame counting. Discord and
  web seek share this fix; command arguments/responses otherwise stay native.
* Source titles: queue/current/bar/history/popular/library titles link to safe
  http/https sources with target=_blank and noopener noreferrer. YouTube variants
  use the canonical watch URL. Handles remain separate, and drag/settling clicks
  suppress navigation. Title style is retained with hover/focus underline.
* Favorites: normalized identity (YouTube video ID) drives filled-heart,
  aria-pressed/title state, reduced-motion animation and request disabling.
  POST /api/library/favorites/tracks still accepts {revision, track}; an existing
  song returns 200 with message 已在收藏中 and does not append.
  PATCH /api/library/favorites adds {revision, action:"remove_url", url} and
  returns the updated private collection with 已取消收藏. Only the session's own
  library is touched. Existing duplicates remain readable and are deduped under
  the existing atomic transaction lock at the next write.
* Preview expiry: POST /play or /playnext with the existing {query, preview_id}
  (plus selected_items for batches) renews only on confirmation, using saved
  original input. Same canonical URLs are matched, never replaced by a different
  search hit. Missing singles return 409 with safe new results; batches report
  added/skipped and recheck all permissions/limits. Renewal is charged to the
  existing per-person rate limit. Provenance is retained up to one hour in
  bounded memory; older previews or a restart still require a fresh search.
* Undo: DELETE /queue/{position} adds undo_token, undo_expires_in:10 and
  removed_title to its ordinary message/state response. POST /queue/undo accepts
  only {undo_token}; live same-voice membership, remove/play permissions,
  requester/user limits and blocklists are rechecked. The server-owned exact
  entry is reinserted at its previous index (or end), preserving the original
  requester. Tokens are actor/guild-bound, single-use, latest-only, expire after
  ten seconds and are deleted on cleanup. Existing current/queued identity
  blocks duplicate restore. Removal/undo each create an activity record.
  The passive toast overlay enables pointer events on its action button.
* Mobile: volume lives inside the current-track card below the progress row;
  the <=640px bottom bar omits its volume row. Desktop volume stays in the bar.
  Queue/seek/volume gestures temporarily disable selection/callouts and clear
  on completion/cancel/Esc/blur; ordinary title copying remains available.
  Pause/resume/skip show text only. Seek/drag guidance is screen-reader-only;
  the timezone sentence is removed. The sidebar says 連線狀態, with color/dot
  and a state tooltip.
* Web Discord notifications always use plain content, no embed, with a small
  -# display-name source line and native play/playlist body. Mentions are disabled.
  Native Discord response configuration is unchanged.
* Homepage playlist URLs share the normal selectable preview and batch-queue
  path. The second action saves the selected source tracks as a new private
  playlist via the existing import API, retaining source URL/name for resync.
  The separate library import form/provider picker is removed; its hint focuses
  the homepage input. Existing source-resync controls remain.
* Spotify playlist reads try the existing API, then the public embed JSON:
  ten-second timeout, three-MiB bound, no redirects and Spotify host validation.
  The fallback is shared with Discord get_playlist; API success is unchanged,
  and failed fallback rethrows an existing API error when one exists.
  Missing data gives a sanitized Chinese dashboard error. Albums/tracks retain
  their existing API methods. Embed previews are explicitly marked partial.

### Round-10 offline verification

Use only a tracked-source archive or an isolated context, with no production
mounts/configuration. Example from the feature worktree before it is removed:
~~~sh
ctx=$(mktemp -d /tmp/musicbot-webtest-r10.XXXXXX)
git archive feature/dashboard-round10 | tar -x -C "$ctx"
printf 'FROM musicbot:ytdlp-base\nWORKDIR /webtest\nCOPY . .\n' > "$ctx/Dockerfile.webtest"
docker build --network none -t musicbot-webtest-r10:check -f "$ctx/Dockerfile.webtest" "$ctx"
docker run --rm --network none --name musicbot-webtest-r10-unit --entrypoint python3 musicbot-webtest-r10:check -W error::DeprecationWarning:aiohttp.web_protocol -m unittest discover -s tests -p 'test_web_dashboard*.py'
docker run --rm --network none --name musicbot-webtest-r10-links --entrypoint python3 musicbot-webtest-r10:check -m tools.test_compound_link
node --test tests/test_web_dashboard*.cjs
~~~
Final suites: 424 backend tests, 139 frontend tests, 16 compound-link cases;
all pass. The original 377/131/16 coverage is retained with fixtures updated for
deduplication, renewed previews, public imports and nonmentioning notifications.
Seven browser smoke checks passed through the loopback relay in desktop Chrome
and at 390px: fake Spotify href, title link attributes, favorite toggle, paused
forward/back seek, deletion/undo, owner metadata/radio form, compact mobile
volume/hidden helper text/no horizontal overflow. No screenshots, page errors
or external requests. The demo uses no real credentials or config/data files.

Run the same --network none demo/relay pattern as round nine, using round-ten
resource names. In the fake Owner session pause then seek to 100 and back to
20 seconds to compare the first queue ETA, click the song title's source link,
toggle the heart twice and observe its count in favorites, and inspect the
fake Spotify track href. Owner management shows the fake cookie warning and
radio controls. All demo storage is inside TemporaryDirectory.


## Round 11: Spotify selected tracks
The dashboard's confirmed-selection boundary accepts the existing downloader's
flattened single-result YouTube search shape (including flat `_type=url`).
It requires exactly one non-nested child with the same YouTube extractor, video
identity and source URL. Genuine playlists remain rejected. Native Discord
commands, Spotify lookup/search and queue permissions are unchanged.
Offline regression uses the real Downloader flattening method and cmd_play,
including expired preview renewal, save, resync and saved-playlist playback.


Spotify images: public embed track coverArt/image falls back to entity
coverArt.sources or visualIdentity.image. API tracks use album.images then
playlist/album images. Persist the optional thumbnail with personal playlists.
Only HTTPS i.scdn.co and mosaic.scdn.co Spotify image hosts are accepted.
CSP also lists the existing YouTube/Discord image hosts explicitly. Missing or
failed images use the existing placeholder; no provider image is fetched by the
demo (same-origin fabricated SVGs).


## Round 11: watch links and mixes
A video+playlist link now opens one playlist preview, marks the URL's video,
and defaults to selecting every allowed track for stable PL/OLAK/YouTube Music
playlists. Dynamic RD/RDMM/RDAMVM mixes preserve the watch URL: converting it
to /playlist caused yt-dlp's "This playlist type is unviewable" exception.
The credential-free public extractor is bounded to 25 items and 8 seconds;
the independently resolved seed (5 seconds, then canonical metadata fallback)
is first, deduplicated, and is the sole default selection. Extraction failures
leave a usable single-item preview. RDCLAK is treated as a stable source when
its normal playlist extraction succeeds; failure degrades to the seed.
Saving a dynamic mix saves selected tracks without source metadata, so sync
is unavailable. Successful RDCLAK sources remain syncable.
Resolve entries add is_requested/default_selected; results add is_mix/saveable.
No new endpoint or permission bypass. Downloader's new public_limit is used
only by the existing credential-free dashboard path; Discord extraction is unchanged.


## Round 11: personal playlist layout
Desktop: collection choices (name/count/source) on the left and selected contents
on the right. Tablet: choices above contents. Phone: list -> selected contents ->
return. Favorites and custom playlists share the same cover/title/duration/delete
rows; long titles truncate. Collection actions use Play All / selected enqueue and
a More menu for whole-list enqueue, rename, source sync and confirmed deletion.
Play All retains native enqueue/start behavior and never clears the current queue.
Creation is collapsed; source URL and rename fields no longer consume the main
song area. Source sync only appears for stable imported sources.
Demo includes an empty Favorites list, long titles, unknown duration, custom and
Spotify-source collections; all artwork is fabricated and same-origin.


## Round 12: one-level player
The persistent player contains artwork, title/requester, favorite toggle,
pause/resume, skip, repeat, seek, volume and the reserved lyrics toggle.
No player dialog, expansion, transport reparenting or swipe-to-close exists.
Click its title for two pre-resolved native links (YouTube/source and Spotify).
Escape, outside click and focus departure dismiss this small choice;
Escape and link activation restore title focus. Other song titles retain links.
The web UI no longer offers any add-to-autoplaylist entrance. Its backend API
and native Discord commands are unchanged; owner read/delete management remains.
Lyrics is opt-in per signed-in viewer and is closed by default.

### Round 11 offline demo and verification
Use the temporary image/context workflow above with a new musicbot-webtest-r11
name and a git archive of feature/dashboard-round11. Run the demo with
--network none and the loopback dashboard_demo_relay.py; no config/data mounts.

* Log in as fake owner. Resolve https://open.spotify.com/playlist/Demo123 :
  covers, selections, enqueue, save and source resync use fabricated data.
* Resolve https://www.youtube.com/watch?v=demo0000000&list=RDdemo :
  25 fabricated tracks, marked seed, sole default selection. Save selected
  tracks and verify the saved collection has no sync action.
* My Playlists: empty Favorites, custom list with long title/unknown duration,
  stable Spotify-source list. At 1280/768/390 check left/top/mobile drill-in
  navigation, More actions, confirmed deletion and title clipping.
* From any page, use the bottom controls directly, and click the title for source/Spotify.
  Empty-queue demo toggles remain available through the existing demo controls.
* Account -> Log out all devices demonstrates the protected new session route.
  All demo session files live in its TemporaryDirectory, created before auth init.

Backend: python3 -W error::DeprecationWarning:aiohttp.web_protocol -m unittest
discover -s tests -p 'test_web_dashboard*.py' in a musicbot-webtest-* container
with --network none. Frontend: node --test tests/test_web_dashboard*.cjs (VM-only,
no network). Links: python3 -m tools.test_compound_link in a --network none
temporary container. Fabricated tests add no external calls or production mounts.


Round 11 retains all prior test cases; revocation assertions distinguish the
first membership/blocklist denial (403) from reuse of the revoked cookie (401).
Backend adds 21 offline cases; frontend adds five behavior cases.
Known boundary: provider-side Spotify embed listings can remain partial, and
dynamic mixes are snapshots. If even seed metadata cannot be read, its canonical
video ID/thumbnail are shown and native playback revalidates it on enqueue.
As with the existing extractor, cancelling an await cannot forcibly stop work
already running in yt-dlp's executor; the UI falls back without awaiting that work.

The final browser check found native range margins plus the new Expand target
could grow the phone bar. Compact padding/range margins now keep its measured
height at 152px (plus any device safe-area requirement), retaining 44px controls.
The full panel also resets the old mobile hero-progress negative left offset.

## Round 12: Liquid Glass
References: [Apple Materials](https://developer.apple.com/design/human-interface-guidelines/materials),
[Adopting Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass),
[Meet Liquid Glass](https://developer.apple.com/videos/play/wwdc2025/219/).
Content cards have no backdrop filter: dark white 4%, light white 50%.
The functional layer alone uses Regular glass (dark 28,30,40 at .28 / light
white .32; blur 18px, saturation 180%). Clear preference reduces the tint to
.16/.18 and blur to 14px. Clear control surfaces are .08/.10 with a highlighted
rim; child controls share their parent blur rather than stacking backdrop filters.
Round 12c removed the album wallpaper and the colour gradient: the page is solid
(dark #0b0b0f with #1c1c1e content blocks, light #f2f2f7 with white blocks).
Navigation, player, lyrics, title choice, menus, dialogs and toast are glass.
Cards, collections and result rows stay flat. Mobile navigation floats 12px
from the edge; player is 8px above navigation. Each keeps its own plane.
The capsule selection moves and resizes, tabs compact on downward scrolling,
range thumbs become 1.6x translucent lenses while dragging, and desktop
pointer highlights are disabled for touch/reduced motion.
Clear glass is the only appearance (10-17 user decision; the selector was removed).
Reduced transparency, increased contrast, unsupported backdrop filters and the
opaque fallback use solid backgrounds. Motion reduction uses opacity only.
Chromium progressively enables a 5px SVG displacement only on an 8px outer rim
of the player/mobile tabs; the center stays undistorted. Safari/Firefox use blur.
Reduced transparency/contrast and fewer than four logical CPUs disable it.
A brief rAF sample drops it if p95 exceeds 34ms; this is a CSS approximation,
not the native Apple renderer.
Offline layout test composites white, black and saturated fabricated covers for
both content and glass, all three preferences and both color schemes (AA 4.5:1).
Browser matrix captures and measurements are held in the temporary test directory.

Measured minimum composited normal-text contrast: dark 5.497:1, light 6.650:1.
Headless Chromium desktop host, 390px viewport, 119 scrolling rAF samples:
median 6.10ms, p95 6.20ms, max 6.20ms, no frame above 33.4ms.
This is a browser smoke measurement, not a physical phone GPU benchmark.
18 width/theme/preference captures passed horizontal-overflow checks.
Phone player height 112px; desktop/tablet 118px. The normal functional layer
has two active backdrop surfaces (navigation and player), adding one per open
lyrics area/popover. Opaque preference has none. Collapsed details descendants
must be excluded with checkVisibility when counting actual painted surfaces.

## Round 12: radio seeds and diversity
The most recent five distinct human-requested YouTube songs form each server's
seed pool. Radio, bot requests and automatic playlists never replace it.
Each refill rotates to the next seed (one mix per refill, up to three additions).
Without human seeds, the top five all-period YouTube popularity entries rotate;
without either source, the existing automatic playlist handles the empty queue.
From the first 25 mix entries, weighted sampling without replacement uses
weight 1/(rank+1). Every candidate is rechecked for duration/blocklist/policy.
A batch rejects repeated channel IDs/names or artist names. NFKC titles strip
presentation/version labels, brackets and a labeled artist prefix; canonical URL
and normalized song title are both compared against the previous 50 plays.
Only URL/title and the rotation cursor persist, atomically, under
data/web_dashboard/radio/<guild_id>.json. Missing, invalid or oversized (64KiB)
state is empty. No requester is stored. Owner empty-queue GET adds seed_titles
and seed_count; management shows the current pool. Existing locks, failover and
three-failure ten-minute suspension remain. Native playback's observational
hook now awaits the off-thread atomic state update inside its existing try/except;
Discord commands, queues, player/playlist/Spotify code are unchanged.

## Round 12: LRCLIB and lyric storage
Lyrics are fetched only on explicit user opt-in; browser access remains same-origin.
Backend LRCLIB /api/get and /api/search use an identifying MusicBot-WebDashboard/12
User-Agent, 8s timeout, 1MiB streamed response limit, failure cooldown and 12
lookups per person/minute. Direct /get results are validated just like search.
Confident Spotify lookup metadata takes priority, otherwise clean title/channel.
Candidates require title similarity >=.90, artist >=.85, duration delta <=60s.
Unknown artist requires title >=.98 and duration delta <=2s. Ambiguous near-ties
are rejected. Instrumental records are supported. Manual query is explicit.
Source documentation: https://lrclib.net/docs
Results are atomic video-ID JSON files in data/web_dashboard/lyrics/cache/.
Missing lyrics are cached one day, successful results seven days, errors 30s.
cache/ plus analysis/ together retain at most 2000 files / 50MiB, oldest first.
To clear results while the bot is stopped, remove the cache/ and analysis/
subdirectories only; offsets/ and settings/ preserve calibration and policy.
Owner GET/POST /api/guilds/{guild_id}/admin/lyrics reads/writes {enabled:boolean},
default true. Disabled servers reject lyric lookup before contacting providers.
All routes keep existing session/member/blocklist/header/same-origin guards.
Offset documents live in lyrics/offsets/<guild_id>/<video_id>.json, with only a
nullable numeric offset (-30..+60 seconds), never the identity of its editor.


## Round 12: lyric alignment and controls
Each signed-in viewer defaults off. localStorage musicbot-lyrics:<viewer> stores
only on/off. While off, no lyric or offset request occurs. Owner disabling also
hides the button and prevents lookup. Nothing is sent to Discord.
Synced lines follow server progress with local interpolation, pause/seek/track
changes re-anchor immediately. Only the lyric viewport scrolls, centered on the
active line; wheel/touch/scrollbar/keyboard input pauses centering for five seconds.
Plain lyrics remain a stationary scrollable full text; instrumental says 純音樂.
The phone viewport is limited to about three lines. Calibration controls are
inline, never in a menu. Reduced motion uses immediate positioning/fades.

Auto alignment runs only after an enabled viewer requests synced lyrics:
1. Video/LRCLIB duration delta <=2s: zero, no audio analysis/download.
2. Otherwise ytsearch5 for an official audio reference, preferring a - Topic
   channel (or a verified Official Audio channel), with title >=.94, artist >=.90
   and duration delta <=2s. Compare the first 90s of MV and first 60s of reference.
   ffmpeg converts local files to 8kHz mono PCM. A pure-Python 20Hz log-energy
   envelope uses normalized Pearson cross-correlation at 50ms steps, -30..+60s.
   Require at least 20s overlap, peak >=.82, margin >=.12 over other peaks
   >=.75s away, and >=.30 above the median correlation. Otherwise reject.
3. Missing/uncertain reference: ffmpeg silencedetect (-40dB, .25s) on the first
   30s, accepting only a region starting within .15s of zero and ending <=30s.
   Dialogue/noise is handled by layer 2, never assumed to be silence.

MV input prefers entry.filename only when its resolved file is within the
configured audio cache; it is read-only. A fresh Python child snapshots the
existing downloader's serializable settings and already-loaded cookie jar over
stdin. It never rereads/saves a cookie file and inherits the configured exit.
The child creates a private yt-dlp instance, local temporary output, no provider
logs or metadata dumps; source downloader params are unchanged.
At most one reference 60s section and, if cache is unavailable, one MV 90s section
are downloaded (20MiB cap per file). No large dependency is added.
A single analysis lock and at most four pending video jobs bound concurrency.
Each active job has a 60s total wall timeout; cancellation kills its process group
including ffmpeg/yt-dlp and deletes the temporary directory. Results, including
uncertainty, cache seven days by video ID under lyrics/analysis/.
Synthetic reference +7s dialogue-like noise measured 7.00s, correlation 1.000,
Python CPU about .20s for conversion orchestration/envelope/correlation; mock
download volume zero. Actual network/download duration is unmeasured offline.
Worker metadata records download_bytes and total self/ffmpeg CPU for future
diagnostics. This does not measure or change active playback.
Uncertain results use zero and show the manual correction hint. Sources display
automatic match, silence detection, duration-equal or manual.

Manual offsets always win and are shared among members of the same guild.
Two-click 對時 shows the first nonblank lyric; the second click sends the local
playback position and the server subtracts that line's timestamp. +/-0.5 adjusts
the effective shared offset; reset removes manual priority and restores auto.
Calibrations are atomic numeric-only files in offsets/<guild>/<video>.json,
range -30..+60s. An activity entry says 調整歌詞位移, without storing its editor
in the calibration file. Open viewers poll the offset every five seconds.
Playback repetition now cycles directly 關閉 -> 單曲 -> 佇列 -> 關閉 with one
button; there is no select/menu on the player. Opening source choices temporarily
hides the lyric glass plane to avoid stacked glass and restores it on dismissal.

### New API details
Existing authentication, membership/blocklist, X-MusicBot-Dashboard: 1 and same-origin
checks apply. Errors are Chinese and never expose provider exceptions or paths.

* GET /api/guilds/{guild_id}/lyrics: member, existing 12/min limit.
  Returns status/title/artist/duration/plain_lyrics/lines plus track_key,
  video_id and track_token. Synced YouTube responses add offset/offset_source/
  analysis_pending. Lookup and alignment start only on this opt-in endpoint.
* GET /api/guilds/{guild_id}/lyrics/offset: member, 60/min polling+write limit.
  Returns video_id, track_token, offset, offset_source, analysis_pending.
  Reads cached state only; never starts lookup, search, download or analysis.
* POST same /lyrics/offset: member; additionally 12/min mutation/lookup limit.
  Body is exactly {action,track_token,...}. Actions: set adds offset (number),
  adjust adds delta (-.5 or +.5), sync adds position (0..video duration),
  reset has no extra field. Stale track token is 409; bad/range data is 400.
  Response is the same as GET; manual calibration takes priority.
* GET/POST /api/guilds/{guild_id}/admin/lyrics: Owner only;
  POST exactly {enabled:boolean}; response {enabled:boolean}, default true.
* Existing Owner GET /admin/empty-queue adds seed_titles and seed_count;
  POST settings shape and permissions are unchanged.

### Offline demo
Run tools.dashboard_demo with the established isolated --network none container
and loopback relay. All stores, settings, sessions and fake provider results use
its TemporaryDirectory. No real config/data/cookie or external provider is used.
Use /?demo-queue=filled&demo-lyrics=synced&demo-art=2 after fake Owner login.
demo-lyrics=plain/instrumental/missing selects other original fake LRCLIB states.
demo-art=0/1/2 chooses fabricated dark/light/vivid album artwork.
/demo-cover/0.svg?tone=white and tone=black/vivid are pure
worst-case fabricated covers used by the contrast sweep.
Open Lyrics, wait up to five seconds for the fake +7s match, try +/-0.5 and
two-click calibration/reset; another signed-in viewer shares the server offset.
Management shows three fabricated radio seeds and can disable lyrics.
Check source/Spotify choice focus, direct repeat cycling, seek, volume,
favorite toggle, library list/detail, More menu and opaque preference.


### Round 12c: solid background, no glow

- The page background is a solid colour: dark `#0b0b0f` (content blocks `#1c1c1e`),
  light `#f2f2f7` (blocks `#fff`). There is no gradient, wallpaper or blurred cover.
- Glass transparency comes from real content scrolling under the sidebar, player,
  tab bar, lyrics area, menus and toast. Floating layers dim what is behind them
  (`brightness(.45)` dark preference) so text stays at least 4.5:1 over any cover.
- Text-bearing popovers (title chooser, menus, dialogs, toast, lyrics) use the denser
  Regular material (`--panel`, 24px blur); the primary button is a flat tinted glass
  capsule with no coloured outer glow.


### Round 17: per-server fallback notification channel

Owner management adds a text-channel selector with **Not specified (use defaults)**.
The choices include only this guild's text/announcement channels for which the bot
can view and send messages. A deleted, inaccessible or binding-excluded selection
shows a warning and can still be cleared. Each request's acting member and the bot
must both be able to view/send in the eventual destination.

The exact candidate order is: current track request channel, latest inserted
queued track request channel, configured fallback notification channel, sorted
bound channels, guild system channel, guild text channels, then the member's voice
channel text chat. Existing restrictions, voice demotion, deduplication and the
final 403 when no destination is usable remain unchanged.

Owner-only GET/POST /api/guilds/{guild_id}/admin/notification-channel uses the
existing membership, blocklist, same-origin and dashboard-header checks.
POST accepts exactly {"channel_id":"101"} or {"channel_id":null}.
IDs must be canonical positive decimal strings; foreign guilds, missing channels,
voice/stage/forum/category/thread channels and bot-inaccessible channels return
400. Non-Owners return 403. Responses contain channel_id, channels (id/name)
and unavailable (boolean). The operation log action is
admin_notification_channel and never contains the channel name or request body.

Settings live at data/web_dashboard/notification_channels/<guild_id>.json.
For fictional guild 1 and channel 101, write notification_channels/1.json:
~~~json
{"channel_id":"101"}
~~~
Clear with {"channel_id":null} or remove the guild file. Missing, unreadable or
malformed settings use the original fallback order. Small bounded reads mean
direct file changes take effect on the next notification/admin read; no restart
is required. External edits should use a sibling temporary file and atomic rename.
The API uses the existing settings writer: fsync, atomic rename, directory fsync;
new files are mode 0600 and replacements preserve the existing mode/ownership.
No guild or channel names are stored. All IDs here and in tests are fictional.

Offline validation from this branch:
~~~sh
git archive HEAD | tar -x -C "$context/src"
docker build --network none -t musicbot-webtest-r17:check -f "$context/Dockerfile" "$context"
docker run --rm --network none --user 0:0 --name musicbot-webtest-r17-unit --entrypoint python3 musicbot-webtest-r17:check -m unittest discover -s tests -p 'test_*.py'
docker run --rm --network none --user 0:0 --name musicbot-webtest-r17-links --entrypoint python3 musicbot-webtest-r17:check -m tools.test_compound_link
docker run --rm --network none --user 0:0 --name musicbot-webtest-r17-i18n --entrypoint python3 musicbot-webtest-r17:check -m tools.check_dashboard_i18n
node --test tests/*.cjs
~~~
The isolated test Dockerfile uses FROM musicbot:ytdlp-base, WORKDIR /musicbot,
COPY src/ /musicbot/ and compiles both zh_TW catalogs with tools/po2mo.py,
as in round16. It has no production mounts or network. Demo notification settings
also use the demo's TemporaryDirectory. Static cache version: r17-notify-channel.

Validation result (round16 baseline retained): 555 backend tests (526 + 29),
183 frontend checks (175 + 8, including the existing catalog fixture file),
16 compound-link cases, and 599 matching en/zh-TW catalog keys; all passed.
The demo browser checks passed with no page errors: saved value after reload,
independent per-guild settings, clear via the default option, English translation,
and mobile layout without horizontal overflow. Screenshots:
- /tmp/musicbot-r17-shots/admin-desktop.png
- /tmp/musicbot-r17-shots/admin-mobile.png


### Round 18: per-server vote-to-skip switch

Owner management's server permissions section adds **Vote to skip**, enabled by
default, with the explanation: when disabled, anyone with Skip permission can
skip immediately. The existing global permission groups remain separate.

Owner-only GET/POST/DELETE /api/guilds/{guild_id}/admin/vote-skip uses the existing
authentication, membership, blocklist, dashboard header and same-origin checks.
POST accepts exactly {"enabled":false} or {"enabled":true}; GET returns the same
shape. DELETE clears the override by atomically persisting {"enabled":true}.
Non-Owners receive 403; invalid values receive 400; write failures receive 503.
The operation log action is admin_vote_skip for every method.

The file is data/web_dashboard/vote_skip/<guild_id>.json. Fictional guild 1:
~~~json
{"enabled":false}
~~~
Missing, corrupt, oversized or unreadable files default to enabled. Removing a
guild file also restores the default. Reads are bounded to 4096 bytes and direct
atomic file replacements take effect on the next command. The shared
GuildSettingsStore is extracted from round17's NotificationChannelStore: both use
the same existing JSON writer (sibling temp file, file fsync, atomic rename,
directory fsync; new files 0600, replacements preserve mode and ownership).
No guild/member names are stored, and all examples and test IDs are fictional.

Text dispatch, /skip and the web skip button still use the single cmd_skip.
Previously the web button validated Skip/voice access then called cmd_skip with
message=None and param=""; it recorded deduplicated votes for ordinary members,
using SkipsRequired/SkipRatio, while InstaSkip followed LegacySkip/force rules.
Only the force-path decision now reads this guild's setting. Disabled voting
enters the existing direct-skip path without counting members, adding votes or
calculating thresholds. It uses the existing "Force skipped" response. The
original Skip gate, voice checks and SkipLooped rules remain in place, including
the existing force behavior for actual InstaSkip holders. Other guilds continue
to read their own setting, defaulting to their original voting behavior.

Activity's votes value is zero while disabled, including pre-existing votes
while the audio player has yet to advance, so the vote label and remaining-votes
reply never appear for new disabled-mode skips. No skip logic is duplicated.
The setting also works when the dashboard is disabled and honors --write-dir.
The demo overrides its settings root to its own TemporaryDirectory.

Static assets and service worker use r18-vote-skip. The switch has an accessible
label, help text and switch role; it is disabled until the Owner read succeeds,
and late responses cannot restore another server's or a logged-out session's
setting. All new text is in the matching en/zh-TW catalogs.


Round18 validation: 582/582 backend tests (555 existing + 27 new), 191/191 frontend
checks (183 existing + 8 new), 16/16 compound-link cases, 606 matching translated
catalog keys (599 existing + 7 new); zero failures. Backend coverage includes real
text dispatch and real /skip callbacks (enabled/disabled and denied permission),
web voting/threshold/deduplication/direct skips, InstaSkip force/LegacySkip,
SkipLooped, voice gates, guild isolation, non-Owner 403, clear-to-default, strict
schemas, owner/membership rechecks, atomic failure preservation and stale votes.
Targeted fixture tests were corrected before this complete passing run; existing
authorization semantics and rejection status codes were retained.

The staged tree was archived with git archive "$(git write-tree)" and extracted
into an isolated context, using a test Dockerfile with FROM musicbot:ytdlp-base,
USER 0:0, WORKDIR /musicbot, COPY src/ /musicbot/ and both zh_TW po2mo compilations.
Complete commands (all container names/images use the musicbot-webtest- prefix):
~~~sh
docker build --network none -t musicbot-webtest-r18-suite:check -f "$context/Dockerfile" "$context"
docker run --rm --network none --user 0:0 --name musicbot-webtest-r18-unit --entrypoint python3 musicbot-webtest-r18-suite:check -m unittest discover -s tests -p 'test_*.py'
docker run --rm --network none --user 0:0 --name musicbot-webtest-r18-links --entrypoint python3 musicbot-webtest-r18-suite:check -m tools.test_compound_link
docker run --rm --network none --user 0:0 --name musicbot-webtest-r18-i18n --entrypoint python3 musicbot-webtest-r18-suite:check -m tools.check_dashboard_i18n
node --test tests/*.cjs
~~~
The browser used its own headless Chromium and a credential-free --network none
demo container reached only through the existing loopback stdio relay. Six browser
checks passed: Owner disable, reload persistence, independent second-guild default,
English translation, mobile width, and re-enable. No page errors. Screenshots:
- /tmp/musicbot-r18-shots/permissions-desktop.png
- /tmp/musicbot-r18-shots/permissions-mobile.png
- /tmp/musicbot-r18-shots/browser-checks.json (browser evidence)

No deployment, production config/data reads, production container access or cookie
sync was needed. No additional reviewer or acceptance subagent was used.


### Round 22: web-only source policy

Web resolve/play/playnext and library playback accept HTTP(S) URLs with an
installed, enabled, dedicated yt-dlp extractor. URLs are normalized before use;
YouTube/YouTube Music, Spotify, SoundCloud and Bandcamp remain supported.
Generic websites, raw media URLs, literal addresses, credentials in URLs and
nonstandard ports are rejected before network I/O. Nested extraction cannot
re-enable GenericIE. Ancillary generic HEAD probes are skipped for web requests.
The localized error is available in English and Traditional Chinese.

This round deliberately uses the no-generic fallback, rather than claiming a
DNS-pinned transport sandbox. Dedicated extractors are trusted provider code:
their own network requests/HTTP redirects are not an address-filtering boundary.
DNS rebinding and redirects of rejected generic input cannot trigger a request,
because input classification performs no DNS or HTTP I/O. Arbitrary provider
extractor bugs or provider-controlled URLs remain a residual risk.
Native Discord commands keep their original clients, generic support and HEAD
behavior; their equivalent SSRF risk remains for a later, separately scoped fix.
