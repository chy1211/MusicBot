"""Real downloader Spotify flattening, fabricated providers, offline."""
import asyncio
import tempfile
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import test_web_dashboard as base
from musicbot.downloader import Downloader, YtdlpResponseDict
from musicbot.spotify import SpotifyTrack
from musicbot.web_dashboard_library import PlaylistStore

class SpotifySelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await base.DashboardTests.asyncSetUp(self)
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-r11-")
        self.dashboard.playlist_store = PlaylistStore(self.temp.name)
        self.bot.loop = asyncio.get_running_loop()
        self.bot.config.spotify_enabled = True
        self.row = {"type":"track","id":"track1","name":"Fixture","duration_ms":120000,
                    "artists":[{"name":"Artist"}],"external_urls":{"spotify":"https://open.spotify.com/track/track1"}}
        self.bot.spotify = NS(get_playlist=AsyncMock(return_value={"name":"List","tracks":{"items":[{"track":self.row}],"total":1}}),
            get_spotify_ytdl_data=AsyncMock(return_value=SpotifyTrack(self.row).to_ytdl_dict()))
        self.child = dict(self.bot.info, _type="url", id="abcdefghijk",
                          url="https://www.youtube.com/watch?v=abcdefghijk",
                          webpage_url="https://www.youtube.com/watch?v=abcdefghijk")
        raw = {"_type":"playlist","extractor":"youtube:search","playlist_count":1,"entries":[self.child]}
        downloader = NS(bot=self.bot, thread_pool=None, _supported_search=["ytsearch"],
            unsafe_ytdl=NS(extract_info=lambda *a, **k: raw), ytdl=NS(sanitize_info=lambda d:d))
        downloader._run_ytdl = lambda safe, method, *a, **kw: getattr(downloader.unsafe_ytdl, method)(*a, **kw)
        async def extract(subject, **kwargs):
            with patch("musicbot.downloader.log.noise",create=True):
                return YtdlpResponseDict(await Downloader._filtered_extract_info(downloader,subject,**kwargs))
        self.bot.downloader.extract_info = extract

    async def asyncTearDown(self):
        await base.DashboardTests.asyncTearDown(self)
        self.temp.cleanup()

    call = base.DashboardTests.call
    async def preview(self):
        return (await self.call(base.BASE+"resolve",{"query":"https://open.spotify.com/playlist/list123?si=ignored"}))["results"][0]

    async def test_real_flat_url_shape_selection_and_expiry(self):
        for expired in (False,True):
            song = await self.preview()
            if expired: self.dashboard.previews[song["preview_id"]]["expires"]=time.monotonic()-1
            info=await self.bot.downloader.extract_info(song["entries"][0]["url"],download=False,process=True)
            self.assertEqual(info.ytdl_type,"url")
            result=await self.call(base.BASE+"play",{"query":song["url"],"preview_id":song["preview_id"],"selected_items":["1"]})
            self.assertEqual((result["added"],result["skipped"]),(1,0),result)

    async def test_save_sync_and_play_use_canonical_track(self):
        song=await self.preview()
        value=await self.call("/api/library/import",{"preview_id":song["preview_id"],"revision":song["save_revision"],"name":"Saved","selected_items":["1"]})
        saved=value["playlists"][-1]
        self.assertEqual(saved["tracks"][0]["url"],self.row["external_urls"]["spotify"])
        preview=await self.call(base.BASE+"library/"+saved["id"]+"/sync/preview",{"revision":value["revision"]})
        value=await self.call("/api/library/"+saved["id"]+"/sync",{"preview_id":preview["preview_id"],"revision":preview["revision"]})
        result=await self.call(base.BASE+"library/"+saved["id"]+"/play",{"revision":value["revision"]})
        self.assertEqual(result["added"],1)

    async def test_true_or_mismatched_nested_playlist_rejected(self):
        for kind,ident in (("playlist","abcdefghijk"),("url","other123456")):
            song=await self.preview()
            parent=dict(self.child,_type=kind,entries=[dict(self.child,id=ident)])
            self.bot.downloader.extract_info=AsyncMock(return_value=YtdlpResponseDict(parent))
            value=await self.call(base.BASE+"play",{"query":song["url"],"preview_id":song["preview_id"],"selected_items":["1"]})
            self.assertEqual(value["added"],0)
