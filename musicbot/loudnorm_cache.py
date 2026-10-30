"""Bounded on-disk cache for loudnorm analysis.

Cache keys bind path + file size + nanosecond mtime, so a changed or replaced
file cannot reuse stale measurements. No media paths or URLs are stored.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import sqlite3
import time

from .loudness import LOUDNORM_TARGET

_VALUES = ("measured_I", "measured_LRA", "measured_TP", "measured_thresh", "offset")
_NUM = r"-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"
_VALID = re.compile(re.escape(LOUDNORM_TARGET) + r":linear=true:" + ":".join(re.escape(k) + "=" + _NUM for k in _VALUES))


def _cache_path(database=None) -> Path:
    if database is not None:
        return Path(database)
    from . import write_path
    return write_path("data/loudnorm_measurements.sqlite3")


def loudnorm_fingerprint(filename: str) -> str | None:
    try:
        path = Path(filename).resolve(strict=True)
        stat = path.stat()
        if not path.is_file():
            return None
        identity = (str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        return hashlib.sha256(repr(identity).encode("utf-8")).hexdigest()
    except (OSError, ValueError, RuntimeError):
        return None


def _valid_options(options) -> bool:
    if not isinstance(options, str) or len(options) >= 400 or not _VALID.fullmatch(options):
        return False
    return all(math.isfinite(float(value)) for value in re.findall(r"(?:measured_I|measured_LRA|measured_TP|measured_thresh|offset)=(" + _NUM + ")", options))


def lookup_loudnorm(filename: str, *, database=None) -> str | None:
    key = loudnorm_fingerprint(filename)
    if not key:
        return None
    try:
        path = _cache_path(database)
        if not path.is_file():
            return None
        with sqlite3.connect(str(path), timeout=0.05) as db:
            row = db.execute("SELECT options FROM measurements WHERE key = ?", (key,)).fetchone()
        opts = row[0] if row else None
        return opts if _valid_options(opts) and loudnorm_fingerprint(filename) == key else None
    except (OSError, sqlite3.Error):
        return None


def store_loudnorm(filename: str, options: str, *, database=None, expected_fingerprint=None) -> bool:
    key = loudnorm_fingerprint(filename)
    if not key or not _valid_options(options) or (expected_fingerprint is not None and key != expected_fingerprint):
        return False
    try:
        path = _cache_path(database)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(str(path), timeout=0.2) as db:
            db.execute("CREATE TABLE IF NOT EXISTS measurements "
                       "(key TEXT PRIMARY KEY, options TEXT NOT NULL, updated INTEGER NOT NULL)")
            db.execute("INSERT OR REPLACE INTO measurements VALUES (?, ?, ?)", (key, options, time.time_ns()))
            db.execute("DELETE FROM measurements WHERE key NOT IN "
                       "(SELECT key FROM measurements ORDER BY updated DESC LIMIT 512)")
        if os.name != "nt":
            os.chmod(path, 0o600)
        return True
    except (OSError, sqlite3.Error):
        return False
