#!/bin/sh
# Refreshes data/cookies.txt from a live logged-in Chrome/Chromium session
# MusicBot hot-reloads changed cookies before the next extraction/download.
# Set MUSICBOT_COOKIE_RESTART=1 only for older images requiring a restart.
#
# Configure via env vars if your setup differs from the defaults:
#   CDP_PORT, CDP_HOST, MUSICBOT_DIR, CONTAINER_NAME
set -e

MUSICBOT_DIR="${MUSICBOT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
CONTAINER_NAME="${CONTAINER_NAME:-musicbot}"

cd "$MUSICBOT_DIR/tools"
node sync_cookies.js "$MUSICBOT_DIR/data/cookies.txt"

if [ "${MUSICBOT_COOKIE_RESTART:-0}" = "1" ]; then
    echo "Cookie sync OK, compatibility restart requested for $CONTAINER_NAME..."
    docker restart "$CONTAINER_NAME"
else
    echo "Cookie sync OK; hot reload enabled, container restart skipped."
fi
