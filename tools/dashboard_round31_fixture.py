"""Round31 isolated demo server. Serves frontend/dist and synthetic MusicBot APIs."""
from __future__ import annotations
import argparse
import asyncio
import signal
from pathlib import Path
import musicbot.web_dashboard as web_dashboard
from musicbot.web_dashboard import DashboardConfig
from tools.dashboard_demo import DemoBot, DemoDashboard, cover

ROOT = Path(__file__).resolve().parents[1]
web_dashboard.STATIC = ROOT / "frontend" / "dist"

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18310)
    args = parser.parse_args()
    config = DashboardConfig(True, args.host, args.port, auth_mode="discord",
        public_url=f"http://localhost:{args.port}", discord_client_id="1000",
        discord_client_secret="round31-fixture-only", session_hours=1)
    dashboard = DemoDashboard(DemoBot(f"http://localhost:{args.port}"), config, "owner")
    dashboard.app.router.add_get("/demo-cover/{index:[0-4]}.svg", cover)
    await dashboard.start()
    print(f"ROUND31 FIXTURE READY {args.host}:{args.port}", flush=True)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    try:
        await stopped.wait()
    finally:
        await dashboard.close()

if __name__ == "__main__":
    asyncio.run(main())
