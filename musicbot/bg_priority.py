"""Best-effort CPU (nice) and I/O (ionice idle) priority lowering for background workers."""
from __future__ import annotations

import os
import shutil
import subprocess


def apply_background_priority(niceness: int = 10, io_class: str = "3") -> None:
    """Lower CPU and I/O priority of the current background worker process.

    Safe no-op on platforms or environments where nice/ionice are unavailable.
    Inherited automatically by child processes (e.g. yt-dlp, deno, lyrics ffmpeg).
    """
    if hasattr(os, "nice"):
        try:
            os.nice(niceness)
        except OSError:
            pass
    ionice = shutil.which("ionice")
    if ionice:
        try:
            subprocess.run(
                [ionice, "-c", str(io_class), "-p", str(os.getpid())],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass
