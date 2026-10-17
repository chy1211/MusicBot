import test_web_dashboard as base
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from musicbot.bot import MusicBot
from musicbot.constructs import Response

class NotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_force_plain_and_mentions_disabled_even_with_embeds_enabled(self):
        config = NS(embeds=True, remove_embed_footer=True, delete_delay_short=0, delete_messages=False)
        bot = NS(config=config)
        destination = NS(name="Fixture",send=AsyncMock())
        response = Response("-# Nick through web\nNative body",force_text=True)
        response.dashboard_no_mentions = True
        await MusicBot.safe_send_message(bot, destination, response)
        args, kwargs = destination.send.call_args
        self.assertEqual(args, ("-# Nick through web\nNative body\n",))
        self.assertNotIn("embed",kwargs)
        self.assertEqual(kwargs["allowed_mentions"].to_dict(), {"parse":[]})
        native = Response("Native")
        destination.send.reset_mock()
        await MusicBot.safe_send_message(bot,destination,native)
        self.assertIs(destination.send.call_args.kwargs["embed"],native)
        self.assertNotIn("allowed_mentions",destination.send.call_args.kwargs)
