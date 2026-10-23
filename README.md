# MusicBot + Web Dashboard

[![CI](https://github.com/chy1211/MusicBot/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/chy1211/MusicBot/actions/workflows/ci.yml)
[![Docker images](https://github.com/chy1211/MusicBot/actions/workflows/docker.yml/badge.svg?branch=dev)](https://github.com/chy1211/MusicBot/actions/workflows/docker.yml)
[![Image](https://img.shields.io/badge/ghcr.io-chy1211%2Fmusicbot-blue)](https://github.com/chy1211/MusicBot/pkgs/container/musicbot)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**English** · [繁體中文](README.zh-TW.md)

The classic [Just-Some-Bots MusicBot](https://github.com/Just-Some-Bots/MusicBot), plus a web dashboard that everyone in your Discord server can use from a browser or phone. Install it with Docker in a few minutes.

Members sign in with their Discord account, then search, queue, reorder and control playback without typing commands. The bot still works exactly as before in Discord, and the dashboard follows the same permission groups and limits.

![Dashboard on desktop](docs/images/dashboard-desktop.png)

## Features

**Listening together**
- Live now-playing bar with seek, pause, skip, repeat and volume, synced to everyone in real time
- Paste a link or type a song name, preview the result, then add it to the queue or play it next
- Drag to reorder the queue, search it, shuffle it, undo a removal
- Discord notifications in your music channel when someone queues from the web

**Playlists and discovery**
- Import public Spotify and YouTube / YouTube Music playlists and mixes, choosing which tracks to add
- Personal playlists and favorites for each member
- Server "popular requests", recent plays, and a radio mode that keeps the music going when the queue runs out; songs members request always play before the radio picks

**Lyrics**
- Optional synced lyrics (off by default for each person), from [LRCLIB](https://lrclib.net)
- Automatic timing for music videos with long intros, plus manual nudge and "sync now" controls for any member

**Built for phones and teams**
- Installable as a phone app (PWA), with a layout made for one-handed use
- Light and dark themes with a one-tap switch that remembers your choice
- English and Traditional Chinese, with a per-person language switch
- Stay signed in for 30 days; sessions are stored server-side and can be signed out everywhere
- Owner pages for permissions, the autoplaylist and read-only maintenance status
- Per-server settings: turn vote-to-skip off (anyone with skip permission skips instantly) and pick a fallback channel for web request notifications
- YouTube cookies reload without restarting the bot, so music keeps playing

![Dashboard on a phone](docs/images/dashboard-mobile.png)

## Quick start (Docker)

You need a Linux machine (amd64 or arm64, including Raspberry Pi 64-bit) with Docker and Compose v2.20+, or Docker Desktop.

```sh
mkdir musicbot && cd musicbot
curl -fsSLO https://raw.githubusercontent.com/chy1211/MusicBot/dev/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/chy1211/MusicBot/dev/.env.example -o .env
```

Fill in `.env` with five values from the [Discord Developer Portal](https://discord.com/developers/applications):

| Variable | Where to find it |
| --- | --- |
| `DISCORD_BOT_TOKEN` | Your app > **Bot** > Reset Token (also enable **Server Members** and **Message Content** intents) |
| `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` | Your app > **OAuth2** |
| `OWNER_ID` | Your own Discord user ID (Developer Mode > right-click your profile > Copy User ID) |
| `DASHBOARD_PUBLIC_URL` | `http://localhost:8080` to try it locally, or your HTTPS domain. Add `<this URL>/auth/callback` under **OAuth2 > Redirects** |

Then start it:

```sh
docker compose up -d
```

Open the dashboard URL, sign in with Discord, join a voice channel and run `/summon`. With an HTTPS dashboard URL, the bot also posts the link in the chat when it joins.

The full guide, including inviting the bot, HTTPS with the bundled Caddy profile, cookies and troubleshooting, is in **[docs/install.md](docs/install.md)**.

### Upgrading

```sh
docker compose pull && docker compose up -d
```

Your settings, playlists and login sessions live in the mounted `config/` and `data/` folders and survive upgrades. Images are rebuilt every week with the current yt-dlp.

## Good to know

- **YouTube bot checks.** The Compose file includes the [bgutil PO token provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider), which helps with YouTube's checks but cannot guarantee every request gets through. If you see "Sign in to confirm you're not a bot", see the cookies section of the install guide.
- **Security.** The dashboard listens on `127.0.0.1` only by default. Put it behind HTTPS (Caddy is included as an option) before sharing it. Keep `.env`, `config/` and `data/` private.
- **The dashboard only accepts known services.** Links from services with a dedicated yt-dlp extractor (YouTube, YouTube Music, Spotify, SoundCloud, Bandcamp and others) and plain searches work. Generic websites, direct media URLs, IP addresses and private addresses are rejected, and each lookup has time and size limits (`ResolveTimeoutSeconds` and related keys in `web_dashboard.ini`).
- **Discord commands keep upstream behavior.** `!play <url>` can still make the bot fetch any URL, including addresses on its own network. If people you don't know can use the bot, remove `generic` from `Extractors` for their group in `config/permissions.ini` (this blocks playback, though the bot may still fetch the URL once), or only give queue permissions to people you trust.
- **Discord commands** are unchanged from upstream MusicBot, plus slash commands. See the [upstream command list](https://just-some-bots.github.io/MusicBot/using/commands/) and [`config/example_options.ini`](config/example_options.ini).
- **Not using Docker?** You can still run it like upstream MusicBot (Python 3.10–3.13, ffmpeg, Deno) and enable the dashboard in `config/web_dashboard.ini`. See [docs/web-dashboard.md](docs/web-dashboard.md).

## Project status

This is an **unofficial**, personal fork. It is not affiliated with Just-Some-Bots. One person maintains it in their spare time, on a best-effort basis, with no guaranteed response time.

Upstream development has slowed down: its `dev` branch was last updated in March 2026, and `master` has not changed since November 2024. This fork builds on upstream `dev` and adds:

- Python 3.12 and Deno, which current yt-dlp needs to play YouTube reliably
- Slash commands
- The web dashboard, Docker packaging and a Traditional Chinese translation

Fixes that make sense for everyone are offered back upstream ([#2481](https://github.com/Just-Some-Bots/MusicBot/pull/2481), [#2482](https://github.com/Just-Some-Bots/MusicBot/pull/2482), [#2483](https://github.com/Just-Some-Bots/MusicBot/pull/2483)). If upstream becomes active again, this fork will follow it.

## Credits and license

This project is a fork of [Just-Some-Bots/MusicBot](https://github.com/Just-Some-Bots/MusicBot), which provides the Discord bot itself. Many thanks to its authors and contributors. The web dashboard, Docker packaging and translations were added in this fork.

Released under the [MIT License](LICENSE), the same license as upstream.

Issues and pull requests are welcome.
