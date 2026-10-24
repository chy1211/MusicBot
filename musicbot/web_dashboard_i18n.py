"""Shared dashboard catalogs; request context never changes Discord gettext."""
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
import json
from aiohttp import web

LANGUAGE = ContextVar("dashboard_language", default="zh-TW")
SUPPORTED = ("en", "zh-TW")

@lru_cache(maxsize=16)
def catalog(language):
    return json.loads((Path(__file__).resolve().parents[1] / "frontend" / "public" / "i18n" / (language + ".json")).read_text(encoding="utf-8"))

def language_tag(value):
    value = str(value).lower().replace("_", "-")
    if value.startswith("en"): return "en"
    if value.startswith("zh"): return "zh-TW"
    return None

def message(key, **params):
    text = catalog(LANGUAGE.get()).get(key) or catalog("en").get(key) or key
    # Replace only named slots. User text never becomes a format string.
    import re
    return re.sub(r"\{(p\d+)\}", lambda m: str(params.get(m[1], m[0])), text)

def request_language(request, default):
    explicit = language_tag(request.query.get("lang", "")) if request.path.endswith("/events") else None
    if explicit: return explicit
    explicit = language_tag(request.headers.get("X-Dashboard-Language", ""))
    if explicit: return explicit
    for value in request.headers.get("Accept-Language", "").split(","):
        value = language_tag(value.split(";")[0].strip())
        if value: return value
    return default

@web.middleware
async def localized_request(request, handler):
    dashboard = request.app[DASHBOARD_KEY]
    language = request_language(request, dashboard.config.default_language)
    token = LANGUAGE.set(language)
    try:
        response = await handler(request)
        response.headers["Content-Language"] = language
        response.headers["Vary"] = "Accept-Language, X-Dashboard-Language"
        return response
    finally:
        LANGUAGE.reset(token)

DASHBOARD_KEY = web.AppKey("dashboard_i18n", object)
