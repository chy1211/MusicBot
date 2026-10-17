# 用 Docker 安裝 MusicBot

這個安裝包包含 Just-Some-Bots 音樂機器人與網頁控制台，內建 Python、
ffmpeg、Deno、yt-dlp、EJS 與 bgutil 外掛。映像支援 Linux amd64／arm64，
包含 64 位元樹莓派與 Oracle ARM。請先安裝 Docker Engine＋Compose v2.20+
或 Docker Desktop。[English](install.md)｜[多語系說明](dashboard-languages.md)

## 快速開始

建立 Discord 應用程式後，安裝約需五分鐘。在新的資料夾下載兩份檔案：

~~~sh
mkdir musicbot
cd musicbot
curl -fsSLO https://raw.githubusercontent.com/chy1211/MusicBot/dev/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/chy1211/MusicBot/dev/.env.example -o .env
~~~

Windows PowerShell 請把上面的 curl 改成 curl.exe。

1. 到 [Discord Developer Portal](https://discord.com/developers/applications)
   建立應用程式，Bot > Reset Token 取得 Bot Token，填入
   DISCORD_BOT_TOKEN。開啟 Server Members Intent 與 Message Content Intent。
2. OAuth2 頁複製 Client ID、Client Secret，分別填入 DISCORD_CLIENT_ID、
   DISCORD_CLIENT_SECRET。Client Secret 與 Bot Token 是兩種不同憑證。
3. Discord「使用者設定 > 進階」開啟開發者模式，右鍵自己的個人檔案，
   複製使用者 ID 填入 OWNER_ID；不要填應用程式 ID。
4. 本機試用可設 DASHBOARD_PUBLIC_URL=http://localhost:8080，並在 OAuth2 >
   Redirects 新增 http://localhost:8080/auth/callback。公開伺服器請改用自己的
   HTTPS 網域，以及相同網址的 /auth/callback。
5. OAuth2 > URL Generator 勾 bot、applications.commands；給予檢視頻道、
   傳送訊息、讀取歷史訊息、連線與說話權限，使用產生的網址邀請機器人。
   然後啟動：

~~~sh
docker compose up -d
docker compose logs --tail 50 config-init musicbot
~~~

開啟設定的網址，用 Discord 登入、加入語音頻道，再用 /summon 叫入機器人。
點歌沿用 MusicBot 原有權限。新加入語音時，/summon 會順便貼出 PublicURL；
移動頻道不重複貼。須使用 Discord 登入模式與 HTTPS 網址，通知語言跟隨
該伺服器的 gettext 語系，不會寫死任何部署網址。

使用預建 ghcr.io/chy1211/musicbot:latest。一次性的 config-init 先驗證設定，
建立 ini 與資料夾權限，再讓非 root 的 MusicBot（預設 UID/GID 1000）啟動。
缺變數時會以非零退出碼列出英文＋中文提示及取得憑證的步驟；MusicBot 等待
初始化成功，避免缺設定造成無限重啟。補齊 .env 後再跑 up -d 即可。

## 服務、連接埠與資料

- musicbot：機器人與控制台；只綁 127.0.0.1:8080，公開使用請放 HTTPS 反向代理。
- bgutil-provider：預設啟用，為 YouTube 產生 PO token，外掛使用內網
  http://bgutil-provider:4416。可改善 YouTube 相容性，仍不保證一定通過反機器人
  檢查。這個服務沒有登入機制，4416 不對外開放。
- config-init：一次性初始化，停用 restart，不需要網路。
- caddy：選用的自動 HTTPS profile。

config、data、audio_cache、logs 四個本機資料夾掛載到容器，升級不會清除。
.env、正式 ini、cookie 與 session 資料都應保持私密。PUID/PGID 可改成其他正整數；
搬入既有資料前，請先讓該使用者有讀寫權限。既有檔案不會被初始化程序重新改權限。

GET /healthz 不需登入，只回傳 {"status":"ok"}，表示控制台程序仍在運作，
不代表 Discord 已連線。Discord 尚未就緒時，受保護 API 會回安全的不可用提示。
停用控制台時，healthcheck 對仍在執行的容器回成功，不表示有網頁監聽。

## 環境變數與設定優先序

首次啟動必填 DISCORD_BOT_TOKEN、OWNER_ID；啟用控制台（預設 true）還須填
DASHBOARD_PUBLIC_URL、DISCORD_CLIENT_ID、DISCORD_CLIENT_SECRET。

選用項目：SPOTIFY_CLIENT_ID／SPOTIFY_CLIENT_SECRET、DEFAULT_LANGUAGE（預設 en，
可用 zh-TW）、TIME_ZONE（預設 UTC，可改 Asia/Taipei）、COMMAND_PREFIX（!）、
YTDLP_AUTO_UPDATE（false）、DASHBOARD_ENABLED（true）、PUID／PGID（1000）、
DASHBOARD_PORT（8080）、MUSICBOT_IMAGE（預建映像或自己的本機映像）。

**已存在的 options.ini／web_dashboard.ini 永遠不覆蓋。** 環境變數只在對應檔案
不存在時產生設定；之後修改 .env 不會改動既有 ini。需要調整時自己編輯 ini 後
重新建立容器，或先把單一 ini 移到私密備份再重新產生。其他檔案保持原樣。
SessionSecret 自動隨機產生；目前的登入 session 使用 data 裡的 opaque session，
不依賴這個舊設定簽章。

控制台語言選擇會存到 localStorage，優先於瀏覽器語系，再退回伺服器預設。
日期時間用 Intl 與伺服器指定時區。Discord 訊息仍用既有的伺服器語言指令設定。

## 公開 HTTPS：選用 Caddy

網域 A/AAAA 記錄指向主機，讓 80／443 可連線。下載 Caddyfile，將 .env 的
DASHBOARD_PUBLIC_URL 改成自己的 HTTPS 網址（例如 https://music.example.com），
Discord Redirect 也加上對應的 /auth/callback。若 ini 已存在，PublicURL 也要自己改。

~~~sh
curl -fsSLO https://raw.githubusercontent.com/chy1211/MusicBot/dev/Caddyfile
docker compose --profile caddy up -d
~~~

Caddy 會讀 .env 的網址，自動申請憑證並代理到 musicbot:8080；憑證存於
caddy_data／caddy_config named volumes。也可用其他 HTTPS 反向代理。
請保留控制台的 loopback 綁定。

## Cookies（選用）

遇到「Sign in to confirm you're not a bot」時，可從自己控制的瀏覽器工作階段
匯出 Netscape 格式 cookies.txt，放在 ./data/cookies.txt，給機器人 UID 讀取權限，
再重新建立容器；機器人已內建讀取這個路徑。cookie 等同密碼，別提交或分享。
建議使用低價值的小帳號，自動存取可能導致帳號限制。

repo 的 tools/sync_cookies.* 是進階、選用腳本，必須自行檢查並配合環境調整，
不屬於預設安裝流程；預設不會自動讀取瀏覽器 cookie。

## 升級與復原

~~~sh
docker compose pull
docker compose up -d
~~~

設定、歌單與登入資料都在掛載資料夾裡，換映像不會遺失；升級前建議備份
config 與 data。要保留 Caddy 憑證就不要用 down -v。既有部署的 VPN、cookie
同步與更新腳本獨立運作，這份 compose 不會遷移它們。

自行建置：下載完整 repo，把共用 compose 區塊的 build: . 取消註解，
MUSICBOT_IMAGE 改成本機映像名，再執行 docker compose build && docker compose up -d。

映像每週重建以更新 yt-dlp 與外掛。預設不在啟動時更新，方便重現版本且較快啟動。
YTDLP_AUTO_UPDATE=true 時，pip 會把新版裝進可寫的 data/runtime-packages，
且只在該次執行載入；需要網路，也可能遇到上游新版問題。更新失敗會使用映像內
套件。改回 false 並重建容器就只用映像版本。

維護者首次啟用：開啟 Docker GitHub Actions，第一次建置推送成功後，到 GitHub
package 設定把 musicbot 改成 public，使用者才能免登入下載。僅使用 GITHUB_TOKEN
的 packages:write 權限，不需新增 secret。
