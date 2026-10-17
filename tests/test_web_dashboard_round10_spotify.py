"""Fabricated embed fixtures; no Spotify or network access."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from musicbot.spotify import Spotify
from musicbot.web_dashboard_imports import parse_spotify_embed, fetch_spotify_embed, SPOTIFY_EMBED_LIMIT

class EmbedTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, entity=None):
        entity = entity if entity is not None else {"name":"Fixture", "trackList":[
            {"uri":"spotify:track:abc123","title":"Song","subtitle":"Artist","duration":123000}]}
        return ('<html><script id="__NEXT_DATA__" type="application/json">' +
                json.dumps({"props":{"pageProps":{"state":{"data":{"entity":entity}}}}}) + '</script></html>').encode()

    async def test_fixture_titles_artist_duration_id_and_partial_label(self):
        value = parse_spotify_embed((Path(__file__).parent / "fixtures/spotify_embed.html").read_bytes(), "list123")
        self.assertEqual(value["tracks"]["items"][0]["track"]["duration_ms"], 123000)
        self.assertEqual(value["tracks"]["items"][0]["track"]["artists"][0]["name"], "Artist")
        self.assertTrue(value["_embed_partial"])

    async def test_missing_fields_and_oversize_fail_closed(self):
        for content in (b"<html></html>", self.fixture({}), self.fixture({"trackList":[{}]}),
                        b"x" * (SPOTIFY_EMBED_LIMIT+1)):
            with self.assertRaises((ValueError, KeyError)):
                parse_spotify_embed(content, "list123")

    async def test_discord_play_current_missing_tracks_repro_and_fallback(self):
        # /play process=True used to index pldata["tracks"]["total"] -> KeyError.
        client = NS(make_api_req=AsyncMock(return_value={"type":"playlist","name":"No tracks"}),
                    aiosession=object())
        client.get_playlist = lambda ident: Spotify.get_playlist(client, ident)
        with patch("musicbot.web_dashboard_imports.fetch_spotify_embed",
                   AsyncMock(return_value=parse_spotify_embed(self.fixture(), "list123"))) as fallback:
            value = await Spotify.get_playlist_object_complete(client, "list123")
        self.assertEqual(value.track_urls, ["https://open.spotify.com/track/abc123"])
        fallback.assert_awaited_once()

    async def test_api_success_does_not_fetch_embed_and_failure_preserves_original(self):
        value = parse_spotify_embed(self.fixture(), "list123")
        client = NS(make_api_req=AsyncMock(return_value=value), aiosession=object())
        with patch("musicbot.web_dashboard_imports.fetch_spotify_embed", AsyncMock()) as fallback:
            self.assertEqual(await Spotify.get_playlist(client, "list123"), value)
            fallback.assert_not_awaited()
        for status in (401,403,404):
            error = RuntimeError(str(status))
            client.make_api_req.side_effect = error
            with patch("musicbot.web_dashboard_imports.fetch_spotify_embed", AsyncMock(side_effect=ValueError())):
                with self.assertRaises(RuntimeError) as caught:
                    await Spotify.get_playlist(client, "list123")
                self.assertIs(caught.exception, error)

    async def test_fetch_rejects_wrong_domain_status_and_size_without_body(self):
        class Response:
            status=200; url="https://evil.test/embed"; content_length=0
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
        response=Response()
        session=NS(get=lambda *args, **kwargs: response)
        for url, status, size in (("https://evil.test/",200,0),
                                  ("https://open.spotify.com/",302,0),
                                  ("https://open.spotify.com/",200,SPOTIFY_EMBED_LIMIT+1)):
            response.url, response.status, response.content_length = url,status,size
            with self.assertRaises(ValueError):
                await fetch_spotify_embed(session, "list123")
