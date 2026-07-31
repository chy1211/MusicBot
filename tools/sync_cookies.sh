#!/bin/sh
# Refreshes data/cookies.txt from a live logged-in Chrome/Chromium session
# and restarts the musicbot container so it picks up the new cookies
# (MusicBot only loads cookies.txt once at startup).
#
# Configure via env vars if your setup differs from the defaults:
#   CDP_PORT, CDP_HOST, MUSICBOT_DIR, CONTAINER_NAME
set -e

MUSICBOT_DIR="${MUSICBOT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
CONTAINER_NAME="${CONTAINER_NAME:-musicbot}"

cd "$MUSICBOT_DIR/tools"
node sync_cookies.js "$MUSICBOT_DIR/data/cookies.txt"

echo "Cookie sync OK, restarting $CONTAINER_NAME to pick up refreshed cookies..."
docker restart "$CONTAINER_NAME"
