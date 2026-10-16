# Owner web dashboard (first version)

This optional dashboard runs inside MusicBot's asyncio loop using the existing
aiohttp dependency. It does not create a Discord client or a second bot instance.
All access acts as the configured OwnerID. It is intended for one owner behind
an authenticated reverse proxy; it is not a multi-user authorization system.

## Configuration

Only an example is tracked: `config/example_web_dashboard.ini`.
To enable during a separately approved deployment, create
`config/web_dashboard.ini` beside the options.ini file used by MusicBot:

```ini
[WebDashboard]
Enabled = yes
Host = 127.0.0.1
Port = 8080
SharedSecret =
```

Defaults: disabled, loopback address, port 8080, empty optional shared secret.
Missing, disabled, malformed or unusable configuration never prevents MusicBot
from starting. Configuration is read once after the first successful on_ready;
OwnerID=auto has already resolved by then. Changes require a bot restart.
No real config file is created automatically, and example values contain no
deployment URL or secret. Do not commit the real file.

For a container reverse proxy, the eventual deployment may need Host=0.0.0.0
and proxy/network changes. Keep the service behind SSO/TLS and prevent direct
unauthenticated access. No ports, routing, SSO, production containers or release
image tags are changed by this feature. A shared secret is recommended as an
additional boundary; it is sent in an Authorization header, never in a URL.
The page holds it in tab memory only. Refreshing the page clears it.

## Lifecycle and failure handling

MusicBot.on_ready starts the server once, after initialization and normal ready
work succeeds. MusicBot.close stops it before discord.py closes; logout uses
close. run_musicbot's finally block also stops it for startup/termination errors.
Startup/import/shutdown failures are logged and contained. Aiohttp middleware
logs and translates request exceptions to JSON errors; unexpected errors return
a generic message without traceback data. Access logging is disabled to avoid
logging credentials. A broken dashboard does not shut down Discord playback.

## API

Every API request needs X-MusicBot-Dashboard: 1. If configured, it also needs
Authorization: Bearer <SharedSecret>. No CORS is enabled. Origins, when present,
must match the request Host (the reverse proxy should preserve the public Host).
The frontend uses paths relative to a dashboard hosted at the root of its own
hostname. Subpath hosting is not currently supported.

All IDs are decimal strings. JSON request bodies are limited to 16 KiB.
Every mutation returns {message, state}; state contains current track, thumbnail,
progress in seconds, volume percent, repeat mode, queue and revision.
The frontend polls state every second (10 seconds when the page is hidden).

| Method | Path (prefix /api/guilds/{guild_id}) | Body | Existing behavior |
| --- | --- | --- | --- |
| GET | /api/guilds (no prefix) | none | bot.guilds, actual owner guild membership |
| GET | /state | none | get_player_in; never creates or joins voice |
| POST | /play | query: URL or keywords | cmd_play -> _cmd_play -> existing downloader and Playlist |
| POST | /pause | {} | cmd_pause |
| POST | /resume | {} | cmd_resume |
| POST | /skip | {} | cmd_skip, normal existing skip/vote semantics |
| POST | /volume | volume: integer 1..100 | cmd_volume, including Opus restart behavior |
| POST | /repeat | mode: off/song/all | cmd_repeat, idempotent target mode |
| DELETE | /queue/{position} | revision | cmd_remove and serialize_queue |
| POST | /queue/move | from, to: 1-based integers; revision | Playlist.delete_entry_at_index + insert_entry_at_index; serialize_queue |
| POST | /queue/shuffle | revision | Playlist.shuffle; serialize_queue |

The owner must actually belong to the selected guild and join a voice channel
before mutating playback. Permissions.for_user receives the actual cached owner
Member. Voice-only restrictions, summonplay, bound/unbound channel settings and
Discord channel visibility/send permissions are checked. Only /play may create
a player, using summonplay permission. Control requests do not join an idle guild.

All track addition uses the original command pipeline: local media setting,
blocklists, extractor permissions, max songs, max song length, karaoke and
playlist limits are retained, including the original Owner group defaults.
Keywords search and add the first result, like !play. This version has no
interactive search result picker. A combined video+playlist URL retains the
existing Discord reaction prompt; use a bare playlist URL to queue a playlist
directly from the web.

Move and shuffle use the same atomic queue primitives as the Discord commands,
without their chat message/animation awaits. This avoids changing a different
position after an awaited Discord message. Web mutations are serialized per
guild, and revision checks reject stale queue actions with HTTP 409.
Discord can still change playback while an asynchronous command is in progress.
After a failed mutation, reload state before retrying: persistence/response errors
may occur after an in-memory mutation has already succeeded.

## Offline tests

No new Python or frontend packages are required. The real dashboard INI is ignored by Git. From a credential-free source
checkout or a clean build context exported from tracked source:

```sh
docker build -t musicbot:web-test .
docker run --rm --network none --name musicbot-webtest-unit \
  --entrypoint python3 musicbot:web-test \
  -m unittest discover -s tests -p test_web_dashboard.py -v
```

Frontend request, state, stale-response and error recovery behavior can also be
checked with the existing Node runtime (built-in test/VM modules, no packages):

```sh
node --check musicbot/web/dashboard.js
node --test tests/test_web_dashboard_frontend.cjs
```

These are DOM behavior tests with a fake document/fetch, not rendered browser
or mobile viewport tests. Responsive CSS is provided, but desktop/mobile visual
verification remains part of rollout acceptance.

Never mount production config/data/cookies or start run.py in test containers.
The tests construct fake bots and players without MusicBot.__init__, login or
real tokens. They exercise real command methods, real Playlist operations and
real aiohttp HTTP listeners/clients. Fixtures replace Discord, download and disk
boundaries only. Build contexts must exclude untracked configuration/backups:
the repository Dockerfile copies config, so building directly in an operational
checkout with secrets is unsafe. Export the reviewed Git tree first.

This does not test a live Discord voice connection, real yt-dlp extraction,
external SSO, reverse proxy reachability, or production deployment. Those need a
separate rollout with no second instance using the same Discord token.
