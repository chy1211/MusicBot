"""Real resolve routes with synthetic providers, never external traffic."""
import unittest
from musicbot import web_dashboard_search_quality as quality
import test_web_dashboard as base

class IdentityTests(unittest.TestCase):
    def test_invalid_provider_urls_are_not_trusted(self):
        for url in ('ftp://youtube.com/watch?v=abcdefghijk',
                    'https://user@youtube.com/watch?v=abcdefghijk',
                    'https://youtube.com:123/watch?v=abcdefghijk',
                    'https://youtube.com.evil.test/watch?v=abcdefghijk',
                    'https://youtube.com\\@evil.test/watch?v=abcdefghijk',
                    'https://youtube.com/\nwatch?v=abcdefghijk'):
            with self.subTest(url=url):
                self.assertEqual(quality.media_identity(url),'')
                self.assertEqual(quality.annotate_preview({'url':url})['source'],'')

    def test_unknown_platform_path_case_is_not_blindly_collapsed(self):
        for host in ('soundcloud.com','artist.bandcamp.com'):
            prefix='track/' if 'bandcamp' in host else 'artist/'
            upper=quality.media_identity(f'https://{host}/{prefix}Song')
            lower=quality.media_identity(f'https://{host}/{prefix}song')
            self.assertNotEqual(upper,lower)

    def test_youtube_variants_share_only_real_video_id(self):
        urls=['https://youtu.be/abcdefghijk?t=2',
              'https://www.youtube.com/watch?v=abcdefghijk&list=anything',
              'https://m.youtube.com/shorts/abcdefghijk',
              'https://youtube.com/live/abcdefghijk']
        self.assertEqual({quality.media_identity(url) for url in urls},{'youtube:abcdefghijk'})

    def test_fixed_multilingual_version_cases_top_one_and_three(self):
        # Synthetic candidates, not live-provider quality measurements.
        for title,artist,query in [('晴天','Jay Chou','周杰倫 晴天'),
                ('First Love','Hikaru Utada','宇多田ヒカル First Love'),
                ('Blue Sky','Example Singer','Example Singer Blue Sky')]:
            for version,label in (('live','Live'),('cover','Cover'),('remix','Remix')):
                with self.subTest(query=query,version=version):
                    rows=[dict(title='Unrelated Song',artist='Other',url='https://youtu.be/00000000000'),
                          dict(title=title+' (Official Audio)',artist=artist,url='https://youtu.be/11111111111'),
                          dict(title=title+' ('+label+')',artist=artist,url='https://youtu.be/22222222222')]
                    ranked=quality.rank_search_results(query+' '+version,rows)
                    self.assertEqual(ranked[0]['version'],version)
                    self.assertIn(rows[1],ranked[:3])

    def test_version_labels_do_not_invent_official_or_topic_claims(self):
        for title in ('Fan Lyric Video', 'Song (Audio Only)', 'Song (Lyric Video)'):
            self.assertEqual(quality.version_from_title(title),'')
        self.assertEqual(quality.version_from_title('Song','ScienceTopic'),'')
        self.assertEqual(quality.version_from_title('Song','Artist - Topic'),'topic')
        self.assertEqual(quality.version_from_title('Song (Official Audio)'),'official_audio')

class ResolveTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=base.DashboardTests.asyncSetUp
    asyncTearDown=base.DashboardTests.asyncTearDown
    call=base.DashboardTests.call

    def candidates(self):
        return [dict(self.bot.info,title=title,duration=duration,
                     webpage_url='https://www.youtube.com/watch?v='+ident,id=ident,
                     uploader='Example Singer')
                for ident,title,duration in [('abcdefghijk','Wrong Song',120),
                    ('12345678901','Blue Sky (Live)',120),
                    ('abcdefghijk','Wrong Song duplicate',120),
                    ('12345678902','Blue Sky (Official Audio)',999999)]]

    async def test_keyword_ranking_dedupe_and_limits_use_one_extraction(self):
        self.bot.perms.max_song_length=180
        self.bot.info=dict(self.bot.info,entries=self.candidates())
        body=await self.call(base.BASE+'resolve',{'query':'Blue Sky live'})
        rows=body['results'];self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['title'],'Blue Sky (Live)')
        self.assertEqual(rows[0]['source'],'YouTube');self.assertEqual(rows[0]['version'],'live')
        self.assertEqual(len(self.bot.extractions),1)
        self.assertEqual(self.bot.extractions[0][0],'ytsearch5:Blue Sky live')
        self.assertEqual(len(self.bot.player.playlist.entries),3)
        blocked=next(row for row in rows if 'Official Audio' in row['title'])
        self.assertFalse(blocked['allowed']);self.assertTrue(blocked['reason'])
        self.assertTrue(all(row['preview_id'] for row in rows))

    async def test_direct_playlist_keeps_entry_order_and_single_extraction(self):
        candidates=self.candidates()
        self.bot.info=dict(self.bot.info,entries=candidates,playlist_count=len(candidates))
        body=await self.call(base.BASE+'resolve',{'query':'https://soundcloud.com/example/list'})
        rows=body['results'][0]['entries']
        self.assertEqual([row['title'] for row in rows],[row['title'] for row in candidates])
        self.assertEqual(len(self.bot.extractions),1)

    async def test_user_search_limit_remains_enforced(self):
        self.bot.perms.max_search_items=2
        self.bot.info=dict(self.bot.info,entries=self.candidates())
        body=await self.call(base.BASE+'resolve',{'query':'Blue Sky live'})
        self.assertEqual(len(body['results']),2)
        self.assertEqual(self.bot.extractions[0][0],'ytsearch2:Blue Sky live')

    async def test_static_icons_are_public_but_only_known_svg_files_are_served(self):
        from dashboard_static_fixture import dashboard_static
        with dashboard_static():
            for name in ('history-add','history-heart','transport-play','transport-pause','transport-skip','transport-repeat'):
                response=await self.client.get('/icons/'+name+'.svg')
                self.assertEqual(response.status,200)
                self.assertEqual(response.content_type,'image/svg+xml')
                self.assertIn('<svg',await response.text())
            for name in ('unknown.svg','%2e%2e%2fsecret.svg','options.ini'):
                response=await self.client.get('/icons/'+name)
                self.assertEqual(response.status,404)
