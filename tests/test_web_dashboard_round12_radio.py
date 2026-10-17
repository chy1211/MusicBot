"""Deterministic offline radio diversity and restart regression."""
import json
import random
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import test_web_dashboard as base
import test_web_dashboard_round10_radio as old
from musicbot.web_dashboard_radio import RadioService, normalized_title
from musicbot.web_dashboard_stats import PopularityStore

class RadioDiversityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = old.RadioTests.asyncSetUp
    asyncTearDown = old.RadioTests.asyncTearDown
    mode = old.RadioTests.mode

    async def test_only_human_seeds_and_pool_five_rotation(self):
        for index in range(7):
            song = base.entry("Human "+str(index), author=self.bot.owner)
            song.url = f"https://www.youtube.com/watch?v=human{index:06d}"
            await self.service.remember(self.bot.guild, song)
        for author, auto, radio in ((None, False, True), (None, True, False), (NS(bot=True), False, False)):
            song = base.entry("Automatic", author=author)
            song.url = "https://www.youtube.com/watch?v=auto0000001"
            song.from_auto_playlist = auto
            song._dashboard_radio_source = radio
            await self.service.remember(self.bot.guild, song)
        rows = await self.service.seed_rows(self.bot.guild)
        self.assertEqual([row["title"] for row in rows], ["Human "+str(i) for i in range(2,7)])
        picks = [await self.service.next_seed(self.bot.guild) for _ in range(6)]
        self.assertEqual(picks, [row["url"] for row in rows]+[rows[0]["url"]])

    async def test_radio_generated_entry_cannot_replace_seed(self):
        await self.service.fill(self.player, await self.mode())
        before = await self.service.seed_rows(self.bot.guild)
        for song in self.player.playlist.entries:
            await self.service.remember(self.bot.guild, song)
        self.assertEqual(await self.service.seed_rows(self.bot.guild), before)

    async def test_no_seed_uses_top_human_requests_then_empty_falls_back(self):
        self.service.seeds.clear()
        store = PopularityStore(Path(self.temp.name)/"stats",flush_interval=0)
        self.service.popularity = store
        self.assertIsNone(await self.service.next_seed(self.bot.guild))
        song = base.entry("Popular",author=self.bot.owner)
        song.url = "https://youtu.be/popular0001"
        await store.record(self.bot.guild,song)
        self.assertEqual(await self.service.next_seed(self.bot.guild),"https://www.youtube.com/watch?v=popular0001")
        self.assertEqual(await self.service.seed_rows(self.bot.guild),[])
        await store.close()

    async def test_restart_recovers_minimal_state_and_rotation(self):
        await self.service.next_seed(self.bot.guild)
        path = self.service.state_path(self.bot.guild)
        raw = json.loads(path.read_text())
        self.assertEqual(set(raw),{"version","seeds","recent","next"})
        for row in raw["recent"]+raw["seeds"]:
            self.assertEqual(set(row),{"url","title"})
        fresh = RadioService(self.bot,self.service.store.root)
        self.assertEqual(await fresh.seed_rows(self.bot.guild),await self.service.seed_rows(self.bot.guild))
        self.assertEqual(list(fresh.recent[1]),list(self.service.recent[1]))
        self.assertEqual(fresh.cursor[1],self.service.cursor[1])
        self.assertEqual(list(path.parent.iterdir()),[path])

    async def test_bad_missing_and_oversized_state_are_empty(self):
        fresh = RadioService(self.bot,self.service.store.root)
        path = fresh.state_path(self.bot.guild)
        for contents in ("broken", '{"version":1,"seeds":"bad"}', "x"*65537):
            path.write_text(contents)
            fresh = RadioService(self.bot,self.service.store.root)
            self.assertEqual(await fresh.seed_rows(self.bot.guild),[])
        path.unlink()
        self.assertEqual(await RadioService(self.bot,self.service.store.root).seed_rows(self.bot.guild),[])

    async def test_normalized_versions_recent_titles_and_artist_channel_dedup(self):
        self.assertEqual(normalized_title("Singer - Orbit (Official MV)"), normalized_title("Singer - Orbit [Live Cover Lyrics]"))
        self.service.recent[1].append({"url":"https://www.youtube.com/watch?v=old00000001","title":"Singer - Orbit (Official MV)"})
        items = [
          {"id":"new00000001","title":"Singer - Orbit [Live]","duration":180,"channel":"A"},
          {"id":"new00000002","title":"Other - First","duration":180,"channel":"B"},
          {"id":"new00000003","title":"Other - Second","duration":180,"channel":"C"},
          {"id":"new00000004","title":"Third - Fine","duration":180,"channel":"B"},
          {"id":"new00000005","title":"Last - Sky","duration":180,"channel":"D"},
        ]
        self.bot.downloader.extract_public_playlist.return_value = old.mix(items)
        self.service.rng = random.Random(5)
        await self.service.fill(self.player,await self.mode())
        rows=list(self.player.playlist.entries)
        self.assertNotIn("Singer - Orbit [Live]",[row.title for row in rows])
        artists = [row.title.split(" - ")[0] for row in rows]
        self.assertEqual(len(artists),len(set(artists)))
        self.assertFalse({"Other - First","Third - Fine"} <= {row.title for row in rows})

    async def test_weighted_sampling_is_repeatable_and_bounded_to_25(self):
        async def choose(seed):
            self.player.playlist.entries.clear()
            self.service.rng = random.Random(seed)
            self.bot.downloader.extract_public_playlist.return_value = old.mix([
              {"id":f"track{i:06d}","title":f"Song {i}","duration":180} for i in range(40)])
            await self.service.fill(self.player,await self.mode())
            return [row.title for row in self.player.playlist.entries]
        first = await choose(1234)
        self.assertEqual(first,await choose(1234))
        self.assertNotEqual(first,["Song 0","Song 1","Song 2"])
        counts = [0,0]
        for seed in range(120):
            rows=await choose(seed)
            self.assertTrue(all(int(title.split()[-1])<25 for title in rows))
            counts[0]+= "Song 0" in rows
            counts[1]+= "Song 24" in rows
        self.assertGreater(counts[0],counts[1]*2)
