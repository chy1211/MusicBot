# syntax=docker/dockerfile:1
FROM python:3.12-alpine AS wheels
RUN apk add --no-cache build-base libffi-dev libsodium-dev
WORKDIR /build
COPY requirements.txt .
# The scheduled workflow disables cache, refreshing yt-dlp and the provider plugin.
RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

FROM python:3.12-alpine AS runtime
LABEL org.opencontainers.image.source="https://github.com/chy1211/MusicBot" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.description="MusicBot with an accessible multilingual web dashboard"
RUN apk add --no-cache ca-certificates deno ffmpeg opus libffi libsodium tzdata \
    && addgroup -g 1000 musicbot && adduser -D -u 1000 -G musicbot musicbot
COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels
WORKDIR /musicbot
COPY . .
# Only public examples enter the image (also enforced by .dockerignore).
RUN mkdir -p sample_config audio_cache config data logs \
    && cp config/example_* sample_config/ \
    && python3 tools/po2mo.py i18n/zh_TW/LC_MESSAGES/musicbot_messages.po \
    && python3 tools/po2mo.py i18n/zh_TW/LC_MESSAGES/musicbot_logs.po \
    && chown -R musicbot:musicbot /musicbot \
    && chmod 755 docker-entrypoint.sh
ENV APP_ENV=docker PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/musicbot DASHBOARD_EARLY_START=true YTDLP_AUTO_UPDATE=false
USER 1000:1000
VOLUME ["/musicbot/config", "/musicbot/data", "/musicbot/audio_cache", "/musicbot/logs"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python3", "-m", "tools.container_healthcheck"]
ENTRYPOINT ["/bin/sh", "/musicbot/docker-entrypoint.sh"]
