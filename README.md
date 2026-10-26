# MusicBot＋網頁控制台 · MusicBot + Web Dashboard

[![CI](https://github.com/chy1211/MusicBot/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/chy1211/MusicBot/actions/workflows/ci.yml)
[![Docker images](https://github.com/chy1211/MusicBot/actions/workflows/docker.yml/badge.svg?branch=dev)](https://github.com/chy1211/MusicBot/actions/workflows/docker.yml)
[![Image](https://img.shields.io/badge/ghcr.io-chy1211%2Fmusicbot-blue)](https://github.com/chy1211/MusicBot/pkgs/container/musicbot)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

點語言標題展開或收合 · Click a language to expand or collapse

<details open>
<summary><h2>繁體中文</h2></summary>

經典的 [Just-Some-Bots MusicBot](https://github.com/Just-Some-Bots/MusicBot)，加上一個網頁控制台，讓 Discord 伺服器裡的每個人都能用瀏覽器或手機點歌。用 Docker 幾分鐘就能裝好。

成員用自己的 Discord 帳號登入，就能查歌、排隊、拖曳排序、控制播放，不用打指令。機器人在 Discord 裡的用法完全不變，網頁也沿用同一套權限群組與限制。

![桌機畫面](docs/images/dashboard-desktop.png)

## 功能

**一起聽**
- 正在播放列：拖進度、暫停、跳過、重複、音量，所有人畫面即時同步
- 貼連結或打歌名，先預覽再加入佇列，或插到下一首
- 佇列可拖曳排序、搜尋、洗牌，刪錯了可以復原
- 有人從網頁點歌時，在音樂頻道發 Discord 通知

**歌單與探索**
- 匯入公開的 Spotify、YouTube／YouTube Music 歌單與合輯，可勾選要加哪幾首
- 每位成員都有自己的歌單與收藏
- 伺服器熱門點播、最近播放，以及佇列播完時自動接歌的電台模式；成員點的歌一律排在電台選的歌前面

**歌詞**
- 同步歌詞，每個人預設關閉，來源為 [LRCLIB](https://lrclib.net)
- MV 前奏較長時會自動對時，所有成員都能手動微調或一鍵對時

**手機與多人使用**
- 可加到手機主畫面當 App 用（PWA），版面為單手操作設計
- 淺色與深色主題，一鍵切換並記住你的選擇
- 英文與繁體中文介面，每個人可自己切換
- 登入可保持 30 天，登入狀態存在伺服器端，可一鍵登出所有裝置
- 擁有者專用頁面：權限、自動播放清單、唯讀維護狀態
- 每個伺服器可分別設定：要不要投票跳過（關閉時有跳過權限的人按一次就跳）、網頁點歌通知的備用頻道
- 更新 YouTube cookie 時不用重開機器人，不會斷歌

![手機畫面](docs/images/dashboard-mobile.png)

## 快速安裝（Docker）

需要一台 Linux 機器（amd64 或 arm64，包含 64 位元樹莓派），裝好 Docker 與 Compose v2.20 以上；或使用 Docker Desktop。

```sh
mkdir musicbot && cd musicbot
curl -fsSLO https://raw.githubusercontent.com/chy1211/MusicBot/dev/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/chy1211/MusicBot/dev/.env.example -o .env
```

到 [Discord 開發者入口](https://discord.com/developers/applications) 取得五個值，填進 `.env`：

| 變數 | 在哪裡找 |
| --- | --- |
| `DISCORD_BOT_TOKEN` | 你的應用程式 > **Bot** > Reset Token，同時開啟 **Server Members** 與 **Message Content** 兩個 intent |
| `DISCORD_CLIENT_ID`／`DISCORD_CLIENT_SECRET` | 你的應用程式 > **OAuth2** |
| `OWNER_ID` | 你自己的 Discord 使用者 ID：開啟開發者模式 > 右鍵自己的頭像 > 複製使用者 ID |
| `DASHBOARD_PUBLIC_URL` | 本機試用填 `http://localhost:8080`，正式使用填你的 HTTPS 網域；並在 **OAuth2 > Redirects** 加入 `<這個網址>/auth/callback` |

想讓介面預設中文、時間用台灣時區，可以再加上：

```sh
DEFAULT_LANGUAGE=zh-TW
TIME_ZONE=Asia/Taipei
```

然後啟動：

```sh
docker compose up -d
```

打開控制台網址，用 Discord 登入，進入語音頻道後執行 `/summon`。控制台網址是 HTTPS 時，機器人進語音也會在聊天室貼出網址。

完整說明在 **[docs/install.zh-TW.md](docs/install.zh-TW.md)**，包含邀請機器人、用內建的 Caddy 設定 HTTPS、cookie 與疑難排解。

### 更新

```sh
docker compose pull && docker compose up -d
```

設定、歌單與登入狀態存在掛載的 `config/`、`data/` 資料夾，更新後都會保留。映像每週會用最新的 yt-dlp 重新建置。

## 注意事項

- **YouTube 機器人檢查**：Compose 內含 [bgutil PO token 服務](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)，能幫忙通過 YouTube 的檢查，但無法保證每次成功。如果出現「Sign in to confirm you're not a bot」，請看安裝說明的 cookie 章節。
- **安全性**：控制台預設只聽 `127.0.0.1`。要分享給別人用之前，請放在 HTTPS 後面（可選用內建的 Caddy）。`.env`、`config/`、`data/` 都不要外流。
- **網頁點歌只接受特定網站**：YouTube、YouTube Music、Spotify、SoundCloud、Bandcamp 等 yt-dlp 有專屬支援的服務，以及關鍵字搜尋。一般網站、直接的音檔網址、IP 與內網位址都會被拒絕；每次解析有時間與流量上限（`web_dashboard.ini` 的 `ResolveTimeoutSeconds` 等設定）。
- **Discord 指令維持原版行為**：`!play <網址>` 仍可讓機器人去抓任意網址，包括它所在網路裡的位址。如果機器人會給不熟的人用，請到 `config/permissions.ini` 把該群組 `Extractors` 裡的 `generic` 拿掉（會擋下播放，但機器人可能仍會先連一次該網址），或只讓信任的人有點歌權限。
- **Discord 指令**與原版 MusicBot 相同，另外加上斜線指令，見[原版指令列表](https://just-some-bots.github.io/MusicBot/using/commands/)與 [`config/example_options.ini`](config/example_options.ini)。
- **不想用 Docker？** 也可以照原版 MusicBot 的方式執行（Python 3.10–3.13、ffmpeg、Deno），再到 `config/web_dashboard.ini` 開啟控制台，見 [docs/web-dashboard.md](docs/web-dashboard.md)。

## 專案狀態

這是**非官方**的個人 fork，和 Just-Some-Bots 沒有關係，由一個人在空閒時維護，盡力而為，不保證回應時間。

原版目前更新得很慢（`dev` 分支最後一次更新是 2026 年 3 月，`master` 自 2024 年 11 月起沒有再變動）。這個 fork 以原版 `dev` 為基礎，另外補上：

- Python 3.12 與 Deno：新版 yt-dlp 需要它們才能正常播放 YouTube
- 斜線指令
- 網頁控制台、Docker 打包與繁體中文翻譯

能通用的修正會送回原版（[#2481](https://github.com/Just-Some-Bots/MusicBot/pull/2481)、[#2482](https://github.com/Just-Some-Bots/MusicBot/pull/2482)、[#2483](https://github.com/Just-Some-Bots/MusicBot/pull/2483)）。如果原版恢復活躍，這個 fork 會跟著同步。

## 致謝與授權

本專案 fork 自 [Just-Some-Bots/MusicBot](https://github.com/Just-Some-Bots/MusicBot)，Discord 機器人本體出自原作者，感謝原作者與所有貢獻者。網頁控制台、Docker 打包與翻譯是這個 fork 新增的。

授權與原版相同，採 [MIT 授權](LICENSE)。

歡迎開 issue 或送 pull request。

</details>

<details>
<summary><h2>English</h2></summary>

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

</details>
