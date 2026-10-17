"""Offline anonymous popularity: deterministic dates and isolated temporary data."""
import asyncio
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from musicbot.web_dashboard_stats import PopularityStore, atomic_write, normalized_url


class PopularityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="musicbot-webtest-stats-")
        self.root = Path(self.temporary.name)
        self.today = dt.date(2026, 10, 17)
        self.store = PopularityStore(self.root, flush_interval=0, clock=lambda: self.today)
        self.guild = NS(id=123)

    async def asyncTearDown(self):
        await self.store.close()
        self.temporary.cleanup()

    def entry(self, *, url="https://youtu.be/abcdefghijk?t=42", title="Song", author=True, **changes):
        values = dict(url=url, title=title, duration=83.25, author=NS(id=777, name="Private Member") if author is True else author or None,
                      from_auto_playlist=False)
        values.update(changes)
        return NS(**values)

    async def add_at(self, day, count, **kwargs):
        self.today = day
        for _ in range(count):
            await self.store.record(self.guild, self.entry(**kwargs))

    async def test_entry_added_once_but_distinct_batch_entries_each_count(self):
        member = self.entry()
        self.assertTrue(await self.store.record(self.guild, member))
        self.assertFalse(await self.store.record(self.guild, member))
        batch = [self.entry() for _ in range(4)]
        await asyncio.gather(*(self.store.record(self.guild, item) for item in batch))
        self.assertEqual((await self.store.top(self.guild))[0]["count"], 5)

    async def test_autoplay_authorless_and_bot_requests_excluded(self):
        self.assertFalse(await self.store.record(self.guild, self.entry(from_auto_playlist=True)))
        self.assertFalse(await self.store.record(self.guild, self.entry(author=False)))
        self.assertFalse(await self.store.record(self.guild, self.entry(author=NS(bot=True))))
        self.assertEqual(await self.store.top(self.guild), [])
        self.assertFalse(self.store.path(self.guild).exists())

    async def test_meta_member_counts_without_persisting_member(self):
        item = self.entry(author=False, meta={"member": NS(id=777, name="Private Member")})
        self.assertTrue(await self.store.record(self.guild, item))
        await self.store.flush()
        value = self.store.path(self.guild).read_text()
        self.assertNotIn("777", value)
        self.assertNotIn("Private Member", value)
        self.assertNotIn("author", value)
        self.assertNotIn("requester", value)
        self.assertEqual(set(json.loads(value)), {"version", "tracks"})
        self.assertEqual(set((await self.store.top(self.guild))[0]), {"title", "url", "duration", "count"})

    async def test_youtube_aliases_merge_video_without_playlist_or_time(self):
        urls = ["https://youtu.be/abcdefghijk?t=4", "https://www.youtube.com/watch?v=abcdefghijk&list=PL123",
                "https://music.youtube.com/watch?v=abcdefghijk&si=private", "http://m.youtube.com/shorts/abcdefghijk"]
        for url in urls:
            await self.store.record(self.guild, self.entry(url=url))
        rows = await self.store.top(self.guild)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(rows[0]["count"], 4)

    async def test_period_boundaries_are_inclusive_utc_calendar_days(self):
        now = self.today
        for ago in (179, 30, 29, 7, 6, 0):
            await self.add_at(now - dt.timedelta(days=ago), 1)
        self.today = now
        self.assertEqual((await self.store.top(self.guild, "7"))[0]["count"], 2)
        self.assertEqual((await self.store.top(self.guild, "30"))[0]["count"], 4)
        self.assertEqual((await self.store.top(self.guild, "all"))[0]["count"], 6)

    async def test_180_day_prune_drops_old_rows_and_future_dates(self):
        now = self.today
        await self.add_at(now - dt.timedelta(days=180), 1, url="https://example.com/old")
        await self.add_at(now - dt.timedelta(days=179), 1, url="https://example.com/kept")
        self.today = now
        await self.store.record(self.guild, self.entry(url="https://example.com/today"))
        self.store.cache[123]["tracks"]["https://example.com/today"]["days"][(now + dt.timedelta(days=1)).isoformat()] = 99
        self.assertEqual(len(await self.store.top(self.guild, "all")), 2)
        await self.store.flush()
        content = self.store.path(self.guild).read_text()
        self.assertNotIn("example.com/old", content)
        self.assertNotIn((now + dt.timedelta(days=1)).isoformat(), content)
        self.assertIn((now - dt.timedelta(days=179)).isoformat(), content)

    async def test_read_prunes_disk_loaded_expired_rows(self):
        await self.store.record(self.guild, self.entry())
        await self.store.close()
        self.today += dt.timedelta(days=180)
        self.store = PopularityStore(self.root, flush_interval=0, clock=lambda: self.today)
        self.assertEqual(await self.store.top(self.guild, "all"), [])
        await self.store.flush()
        self.assertEqual(json.loads(self.store.path(self.guild).read_text())["tracks"], {})

    async def test_guilds_isolated_with_server_generated_paths(self):
        await self.store.record(self.guild, self.entry())
        await self.store.record(NS(id=456), self.entry(title="Other"))
        self.assertEqual((await self.store.top(self.guild))[0]["title"], "Song")
        self.assertEqual((await self.store.top(NS(id=456)))[0]["title"], "Other")
        for bad in ("../escape", "123", -1, True, NS(id="123")):
            with self.assertRaises(ValueError):
                await self.store.top(bad)
        self.assertEqual(self.store.path(self.guild), self.root / "123.json")

    async def test_buffered_record_does_not_write_until_flush(self):
        await self.store.record(self.guild, self.entry())
        self.assertFalse(self.store.path(self.guild).exists())
        await self.store.flush()
        self.assertTrue(self.store.path(self.guild).exists())
        self.assertFalse(self.store.dirty)

    async def test_periodic_flush_and_close_flush(self):
        await self.store.close()
        self.store = PopularityStore(self.root, flush_interval=.01, clock=lambda: self.today)
        await self.store.record(self.guild, self.entry())
        for _ in range(100):
            if self.store.path(self.guild).exists():
                break
            await asyncio.sleep(.005)
        self.assertTrue(self.store.path(self.guild).exists())
        await self.store.record(self.guild, self.entry())
        await self.store.close()
        value = json.loads(self.store.path(self.guild).read_text())
        self.assertEqual(next(iter(value["tracks"].values()))["days"][self.today.isoformat()], 2)
        self.assertFalse(await self.store.record(self.guild, self.entry()))

    async def test_close_waits_for_inflight_record_before_final_flush(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.store._load

        async def delayed_load(gid):
            entered.set()
            await release.wait()
            return await original(gid)

        with patch.object(self.store, "_load", delayed_load):
            recording = asyncio.create_task(self.store.record(self.guild, self.entry()))
            await entered.wait()
            closing = asyncio.create_task(self.store.close())
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
            release.set()
            await asyncio.gather(recording, closing)
        value = json.loads(self.store.path(self.guild).read_text())
        self.assertEqual(next(iter(value["tracks"].values()))["days"][self.today.isoformat()], 1)

    async def test_atomic_replace_fsync_and_no_temporary_left(self):
        await self.store.record(self.guild, self.entry())
        from musicbot import web_dashboard_stats as module
        with patch.object(module.os, "replace", wraps=module.os.replace) as replace, patch.object(module.os, "fsync", wraps=module.os.fsync) as fsync:
            await self.store.flush()
        self.assertEqual(replace.call_count, 1)
        self.assertEqual(fsync.call_count, 2)
        self.assertEqual(list(self.root.iterdir()), [self.store.path(self.guild)])

    async def test_atomic_failure_preserves_previous_and_retries_dirty(self):
        await self.store.record(self.guild, self.entry())
        await self.store.flush()
        original = self.store.path(self.guild).read_bytes()
        await self.store.record(self.guild, self.entry())
        with patch("musicbot.web_dashboard_stats.os.replace", side_effect=OSError("private/path")):
            with self.assertRaises(OSError):
                await self.store.flush()
        self.assertEqual(self.store.path(self.guild).read_bytes(), original)
        self.assertEqual(self.store.dirty, {123})
        self.assertEqual(list(self.root.iterdir()), [self.store.path(self.guild)])
        await self.store.flush()
        self.assertNotEqual(self.store.path(self.guild).read_bytes(), original)

    async def test_corrupt_file_quarantined_without_overwrite(self):
        path = self.store.path(self.guild)
        path.write_text("{broken", encoding="utf-8")
        previous = path.with_name(path.name + ".corrupt-1")
        previous.write_text("previous recovery", encoding="utf-8")
        with patch("musicbot.web_dashboard_stats.time.time_ns", side_effect=[1, 2]):
            self.assertTrue(await self.store.record(self.guild, self.entry()))
        self.assertEqual(previous.read_text(), "previous recovery")
        self.assertEqual(path.with_name(path.name + ".corrupt-2").read_text(), "{broken")
        self.assertFalse(path.exists())
        await self.store.flush()
        self.assertEqual(json.loads(path.read_text())["version"], 1)

    async def test_unexpected_personal_fields_are_quarantined(self):
        self.store.path(self.guild).write_text(json.dumps({"version": 1, "tracks": {}, "requester": 777}))
        self.assertEqual(await self.store.top(self.guild), [])
        self.assertEqual(len(list(self.root.glob("*.corrupt-*"))), 1)
        self.assertNotIn(777, self.store.cache[123].values())

    async def test_filesystem_read_error_is_not_corruption(self):
        self.store.path(self.guild).write_text("{}")
        with patch.object(Path, "read_text", side_effect=PermissionError("private/path")):
            with self.assertRaises(PermissionError):
                await self.store.top(self.guild)
        self.assertTrue(self.store.path(self.guild).exists())
        self.assertEqual(list(self.root.glob("*.corrupt-*")), [])

    async def test_concurrent_same_entry_and_flush_no_lost_updates(self):
        repeated = self.entry()
        entries = [self.entry() for _ in range(75)] + [repeated] * 25
        await asyncio.gather(*(self.store.record(self.guild, item) for item in entries), self.store.flush())
        await self.store.flush()
        self.assertEqual((await self.store.top(self.guild))[0]["count"], 76)
        document = json.loads(self.store.path(self.guild).read_text())
        self.assertEqual(next(iter(document["tracks"].values()))["days"][self.today.isoformat()], 76)

    async def test_top_twenty_deterministic_and_invalid_period(self):
        for i in range(25):
            await self.store.record(self.guild, self.entry(url=f"https://example.com/{i}", title=f"Track {i:02}"))
        rows = await self.store.top(self.guild, "all")
        self.assertEqual(len(rows), 20)
        self.assertEqual([row["title"] for row in rows], [f"Track {i:02}" for i in range(20)])
        with self.assertRaises(ValueError):
            await self.store.top(self.guild, "180")

    async def test_invalid_url_skipped_and_titles_bounded(self):
        self.assertFalse(await self.store.record(self.guild, self.entry(url="file:///private/song")))
        await self.store.record(self.guild, self.entry(title="\x00" + "X" * 301))
        self.assertEqual((await self.store.top(self.guild))[0]["title"], "X" * 300)


class NormalizeTests(unittest.TestCase):
    def test_public_url_canonicalization(self):
        self.assertEqual(normalized_url("https://EXAMPLE.com:443/song?b=2&a=1&utm_source=x#private"), "https://example.com/song?a=1&b=2")
        self.assertEqual(normalized_url("https://open.spotify.com/track/abcd?si=private"), "https://open.spotify.com/track/abcd")
        self.assertEqual(normalized_url("https://www.youtube.com/embed/abcdefghijk"), "https://www.youtube.com/watch?v=abcdefghijk")

    def test_unsafe_or_non_track_youtube_urls_rejected(self):
        for url in ("file:///etc/passwd", "javascript:alert(1)", "https://user:password@example.com/song", "https://localhost/song",
                    "http://127.0.0.1/song", "http://192.168.1.1/song", "http://169.254.169.254/song", "https://example.com:bad/song",
                    "https://example.com/a\nb", "https://youtube.com/playlist?list=PLabc", "https://youtu.be/bad", None):
            self.assertEqual(normalized_url(url), "", repr(url))


if __name__ == "__main__":
    unittest.main()
