# Source-read cadence diagnostics

Set `MUSICBOT_SOURCE_READ_CADENCE=1` before starting the bot to enable optional
diagnostics for new sources. It is disabled by default. Remove the variable or
set it to `0` and restart to disable it. No playback/FFmpeg settings are changed.

Each completed source emits at most one `source_read_cadence_summary` JSON record
on the event loop, including stopped/replaced sources. Read errors remain genuine
playback errors; a diagnostics failure disables only the optional observer.
Pause/resume boundaries are queued by controls and drained by the audio reader.

The record contains `session`, `source_generation`, `track_hash`, `playback_speed`,
`source_media_offset_ms`, valid `read_frames`, interval/read-time extrema, and
`source_read_interval_histogram` with mutually exclusive `lt5`, `5to10`, `10to15`,
`15to25`, `25to60`, and `gte60` millisecond buckets. The first frame has no interval.

Three consecutive intervals below 10ms form a burst, independently of whether a
60ms gap preceded them. Counts distinguish independent and post-gap bursts and
include total shortfall against a 20ms read cadence. At most 12 recent event samples
are retained, with dropped-sample totals preserved. Samples include approximate
UTC onset, media progress, source boundaries and interval/time-shortfall values.
These counters describe source.read invocations; `packet_send_status` remains
`not_instrumented`. They do not measure UDP completion, network arrival, or the
listener's playback clock, and cannot by themselves prove where acceleration occurs.

Normal 20ms reads produce no burst. Three successive 2ms intervals without a 60ms
gap produce an independent burst and 54ms shortfall. A 80ms gap followed by those
intervals produces a post-gap burst. These are synthetic test examples.

Deployment integrations may share the session with an existing source monitor;
attach only once and retain existing monitor counters. No private deployment text,
cookies, signed media URLs or credentials belong in this module or its logs.

R22 optional layered read/GC observation: add `MUSICBOT_CADENCE_LAYERS=1`
while keeping `MUSICBOT_SOURCE_READ_CADENCE=1`. With
`MUSICBOT_CADENCE_GC=1`, per-source bounded callbacks capture actual GC
start/stop monotonic times; callback unregisters on source cleanup. The new
`schema_version=2` adds `gap_context` (`immediately_after_gap`, `recent_gap`,
`no_recent_gap`), gap age and frame distance (window <=500ms and <=10 frames),
GC actual-window overlap/nearby indicators, and bounded live event IDs. The old
`after_large_gap` retains its original *adjacent-gap only* semantics.

Events are drained on the asyncio loop at 0.5s intervals, never logged in the
audio thread. Ring has at most 12 pending events; summary retains aggregate
counts even when the live ring drops samples. Time is anchored to UTC, with
`at_utc_ms` from source monotonic origin; `logged_at_utc_ms` is only logger
presentation time. `at_progress_ms` is approximate source-media progress,
not the listener's timestamp. GC correlation is not causal proof.

**VoiceClient/send_packet/socket_send are NOT instrumented by this safe R22
stage:** their counters remain `not_instrumented`, not zero. Before modifying
`discord.py 2.7.1` internals, Codex must verify a reversible instance-scoped
hook, socket OSError semantics, and how silence frames are identified, with
fake transport regression tests. Never infer socket success from a high-level
`VoiceClient.send_audio_packet` returning normally.

This release also prioritizes cached lyrics before Spotify lookup, caps auxiliary
Spotify waiting at 3 seconds, and labels duration-only alignment as a low-confidence
one-hour assumption. Existing duration-only confidence=1 caches are downgraded on
read. Manual lyric selection/full-text reverse search and packet-send instrumentation
are separate future work; no claim is made that brief acceleration has been fixed.

Native URL preflight permits dedicated-provider URLs and provider search syntax,
while rejecting explicit unsupported/generic and internal URL forms before provider
execution. It is not a DNS/redirect/secondary-media SSRF firewall. Existing local-media
permissions still apply. Lyric pruning is periodic, with conservative count/byte
pressure estimates forcing earlier cleanup rather than dropping capacity protection.

Lazy route mounting avoids eager view setup and API calls. Existing service-worker
asset precaching is preserved, so this is not a promise that background downloads
of every route bundle disappear on first installation.
