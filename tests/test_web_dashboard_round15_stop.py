"""Invented shutdown logs only; no deployment names or live log fixtures."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from musicbot.web_dashboard_maintenance import last_stop
from musicbot.web_dashboard_i18n import LANGUAGE, message
from musicbot.bot import MusicBot

SIGNAL = "[WARNING] Caught a signal from the OS: SIGTERM\n"
SHUTDOWN = "[INFO] Disconnecting and closing down MusicBot...\n"
INTERRUPT = "[ERROR] Exception thrown while handling interrupt signal!\n"
# Paths and line numbers below are fictional.
TRACE = """Traceback (most recent call last):
  File "/app/musicbot/bot.py", line 10, in on_os_signal
    await self.logout()
  File "/app/musicbot/bot.py", line 20, in logout
    await self.update_now_playing_status(set_offline=True)
  File "/app/musicbot/bot.py", line 30, in update_now_playing_status
    await self.change_presence(status=status)
  File "/lib/discord/client.py", line 40, in change_presence
    await self.ws.change_presence(status=status)
  File "/lib/discord/gateway.py", line 50, in change_presence
    await self.send_as_json(payload)
  File "/lib/aiohttp/_websocket/writer.py", line 60, in send_frame
    raise RuntimeError("Cannot write to closing transport")
RuntimeError: Cannot write to closing transport
"""
CRASH = """Traceback (most recent call last):
  File "/app/musicbot/worker.py", line 70, in run
    raise ValueError("synthetic failure")
ValueError: synthetic failure
"""


class StopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-stop-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root/"musicbot.ended-2099-001-000000.log"

    def check(self, text, key):
        self.path.write_text(text)
        for language in ("en", "zh-TW"):
            token = LANGUAGE.set(language)
            try:
                result = last_stop(self.root)
                self.assertEqual(result["classification"], message(key))
                self.assertEqual(set(result), {"time","classification"})
            finally:
                LANGUAGE.reset(token)

    def test_signal_then_known_logout_traceback_is_normal(self):
        self.check(SIGNAL+SHUTDOWN+INTERRUPT+TRACE+"All done.\n", "m0556")

    def test_new_aiohttp_closed_transport_exception_is_normal(self):
        trace = TRACE.replace("RuntimeError:", "aiohttp.client_exceptions.ClientConnectionResetError:")
        self.check(SIGNAL+SHUTDOWN+INTERRUPT+trace, "m0556")

    def test_startup_failure_wins_even_if_later_shutdown_is_known(self):
        self.check("Error starting bot\n"+SIGNAL+SHUTDOWN+INTERRUPT+TRACE, "m0557")
        self.check("Start up failed at login.\nAll done.\n", "m0557")

    def test_known_traceback_without_signal_is_abnormal(self):
        self.check(SHUTDOWN+INTERRUPT+TRACE, "m0557")

    def test_traceback_before_signal_is_abnormal(self):
        self.check(TRACE+SIGNAL+SHUTDOWN, "m0557")

    def test_signal_with_unexpected_exception_is_abnormal(self):
        self.check(SIGNAL+SHUTDOWN+INTERRUPT+CRASH, "m0557")

    def test_same_exception_from_unrelated_stack_is_abnormal(self):
        self.check(SIGNAL+SHUTDOWN+TRACE.replace("in logout", "in play"), "m0557")

    def test_additional_crash_and_unattributed_error_message_are_abnormal(self):
        self.check(SIGNAL+SHUTDOWN+INTERRUPT+TRACE+CRASH, "m0557")
        self.check(SIGNAL+SHUTDOWN+"Exception thrown by worker!\n"+TRACE, "m0557")

    def test_incomplete_traceback_is_abnormal(self):
        self.check(SIGNAL+SHUTDOWN+"Traceback (most recent call last):\n", "m0557")

    def test_signal_context_survives_more_than_forty_lines(self):
        self.check(SIGNAL+SHUTDOWN+"[INFO] synthetic cleanup step\n"*80+INTERRUPT+TRACE, "m0556")

    def test_empty_missing_unreadable_return_none(self):
        self.assertIsNone(last_stop(self.root))
        self.path.write_text("")
        self.assertIsNone(last_stop(self.root))
        self.path.write_text("All done.")
        with patch.object(Path,"open",side_effect=PermissionError):
            self.assertIsNone(last_stop(self.root))

    def test_clean_shutdown_and_requested_restart_remain_normal(self):
        self.check(SHUTDOWN+"All done.\n", "m0556")
        self.check("Doing a full process restart.\n", "m0556")


class LogoutTests(unittest.IsolatedAsyncioTestCase):
    def bot(self, error):
        return NS(update_now_playing_status=AsyncMock(side_effect=error),
                  disconnect_all_voice_clients=AsyncMock(), close=AsyncMock(),
                  logout_called=False)

    async def test_closed_transport_during_logout_still_cleans_up(self):
        for error in (RuntimeError("Cannot write to closing transport"),
                      ConnectionResetError("Cannot write to closing transport")):
            bot = self.bot(error)
            with patch("musicbot.bot.log.noise",create=True):
                await MusicBot.logout(bot)
            self.assertTrue(bot.logout_called)
            bot.disconnect_all_voice_clients.assert_awaited_once()
            bot.close.assert_awaited_once()
            bot.update_now_playing_status.assert_awaited_once_with(set_offline=True)

    async def test_other_shutdown_exceptions_are_not_swallowed(self):
        for error in (RuntimeError("synthetic failure"),
                      ValueError("Cannot write to closing transport")):
            bot = self.bot(error)
            with patch("musicbot.bot.log.noise",create=True):
                with self.assertRaises(type(error)):
                    await MusicBot.logout(bot)
            self.assertFalse(bot.logout_called)
