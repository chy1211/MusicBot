"""Web-only extraction policy; native Discord commands keep their own clients."""
from contextvars import ContextVar
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit
import re

from yt_dlp import YoutubeDL
from yt_dlp.extractor import gen_extractor_classes

WEB_EXTRACTION = ContextVar("dashboard_extraction", default=False)
SEARCH = re.compile(r"(?:yt|gv|yv|sc|bili|nico)search[0-9]*:")


class UnsupportedDashboardURL(ValueError):
    """The web entry would require an unrestricted extractor."""


@lru_cache(maxsize=1)
def dedicated_extractors():
    return tuple(ie for ie in gen_extractor_classes()
                 if ie.IE_NAME.lower() != "generic" and ie._ENABLED)


def normalize_query(value):
    """Normalize HTTP URLs without DNS or network I/O; text remains search text."""
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    if value.startswith("//"):
        value = "https:" + value
    if re.match(r"^(?:www\.|(?:music\.)?youtube\.com/|youtu\.be/|open\.spotify\.com/|soundcloud\.com/|[a-z0-9-]+\.bandcamp\.com/)", value, re.I):
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ("http", "https"):
            if "://" in value or parsed.scheme.lower() in ("file", "data", "javascript", "spotify", "mbapl"):
                raise UnsupportedDashboardURL()
            return value
        if (not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 80, 443) or "\\" in value
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
            raise UnsupportedDashboardURL()
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        netloc = host + (":" + str(parsed.port) if parsed.port else "")
        canonical = urlunsplit((parsed.scheme.lower(), netloc, parsed.path, parsed.query, ""))
        if not any(ie.suitable(canonical) for ie in dedicated_extractors()):
            raise UnsupportedDashboardURL()
        return canonical
    except (ValueError, UnicodeError):
        raise UnsupportedDashboardURL() from None


def check_subject(value):
    # Only internally generated provider searches are executable pseudo-URLs.
    if SEARCH.match(value):
        return value
    canonical = normalize_query(value)
    if urlsplit(canonical).scheme not in ("http", "https"):
        raise UnsupportedDashboardURL()
    return canonical


class DashboardYoutubeDL(YoutubeDL):
    def __init__(self, options):
        options = dict(options, allowed_extractors=["default", "-generic"])
        # Never let this transient client reload/write an on-disk cookie file.
        options.update(cookiefile=None, cookiesfrombrowser=None, usenetrc=False)
        super().__init__(options)

    def extract_info(self, url, download=True, ie_key=None, extra_info=None,
                     process=True, force_generic_extractor=False):
        # Also runs on transparent/nested results. A forced Generic key must not
        # lazily instantiate GenericIE even though it is absent from defaults.
        if force_generic_extractor or str(ie_key).lower() == "generic":
            raise UnsupportedDashboardURL()
        return super().extract_info(check_subject(url), download=download, ie_key=ie_key,
                                    extra_info=extra_info or {}, process=process)
