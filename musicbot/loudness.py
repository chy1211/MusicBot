"""FFmpeg EBU R128 loudness normalization helpers.

Parsing stays separate from Discord/player initialization so FFmpeg analysis failures
can be handled without preventing a track from playing.
"""

import json
import math
import re
from typing import Dict


LOUDNORM_TARGET = "I=-24.0:LRA=7.0:TP=-2.0"


def measured_loudnorm_filter(output: str) -> str:
    """Return FFmpeg two-pass loudnorm parameters from an analysis log.

    Raise ValueError if FFmpeg did not emit complete, finite measurements;
    the caller can then use live one-pass normalization instead.
    """
    names: Dict[str, str] = {
        "input_i": "measured_I",
        "input_lra": "measured_LRA",
        "input_tp": "measured_TP",
        "input_thresh": "measured_thresh",
        "target_offset": "offset",
    }
    # FFmpeg writes JSON into its stderr along with informational messages.
    match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', output, flags=re.DOTALL)
    if match is None:
        raise ValueError("FFmpeg did not output loudnorm measurements")

    try:
        raw = json.loads(match.group(0))
        measurements = {dest: float(raw[src]) for src, dest in names.items()}
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Incomplete FFmpeg loudnorm measurements") from exc

    if not all(math.isfinite(value) for value in measurements.values()):
        raise ValueError("Non-finite FFmpeg loudnorm measurements")

    return (
        f"{LOUDNORM_TARGET}:linear=true:"
        + ":".join(f"{key}={value}" for key, value in measurements.items())
    )
