"""Compact completion receipts for unknown-size yt-dlp cache files.

No media path, URL, cookie or download format is stored. A receipt is written only
following successful yt-dlp download and keyed by inode/size/mtime. Existing
unmarked cache files fail closed when the server provides no Content-Length.
"""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import time

_SUFFIXES = ('.part', '.ytdl', '.temp', '.tmp', '.frag')

def _identity(filename):
    try:
        p = Path(filename).resolve(strict=True)
        stat = p.stat()
        if (not p.is_file() or stat.st_size <= 0 or
                p.name.lower().endswith(_SUFFIXES)):
            return None
        key = hashlib.sha256(str(p).encode('utf-8')).hexdigest()
        stamp = f'{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}'
        return key, stamp, stat.st_size
    except (OSError, ValueError, RuntimeError, TypeError):
        return None

def _database():
    from . import write_path
    return write_path('data/audio_completion.sqlite3')

def mark_complete(filename, *, database=None, expected_identity=None):
    """Record a stat receipt after yt-dlp reports successful completion."""
    identity = _identity(filename)
    if identity is None or (expected_identity is not None and identity != expected_identity):
        return False
    try:
        dbfile = Path(database) if database is not None else _database()
        dbfile.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(dbfile, timeout=0.05)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS receipts '
                       '(key TEXT PRIMARY KEY, stamp TEXT NOT NULL, updated INTEGER NOT NULL)')
            db.execute('INSERT OR REPLACE INTO receipts VALUES (?, ?, ?)',
                       (identity[0], identity[1], time.time_ns()))
            db.execute('DELETE FROM receipts WHERE key NOT IN '
                       '(SELECT key FROM receipts ORDER BY updated DESC LIMIT 1024)')
        if os.name != 'nt':
            os.chmod(dbfile, 0o600)
        return True
    except (OSError, sqlite3.Error):
        return False

def cache_verdict(filename, remote_bytes=None, *, database=None):
    """Return (hit, stable reason) without hashing media or making HTTP requests."""
    identity = _identity(filename)
    if identity is None:
        return False, 'missing-empty-or-partial'
    if remote_bytes is not None:
        try:
            remote = int(remote_bytes)
        except (TypeError, ValueError, OverflowError):
            remote = 0
        if remote > 0:
            return (True, 'known-size-match') if identity[2] == remote and _identity(filename) == identity else (False, 'known-size-mismatch')
    try:
        dbfile = Path(database) if database is not None else _database()
        if not dbfile.is_file():
            return False, 'unknown-size-no-receipt'
        with closing(sqlite3.connect(dbfile, timeout=0.05)) as db, db:
            row = db.execute('SELECT stamp FROM receipts WHERE key=?', (identity[0],)).fetchone()
        return ((True, 'unknown-size-verified') if row and row[0] == identity[1] and _identity(filename) == identity
                else (False, 'unknown-size-unverified'))
    except (OSError, sqlite3.Error):
        return False, 'receipt-unavailable'
