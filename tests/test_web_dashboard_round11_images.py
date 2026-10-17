"""Fabricated Spotify image structure and persisted fallback."""
import unittest
import test_web_dashboard_round10_spotify as embed
from musicbot.web_dashboard_imports import parse_spotify_embed, imported_track, spotify_image
from musicbot.web_dashboard_library import song
class Images(unittest.TestCase):
    def test_embed_cover_and_track_precedence(self):
        helper=embed.EmbedTests()
        entity={"name":"Test","coverArt":{"sources":[{"url":"https://mosaic.scdn.co/640/fake"}]},
                "trackList":[{"uri":"spotify:track:abc","title":"Song","duration":120000}]}
        for custom in (False,True):
            if custom: entity["trackList"][0]["coverArt"]={"sources":[{"url":"https://i.scdn.co/image/fake"}]}
            row=parse_spotify_embed(helper.fixture(entity),"list123")["tracks"]["items"][0]["track"]
            expected="https://i.scdn.co/image/fake" if custom else "https://mosaic.scdn.co/640/fake"
            self.assertEqual(imported_track(row,"spotify")["thumbnail"],expected)
            self.assertEqual(song(imported_track(row,"spotify"))["thumbnail"],expected)
    def test_normalization_and_safe_placeholder(self):
        for value in ("spotify:image:abc123","/image/abc123","//i.scdn.co/image/abc123"):
            self.assertEqual(spotify_image(value),"https://i.scdn.co/image/abc123")
        for value in ("http://i.scdn.co/a","https://evil.test/a","https://u:p@i.scdn.co/a","https://i.scdn.co.evil.test/a",{}):
            self.assertEqual(spotify_image(value),"")
