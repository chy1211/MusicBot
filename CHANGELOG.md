# Changelog

本檔記錄此專案的重要變更，格式參考 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)。
This file records notable changes, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### 修正 / Fixed

- 解析結果不再保留用不到的字幕清單，網頁點歌較少需要重新解析，佇列存檔變小。
  Discard unused subtitle lists from extraction results, reducing repeat extraction for web requests and shrinking saved queues.

- 開播前先在背景執行緒預讀第一個音訊封包，最多等候 10 秒，避免來源啟動慢造成開頭連續補送；支援 PCM、Opus、響度正規化及重新開啟來源。
  Prepare the first audio frame off the event loop with a 10-second timeout before playback, preventing startup catch-up bursts across PCM, Opus, normalization and source rebuilds.
- Discord 指令與網頁點歌會排在尚未播放的舊式自動播放清單歌曲前面；插到下一首仍優先，目前播放的歌曲不受影響。
  Discord and web requests now precede pending legacy autoplaylist tracks; play-next priority and the currently playing track are preserved.

## [1.0.0] - 2026-10-26

### 新增 / Added

- 第一個正式版本，以 [Just-Some-Bots/MusicBot](https://github.com/Just-Some-Bots/MusicBot) 的 dev 分支為基礎。
  First release, based on the [Just-Some-Bots/MusicBot](https://github.com/Just-Some-Bots/MusicBot) dev branch.
- 網頁控制台：使用 Discord 帳號登入即可查歌、點歌、拖曳排序、跳過和調整播放進度，沿用原有權限群組。
  Web dashboard with Discord login, search, requests, queue reordering, skipping and seeking using the existing permission groups.
- 可安裝成 App（PWA），手機和桌面都能加到主畫面。
  Installable PWA for phone and desktop home screens.
- 個人歌單與收藏，可匯入公開的 Spotify／YouTube 播放清單並重新同步。
  Personal playlists and favorites with public Spotify/YouTube playlist import and resynchronization.
- 歌詞自動對時，也可手動校正時間。
  Automatically synchronized lyrics with manual timing adjustment.
- 電台與推薦：佇列空時自動接歌，成員點歌排在電台歌曲前面。
  Radio and recommendations when the queue is empty, with member requests ahead of radio tracks.
- 四組配色主題：薄荷炭灰、琥珀夜色、深海藍、莓果玫瑰，各有日間與夜間版本，每位成員可自行選擇。
  Four personal color themes with light and dark variants: mint charcoal, amber night, deep ocean blue and berry rose.
- 響度正規化（-16 LUFS），讓每首歌音量接近。
  Loudness normalization at -16 LUFS for consistent track volume.
- Discord 訊息、斜線指令及網頁控制台的繁體中文翻譯，每位成員可自行切換語言。
  Traditional Chinese translations for Discord messages, slash commands and the dashboard, with per-user language selection.
- Docker 首次設定精靈與多架構映像（amd64／arm64），CI 測試通過後自動發佈。
  Docker setup wizard and multi-architecture images (amd64/arm64), published automatically after CI passes.

版本內容依據 [GitHub Release v1.0.0](https://github.com/chy1211/MusicBot/releases/tag/v1.0.0)；安裝方式見 [README](README.md) 與[安裝說明](docs/install.zh-TW.md)。
Release details follow [GitHub Release v1.0.0](https://github.com/chy1211/MusicBot/releases/tag/v1.0.0); see the [README](README.md) and [installation guide](docs/install.zh-TW.md).
