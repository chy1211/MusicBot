# Cookie sync tool

YouTube now requires an authenticated session for most playback (see
[Intents docs](../docs) / yt-dlp's cookie guidance). This tool keeps
`config/data/cookies.txt` fresh by reading cookies out of an **already
logged-in** Chrome/Chromium instance over the Chrome DevTools Protocol
(CDP), instead of storing a password or re-logging-in anywhere. It never
authenticates on its own -- if the browser session expires, the sync will
simply fail loudly and leave your last-good `cookies.txt` alone.

## Prerequisites

1. A Chrome/Chromium browser, running somewhere reachable from this script,
   started with remote debugging enabled, e.g.:
   ```
   chromium --remote-debugging-port=9224 --remote-debugging-address=127.0.0.1
   ```
   (Keep the debugging port bound to localhost / a private network -- it
   grants full control of the browser to anyone who can reach it.)
2. That browser logged into the Google/YouTube account you want MusicBot to
   use. Use a secondary/throwaway account, not your primary one -- this
   account's traffic pattern (automated song lookups) can get flagged.

## Setup

```
cd tools
npm install
node sync_cookies.js /path/to/musicbot/data/cookies.txt
```

Or use the wrapper, which also restarts the `musicbot` container afterward
(MusicBot only reads `cookies.txt` once at startup, so a refreshed file on
disk needs a restart to take effect):

```
./sync_cookies.sh
```

Environment variables (all optional):

| Var | Default | Meaning |
|---|---|---|
| `CDP_HOST` | `127.0.0.1` | Host where the browser's CDP endpoint listens |
| `CDP_PORT` | `9224` | CDP port |
| `MUSICBOT_DIR` | parent of `tools/` | Root of the MusicBot checkout (`sync_cookies.sh` only) |
| `CONTAINER_NAME` | `musicbot` | Docker container to restart after a sync (`sync_cookies.sh` only) |

## Scheduling

Pick whichever matches your platform -- neither is bundled/required, this
is just a plain script you can run however you like.

**cron** (works on any Unix-like system regardless of init system):
```
# Sync cookies daily at 04:00
0 4 * * * /path/to/musicbot/tools/sync_cookies.sh >> /path/to/musicbot/logs/cookie-sync.log 2>&1
```

**systemd timer** (Linux with systemd): see `tools/systemd/` for an example
`.service` + `.timer` pair. Adjust the paths/user inside before installing:
```
sudo cp tools/systemd/musicbot-cookie-sync.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now musicbot-cookie-sync.timer
```

There's nothing special about a daily interval -- pick whatever cadence
suits how often your session tends to go stale.
