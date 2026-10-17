"""Summon announcement link stays opt-in and member-login only."""
import types
import unittest

from musicbot.web_dashboard import summon_dashboard_url


def bot_with(**config):
    dashboard = types.SimpleNamespace(config=types.SimpleNamespace(**config)) if config else None
    return types.SimpleNamespace(_web_dashboard=dashboard)


class SummonLinkTests(unittest.TestCase):
    def test_discord_mode_https_url_is_announced(self):
        bot = bot_with(auth_mode="discord", public_url="https://music.example.com")
        self.assertEqual(summon_dashboard_url(bot), "https://music.example.com/")

    def test_trailing_slash_is_normalized(self):
        bot = bot_with(auth_mode="discord", public_url="https://music.example.com/")
        self.assertEqual(summon_dashboard_url(bot), "https://music.example.com/")

    def test_owner_mode_missing_or_insecure_url_is_not_announced(self):
        self.assertEqual(summon_dashboard_url(bot_with()), "")
        self.assertEqual(summon_dashboard_url(bot_with(auth_mode="owner", public_url="https://music.example.com")), "")
        self.assertEqual(summon_dashboard_url(bot_with(auth_mode="discord", public_url="")), "")
        self.assertEqual(summon_dashboard_url(bot_with(auth_mode="discord", public_url="http://music.example.com")), "")
        self.assertEqual(summon_dashboard_url(types.SimpleNamespace()), "")


if __name__ == "__main__":
    unittest.main()
