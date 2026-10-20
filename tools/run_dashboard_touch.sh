#!/usr/bin/env bash
# Run from a committed checkout: bash tools/run_dashboard_touch.sh
# Requires Docker (with musicbot:ytdlp-base), Node >=18, npm and Python 3.
# All optional dependencies, browser binaries and build files live in /tmp.
set -euo pipefail
cd "$(dirname "$0")/.."
root=$(mktemp -d /tmp/musicbot-webtest-touch-XXXXXX)
name="${MUSICBOT_TOUCH_PREFIX:-musicbot-webtest-touch}-$(basename "$root" | tr '[:upper:]' '[:lower:]')"
relay_pid=""
cleanup() {
  if [ -n "$relay_pid" ]; then
    kill "$relay_pid" >/dev/null 2>&1 || true
    wait "$relay_pid" >/dev/null 2>&1 || true
  fi
  docker rm -f -v "$name" >/dev/null 2>&1 || true
  docker image rm "$name" >/dev/null 2>&1 || true
  case "$root" in /tmp/musicbot-webtest-touch-*) rm -rf -- "$root";; esac
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir "$root/src"
git archive HEAD | tar -x -C "$root/src"
printf 'FROM musicbot:ytdlp-base\nUSER 0:0\nWORKDIR /musicbot\nCOPY . /musicbot/\nENTRYPOINT []\n' > "$root/src/Dockerfile.touch"
docker build --network none -q -t "$name" -f "$root/src/Dockerfile.touch" "$root/src"
npm install --prefix "$root/deps" --no-audit --no-fund playwright@1.58.2
export NODE_PATH="$root/deps/node_modules"
export PLAYWRIGHT_BROWSERS_PATH="$root/browsers"
"$root/deps/node_modules/.bin/playwright" install chromium
port=$(python3 -c "import socket; s=socket.socket(); s.bind(('localhost',0)); print(s.getsockname()[1]); s.close()")
docker run -d --name "$name" --user 0:0 --network none \
  --entrypoint python3 "$name" -m tools.dashboard_demo \
  --host 0.0.0.0 --port 8080 --public-origin "http://localhost:$port" --fake-login owner
python3 tools/dashboard_demo_relay.py --container "$name" --port "$port" > "$root/relay.log" 2>&1 &
relay_pid=$!
python3 - "$port" <<'PY'
import sys,time,urllib.request
url="http://localhost:"+sys.argv[1]+"/"
for attempt in range(100):
    try:
        with urllib.request.urlopen(url,timeout=1) as response:
            if response.status==200:
                break
    except OSError:
        time.sleep(.2)
else:
    raise SystemExit("Isolated demo did not start")
PY
node tools/test_dashboard_touch.cjs --url "http://localhost:$port" --output "${MUSICBOT_TOUCH_OUTPUT:-$root/shots}" "$@"

node tools/test_dashboard_round26.cjs --url "http://localhost:$port" --output "${MUSICBOT_TOUCH_OUTPUT:-$root/shots}"
