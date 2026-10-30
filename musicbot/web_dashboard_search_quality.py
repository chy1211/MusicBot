"""Bounded, conservative search-result presentation (no provider calls).

A title's 'Official' claim is not channel verification. Only the user chooses
which result to queue; this module never auto-queues or bypasses permissions.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlsplit
import re
import unicodedata

_ALIASES = (("周杰倫", "jay chou"), ("宇多田ヒカル", "hikaru utada"))
_VIDEO = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_TAGS = (
    ("remix", re.compile(r"(?<!\w)(?:remix|remaster(?:ed)?)(?!\w)|リミックス", re.I)),
    ("cover", re.compile(r"(?<!\w)(?:cover|covered by)(?!\w)|歌ってみた|翻唱", re.I)),
    ("live", re.compile(r"(?<!\w)(?:live|concert|on stage)(?!\w)|ライブ|現場版|演唱會", re.I)),
    ("official_audio", re.compile(r"(?<!\w)(?:official\s+audio)(?!\w)|官方音源", re.I)),
    ("mv", re.compile(r"(?<!\w)(?:official\s+)?(?:mv|music\s+video)(?!\w)|ミュージックビデオ|官方mv", re.I)),
)


def normalize(value):
    """Unicode NFKC, case-folding, whitespace and punctuation normalization."""
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[^\W_]+", value, re.UNICODE))


def _equivalent_queries(value):
    base = normalize(value)
    values = {base}
    for a, b in _ALIASES:
        aa, bb = normalize(a), normalize(b)
        if aa in base:
            values.add(base.replace(aa, bb))
        if bb in base:
            values.add(base.replace(bb, aa))
    return tuple(values)


def version_from_title(title, uploader=""):
    for key, pattern in _TAGS:
        if pattern.search(str(title or "")[:300]):
            return key
    # Topic is a channel designation, not proof of an official recording.
    if normalize(uploader).split()[-1:] == ["topic"]:
        return "topic"
    return ""


def _media_url(value):
    if (not isinstance(value, str) or len(value) > 2048
            or re.search(r"[\s\\\x00-\x1f\x7f]", value)):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("https", "http") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 80, 443)):
            return None
        return parsed
    except ValueError:
        return None


def _source(url):
    parsed = _media_url(url)
    if parsed is None:
        return ""
    host = parsed.hostname.lower().rstrip(".")
    if host in ("youtube.com", "youtu.be") or host.endswith(".youtube.com"):
        return "YouTube"
    if host == "soundcloud.com" or host.endswith(".soundcloud.com"):
        return "SoundCloud"
    if host == "open.spotify.com":
        return "Spotify"
    if host.endswith(".bandcamp.com"):
        return "Bandcamp"
    return ""


def annotate_preview(item):
    """Allowlisted source and clearly *claimed*, not verified, version tag."""
    item["source"] = _source(str(item.get("url") or ""))
    item["version"] = version_from_title(item.get("title"), item.get("artist"))
    return item


def media_identity(url):
    """Dedupe only a verifiable media ID or canonical platform path; not a title."""
    try:
        parsed = _media_url(url)
        if parsed is None:
            return ""
        host = (parsed.hostname or "").lower().rstrip(".")
        path = parsed.path.rstrip("/")
        ident = None
        if host in ("youtu.be", "youtube.com") or host.endswith(".youtube.com"):
            if host == "youtu.be":
                ident = path.lstrip("/")
            elif path == "/watch":
                ident = parse_qs(parsed.query).get("v", [""])[0]
            elif path.startswith(("/shorts/", "/live/")):
                ident = path.split("/")[2]
            if ident and _VIDEO.fullmatch(ident):
                return "youtube:" + ident
        if host in ("soundcloud.com", "www.soundcloud.com") and len(path) > 1:
            return "soundcloud:" + path
        if host.endswith(".bandcamp.com") and path.startswith("/track/"):
            return "bandcamp:" + host + path
    except (ValueError, TypeError):
        pass
    return ""  # Unknown identity: do not drop a potentially distinct song.


def _score(query, song):
    title = normalize(song.get("title"))[:256]
    artist = normalize(song.get("artist"))[:120]
    version = song.get("version") or ""
    # A tag may be present in both title and query; do not indiscriminately
    # prefer one recording (Official Audio, MV, live, cover, remix) over another.
    cleaned = title
    for _, regex in _TAGS:
        cleaned = normalize(regex.sub(" ", cleaned))
    best = 0.0
    for q in _equivalent_queries(str(query)[:256]):
        if not q:
            continue
        qwords = set(q.split())
        combo = normalize(cleaned + " " + artist)
        title_sim = max(SequenceMatcher(None, q, cleaned).ratio(),
                        SequenceMatcher(None, q, combo).ratio())
        coverage = len([word for word in qwords if word in combo]) / max(1, len(qwords))
        bonus = 0.18 if q == cleaned or q == combo else 0
        artist_bonus = 0.08 if artist and artist in q else 0
        best = max(best, 0.65 * title_sim + 0.27 * coverage + bonus + artist_bonus)
    requested_version = version_from_title(query)
    if requested_version:
        best += 0.13 if requested_version == version else -0.13
    else:
        # Modest nudge only: text labels are self-reported by video uploaders.
        best += {"official_audio": 0.035, "topic": 0.025, "mv": 0.015,
                 "live": -0.035, "cover": -0.05, "remix": -0.045}.get(version, 0)
    if song.get("allowed") is False:
        best -= 0.25
    return best


def rank_search_results(query, results):
    """Stable rank+dedupe of *already extracted* candidates; never re-extract."""
    found = set()
    kept = []
    for index, item in enumerate(results):
        # Keep metadata as plain JSON; previews and confirmation remain owned by
        # the existing authorization and quota machinery.
        item = annotate_preview(item)
        ident = media_identity(item.get("url") or "")
        if ident:
            if ident in found:
                continue
            found.add(ident)
        kept.append((-_score(query, item), index, item))
    kept.sort(key=lambda row: (row[0], row[1]))
    return [item for _, _, item in kept]
