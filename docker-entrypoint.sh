#!/bin/sh
set -eu
umask 077
cd /musicbot
python3 -m tools.container_config
if [ "${YTDLP_AUTO_UPDATE:-false}" = "true" ]; then
    echo "Updating yt-dlp and its provider plugin in the writable data volume..."
    if python3 -m pip install --disable-pip-version-check --no-cache-dir --upgrade \
        --target /musicbot/data/runtime-packages "yt-dlp[default]" bgutil-ytdlp-pot-provider >/dev/null 2>&1; then
        export PYTHONPATH="/musicbot/data/runtime-packages${PYTHONPATH:+:$PYTHONPATH}"
        echo "yt-dlp update completed."
    else
        echo "yt-dlp update failed; using the packages bundled in this image."
    fi
fi
exec python3 run.py --no-checks --no-install-deps "$@"
