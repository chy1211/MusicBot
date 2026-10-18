"""Web-only extraction policy; native Discord commands keep their own clients."""
from contextvars import ContextVar, copy_context
from functools import lru_cache
from urllib.parse import parse_qs, urlsplit, urlunsplit
import re
import ipaddress

from yt_dlp import YoutubeDL
from yt_dlp.extractor import gen_extractor_classes

WEB_EXTRACTION = ContextVar("dashboard_extraction", default=False)
SEARCH = re.compile(r"(?:yt|gv|yv|sc|bili|nico)search[0-9]*:")


class UnsupportedDashboardURL(ValueError):
    """The web entry would require an unrestricted extractor."""


# Account-relative aliases resolve against the downloader's signed-in account.
PRIVATE_YOUTUBE_LISTS = frozenset(("WL", "LL", "LM", "HL", "FL", "FV", "FAVORITES"))
PRIVATE_YOUTUBE_PATHS = frozenset((
    "/feed/history", "/feed/watch_later", "/feed/liked_videos",
    "/feed/library", "/feed/you", "/feed/playlists", "/feed/subscriptions",
    "/my_playlists", "/my_favorites", "/my_videos", "/@me",
))


def youtube_subject(parsed):
    host = (parsed.hostname or "").lower().rstrip(".")
    return (host in ("youtube.com", "youtube-nocookie.com", "youtu.be", "www.youtu.be")
            or host.endswith((".youtube.com", ".youtube-nocookie.com")))


def check_youtube_public(parsed):
    if youtube_subject(parsed) and (
            any(ident.upper() in PRIVATE_YOUTUBE_LISTS
                for ident in parse_qs(parsed.query).get("list", []))
            or parsed.path.rstrip("/").lower() in PRIVATE_YOUTUBE_PATHS
            or parsed.path.lower().startswith("/@me/")):
        raise UnsupportedDashboardURL()


def youtube_playlist_subject(value):
    parsed = urlsplit(value)
    return youtube_subject(parsed) and bool(parse_qs(parsed.query).get("list"))


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
            if (value.startswith(("/", "./", "../", "~/")) or "\\" in value
                    or re.match(r"^[A-Za-z]:", value)
                    or re.fullmatch(r"[^\s:]+/[^\s]+\.[A-Za-z0-9]{1,8}", value)
                    or re.fullmatch(r"[^/\s]+\.(?i:mp3|mp4|m4a|wav|flac|ogg|opus|aac|webm|m3u8?)", value)):
                raise UnsupportedDashboardURL()
            if "://" in value or parsed.scheme.lower() in ("file", "data", "javascript", "spotify", "mbapl"):
                raise UnsupportedDashboardURL()
            return value
        if (not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 80, 443) or "\\" in value
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
            raise UnsupportedDashboardURL()
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise UnsupportedDashboardURL()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home")):
            raise UnsupportedDashboardURL()
        netloc = host + (":" + str(parsed.port) if parsed.port else "")
        canonical = urlunsplit((parsed.scheme.lower(), netloc, parsed.path, parsed.query, ""))
        check_youtube_public(parsed)
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
        self.read_budget = None

    def urlopen(self, req):
        response = super().urlopen(req)
        return BudgetResponse(response, self.read_budget) if self.read_budget else response

    def extract_info(self, url, download=True, ie_key=None, extra_info=None,
                     process=True, force_generic_extractor=False):
        # Also runs on transparent/nested results. A forced Generic key must not
        # lazily instantiate GenericIE even though it is absent from defaults.
        if force_generic_extractor or str(ie_key).lower() == "generic":
            raise UnsupportedDashboardURL()
        return super().extract_info(check_subject(url), download=download, ie_key=ie_key,
                                    extra_info=extra_info or {}, process=process)


# Mutable per-resolution budget, shared by nested provider requests/calls.
import asyncio
from dataclasses import dataclass
import json
import os
import signal
import sys
import time
from yt_dlp.networking.common import Response


class ExtractionBudgetExceeded(ValueError):
    pass


@dataclass
class ExtractionBudget:
    timeout: float = 20
    max_response: int = 8 * 1024 * 1024
    max_total: int = 32 * 1024 * 1024
    used: int = 0
    deadline: float = 0

    def __post_init__(self):
        if not self.deadline:
            self.deadline = time.monotonic() + self.timeout

    def consume(self, count, response_count):
        self.used += count
        if response_count > self.max_response or self.used > self.max_total:
            raise ExtractionBudgetExceeded()


WEB_LIMITS = ContextVar("dashboard_extraction_limits", default=(20, 8388608, 33554432))
RESOLUTION_BUDGET = ContextVar("dashboard_resolution_budget", default=None)


def new_budget():
    return ExtractionBudget(*WEB_LIMITS.get())


class BudgetResponse(Response):
    """Count decoded bytes; even read(-1) requests allocate only bounded chunks."""
    def __init__(self, response, budget):
        super().__init__(response, response.url, response.headers, response.status,
                         response.reason, response.extensions)
        self.budget = budget
        self.count = 0
        length = response.headers.get('Content-Length', '')
        if length.isdecimal() and int(length) > min(budget.max_response, budget.max_total - budget.used):
            self.close()
            raise ExtractionBudgetExceeded()

    def read(self, amt=None):
        if amt == 0:
            return b''
        chunks = []
        remaining = amt if amt is not None and amt >= 0 else None
        try:
            while remaining is None or remaining > 0:
                allowance = min(self.budget.max_response - self.count,
                                self.budget.max_total - self.budget.used)
                size = min(65536, allowance + 1)
                if remaining is not None:
                    size = min(size, remaining)
                chunk = self.fp.read(size)
                if not chunk:
                    break
                self.count += len(chunk)
                self.budget.consume(len(chunk), self.count)
                chunks.append(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
            return b''.join(chunks)
        except BaseException:
            self.close()
            raise


async def bounded_json(response):
    """Bound cancellable Spotify API reads only in dashboard extraction tasks."""
    if not WEB_EXTRACTION.get():
        return await response.json()
    budget = RESOLUTION_BUDGET.get() or new_budget()
    chunks, count = [], 0
    async for chunk in response.content.iter_chunked(65536):
        count += len(chunk)
        budget.consume(len(chunk), count)
        chunks.append(chunk)
    return json.loads(b''.join(chunks))


async def run_extraction_process(payload, budget, *, command=None):
    """Kill the isolated process group, reap it, then propagate timeout/cancel.

    command is a trusted test seam, never populated from an HTTP request.
    No credentials appear in argv, environment, output logs or temporary files.
    """
    remaining = budget.deadline - time.monotonic()
    if remaining <= 0:
        raise asyncio.TimeoutError()
    command = command or [sys.executable, '-m', 'musicbot.web_dashboard_extract_worker']
    encoded = json.dumps(payload).encode()
    if len(encoded) > 8 * 1024 * 1024:
        raise ExtractionBudgetExceeded()
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True))
    process = None

    async def exchange():
        process.stdin.write(encoded)
        await process.stdin.drain()
        process.stdin.close()
        chunks, count = [], 0
        while True:
            chunk = await process.stdout.read(min(65536, budget.max_response + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            if count > budget.max_response:
                raise ExtractionBudgetExceeded()
            chunks.append(chunk)
        await process.wait()
        if process.returncode:
            raise RuntimeError('Dashboard extraction worker failed')
        result = json.loads(b''.join(chunks))
        budget.consume(result.get('read_bytes', 0), 0)
        if result.get('error') == 'unsupported':
            raise UnsupportedDashboardURL()
        if result.get('error') == 'budget':
            raise ExtractionBudgetExceeded()
        if result.get('error'):
            raise RuntimeError('Dashboard provider extraction failed')
        return result['data']

    try:
        process = await asyncio.shield(spawn)
        return await asyncio.wait_for(exchange(), max(.001, budget.deadline - time.monotonic()))
    finally:
        # Cancellation during spawn must not orphan an already-created process.
        if process is None:
            process = await spawn
        await reap_worker(process)


WEB_POOL = ContextVar("dashboard_extraction_pool", default=None)


async def reap_worker(process):
    """Cleanup must finish even if request cancellation is repeated."""
    async def reap():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
    cleanup = asyncio.create_task(reap())
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue
    cleanup.result()


class DashboardExtractionPool:
    """Two preloaded, reusable workers. Timeouts kill/reap and replace a worker.

    Clients/options/cookies are recreated for every job; only Python imports are
    reused. Warming is local-only and adds no per-song provider requests/delay.
    """
    def __init__(self):
        self.started = False
        self.available = asyncio.Queue()
        self.workers = set()
        self.replacements = set()

    async def spawn(self):
        pending = asyncio.create_task(asyncio.create_subprocess_exec(
            sys.executable, '-m', 'musicbot.web_dashboard_extract_worker', '--serve',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True))
        process = None
        try:
            process = await asyncio.shield(pending)
            self.workers.add(process)
            if await asyncio.wait_for(process.stdout.readline(), 10) != b'READY\n':
                raise RuntimeError('Dashboard worker could not start')
            self.available.put_nowait(process)
        except BaseException:
            if process is None:
                process = await pending
            await reap_worker(process)
            self.workers.discard(process)
            raise

    async def start(self):
        self.started = True
        starting = [asyncio.create_task(self.spawn()) for _ in range(2)]
        self.replacements.update(starting)
        try:
            await asyncio.gather(*starting)
        except BaseException:
            await self.close()
            raise
        finally:
            self.replacements.difference_update(starting)

    async def run(self, payload, budget):
        async def exchange():
            process = await self.available.get()
            success = False
            try:
                raw = json.dumps(payload).encode()
                if len(raw) > 8 * 1024 * 1024:
                    raise ExtractionBudgetExceeded()
                process.stdin.write(str(len(raw)).encode() + b'\n' + raw)
                await process.stdin.drain()
                header = await process.stdout.readline()
                if len(header) > 20 or not header.strip().isdigit():
                    raise RuntimeError('Invalid worker frame')
                size = int(header)
                if size > budget.max_response:
                    raise ExtractionBudgetExceeded()
                result = json.loads(await process.stdout.readexactly(size))
                budget.consume(result.get('read_bytes', 0), 0)
                if result.get('error') == 'unsupported':
                    raise UnsupportedDashboardURL()
                if result.get('error') == 'budget':
                    raise ExtractionBudgetExceeded()
                if result.get('error'):
                    raise RuntimeError('Dashboard provider extraction failed')
                success = True
                return result['data']
            finally:
                if success and self.started:
                    self.available.put_nowait(process)
                else:
                    await reap_worker(process)
                    self.workers.discard(process)
                    if self.started:
                        replacement = asyncio.create_task(self.spawn())
                        self.replacements.add(replacement)
                        def finished(task):
                            self.replacements.discard(task)
                            if not task.cancelled():
                                task.exception()
                        replacement.add_done_callback(finished)
        remaining = budget.deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        return await asyncio.wait_for(exchange(), remaining)

    async def close(self):
        self.started = False
        pending = list(self.replacements)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.gather(*(reap_worker(p) for p in list(self.workers)))
        self.workers.clear()
        while not self.available.empty():
            self.available.get_nowait()


def playback_context():
    """A queued media download must not inherit a web parser's expiring budget."""
    context = copy_context()
    context.run(WEB_EXTRACTION.set, False)
    context.run(RESOLUTION_BUDGET.set, None)
    context.run(WEB_POOL.set, None)
    return context
