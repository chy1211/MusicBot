# Install MusicBot with Docker

MusicBot combines the Just-Some-Bots music bot and a web dashboard. Docker
includes Python, ffmpeg, Deno, yt-dlp, EJS and the bgutil provider plugin.
Supported image platforms: Linux amd64 and arm64 (including Raspberry Pi 64-bit
and Oracle ARM). Use Docker Engine with Compose v2.20+ or Docker Desktop.
See [Traditional Chinese](install.zh-TW.md) and [dashboard languages](dashboard-languages.md).

## Quick start (about five minutes after creating your Discord app)

In a new directory, download just the Compose file and environment template:

~~~sh
mkdir musicbot
cd musicbot
curl -fsSLO https://raw.githubusercontent.com/chy1211/MusicBot/dev/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/chy1211/MusicBot/dev/.env.example -o .env
~~~

On Windows PowerShell use `curl.exe` in those commands.

1. Open [Discord Developer Portal](https://discord.com/developers/applications),
   create an application, and open **Bot > Reset Token**. Put the bot token in
   `DISCORD_BOT_TOKEN`. Enable **Server Members Intent** and **Message Content Intent**.
2. Under **OAuth2**, copy **Client ID** and **Client Secret** to
   `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET`. The client secret and bot token
   are different credentials.
3. In Discord **User Settings > Advanced**, enable Developer Mode. Right-click
   your own profile and copy its User ID to `OWNER_ID` (not the application ID).
4. For a local trial, set `DASHBOARD_PUBLIC_URL=http://localhost:8080`. Add exactly
   `http://localhost:8080/auth/callback` under the app's **OAuth2 > Redirects**.
   For a public server, use your HTTPS domain and its matching callback instead.
5. Use **OAuth2 > URL Generator** with `bot` and `applications.commands` scopes
   to invite the bot. Allow View Channels, Send Messages, Read Message History,
   Connect and Speak. Then start:

~~~sh
docker compose up -d
docker compose logs --tail 50 config-init musicbot
~~~

Open the configured dashboard URL, sign in with Discord, join a voice channel
and use `/summon`. Requests respect your existing MusicBot permission group.
When summon newly joins voice, it includes the configured PublicURL in its reply
in the guild's language. It does not post the URL again when moving channels;
public announcements require Discord auth and an HTTPS PublicURL.

The image is `ghcr.io/chy1211/musicbot:latest`. The one-time `config-init`
container checks the settings, creates configuration, and assigns new files
and volume roots to UID/GID 1000. **MusicBot runs as a non-root user.**
If a required variable is missing, config-init exits nonzero with English and
Chinese portal instructions. MusicBot waits for successful initialization, so
invalid first-run configuration does not cause an endless restart loop.
Fix .env and run `docker compose up -d` again.

## Services, ports and data

- `musicbot`: bot and dashboard. The port defaults to **127.0.0.1:8080**;
  use a reverse proxy for public access.
- `bgutil-provider`: enabled by default, generates YouTube proof-of-origin
  tokens for the bundled yt-dlp plugin at `http://bgutil-provider:4416`.
  YouTube may require these tokens. This helps compatibility but cannot
  guarantee bypassing bot checks. Port 4416 is internal and unauthenticated;
  never expose it to the internet.
- `config-init`: once per Compose startup, restart disabled; no network needed.
- `caddy`: optional profile for HTTPS.

Four bind mounts keep your data outside the image: `./config`, `./data`,
`./audio_cache`, and `./logs`. Keep .env, ini files, cookies and session data
private. Set optional PUID/PGID to positive IDs if you need a different Linux
owner. Existing files retain their permissions; when importing an old install,
make its volume files readable/writable by that UID/GID first.

`GET /healthz` is unauthenticated and returns only `{"status":"ok"}`. It is a
**dashboard liveness** check; Discord can be unavailable while it remains healthy.
Protected APIs return a safe unavailable message until Discord is ready.
With DASHBOARD_ENABLED=false the health command simply succeeds for a running
container; it does not claim a dashboard is listening.

## Environment and existing settings

First-run required variables: DISCORD_BOT_TOKEN, OWNER_ID, and (while the
dashboard is enabled) DASHBOARD_PUBLIC_URL, DISCORD_CLIENT_ID,
DISCORD_CLIENT_SECRET. Optional variables are listed in .env.example:

| Variable | Default / purpose |
| --- | --- |
| SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET | Optional Spotify API credentials |
| DEFAULT_LANGUAGE | en; dashboard default, or zh-TW |
| TIME_ZONE | UTC; IANA zone such as Asia/Taipei |
| COMMAND_PREFIX | !; traditional Discord text commands |
| YTDLP_AUTO_UPDATE | false; optional writable yt-dlp update at startup |
| DASHBOARD_ENABLED | true; applied when generating dashboard ini |
| PUID / PGID | 1000 / 1000; non-root volume ownership |
| DASHBOARD_PORT | 8080; loopback host port |
| MUSICBOT_IMAGE | Override the prebuilt image, primarily for local builds |

**An existing options.ini or web_dashboard.ini is never overwritten.**
Environment values generate each file only when that file does not exist;
changing .env afterward does not change settings in an existing ini. Edit that
ini yourself and recreate the bot, or move only the relevant ini to a private
backup before regeneration. Other files remain intact. Random SessionSecret is
created automatically; current opaque login sessions are stored in the data
volume, not signed using that legacy setting.

The dashboard language selector overrides browser languages and the server
default. Discord notification text follows the bot's existing per-guild
gettext language (use its language command). These are independent settings.

## Public HTTPS with Caddy

Point your domain's A/AAAA DNS records to your server and make ports 80/443
available. Download Caddyfile into the same directory, set
`DASHBOARD_PUBLIC_URL=https://music.example.com` to **your domain**, and add its
`/auth/callback` URL in Discord. If an ini already exists, update PublicURL there.

~~~sh
curl -fsSLO https://raw.githubusercontent.com/chy1211/MusicBot/dev/Caddyfile
docker compose --profile caddy up -d
~~~

Caddy reads DASHBOARD_PUBLIC_URL from .env, obtains HTTPS certificates and
proxies to musicbot:8080. Certificate state uses the named caddy_data/config
volumes. You can use another HTTPS reverse proxy instead. Do not publish the
dashboard port on all host interfaces as a shortcut.

## Cookies (optional)

If YouTube says **Sign in to confirm you're not a bot**, export a Netscape-format
cookies.txt from a browser session you control, and save it as
`./data/cookies.txt`. MusicBot already reads that path at startup.
Give the bot UID read access and recreate the container after changing cookies.
Treat the file like a password. Prefer a separate, low-value account: automated
access can lead to account restrictions. Do not commit it or share it.

The repository's tools/sync_cookies.* scripts are **advanced and optional**;
they are not part of this installer and must be reviewed and adapted to your
own environment. The default flow never harvests browser cookies.

## Upgrade, rebuild and recovery

~~~sh
docker compose pull
docker compose up -d
~~~

Your mounted configuration, playlists, history and login data survive image
upgrades. Back up config and data first. Do not run `down -v` if you want to
preserve Caddy certificates. Existing per-install VPN/cookie/update scripts
are independent and are not migrated by this Compose file.

To build locally, clone/download the repository and uncomment `build: .` in
the shared Compose definition; set MUSICBOT_IMAGE to your own local image name,
then use `docker compose build && docker compose up -d`.

The weekly image workflow rebuilds with current yt-dlp and provider plugin
packages. Startup auto-update is **off** for repeatability and fast starts.
With YTDLP_AUTO_UPDATE=true, pip installs upgraded packages under
`data/runtime-packages` and uses them only for that run. It needs internet and
can introduce upstream regressions; a failed update uses the image's packages.
Set it false and recreate the container to use only bundled packages again.

For maintainers: first publishing requires the Docker GitHub workflow to be
enabled. After its first successful run, open the GitHub package settings and
make the musicbot package **public** so users can pull without registry login.
No extra Actions secret is needed; GITHUB_TOKEN provides packages:write.
