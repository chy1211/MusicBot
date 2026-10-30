# Changelog

本檔記錄此專案的重要變更，格式參考 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)。
This file records notable changes, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [1.1.0] - 2026-10-31
+
+### 新增 / Added
+
+- 搜尋播放清單可匯入既有或新個人歌單，使用一次性預覽與持久化交易，保留順序、去重與200首限制；頁尾操作說明左側保留原文，右側顯示v1.1.0。
+  Import selected search-playlist tracks into an existing or new personal playlist using one-time previews and durable transactions; show the release version at the right of the identity note.
+- 任一個人歌單的儲存狀態以實心愛心顯示；改善加入提示、桌面音波、手機資訊卡與空佇列控制。新增可選GC實際時序與有界來源事件，尚未觀測實際socket送包。
+  Reflect membership in any personal playlist, refine responsive controls and add optional bounded source/GC timelines without claiming socket-send or listener measurements.
+
+
### 修正 / Fixed

- 新增可選的來源讀取節奏診斷，獨立統計短間隔並在停止及換來源時保留摘要；不改音訊節奏，尚不量測封包送出或收聽端。改善歌詞快取優先查詢、對時信心與桌面清單布局。
  Add optional source-read cadence diagnostics with independent short-interval statistics and summaries for replaced sources, without changing audio pacing or claiming packet-send/listener measurements. Improve cache-first lyrics, alignment confidence and compact desktop playlists.
- 頁面與管理資料改為按需載入，隔離頂部搜尋狀態，修正輪詢逾時後重試、隱藏頁時鐘及全域存歌單流程。歌單磁碟交易移至工作執行緒並保留取消時的鎖定，傳統提取入口增加網址預檢，歌詞清理在節流時保留容量保護，Spotify 多候選保守匹配。
  Load route views on demand, isolate header search, and fix resolution polling retries, hidden-page clocks and global playlist saves. Move playlist transactions off the event loop while retaining locks through cancellation; preflight native extraction URLs, retain lyric cache bounds during throttled pruning, and conservatively rank Spotify candidates.

- 恢復分段導覽與鍵盤快捷鍵入口，補上手機橫向收藏及向量播放控制；桌面和平板通知避開搜尋欄並置於播放列上方。所有播放狀態優先顯示最近播過，再顯示操作紀錄，移除佇列內重複紀錄。全域 CSS 依功能重新命名，並在 CI 執行跨尺寸瀏覽器回歸測試。
  Restore segmented navigation and shortcut help, add landscape favorites and vector controls, and place desktop/tablet notifications above the dock. Show recent history before activity in every playback state without duplicating it inside the queue. Name global styles by feature and run responsive browser regressions in CI.

- 以實際下載與檔案指紋憑證驗證未知大小音檔快取，依登入世代與解析設定短期重用完整單曲資訊；加入手動頂部搜尋、下一首卡片、手機橫向控制與兩款配色。
  Verify unknown-size audio caches with real-transfer completion receipts and reuse complete track metadata within cookie and option boundaries. Add manual header search, an up-next card, touch landscape controls and two palettes.

- 首首歌未命中分析快取時使用即時音量正規化，避免等待全曲掃描；後續分析結果以音檔指紋快取。修正管理頁分區切換、概況更新與跳過提示，整合聽眾與點播者，改善觸控橫放及更新按鈕位置。
  Start an uncached first track with one-pass normalization and cache later measurements by file identity. Fix admin section navigation, health refresh and skip messages, integrate listeners and requester details, and improve touch landscape and update controls.

- 管理頁分組顯示設定與即時音訊健康；切換伺服器清除舊設定與草稿，載入失敗或未變更時停用儲存，自動播放清單優先顯示已有曲目資料。
  Group administration settings and live audio health, clear stale settings and drafts on guild changes, disable saves for unloaded or unchanged settings, and enrich autoplaylists from existing metadata.

- 平板橫直向的側欄依播放列實際高度預留間距，避免兩者重疊。
  Reserve sidebar clearance from the measured playback bar height in tablet portrait and landscape layouts.

- 換歌準備下載或音源時保留下一首的封面與歌名，顯示準備中；停止、失敗或斷線時清除過場提示。
  Keep the next track's cover and title visible while preparing playback, and clear the transition hint on stop, failure or disconnection.

- 事件監聽器統一在所屬事件迴圈執行，非同步單次監聽器不再被遺漏；Opus 格式偵測保留音量、速度與正規化效果，必要時重新編碼，暫停中及連續調整仍保留進度與暫停狀態。
  Dispatch event listeners on their owning loop and await asynchronous once callbacks; preserve volume, speed and normalization with Opus probing by re-encoding filtered audio, retaining position and pause state across repeated adjustments.

- 下載、格式偵測與音源準備期間的停止、跳過和連續調整進度會依最後有效的操作執行；舊任務與音源回呼不再覆蓋新的播放狀態，暫停中調整進度仍保持暫停。
  Respect the latest stop, skip and seek request during download, codec probing and source preparation; prevent stale tasks and audio callbacks from overwriting replacement playback, and preserve paused seeks.

## [1.0.1] - 2026-10-29

### 變更 / Changed

- 網頁控制台「最近播過」的按鈕改成按一下直接加入佇列，不用再經過搜尋預覽。
  Recently played buttons in the web dashboard now add the song to the queue in one click instead of opening a search preview.

### 修正 / Fixed

- 準備下一首時若語音已斷線，播放器會安靜停止並把該首留在佇列最前面，不再留下錯誤紀錄。
  Stop the player quietly when voice disconnects while preparing the next song, keeping it at the front of the queue for reconnection without logging an error.
- 解析結果不再保留用不到的字幕清單，網頁點歌較少需要重新解析，佇列存檔變小。
  Discard unused subtitle lists from extraction results, reducing repeat extraction for web requests and shrinking saved queues.
- 開播前先在背景預讀前幾個音訊封包，減少來源暖機造成的開頭連續補送；最多等候 10 秒，封包不足或逾時時仍會播放已讀取的內容，支援 PCM、Opus、響度正規化及重新開啟來源。
  Buffer the first few audio packets in the background before playback to reduce startup catch-up bursts; wait up to 10 seconds and play any packets already read if the source ends or times out, across PCM, Opus, normalization and source rebuilds.
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

- R21 search previews rank existing provider candidates without extra extraction, deduplicate trusted media identities, and show unverified title/version labels; recent-history actions use accessible 44px icons.
- R21 搜尋預覽只排序既有候選、依可信媒體身分去重並標示來源與未驗證的標題版本；最近播過的操作改用可及性圖示。
