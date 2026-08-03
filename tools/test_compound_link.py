#!/usr/bin/env python3
"""
Check get_compound_link_ids against every YouTube watch-link shape, and show what
the replaced PL-only regex did with the same input.

Run from the repo root:  python3 tools/test_compound_link.py
"""
import re
import sys

from musicbot.utils import get_compound_link_ids

# The implementation this replaced, kept here so the table shows what changed.
OLD_RE = re.compile(
    r"(?:youtube.com/watch\?v=|youtu\.be/)([^?&]{6,})[&?]{1}(list=PL[^&]+)",
    re.I | re.X,
)


def old_impl(url):
    m = OLD_RE.search(url)
    if not m:
        return "", ""
    return m.group(2)[len("list="):], m.group(1)


VID = "dQw4w9WgXcQ"

CASES = [
    # (url, expected_playlist_id, expected_video_id, note)
    (f"https://www.youtube.com/watch?v={VID}&list=PLabcdefghij", "PLabcdefghij", VID,
     "classic watch + PL playlist"),
    (f"https://youtu.be/{VID}?list=PLabcdefghij", "PLabcdefghij", VID,
     "short link + PL playlist"),
    (f"https://www.youtube.com/watch?list=PLabcdefghij&v={VID}", "PLabcdefghij", VID,
     "list before v"),
    (f"https://www.youtube.com/watch?v={VID}&t=42s&list=PLabcdefghij", "PLabcdefghij", VID,
     "timestamp between v and list"),
    (f"https://music.youtube.com/watch?v={VID}&list=OLAK5uy_abc123", "OLAK5uy_abc123", VID,
     "YouTube Music album"),
    (f"https://www.youtube.com/watch?v={VID}&list=RD{VID}", f"RD{VID}", VID,
     "auto-generated mix"),
    (f"https://www.youtube.com/watch?v={VID}&list=UUabc123def", "UUabc123def", VID,
     "channel uploads"),
    (f"https://m.youtube.com/watch?v={VID}&list=PLabcdefghij", "PLabcdefghij", VID,
     "mobile host"),
    (f"https://www.youtube.com/watch?v={VID}&list=PLabcdefghij#t=10", "PLabcdefghij", VID,
     "trailing fragment"),

    # Must NOT prompt.
    (f"https://www.youtube.com/watch?v={VID}&list=WL", "", "",
     "Watch Later is private to the bot account"),
    (f"https://www.youtube.com/watch?v={VID}&list=LL", "", "",
     "Liked videos is private to the bot account"),
    ("https://www.youtube.com/playlist?list=PLabcdefghij", "", "",
     "bare playlist link, play already queues it whole"),
    (f"https://www.youtube.com/watch?v={VID}", "", "",
     "no playlist named"),
    (f"https://notyoutube.com/watch?v={VID}&list=PLabcdefghij", "", "",
     "lookalike host must not match"),
    (f"https://vimeo.com/watch?v={VID}&list=PLabcdefghij", "", "",
     "unrelated host"),
    ("not a url at all", "", "", "garbage input"),
]


def main():
    width = max(len(c[3]) for c in CASES)
    failures = 0
    fixed = 0

    print(f"{'case':<{width}}  {'old':<14} {'new':<14} result")
    print("-" * (width + 40))

    for url, want_pl, want_vid, note in CASES:
        got_pl, got_vid = get_compound_link_ids(url)
        old_pl, _old_vid = old_impl(url)

        ok = (got_pl, got_vid) == (want_pl, want_vid)
        if not ok:
            failures += 1
        elif bool(old_pl) != bool(want_pl):
            fixed += 1

        old_show = (old_pl or "-")[:13]
        new_show = (got_pl or "-")[:13]
        mark = "PASS" if ok else f"FAIL want={want_pl!r},{want_vid!r} got={got_pl!r},{got_vid!r}"
        print(f"{note:<{width}}  {old_show:<14} {new_show:<14} {mark}")

    print("-" * (width + 40))
    print(f"{len(CASES)} cases, {failures} failed, {fixed} behaviours corrected vs the old regex")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
