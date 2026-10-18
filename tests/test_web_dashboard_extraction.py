"""Offline web extraction security regressions; never contact a provider."""
import asyncio
import socket
import unittest
from unittest.mock import patch, Mock

from yt_dlp.extractor.common import InfoExtractor
from musicbot.web_dashboard_extraction import (
    WEB_EXTRACTION, DashboardYoutubeDL, UnsupportedDashboardURL, normalize_query,
)
import test_web_dashboard as fixtures
from test_web_dashboard import BASE

# These are test-only addresses, not deployment/network discovery targets.
UNSAFE = (
    'http://127.0.0.1/song', 'http://localhost/song', 'http://10.1.2.3/song',
    'http://172.16.0.1/song', 'http://192.168.1.1/song',
    'http://169.254.169.254/latest/meta-data/', 'http://100.64.0.1/song',
    'http://224.0.0.1/song', 'http://240.0.0.1/song', 'http://0.0.0.0/song',
    'http://[::1]/song', 'http://[fc00::1]/song', 'http://[fe80::1]/song',
    'http://[::ffff:127.0.0.1]/song', 'http://2130706433/song',
    'https://media.example/song.mp3', 'https://rebind.example/song',
)


class FakeServiceIE(InfoExtractor):
    IE_NAME = 'security-test-service'
    _VALID_URL = r'https://video\.example/(?P<id>[a-z]+)'
    target = None

    def _real_extract(self, url):
        if self.target:
            return {'_type': 'url', 'url': self.target, 'ie_key': 'Generic'}
        return {'id': 'song', 'title': 'Public song', 'url': 'https://cdn.example/song.mp3',
                'ext': 'mp3'}


class ExtractionPolicyTests(unittest.TestCase):
    def test_non_public_and_generic_inputs_never_resolve_dns(self):
        # Simulated rebinding resolver: first public answer, then loopback.
        resolver = Mock(side_effect=[[(socket.AF_INET, 1, 6, '', ('93.184.216.34', 80))],
                                    [(socket.AF_INET, 1, 6, '', ('127.0.0.1', 80))]])
        with patch('socket.getaddrinfo', resolver):
            for url in UNSAFE:
                with self.subTest(url=url), self.assertRaises(UnsupportedDashboardURL):
                    normalize_query(url)
        resolver.assert_not_called()

    def test_normalize_known_services_without_network(self):
        for url in ('https://www.youtube.com/watch?v=abc12345678',
                    'https://music.youtube.com/watch?v=abc12345678',
                    'https://youtu.be/abc12345678',
                    'https://open.spotify.com/track/1234567890',
                    'https://soundcloud.com/example/song',
                    'https://artist.bandcamp.com/track/song'):
            with self.subTest(url=url):
                self.assertEqual(normalize_query(url), url)
        self.assertEqual(normalize_query(' <HTTPS://SOUNDCLOUD.COM/example/song#t=3> '),
                         'https://soundcloud.com/example/song')
        self.assertEqual(normalize_query('music.youtube.com/watch?v=abc12345678'),
                         'https://music.youtube.com/watch?v=abc12345678')

    def test_credentials_schemes_ports_and_host_spoofing(self):
        for url in ('https://soundcloud.com@localhost/song', 'file:///etc/passwd',
                    'https://soundcloud.com:9000/example/song',
                    'https://soundcloud.com.evil.example/example/song',
                    'https://soundcloud.com\\@localhost/song', 'https://[::1/song'):
            with self.subTest(url=url), self.assertRaises(UnsupportedDashboardURL):
                normalize_query(url)

    def test_generic_redirect_to_internal_never_makes_initial_request(self):
        # A generic redirect endpoint is rejected before GET, HEAD or download.
        with patch.object(DashboardYoutubeDL, 'urlopen', side_effect=AssertionError('network')) as network:
            with DashboardYoutubeDL({'quiet': True}) as client:
                for download in (False, True):
                    with self.assertRaises(UnsupportedDashboardURL):
                        client.extract_info('https://redirect.example/to-private', download=download)
                self.assertNotIn('Generic', client._ies)
        network.assert_not_called()

    def test_dedicated_nested_generic_redirect_is_denied(self):
        for target in UNSAFE:
            with self.subTest(target=target), patch(
                    'musicbot.web_dashboard_extraction.dedicated_extractors', return_value=(FakeServiceIE,)):
                with DashboardYoutubeDL({'quiet': True}) as client:
                    fake = FakeServiceIE(); fake.target = target
                    client.add_info_extractor(fake)
                    with patch.object(client, 'urlopen', side_effect=AssertionError('network')) as network:
                        with self.assertRaises(UnsupportedDashboardURL):
                            client.extract_info('https://video.example/redirect', download=False)
                        network.assert_not_called()

    def test_normal_public_service_extracts_with_mock(self):
        with patch('musicbot.web_dashboard_extraction.dedicated_extractors', return_value=(FakeServiceIE,)):
            with DashboardYoutubeDL({'quiet': True}) as client:
                client.add_info_extractor(FakeServiceIE())
                with patch.object(client, 'urlopen', side_effect=AssertionError('network')):
                    info = client.extract_info('https://video.example/song', download=False)
                self.assertEqual(info['title'], 'Public song')

    def test_native_discord_runner_keeps_original_client_and_generic(self):
        from musicbot.downloader import Downloader
        client = Mock()
        owner = Mock(); owner._cookie_clients.snapshot.return_value = (client, client)
        token = WEB_EXTRACTION.set(False)
        try:
            Downloader._run_ytdl(owner, False, 'extract_info', 'https://generic.example/song')
        finally:
            WEB_EXTRACTION.reset(token)
        client.extract_info.assert_called_once_with('https://generic.example/song')


class WebEntrySecurityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.DashboardTests.asyncSetUp
    asyncTearDown = fixtures.DashboardTests.asyncTearDown
    call = fixtures.DashboardTests.call

    async def test_resolve_and_unconfirmed_play_reject_generic_before_downloader(self):
        for action in ('resolve', 'play', 'playnext'):
            for url in UNSAFE:
                with self.subTest(action=action, url=url):
                    result = await self.call(BASE + action, {'query': url}, status=400)
                    self.assertTrue(result['error'])
        self.assertFalse(self.bot.extractions)
        self.bot.get_player.assert_not_awaited()

    async def test_errors_are_localized(self):
        for language, expected in [('en', 'not supported'), ('zh-TW', '\u4e0d\u652f\u63f4')]:
            result = await self.call(BASE + 'resolve', {'query': UNSAFE[0]}, status=400,
                headers={'X-MusicBot-Dashboard': '1', 'X-Dashboard-Language': language})
            self.assertIn(expected, result['error'])

    async def test_web_context_is_scoped_and_normal_public_resolution_works(self):
        seen = []
        original = self.bot.downloader.extract_info
        async def extract(*args, **kwargs):
            seen.append(WEB_EXTRACTION.get())
            return await original(*args, **kwargs)
        self.bot.downloader.extract_info = extract
        await self.call(BASE + 'resolve', {'query': 'https://soundcloud.com/example/song'})
        await self.call(BASE + 'play', {'query': 'https://soundcloud.com/example/song'})
        self.assertEqual(seen, [True, True])
        self.assertFalse(WEB_EXTRACTION.get())
