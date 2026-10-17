# Round 13 validation

Branch: feature/round13-packaging, based on dev b7504db. No deployment or push.
This document records implementation testing; independent acceptance belongs to
the maintainer.

## Commits before validation

- d48b4e8: unified player controls and bounded tab geometry (priority item 0).
- 33cc47f: English / Traditional Chinese dashboard and existing Discord gettext.
- 368b11d: first-run Docker installer, non-root runtime, health endpoint and docs.
- 0175db9: CI and weekly multi-platform GHCR publishing definitions.
- The commit containing this report includes the final regression fixes.

## Phone UI

All five player controls share player-control: 52 x 40 px, radius 20 px.
Pressed / selected states change color and material only. Both phone viewport
sizes retain the existing 112 px player height. Desktop controls use the same
geometry.

The old cubic-bezier(.2,.9,.3,1.2) spring overshot the target, while the selected
pseudo-element was not clipped. Hidden first paints, compact changes and font
layout changes also lacked complete initialization / remeasurement handling.
The final pill reads actual button offsets and sizes, clamps to container client
dimensions and padding, clips to the outer rounded shape, applies size changes
immediately and uses a bounded transform easing. It waits for valid geometry
before showing or animating. ResizeObserver covers groups and buttons; resize,
orientation, visualViewport, fonts.ready and compact transitions trigger updates.

Screenshots: /tmp/musicbot-r13-phone-shots/
- before-390x844-* and before-375x667-*: baseline.
- after-390x844-4tabs-normal-{play,library,popular,admin}.png
- after-375x667-4tabs-normal-{play,library,popular,admin}.png
- after-*-3tabs-*, after-*-compact-*: additional layout cases.
- language-en-390x844.png and language-zh-TW-390x844.png.
- readme-en-390x844.png and readme-en-1440x1000.png:
  demo helper links hidden for these captures only.
- geometry JSON and animation-bounds.json accompany the pictures.

Browser checks: 28 selected-tab cases and
176 mid-animation frames stayed within the container.
English / zh-TW login, authenticated pages, localStorage preference and reload
switching passed. The browser was headless Chromium.

## Localization

590 matching keys in web/i18n/en.json and zh-TW.json.
All frontend visible Chinese literals were removed from production JS/HTML.
User / server / track names, lyrics and demo fixture metadata retain their
original language. Reserved Favorites labels are translated at render time.

Backend errors use the same catalogs, selected per request with a ContextVar;
the dashboard never returns arbitrary exception text. EventSource carries a
validated public language option. Discord notifications use the existing
MusicBot gettext per-guild language, including the summon URL message.
UI time formatting uses Intl and the configured IANA time zone, default UTC.
See dashboard-languages.md for extension instructions.

## Docker / first-run install

The shared image contains the bot, web assets, ffmpeg, Deno, yt-dlp/EJS and
bgutil plugin. Compose adds bgutil-provider and one-time config-init; optional
Caddy provides HTTPS. Bot ports are loopback-only by default. The config, data,
audio_cache and logs directories are bind mounts. Runtime UID/GID is 1000:1000;
config-init uses root only to initialize the mounted directory ownership.

Environment variables generate options.ini / web_dashboard.ini only if each
file does not exist. Existing ini bytes are preserved. SessionSecret is random.
Missing required variables cause init exit 78, with bilingual portal guidance.
MusicBot depends on successful initialization, avoiding a bot restart storm.

Fresh-user simulation began with only docker-compose.yml and .env under
/tmp/musicbot-webtest-install-r13. The image was built locally and selected via
MUSICBOT_IMAGE. A test-only override disabled networking for all three services
and removed port publication. No real credentials or Discord connection used.

Results:
- Missing variables: config-init exit 78, RestartCount 0; bot stayed unstarted.
- Complete fake environment: ini fields and random secret correct.
- GET /healthz and the login page: 200, checked inside the network-none container.
- Actual process UID: 1000. Docker health: healthy, RestartCount 0.
- Discord connectivity failure: clear English retry log; no token/secret value.
- Re-running config generation preserved both ini file hashes.

Health is listener liveness, not Discord or playback readiness.

Measured native arm64 image: 577,483,514 bytes (577.48 MB).
Existing production image musicbot:dev-zhtw-ytdlp: 910,714,660
bytes (910.71 MB). Reduction: 36.59%.
The existing ytdlp-base was 910,552,288 bytes. Production images were read only.

## Commands and final results

- python -m unittest discover -s tests -p 'test_*.py': 486 passed, 0 failed.
- node --test tests/test_*.cjs: 156 passed, 0 failed.
- python -m tools.test_compound_link: 16 passed, 0 failed.
- python -m tools.check_dashboard_i18n: 590 complete matching keys, no hardcoded
  production frontend Chinese; placeholder sets match.
- actionlint v1.7.12 .github/workflows/ci.yml .github/workflows/docker.yml: passed.
- docker build: native linux/arm64 passed; runtime user verified as 1000:1000.

Regression fixes include distinguishing removal undo metadata from batch-play
summary counts (preventing a removal KeyError), independent translated web
messages versus native gettext notifications, and explicit language/time-zone
test fixtures. No original behavior tests were removed.

Verification logs and JSON: /tmp/musicbot-webtest-r13/
Disposable containers, named test images and the fresh installer directory were
removed. Downloaded test dependencies were removed. Screenshots and logs remain
for maintainer review. The feature worktree is removed after this commit.

## Actions and first publication

CI runs backend, frontend, compound-link and locale checks on push / PR.
Docker publishing targets dev pushes, v* tags and Sunday 04:15 UTC. Buildx builds
amd64 + arm64; tags are latest for dev / scheduled builds, the v* tag for releases,
and sha- plus seven characters. Scheduled builds bypass dependency cache.
Only GITHUB_TOKEN packages:write is required. No workflow was executed or
registry authentication performed here. After the maintainer pushes and enables
Actions, make the first GHCR musicbot package public.

## README handoff

README.md was not changed. It should link install.md, install.zh-TW.md and
dashboard-languages.md, show downloading Compose and .env.example, the five
required variables, docker compose up -d, the Discord invite / intents / OAuth
callback steps, optional Caddy HTTPS, and docker compose pull followed by up -d.
Use the readme-en-* screenshots above. Emphasize easy installation and use,
preserve Just-Some-Bots attribution and MIT licensing.

## Known limits

- No real iPhone Safari re-test, real Discord OAuth/playback, YouTube downloads,
  public ACME certificate issuance or optional online startup update was run.
- Native arm64 was built and tested; amd64 is configured but awaits the first
  multi-platform Actions build.
- Workflows passed actionlint but await their first actual GitHub run.
- Prebuilt public pulls require the maintainer's first publication and package
  visibility change. Existing custom deployments are not migrated.

## Changed paths

docker-compose.example.yml is removed in favor of docker-compose.yml.

- .dockerignore
- .env.example
- .github/workflows/ci.yml
- .github/workflows/docker.yml
- .gitignore
- Caddyfile
- Dockerfile
- config/example_web_dashboard.ini
- docker-compose.example.yml
- docker-compose.yml
- docker-entrypoint.sh
- docs/dashboard-languages.md
- docs/install.md
- docs/install.zh-TW.md
- docs/round13-validation.md
- docs/web-dashboard.md
- i18n/zh_TW/LC_MESSAGES/musicbot_messages.po
- musicbot/bot.py
- musicbot/downloader.py
- musicbot/web/admin.js
- musicbot/web/dashboard.css
- musicbot/web/dashboard.js
- musicbot/web/i18n.js
- musicbot/web/i18n/en.json
- musicbot/web/i18n/zh-TW.json
- musicbot/web/index.html
- musicbot/web/library.js
- musicbot/web/manifest.webmanifest
- musicbot/web/offline.html
- musicbot/web/permissions.js
- musicbot/web/popular.js
- musicbot/web/pwa.js
- musicbot/web/sw.js
- musicbot/web_dashboard.py
- musicbot/web_dashboard_activity.py
- musicbot/web_dashboard_admin.py
- musicbot/web_dashboard_auth.py
- musicbot/web_dashboard_events.py
- musicbot/web_dashboard_i18n.py
- musicbot/web_dashboard_imports.py
- musicbot/web_dashboard_library.py
- musicbot/web_dashboard_maintenance.py
- musicbot/web_dashboard_permissions.py
- musicbot/web_dashboard_radio.py
- musicbot/web_dashboard_spotify.py
- musicbot/web_dashboard_undo.py
- requirements.txt
- tests/dashboard_i18n_fixture.cjs
- tests/test_container_config.py
- tests/test_web_dashboard.py
- tests/test_web_dashboard_demo.py
- tests/test_web_dashboard_discord.py
- tests/test_web_dashboard_frontend.cjs
- tests/test_web_dashboard_health.py
- tests/test_web_dashboard_i18n.cjs
- tests/test_web_dashboard_i18n.py
- tests/test_web_dashboard_layout.cjs
- tests/test_web_dashboard_phone.cjs
- tests/test_web_dashboard_popular.cjs
- tests/test_web_dashboard_pwa.py
- tests/test_web_dashboard_round8.py
- tests/test_web_dashboard_round9.py
- tools/check_dashboard_i18n.py
- tools/container_config.py
- tools/container_healthcheck.py
