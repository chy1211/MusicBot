# Search preview ranking

Keyword searches rank only the existing provider candidates (maximum five,
further reduced by user permissions). This does not add extraction, download,
format inspection or automatic enqueue requests. Direct URL and playlist entry
order is unchanged. Preview confirmation still validates permissions and media.

Ranking uses normalized titles/artists, two explicitly curated artist aliases,
and a small version preference. Aliases are not general translation. Source
labels use allowlisted platform hosts and HTTP(S) URLs. YouTube deduplication
uses an 11-character video ID, never the title. Other supported platform paths
retain their case; unknown identities are kept. Version labels describe title
claims; Official Audio and MV are explicitly unverified. Topic is a channel
designation. No verified-channel or original-recording guarantee is made.

History plus and heart buttons retain their enqueue/save-dialog actions. The
heart opens the playlist save dialog; it does not toggle favorites. Buttons
retain accessible names, per-song labels, busy/disabled behavior, focus rings,
tooltips and a minimum 44px target.

Validation includes real synthetic HTTP routes that assert one extraction,
provider/user result limits, deduplication, unchanged playlist order and denied
preview flags; fixed multilingual/version cases; and browser rendering in all
six palettes at desktop, phone and tablet widths. Synthetic Top-1/Top-3 checks
are regression fixtures, not measurements of live provider search quality.
No query history, new cross-user cache, provider request increase, verified
official-channel lookup or lyrics-based full-text search is introduced.

The static icon endpoint serves only six named repository SVG files and rejects
unknown names and path traversal. Real service-worker installation is checked:
all six icons must be cached successfully, with no API/auth/event data cached.

The release also changes the service-worker cache version. The real-browser
installation check starts with the previous static cache and verifies that
activation removes it only after the new release has installed successfully.

Audio-only or lyric-video titles are not labeled Official Audio unless they
explicitly make that claim. A Topic tag must be a terminal word, not an arbitrary
uploader-name substring.
