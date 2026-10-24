"""Private, bounded single-URL preview extractions and task-local admission."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from contextvars import ContextVar

from .web_dashboard_extraction import normalize_query

log = logging.getLogger(__name__)
PREVIEW_EXTRACTION = ContextVar("dashboard_preview_extraction", default=None)
# Serialized private payloads total at most 4 MiB, independent of preview count.
MAX_SAVED_EXTRACTIONS = 8
MAX_EXTRACTION_BYTES = 512 * 1024
# Match the existing preview lifetime; stricter than download reuse's 30 minutes.
MAX_EXTRACTION_AGE = 5 * 60


class PreviewTrack(dict):
    """JSON sees only the public dict; the private payload is an attribute."""
    extraction = None
    extraction_reason = "not-single-url"


def extraction_reason(data, query):
    if not isinstance(data, dict):
        return "invalid-result"
    if "entries" in data or data.get("_type", "video") != "video":
        return "not-single-track"
    extractor = str(data.get("extractor", "")).lower()
    if not extractor or any(word in extractor for word in ("spotify", "search", "playlist", "generic")):
        return "unsupported-extractor"
    if not isinstance(data.get("formats"), list) or not data["formats"]:
        return "no-download-formats"
    try:
        if normalize_query(data.get("__input_subject", "")) != normalize_query(query):
            return "url-mismatch"
    except (ValueError, TypeError, AttributeError):
        return "url-mismatch"
    stamp = data.get("__extracted_at")
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return "invalid-timestamp"
    try:
        if not math.isfinite(stamp):
            return "invalid-timestamp"
        age = time.time() - stamp
    except OverflowError:
        return "invalid-timestamp"
    if age < 0 or age > MAX_EXTRACTION_AGE:
        return "expired-extraction"
    return ""


def save_extraction(info, subject, preview_url):
    data = info.data
    reason = extraction_reason(data, preview_url)
    if reason:
        return None, reason
    if normalize_query(subject) != normalize_query(preview_url):
        return None, "url-mismatch"
    # Preserve the complete sanitized extraction, including formats and private
    # download metadata. Oversized/unserializable results simply use normal play.
    chunks, size = [], 0
    try:
        for chunk in json.JSONEncoder(ensure_ascii=True, allow_nan=False).iterencode(data):
            encoded = chunk.encode("ascii")
            size += len(encoded)
            if size > MAX_EXTRACTION_BYTES:
                return None, "result-too-large"
            chunks.append(encoded)
    except (TypeError, ValueError, OverflowError):
        return None, "unserializable-result"
    return b"".join(chunks), ""


def prune_extractions(previews, now):
    retained = 0
    for preview in reversed(list(previews.values())):
        if "extraction" not in preview:
            continue
        if preview["expires"] <= now or preview["status"] != "ready":
            preview.pop("extraction", None)
            preview["extraction_reason"] = "expired-preview"
        elif retained >= MAX_SAVED_EXTRACTIONS:
            preview.pop("extraction", None)
            preview["extraction_reason"] = "cache-limit"
        else:
            retained += 1


def load_extraction(preview, query):
    if preview.get("kind") != "track":
        return None, "not-single-track"
    if preview["expires"] <= time.monotonic():
        return None, "expired-preview"
    if normalize_query(query) != normalize_query(preview["url"]):
        return None, "url-mismatch"
    blob = preview.get("extraction")
    if not isinstance(blob, bytes) or len(blob) > MAX_EXTRACTION_BYTES:
        return None, preview.get("extraction_reason") or "no-saved-result"
    try:
        data = json.loads(blob)
    except (ValueError, TypeError):
        return None, "invalid-result"
    reason = extraction_reason(data, query)
    return (None, reason) if reason else (data, "")


class PreviewExtraction:
    """One command may reuse once; every miss is admitted before doing any I/O."""
    def __init__(self, data, admit):
        self.data = data
        self.admit = admit
        self.task = asyncio.current_task()
        self.active = True
        self.used = False

    def close(self):
        self.active = False
        # Inherited background contexts must not retain request/identity metadata
        # or another reference to a large decoded extraction after command exit.
        self.data = self.admit = self.task = None

    def owns_current_task(self):
        # Playlist/download background tasks inherit contextvars. They must keep
        # their existing download behavior, even if started before command exit.
        return self.active and asyncio.current_task() is self.task

    async def extract(self, downloader, subject, args, kwargs):
        from .downloader import YtdlpResponseDict
        reason = "already-consumed" if self.used else extraction_reason(self.data, subject)
        if args or kwargs != {"download": False, "process": True}:
            reason = "different-extraction-options"
        if not reason:
            self.used = True
            # This dict was decoded for this command only; no shared mutable info.
            log.info("Dashboard add reused preview extraction")
            return YtdlpResponseDict(self.data)
        log.info("Dashboard add re-extracting preview: %s", reason)

        async def admitted():
            token = PREVIEW_EXTRACTION.set(None)
            try:
                return await downloader.extract_info(subject, *args, **kwargs)
            finally:
                PREVIEW_EXTRACTION.reset(token)
        return await self.admit(admitted())
