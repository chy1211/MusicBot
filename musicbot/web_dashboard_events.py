"""Bounded SSE transport; never authorize a stream only at connection time."""
from __future__ import annotations
from .web_dashboard_i18n import message as _web_text

import asyncio
import json
import logging
import time

log = logging.getLogger(__name__)

from aiohttp import web


class DashboardEvents:
    STREAMS_PER_USER = 6
    STREAMS_GLOBAL = 64
    EVENT_INTERVAL = 1
    HEARTBEAT_INTERVAL = 15
    WRITE_TIMEOUT = 5

    def init_events(self):
        self.stream_users = {}
        self.stream_transports = {}
        self.stream_stop = asyncio.Event()
        self.app.on_shutdown.append(self.shutdown_events)

    async def shutdown_events(self, _app=None):
        self.stream_stop.set()
        tasks = list(self.stream_users)
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=self.WRITE_TIMEOUT + 1)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def listeners(self, request):
        guild, _member = self.guild_owner(request)
        return web.json_response(self.listener_snapshot(guild))

    def listener_snapshot(self, guild):
        channel = self.bot_voice_channel(guild)
        if channel is None:
            return {"connected": False, "channel": "", "members": []}
        from .web_dashboard import public_url
        own_id = getattr(getattr(self.bot, "user", None), "id", None)
        members = [
            {"name": str(getattr(member, "display_name", None)
                         or getattr(member, "name", _web_text('m0475')))[:128],
             "avatar": public_url(getattr(getattr(member, "display_avatar", None), "url", ""))}
            for member in getattr(channel, "members", ())
            if not getattr(member, "bot", False) and getattr(member, "id", None) != own_id
        ]
        return {"connected": True, "channel": str(getattr(channel, "name", ""))[:128],
                "members": members}

    async def activity(self, request):
        guild, _member = self.guild_owner(request)
        return web.json_response(self.activity_snapshot(guild))

    def activity_snapshot(self, guild):
        records = []
        for stored in self.activities.get(guild.id, ()):
            item = dict(stored)
            parts = item.pop("detail_parts", None)
            if parts:
                item["detail"] = "".join(_web_text(part["code"], **part.get("params", {}))
                                         if isinstance(part, dict) else part for part in parts)
            code = item.pop("result_code", None)
            if code: item["result"] = _web_text(code)
            records.append(item)
        return {"activity": records,
                "resets_on_restart": True, "limit": 100}

    def record_activity(self, guild, actor, action, source, detail, result, timestamp=None, *, detail_parts=None, result_code=None):
        # Deliberately no actor ID or free-form command payload.
        self.activities[guild.id].appendleft({
            "actor": str(actor)[:128], "action": str(action)[:32],
            "source": source if source in ("web", "discord_text", "discord_slash") else "discord_text",
            "detail": str(detail)[:1600], "result": str(result)[:80],
            "time": float(timestamp if timestamp is not None else time.time()),
            "detail_parts":detail_parts,"result_code":result_code})

    def event_snapshot(self, guild, member):
        return {"state": self.snapshot(guild, member),
                "listeners": self.listener_snapshot(guild),
                "activity": self.activity_snapshot(guild),
                "history": self.history_snapshot(guild)}

    async def events(self, request):
        from .web_dashboard import APIError
        guild, member = self.guild_owner(request)
        if self.stream_stop.is_set():
            raise APIError(503, _web_text('m0497'))
        uid = member.id
        # Closed tabs can linger until the next heartbeat/write. Do not count
        # their transports against a reconnect (nor against unrelated viewers).
        live_users = [value for task, value in self.stream_users.items()
                      if not task.done() and self.stream_transports[task] is not None
                      and not self.stream_transports[task].is_closing()]
        if (len(live_users) >= self.STREAMS_GLOBAL or
                live_users.count(uid) >= self.STREAMS_PER_USER):
            raise APIError(429, _web_text('m0498'))
        task = asyncio.current_task()
        # Reserve synchronously before any await, across guilds and sessions.
        self.stream_users[task] = uid
        self.stream_transports[task] = request.transport
        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer"})
        async def write(data):
            await asyncio.wait_for(response.write(data.encode("utf-8")), self.WRITE_TIMEOUT)
        try:
            self.renew_session(request, response)
            await response.prepare(request)
            last_key, last_state, last_at = None, None, 0
            heartbeat = time.monotonic()
            while not self.stream_stop.is_set():
                if request.transport is None or request.transport.is_closing():
                    break
                if self.bot.logout_called or not self.bot.is_ready() or not self.bot.init_ok:
                    break
                # Every inspection (normally 1s): expiry, logout, blocklist and live
                # membership are checked BEFORE either data or heartbeat is written.
                if self.discord_auth:
                    self.authenticate(request)
                guild, member = self.guild_owner(request)
                bundle = self.event_snapshot(guild, member)
                current = bundle["state"]
                stable = dict(current)
                stable.pop("progress", None)
                key = json.dumps(dict(bundle, state=stable), sort_keys=True, ensure_ascii=True)
                now = time.monotonic()
                expected = ((last_state["progress"] + now - last_at)
                            if last_state and last_state["status"] == "playing"
                            else last_state["progress"] if last_state else 0)
                jumped = last_state and abs(current["progress"] - expected) > 2
                if key != last_key or jumped:
                    await write("event: snapshot\ndata: " + json.dumps(bundle, ensure_ascii=True) + "\n\n")
                    last_key, last_state, last_at = key, current, now
                if now - heartbeat >= self.HEARTBEAT_INTERVAL:
                    await write(": heartbeat\n\n")
                    heartbeat = now
                try:
                    await asyncio.wait_for(self.stream_stop.wait(), self.EVENT_INTERVAL)
                except asyncio.TimeoutError:
                    pass
        except APIError as exc:
            try:
                await write("event: access\ndata: " + json.dumps({"status": exc.status}) + "\n\n")
            except (ConnectionError, RuntimeError, asyncio.TimeoutError):
                pass
        except (ConnectionError, RuntimeError, asyncio.TimeoutError):
            pass
        except Exception as exc:
            # Headers have been sent: close rather than returning a second JSON
            # response or logging possibly sensitive exception text.
            log.warning("Dashboard stream failed (%s)", type(exc).__name__)
        finally:
            self.stream_users.pop(task, None)
            self.stream_transports.pop(task, None)
            try:
                await asyncio.wait_for(response.write_eof(), self.WRITE_TIMEOUT)
            except (ConnectionError, RuntimeError, asyncio.TimeoutError):
                pass
        return response
