# Owner web dashboard (second iteration, not deployed)

Optional aiohttp dashboard inside MusicBot's event loop; never creates a second
Discord client. All access uses the actual configured OwnerID member.
Use an authenticated reverse proxy/TLS for deployment; this is not multi-user auth.

## Configuration and lifecycle

Only config/example_web_dashboard.ini is tracked. A separately approved deployment
can create config/web_dashboard.ini beside the active options.ini:

```ini
[WebDashboard]
Enabled = yes
Host = 127.0.0.1
Port = 8080
SharedSecret =
```

Defaults: disabled, loopback, port 8080, optional empty secret. Missing, invalid,
disabled or unusable configuration must not stop MusicBot. Read once after the
first successful on_ready; configuration changes need a restart. The page keeps
the secret in tab memory only. Never commit real configuration. Future container
proxy access may require Host=0.0.0.0 and separately approved network changes.
This feature changes no production container, routing, proxy, SSO or release tag.

on_ready starts once; close/logout/run_musicbot-finally clean up the listener.
Startup/request failures are contained. Access logging is disabled; error
responses omit tracebacks. Pending preview tasks are cancelled during shutdown.

## HTTP API

Every API request requires X-MusicBot-Dashboard: 1 and, if configured,
Authorization: Bearer <SharedSecret>. No CORS; supplied Origin must match Host.
Reverse proxies must preserve Host. Root hosting only, no subpaths. JSON bodies
are limited to 16 KiB; guild IDs are decimal strings. Errors return {error}.
Mutations return {message, state}; state includes current track, progress in
seconds, volume percent, repeat, queue and revision.

Paths below use /api/guilds/{guild_id}, except the guild list.

| Method | Path | Request | Existing behavior |
| --- | --- | --- | --- |
| GET | /api/guilds | none | actual owner guild membership |
| GET | /state | none | get_player_in; never creates player |
| POST | /resolve | {query: URL or keywords} | Downloader.extract_info(download=False, process=True) |
| POST | /play | {query: selected URL, preview_id: token} | cmd_play -> _cmd_play -> Playlist |
| POST | /pause, /resume | {} | cmd_pause / cmd_resume |
| POST | /skip | {} | cmd_skip, original skip/vote semantics |
| POST | /volume | {volume: integer 1..100} | cmd_volume |
| POST | /repeat | {mode: off/song/all} | cmd_repeat, idempotent target mode |
| DELETE | /queue/{position} | {revision} | cmd_remove + serialize_queue |
| POST | /queue/move | {from, to, revision}, 1-based positions | Playlist delete/insert + serialize_queue |
| POST | /queue/shuffle | {revision} | Playlist.shuffle + serialize_queue |

The first-version POST /play {query} remains compatible. The browser always uses
resolve then explicit confirmation. Deduplication requires preview_id.

### Preview and confirmation

POST /api/guilds/1/resolve {"query":"song name"} returns:

```json
{
  "expires_in": 300,
  "results": [{
    "kind": "track",
    "title": "A song",
    "url": "https://example.test/watch/123",
    "thumbnail": "https://example.test/cover.jpg",
    "duration": 180,
    "allowed": true,
    "reason": "",
    "warning": "",
    "preview_id": "<opaque per-choice token>"
  }]
}
```

Keywords use default_search_service with up to five results, also bounded by
max_search_items. Selecting one confirms its canonical source URL. Search
candidates do not require AllowPlaylists. Non-HTTP/local inputs are not previewed.

Playlist results have kind=playlist, title, url, thumbnail, duration=0, count,
checked_count, eligible_count, entries (first ten only), allowed, reason, warning
and preview_id. Every extracted entry is inspected, including entries outside
those ten. Unknown duration carries a warning. Counts describe metadata available
at preview time; confirmation re-resolves and may skip individual invalid tracks.

Mixed YouTube video+playlist URLs become separate explicit choices using
get_compound_link_ids. Confirmed URLs do not trigger the mixed-link reaction
prompt. Failure to resolve either source fails the query as a whole.

Resolve reuses _do_song_blocklist_check, PermissionGroup.can_use_extractor,
_do_playlist_checks and the existing downloader. It also checks max_songs,
karaoke, source enablement and supported source URL rules. Per-track length and
deleted/private checks mirror the existing command/playlist rules. Missing child
extractor metadata inherits the checked parent extractor for preview.

Resolve uses get_player_in or a read-only empty-queue view; never get_player,
cmd_play, Playlist.add_entry or voice connection code. It does not download audio
or enqueue anything. Existing downloader metadata/HTTP HEAD requests can read
the bot's existing cookies.

The resolve HTTP deadline is 20 seconds. One active resolve per guild, two
overall; excess requests return 429. Resolve never holds the guild mutation lock.
Timed-out work retains its admission slot until completion, preventing executor
flooding. Python cannot forcibly stop a running yt-dlp worker thread. HTTP
timeout returns 504 and controls remain available. Shutdown cancels asyncio tasks.

400: invalid input; 403: query/extractor/global permission denial; 404: no results;
429: resolver busy; 502: sanitized extraction error; 504: deadline.
Individual denied songs/playlists return 200 with allowed=false and visible reason.

Confirm using POST /play {"query":"<result.url>","preview_id":"<result.preview_id>"}.
Tokens last five minutes, bind guild/owner/URL and are bounded to 100 choices;
eviction or restart may invalidate them sooner. Guild mutations are serialized.
Successful duplicate confirmation returns current state without adding again.
Once cmd_play starts, the token is consumed even on failure because partial
enqueue is possible. Inspect the queue and re-query before intentionally adding
again. A completed-token retry succeeds; expired, failed-used or wrong-guild
tokens return 409; tampering or denied choices return 403.

Confirmation repeats the original real-owner voice, ignore_non_voice,
summonplay, channel visibility/send/binding, blocklist, extractor, queue/length/
playlist and karaoke checks. Only confirmed play may summon a player. cmd_play
still holds the guild mutation lock while executing; source/Discord delays can
delay other mutations during confirmation.

## Interface and dragging

No external scripts/fonts/CDN, build tools or frontend dependencies. Dark surfaces,
green accents, rounded cards, server sidebar, large current artwork and fixed
bottom playback controls. Mobile uses a top server selector, single column,
visible queue buttons and touch targets. Missing covers have local fallbacks.

Mouse: move the primary-pointer drag handle. Touch/pen: hold the handle for
420 ms then move. Early movement cancels; the rest of the row scrolls normally.
Pointer capture, cancellation, edge scrolling and direction-aware insertion marks
are implemented with Pointer Events. Release sends captured {from,to,revision}
to queue/move. No optimistic reorder. HTTP 409 refreshes and retains the error.
Queue/guild changes, Escape, pointercancel and lost capture cancel dragging;
same-position drops send no request. Labeled up/down/remove buttons remain
keyboard alternatives. Only the handle disables touch scrolling.

Polling is every second (ten seconds hidden); guild generations and state
request sequences reject stale responses. Slow lookup leaves playback controls
available. Lookup and drag status use an aria-live region.

## Offline tests and demo build

Export reviewed Git source rather than building in the operational checkout:
its untracked config/backups can contain secrets. Use existing dependency image
musicbot:ytdlp-base read-only; do not change its tag. The following also works
after the operational checkout has returned to dev:

```sh
ctx=$(mktemp -d /tmp/musicbot-webtest.XXXXXX)
git -C "$HOME/musicbot" archive feature/web-dashboard | tar -x -C "$ctx"
printf '%s\n' 'FROM musicbot:ytdlp-base' 'WORKDIR /webtest' 'COPY . .' \
  'ENTRYPOINT ["python3"]' | docker build -t musicbot-webtest-demo:latest -f - "$ctx"
docker run --rm --network none --name musicbot-webtest-unit \
  --entrypoint python3 musicbot-webtest-demo:latest \
  -m unittest discover -s tests -p 'test_web_dashboard*.py'
docker run --rm --network none --name musicbot-webtest-links \
  --entrypoint python3 musicbot-webtest-demo:latest -m tools.test_compound_link
(cd "$ctx" && node --check musicbot/web/dashboard.js && \
  node --test tests/test_web_dashboard_frontend.cjs)
```

All original 47 Python and nine frontend behavior tests are retained. Frontend
interaction assertions now include the explicit preview/confirm step. Additional
tests cover metadata, playlists, search selection, denials, timeouts, independent
control locks, tokens, concurrent confirmation, partial failure, real playlist
filtering, pointer/long-press/cancellation, stale revisions, lookup races and stale
polls. No real Discord login, download or source extraction occurs.

## Credential-free visual demo

tools/dashboard_demo.py uses this same Dashboard and static assets, two fake
guilds/players, locally served SVG covers and fake extraction/commands. It never
constructs MusicBot or a Discord client, reads production config/data, or makes
source requests. Try keywords for five results, any HTTPS song URL for one song,
https://example.test/playlist for a five-track playlist, or blocked for denial.

From the image above, publish only to VPS loopback (no config/data mounts):

```sh
docker run --rm -d --name musicbot-webtest-demo \
  -p 127.0.0.1:18080:8080 --entrypoint python3 musicbot-webtest-demo:latest \
  -m tools.dashboard_demo --host 0.0.0.0 --port 8080 \
  --public-origin http://127.0.0.1:18080
```

In a separate Windows PowerShell window, keep the tunnel open:

```powershell
ssh -N -L 127.0.0.1:18080:127.0.0.1:18080 -o ExitOnForwardFailure=yes your-vps
```

Browser URL: http://127.0.0.1:18080/ . If choosing a different local port, change
--public-origin accordingly so the covers use the browser's forwarded origin.

Alternatively, in an existing VPS Python environment with MusicBot requirements:

```sh
cd "$ctx"
python3 -m tools.dashboard_demo --host 127.0.0.1 --port 18080 \
  --public-origin http://127.0.0.1:18080
```

The VPS system Python lacks aiohttp; use the container for a reproducible run.
Stop a direct Python demo with Ctrl+C. After inspection, stop only the named demo
container, remove only the new test image, and remove the exported temporary
directory identified by $ctx (verify its absolute path starts with
/tmp/musicbot-webtest. first). Close the SSH tunnel with Ctrl+C.

The implementation run exercised demo HTTP/static/artwork, both guilds, resolve,
confirm deduplication and queue controls. This session had no available browser
surface: rendered desktop/mobile appearance and real touch behavior still need
visual inspection. Node tests use a fake DOM; they are not layout/device tests.
Live Discord/voice, real yt-dlp, external SSO and proxy integration are also outside
offline verification. No production deployment is included.
