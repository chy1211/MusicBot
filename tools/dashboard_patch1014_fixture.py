"""Round31 synthetic API with seek completion; never opens a voice connection."""
import asyncio
import time
from tools.dashboard_demo import DemoBot
from tools.dashboard_round31_fixture import main


async def seek(self, player, seek_time, **kwargs):
    # The synthetic player has no FFmpeg rebuild to complete pending seeks.
    player._pending_seek = None
    player.progress = float(seek_time)
    player.tick = time.monotonic()


DemoBot.cmd_seek = seek

if __name__ == '__main__':
    asyncio.run(main())
