"""Static dashboard pages and assets."""
from pathlib import Path

from aiohttp import web


class DashboardStaticRoutes:

    def _static_root(self):
        # Keep STATIC as the facade patch point used by tests and dev setups.
        from .. import web_dashboard

        return Path(web_dashboard.STATIC) / "dist"


    async def pwa_asset(self, request):
        root = self._static_root()
        name = request.path.lstrip("/")
        if not name or Path(name).name != name or name in (".", ".."):
            raise web.HTTPNotFound()
        path = root / name
        if not path.is_file():
            raise web.HTTPNotFound()
        content_types = {
            ".webmanifest": "application/manifest+json",
            ".png": "image/png",
            ".html": "text/html",
            ".js": "text/javascript",
            ".css": "text/css",
        }
        response = web.Response(
            body=path.read_bytes(),
            content_type=content_types.get(Path(name).suffix, "application/octet-stream"),
        )
        if name == "sw.js":
            response.headers["Cache-Control"] = "no-cache"
        return response


    async def favicon(self, _request):
        root = self._static_root()
        path = root / "favicon.svg"
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.Response(text=path.read_text(encoding="utf-8"), content_type="image/svg+xml")


    async def healthz(self, _request):
        return web.json_response({"status": "ok"})


    async def ui_config(self, _request):
        return web.json_response(
            {"default_language": self.config.default_language, "time_zone": self.config.time_zone}
        )


    async def language_catalog(self, request):
        from ..web_dashboard_i18n import catalog

        locale = request.match_info["locale"]
        if locale not in ("en", "zh-TW"):
            raise web.HTTPNotFound()
        return web.json_response(catalog(locale))


    async def index(self, _request):
        root = self._static_root()
        path = root / "index.html"
        if not path.is_file():
            return web.Response(status=503, text="dashboard frontend is not built\n", content_type="text/plain")
        return web.Response(text=path.read_text(encoding="utf-8"), content_type="text/html")


    async def asset(self, request):
        root = self._static_root()
        name = request.path.lstrip("/")
        if not name or Path(name).name != name or name in (".", ".."):
            raise web.HTTPNotFound()
        path = root / name
        if not path.is_file() and name in (
            "dashboard.js", "admin.js", "library.js", "popular.js", "permissions.js"
        ) and (root / "index.html").is_file():
            return web.Response(
                text="if (!document.getElementById('app')) location.replace('/');",
                content_type="text/javascript",
            )
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.Response(
            text=path.read_text(encoding="utf-8"),
            content_type="text/css" if name.endswith(".css") else "text/javascript",
        )


    async def icon_asset(self, request):
        name = request.match_info.get("name", "")
        if name not in {
            "history-add.svg", "history-heart.svg", "history-heart-filled.svg", "transport-play.svg",
            "transport-pause.svg", "transport-skip.svg", "transport-repeat.svg",
        }:
            raise web.HTTPNotFound()
        root = self._static_root() / "icons"
        path = root / name
        if path.resolve().parent != root.resolve() or not path.is_file():
            raise web.HTTPNotFound()
        return web.Response(body=path.read_bytes(), content_type="image/svg+xml")


    async def hashed_asset(self, request):
        name = request.match_info.get("name", "")
        if not name or Path(name).name != name or name in (".", ".."):
            raise web.HTTPNotFound()
        asset_root = self._static_root() / "assets"
        path = asset_root / name
        if path.resolve().parent != asset_root.resolve() or not path.is_file():
            raise web.HTTPNotFound()
        response = web.FileResponse(path)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
