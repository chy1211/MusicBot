"""Bounded addition of validated preview tracks into a personal playlist.

No external requests and no global state. The caller holds the user's
transaction lock, rechecks identity/permissions and performs the durable write.
"""


def append_preview_tracks(target, rows, *, make_track, identity, limit=200):
    """Append in input order, skipping already-saved tracks and overflow.

    Convert and validate the full selection *before* modifying the destination;
    errors therefore cannot partially update an in-memory transaction.
    """
    if target.get('source_url'):
        raise ValueError('source-backed playlists are not appendable')
    if not 1 <= len(rows) <= limit:
        raise ValueError('invalid preview selection size')
    if not isinstance(target.get('tracks'), list) or len(target['tracks']) > limit:
        raise ValueError('invalid destination')
    normalized = [make_track(row) for row in rows]
    keyed = [(identity(track['url']), track) for track in normalized]
    existing = {identity(track['url']) for track in target['tracks']}
    added = skipped = 0
    for key, candidate in keyed:
        if key in existing or len(target['tracks']) >= limit:
            skipped += 1
            continue
        target['tracks'].append(candidate)
        existing.add(key)
        added += 1
    return {'added': added, 'skipped': skipped}
