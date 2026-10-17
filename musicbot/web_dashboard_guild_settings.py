"""Bounded per-guild settings using round17's atomic settings writer."""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
from . import write_path
from .web_dashboard_stats import atomic_write

log = logging.getLogger(__name__)


class GuildSettingsStore:
    # Round17 bounded reads and atomic writes, shared by both settings.
    def __init__(self, root, validator, default):
        self.root = Path(root)
        self.validator, self.default = validator, default
        self.lock = asyncio.Lock()

    def path(self, guild):
        gid = getattr(guild, "id", guild)
        if type(gid) is not int or gid <= 0:
            raise ValueError()
        return self.root / (str(gid) + ".json")

    def read(self, guild):
        # Small bounded reads also let direct atomic file edits take effect.
        try:
            with self.path(guild).open("rb") as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise ValueError()
            return self.validator(json.loads(raw))
        except FileNotFoundError:
            return dict(self.default)
        except (ValueError, TypeError, OSError):
            log.warning("Guild settings unavailable; using defaults")
            return dict(self.default)

    async def put(self, guild, data):
        value = self.validator(data)
        async with self.lock:
            await asyncio.to_thread(atomic_write, self.path(guild), value)
        return value


def validate_vote_skip(data):
    if not isinstance(data, dict) or set(data) != {"enabled"} or type(data["enabled"]) is not bool:
        raise ValueError()
    return {"enabled": data["enabled"]}


class VoteSkipStore(GuildSettingsStore):
    def __init__(self, root=None):
        super().__init__(root if root is not None else write_path("data/web_dashboard/vote_skip"),
                         validate_vote_skip, {"enabled": True})


def vote_skip_enabled(bot, guild):
    # Native commands also work with the dashboard disabled, and with --write-dir.
    dashboard = getattr(bot, "_web_dashboard", None)
    store = getattr(dashboard, "vote_skip_store", None)
    return (store if store is not None else VoteSkipStore()).read(guild)["enabled"]
