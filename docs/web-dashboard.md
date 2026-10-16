# Web dashboard: owner or Discord login (not deployed)

Optional aiohttp dashboard inside the bot event loop, without another Discord
client or dependency. Default AuthMode=owner preserves the deployed OwnerID
behavior when the key is missing. That mode still requires external SSO.
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
| POST /resolve | play, query first argument | none; never summons | extract_info, _do_song_blocklist_check, can_use_extractor, _do_playlist_checks |
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
bounded by MaxSearchItems; playlists inspect all extracted entries but display
the first ten. Blocklist, extractor, MaxSongs, MaxSongLength, AllowPlaylists,
MaxPlaylistLength, source enablement and karaoke use the logged-in member.
Unknown duration warns and is checked again at play. Mixed YouTube links offer
separate video/playlist choices.

POST /play {query:selected_url, preview_id} confirms a choice. Tokens bind guild,
user and URL for five minutes, with at most 100 cached choices. Play repeats the
original restrictions. Duplicate successful confirmations never add twice;
attempts consumed once cmd_play begins remain consumed on partial failure.
The API also accepts legacy /play {query}; the browser uses explicit previews.

Move: {from,to,revision}, 1-based. Shuffle/remove: {revision}. Stale/concurrent
queue requests return 409. Volume: integer 1..100. Repeat: off/song/all.

Discord mode allows **12 combined resolve/play attempts per user per rolling
60 seconds**, across guilds and sessions; owner mode is unaffected. Additionally
one resolver per guild, two overall. Resolve deadlines are 20 seconds without
holding playback mutation locks; timed-out work retains its slot until finished.
Python cannot kill an executing yt-dlp worker thread.

Pointer sorting, touch hold (420ms), Escape/cancel/revision handling, keyboard
up/down/remove, mobile layout and stale-response guards remain. Authenticated
polling runs every second, or ten seconds while hidden.

## Offline tests and fake-login demo

Build from Git archive, never the operational directory containing credentials
and backups. Existing dependency tags are read only; all new test images and
containers start musicbot-webtest-. No production mounts.

~~~sh
ctx=$(mktemp -d /tmp/musicbot-webtest-discord.XXXXXX)
git -C "$HOME/musicbot" archive feature/dashboard-discord-login | tar -x -C "$ctx"
printf '%s\n' 'FROM musicbot:ytdlp-base' 'WORKDIR /webtest' 'COPY . .' \
  'ENTRYPOINT ["python3"]' | docker build --network none \
  -t musicbot-webtest-discord:demo -f - "$ctx"
docker run --rm --network none --name musicbot-webtest-discord-unit \
  --entrypoint python3 musicbot-webtest-discord:demo \
  -W 'error::DeprecationWarning:aiohttp.web_protocol' \
  -m unittest discover -s tests -p 'test_web_dashboard*.py'
docker run --rm --network none --name musicbot-webtest-discord-links \
  --entrypoint python3 musicbot-webtest-discord:demo -m tools.test_compound_link
(cd "$ctx" && node --check musicbot/web/dashboard.js && \
  node --test tests/test_web_dashboard_frontend.cjs)
~~~

Python tests use real command/Playlist logic with fake Discord boundaries.
OAuth endpoints are local aiohttp mocks, including failures/timeouts/replay/expiry.
No live OAuth, real token, download or Discord connection is used. Frontend uses
Node VM/fake DOM without network.

Demo default is a fake login picker using real Dashboard/assets/session code and
fake guilds/extraction. Fake login endpoints exist **only in the demo executable**.
Never deploy tools/dashboard_demo.py as the production dashboard.

~~~sh
docker run --rm -d --name musicbot-webtest-discord-demo \
  -p 127.0.0.1:18080:8080 --entrypoint python3 musicbot-webtest-discord:demo \
  -m tools.dashboard_demo --host 0.0.0.0 --port 8080 \
  --public-origin http://127.0.0.1:18080
~~~

Keep this Windows PowerShell tunnel open:

~~~powershell
ssh -N -L 127.0.0.1:18080:127.0.0.1:18080 -o ExitOnForwardFailure=yes your-vps
~~~

Open http://127.0.0.1:18080/ and click login. Choose owner, member, away or denied;
logout then log back in to switch. Owner has unrestricted controls. Member has
210-second/three-song limits, no playlists/instant skip and can remove only own
songs (the second queued song initially). Away can read but not mutate. Denied
can read but cannot resolve/control. Demo uses actual cmd_skip/cmd_remove.
Try a keyword, HTTPS song URL, https://example.test/playlist or blocked.
Optional --fake-login member auto-selects that user after clicking login;
--auth-mode owner shows the old owner-only demo.

The port-forwarded demo needs Docker's default bridge; it makes no external
requests. Unit tests always use --network none. Strict isolated demo tests use
in-container TestServer without publishing a port.

~~~sh
docker stop musicbot-webtest-discord-demo
docker image rm musicbot-webtest-discord:demo
case "$ctx" in /tmp/musicbot-webtest-discord.*) rm -rf -- "$ctx";; esac
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
