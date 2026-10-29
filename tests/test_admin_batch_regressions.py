"""Patches #5-8: run inside MusicBot's tests directory.

python -m unittest discover -s tests -p 'test_admin_batch_regressions.py' -v
Requires the repository's normal dependencies; no Discord login or network I/O.
"""
import asyncio
import json
import unittest
from collections import deque
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from threading import Condition, Event

from musicbot.web_dashboard_admin import DashboardAdmin
from musicbot.web_dashboard_maintenance import DashboardMaintenance
from musicbot.player import SourcePlaybackCounter

class AutoplaylistMetadataTests(unittest.TestCase):
    def fixture(self):
        guild = NS(id=200)
        from_history = {'url': 'https://example.org/old', 'title': 'History title',
                        'thumbnail': 'https://example.org/old.jpg', 'duration': 120}
        live = NS(url='https://example.org/live', title='Now playing',
                  thumbnail_url='https://example.org/live.jpg', duration=180)
        player = NS(current_entry=live, playlist=NS(entries=deque()))
        dashboard = NS(recent_history={200:deque([from_history])},
                       bot=NS(get_player_in=lambda _:player))
        request = NS(query={'page':'1','q':''})
        return dashboard, guild, request

    def test_cached_titles_covers_and_unknown_fallback(self):
        dashboard,guild,req=self.fixture()
        rows=DashboardAdmin.autoplaylist_page(dashboard,[
            'https://example.org/live','https://example.org/old','https://example.org/unknown'],req,guild)['tracks']
        self.assertEqual(rows[0]['title'],'Now playing')
        self.assertEqual(rows[0]['thumbnail'],'https://example.org/live.jpg')
        self.assertTrue(rows[0]['known'])
        self.assertEqual(rows[1]['title'],'History title')
        self.assertFalse(rows[2]['known'])
        self.assertFalse(rows[2]['thumbnail'])
        self.assertEqual(len(rows),3)

    def test_no_remote_fetch_and_no_private_file_path(self):
        dashboard,guild,req=self.fixture()
        dashboard.bot.get_player_in=Mock(side_effect=dashboard.bot.get_player_in)
        rows=DashboardAdmin.autoplaylist_page(dashboard,[
            '/private/secret.mp3','file:///private/secret.mp3','https://example.org/public'],req,guild)['tracks']
        self.assertNotIn('/private/secret',str(rows))
        self.assertEqual([row['index'] for row in rows],[0,1,2])
        dashboard.bot.get_player_in.assert_called_once_with(guild)

    def test_search_uses_enriched_title(self):
        dashboard,guild,req=self.fixture()
        req.query={'page':'1','q':'history title'}
        data=DashboardAdmin.autoplaylist_page(dashboard,[
            'https://example.org/live','https://example.org/old'],req,guild)
        self.assertEqual(data['matched'],1)
        self.assertEqual(data['tracks'][0]['url'],'https://example.org/old')

    def test_youtube_cover_validation_and_original_indices(self):
        dashboard,guild,req=self.fixture()
        urls=['https://youtu.be/dQw4w9WgXcQ',
              'https://youtube.com.evil.invalid/watch?v=dQw4w9WgXcQ',
              'https://www.youtube.com/watch?v=invalid',
              'https://example.org/old']
        rows=DashboardAdmin.autoplaylist_page(dashboard,urls,req,guild)['tracks']
        self.assertEqual(rows[0]['thumbnail'],'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg')
        self.assertEqual(rows[1]['thumbnail'],'')
        self.assertEqual(rows[2]['thumbnail'],'')
        req.query={'q':'history title'}
        filtered=DashboardAdmin.autoplaylist_page(dashboard,urls,req,guild)
        self.assertEqual(filtered['tracks'][0]['index'],3)
        self.assertEqual(filtered['revision'],DashboardAdmin.autoplaylist_page(dashboard,urls,NS(query={}),guild)['revision'])

    def test_other_guild_metadata_is_not_used(self):
        dashboard,guild,req=self.fixture()
        dashboard.recent_history[999]=[{'url':'https://example.org/unknown','title':'private other guild'}]
        row=DashboardAdmin.autoplaylist_page(dashboard,['https://example.org/unknown'],req,guild)['tracks'][0]
        self.assertFalse(row['known'])
        self.assertNotIn('private other guild',str(row))

class AudioDiagnosticsTests(unittest.TestCase):
    def test_bounded_numeric_fields_do_not_leak_errors(self):
        import musicbot.player as runtime
        self.enterContext(patch.object(runtime.log,'noise',runtime.log.debug,create=True))
        source=NS(cleanup=lambda:None)
        # is_opus is computed using isinstance(FFmpegOpusAudio) without I/O.
        counter=SourcePlaybackCounter(source, continuous=True)
        with counter._buffer_cond:
            counter._prefetched_frames.append(b'not-for-the-dashboard')
            counter._underrun_frames=7
            counter._prefetch_error=OSError('SECRET_MEDIA_PATH_MUST_NOT_ESCAPE')
        data=counter.diagnostics()
        self.assertEqual(data['buffered_ms'],20)
        self.assertEqual(data['capacity_ms'],1000)
        self.assertEqual(data['underrun_frames'],7)
        self.assertEqual(data['read_error'],'OSError')
        self.assertNotIn('SECRET_',json.dumps(data))
        self.assertNotIn('not-for-the-dashboard',json.dumps(data))
        counter.cleanup()

class OwnerHealthRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_only_live_snapshot_does_not_inherit_cache_staleness(self):
        guild=NS(id=200)
        current=NS(diagnostics=lambda:{'buffered_ms':200,'capacity_ms':1000,
                                      'underrun_frames':2,'read_error':''})
        player=NS(is_playing=True,is_paused=False,_source=current)
        context=NS(discord_auth=False,
            require_owner=lambda request:(guild,None),
            bot=NS(get_player_in=lambda guild:player,_init_time=1000),
            web_viewers={},dashboard_started_at=1000,
            maintenance_lock=asyncio.Lock(),
            maintenance_cached=(float('inf'),{'cookie':{'status':'unused'}}))
        result=await DashboardMaintenance.admin_maintenance(context,NS())
        data=json.loads(result.text)
        self.assertEqual(data['audio']['state'],'playing')
        self.assertEqual(data['audio']['buffered_ms'],200)
        self.assertEqual(data['audio']['underrun_frames'],2)
        player._source=None
        player.is_playing=False
        player._play_task=NS(done=lambda:False)
        result=await DashboardMaintenance.admin_maintenance(context,NS())
        self.assertEqual(json.loads(result.text)['audio']['state'],'preparing')

if __name__=='__main__': unittest.main(verbosity=2)
