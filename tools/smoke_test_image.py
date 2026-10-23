#!/usr/bin/env python3
"""Credential-free Docker smoke test (host needs Python 3.10+ and Docker).

    python3 tools/smoke_test_image.py musicbot-webtest-candidate
    python3 tools/smoke_test_image.py musicbot-webtest-arm64 --platform linux/arm64 --basic-only
    python3 tools/smoke_test_image.py musicbot-webtest-candidate --network none

Required failures always return nonzero, including external-source outages.
YouTube/provider failures only warn. No host directories or ports are mounted.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

# Long-lived public tracks; no credentials, cookies or private playlists.
SOURCES = (
    "https://soundcloud.com/ethmusic/lostin-powers-she-so-heavy",
    "https://benprunty.bandcamp.com/track/space-cruise-title",
)
YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # long-lived public music video


class SmokeFailure(Exception):
    pass


def run(command, timeout=30):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SmokeFailure(f"[timeout/unknown] {command[0]} exceeded {timeout}s") from exc
    if result.returncode:
        raise SmokeFailure(f"{command[0]} exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def probe(path):
    info = json.loads(run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
        "-of", "json", str(path),
    ]))
    duration = float(info.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or not 0 < duration < 9:
        raise SmokeFailure(f"[tool/media] invalid short audio duration: {duration}")
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        raise SmokeFailure("[tool/media] ffprobe found no audio stream")
    return duration


def download(url, directory, timeout, extra=()):
    run([
        "yt-dlp", "--ignore-config", "--no-playlist", "--no-progress",
        "--socket-timeout", "15", "--retries", "1", "--fragment-retries", "1",
        "--extractor-retries", "1", "--download-sections", "*0-5",
        "--downloader-args", "ffmpeg_i:-rw_timeout 15000000",
        "-f", "bestaudio/best", "-o", str(directory / "audio.%(ext)s"),
        *extra, url,
    ], timeout=timeout)
    files = [p for p in directory.glob("audio.*") if p.suffix not in (".part", ".ytdl")]
    if len(files) != 1:
        raise SmokeFailure("[tool/media] yt-dlp did not produce one complete audio file")
    return probe(files[0])


def basics():
    import musicbot.bot  # noqa: F401; no Discord client is constructed
    print(f"PASS import musicbot.bot ({platform.machine()})", flush=True)
    for binary in ("yt-dlp", "ffmpeg", "ffprobe", "deno"):
        if not shutil.which(binary):
            raise SmokeFailure(f"[tool/runtime] missing executable: {binary}")
        option = "-version" if binary in ("ffmpeg", "ffprobe") else "--version"
        print(f"VERSION {binary}: {run([binary, option]).splitlines()[0]}", flush=True)
    for package in ("yt-dlp", "yt-dlp-ejs", "bgutil-ytdlp-pot-provider"):
        print(f"VERSION package {package}: {importlib.metadata.version(package)}", flush=True)

    # Prove yt-dlp + ffmpeg + ffprobe work without any third-party network.
    # This is diagnostic only: it NEVER substitutes for the public-source gate.
    with tempfile.TemporaryDirectory(prefix="musicbot-webtest-offline-") as temporary:
        root = Path(temporary)
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=1", str(root / "fixture.wav")])

        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

        handler = functools.partial(QuietHandler, directory=str(root))
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                output = root / "output"
                output.mkdir()
                download(f"http://127.0.0.1:{server.server_port}/fixture.wav", output, 30)
            finally:
                server.shutdown()
                thread.join(timeout=5)
    print("PASS offline yt-dlp/ffmpeg/ffprobe pipeline", flush=True)


def dashboard():
    with tempfile.TemporaryFile(mode="w+") as log:
        process = subprocess.Popen([
            sys.executable, "-m", "tools.dashboard_demo", "--host", "127.0.0.1",
            "--port", "18080", "--public-origin", "http://127.0.0.1:18080",
        ], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    for path in ("/healthz", "/"):
                        with urllib.request.urlopen("http://127.0.0.1:18080" + path, timeout=2) as response:
                            if response.status != 200:
                                raise SmokeFailure(f"[startup] {path}: HTTP {response.status}")
                    print("PASS dashboard /healthz=200 /=200 (no Discord token)", flush=True)
                    return
                except (OSError, urllib.error.URLError):
                    time.sleep(.5)
            log.seek(0)
            raise SmokeFailure("[startup] demo failed to become healthy:\n" + log.read()[-6000:])
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def classify(url, detail):
    # Diagnose from explicit transport/HTTP evidence. An accessible web page does
    # not prove the extractor works; unrecognized errors stay unknown and fail.
    network = r"(?i)(name or service not known|name resolution|network is unreachable|no route to host|connection (?:refused|reset)|unable to resolve|HTTP Error (?:403|404|410|429|5\d\d))"
    if re.search(network, detail):
        return "network/source"
    try:
        with urllib.request.urlopen(url, timeout=12) as response:
            response.read(1)
    except (OSError, urllib.error.URLError):
        return "network/source"
    return "extractor/unknown"


def public_downloads(args):
    failures = []
    for url in SOURCES:
        for attempt in range(1, args.attempts + 1):
            print(f"TRY public source {url} ({attempt}/{args.attempts})", flush=True)
            with tempfile.TemporaryDirectory(prefix="musicbot-webtest-download-") as temporary:
                try:
                    duration = download(url, Path(temporary), args.attempt_timeout)
                    print(f"PASS public audio {url} duration={duration:.3f}s", flush=True)
                    return
                except SmokeFailure as exc:
                    category = classify(url, str(exc))
                    failures.append(category)
                    print(f"SOURCE FAIL [{category}] {exc}", flush=True)
            if attempt < args.attempts:
                time.sleep(2)
    category = "network/source" if all(f == "network/source" for f in failures) else "extractor/unknown"
    raise SmokeFailure(f"[{category}] all public sources failed; offline tools passed. Publication blocked.")


def inside(args):
    if args.inside == "youtube":
        deadline = time.monotonic() + 35
        while True:
            try:
                with socket.create_connection(("127.0.0.1", 4416), timeout=2):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise SmokeFailure("bgutil did not listen on port 4416")
                time.sleep(1)
        with tempfile.TemporaryDirectory(prefix="musicbot-webtest-youtube-") as temporary:
            duration = download(YOUTUBE, Path(temporary), args.attempt_timeout, (
                "--extractor-args", "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416",
            ))
        print(f"PASS YouTube OK duration={duration:.3f}s", flush=True)
        return
    basics()
    if args.inside == "required":
        dashboard()
        public_downloads(args)
    print("PASS all required checks", flush=True)


def summary(title, output):
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        lines = [line for line in output.splitlines()
                 if line.startswith(("VERSION ", "PASS ", "FAIL ", "WARNING ", "ERROR: "))]
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(f"\n### {title}\n\n")
            stream.write("\n".join("- " + line.replace("`", "") for line in lines) + "\n")


def host(args):
    source = Path(__file__).read_text(encoding="utf-8")
    prefix = args.name_prefix + "-" + uuid.uuid4().hex[:12]
    names = [prefix + suffix for suffix in ("-required", "-bgutil", "-youtube")]
    docker_platform = ["--platform", args.platform] if args.platform else []

    def container(name, mode, network):
        command = ["docker", "run", "--rm", "-i", "--name", name, "--network", network,
                   *docker_platform, "--entrypoint", "python3", args.image, "-", "--inside", mode,
                   "--attempts", str(args.attempts), "--attempt-timeout", str(args.attempt_timeout)]
        try:
            result = subprocess.run(command, input=source, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    timeout=100 + 2 * args.attempts * (args.attempt_timeout + 15))
            output, code = result.stdout, result.returncode
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout or b""
            output = (partial.decode(errors="replace") if isinstance(partial, bytes) else partial)
            output += "\nFAIL [timeout/unknown] container smoke timeout\n"
            code = 1
        print(output, end="", flush=True)
        summary(f"{mode}: {args.platform or 'native'}", output)
        return code

    try:
        code = container(names[0], "basic" if args.basic_only else "required", args.network)
        if code:
            summary("Publication blocked", "FAIL required smoke checks; no images may be published")
            return code
        if args.basic_only:
            return 0
        try:
            run(["docker", "run", "-d", "--name", names[1], "--network", args.network,
                 "--init", args.bgutil_image], timeout=180)
            code = container(names[2], "youtube", "container:" + names[1])
            if code:
                raise SmokeFailure("YouTube download failed; see output above")
        except (SmokeFailure, OSError) as exc:
            print(str(exc), flush=True)
            warning = ("YouTube test failed: the GitHub runner datacenter IP may be blocked by YouTube; "
                       "this is informational and does not block publication.")
            print("::warning::" + warning, flush=True)
            summary("YouTube (informational)", "WARNING " + warning)
        return 0
    finally:
        # Names are generated by this invocation; never enumerate/remove others.
        for name in names:
            subprocess.run(["docker", "rm", "-fv", name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?")
    parser.add_argument("--name-prefix", default="musicbot-webtest-smoke")
    parser.add_argument("--platform", choices=("linux/amd64", "linux/arm64"))
    parser.add_argument("--network", choices=("bridge", "none"), default="bridge")
    parser.add_argument("--basic-only", action="store_true", help="Offline checks only, e.g. arm64 under QEMU")
    parser.add_argument("--bgutil-image", default="brainicism/bgutil-ytdlp-pot-provider:latest")
    parser.add_argument("--attempts", type=int, choices=range(1, 4), default=2)
    parser.add_argument("--attempt-timeout", type=int, choices=range(30, 181), default=90)
    parser.add_argument("--inside", choices=("basic", "required", "youtube"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not re.fullmatch(r"musicbot-webtest-[a-zA-Z0-9_.-]+", args.name_prefix):
        parser.error("name-prefix must name a disposable musicbot-webtest container")
    if not args.inside and not args.image:
        parser.error("image is required")
    try:
        if args.inside:
            inside(args)
            return 0
        return host(args)
    except (SmokeFailure, OSError, importlib.metadata.PackageNotFoundError) as exc:
        print(f"FAIL {exc}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
