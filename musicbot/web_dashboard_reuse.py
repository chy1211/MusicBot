"""Per-owner/guild, per-cookie-generation bounded complete-info reuse.

Only processed, single-URL metadata with formats qualifies; flat playlists and
search results do not. This cache is strictly in-process, short-lived, and does
not bypass dashboard authorization or confirmation checks.
"""
import logging
import hashlib
import json
import time
from collections import OrderedDict

from .web_dashboard_preview import extraction_reason, MAX_EXTRACTION_BYTES

log = logging.getLogger(__name__)

class CompleteInfoCache:
    MAX_ITEMS = 8
    TTL = 120

    def __init__(self):
        self._items = OrderedDict()
        self._client = None

    def scope(self, client, options):
        # Keep a strong generation reference; object IDs alone can be recycled.
        if self._client is not client:
            self._items.clear()
            self._client = client
        settings = {k: v for k, v in options.items() if k not in
                    ('logger', 'progress_hooks', 'postprocessor_hooks')}
        # Rotating UA is cosmetic; formats retain their original request headers.
        headers = dict(settings.get('http_headers') or {})
        settings['http_headers'] = {k: v for k, v in headers.items() if k.lower() != 'user-agent'}
        blob = json.dumps(settings, sort_keys=True, default=str).encode()
        return id(client), hashlib.sha256(blob).hexdigest()

    def get(self, key, url):
        now = time.monotonic()
        self._items = OrderedDict((k, v) for k, v in self._items.items() if v[0] > now)
        item = self._items.get(key)
        if item is None:
            return None, 'not-cached'
        try:
            data = json.loads(item[1])
        except (ValueError, TypeError):
            return None, 'invalid-cache'
        reason = extraction_reason(data, url)
        if reason:
            self._items.pop(key, None)
            return None, reason
        self._items.move_to_end(key)
        return data, 'hit'

    def put(self, key, url, data):
        if extraction_reason(data, url):
            return False
        try:
            blob = json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')
        except (TypeError, ValueError, OverflowError):
            return False
        if len(blob) > MAX_EXTRACTION_BYTES:
            return False
        self._items[key] = (time.monotonic() + self.TTL, blob)
        self._items.move_to_end(key)
        while len(self._items) > self.MAX_ITEMS:
            self._items.popitem(last=False)
        return True
