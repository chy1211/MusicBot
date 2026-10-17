"""Persistent hashed sessions, restart, revocation and daily renewal, offline."""
import dataclasses
import json
import os
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from aiohttp.test_utils import make_mocked_request
import test_web_dashboard_discord as fixtures
from musicbot.web_dashboard import Dashboard
from musicbot.web_dashboard_sessions import SessionStore

class Sessions(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.DiscordTests.asyncSetUp
    asyncTearDown=fixtures.DiscordTests.asyncTearDown
    call=fixtures.DiscordTests.call
    login_as=fixtures.DiscordTests.login_as
    provider_token=fixtures.DiscordTests.provider_token
    provider_me=fixtures.DiscordTests.provider_me

    def request(self, token):
        return make_mocked_request("GET","/auth/session",headers={
            "Host":self.dashboard.public_origin.split("://")[1],
            "Cookie":self.dashboard.session_cookie+"="+token})

    async def test_restart_same_cookie_and_only_hashes_private_atomic_file(self):
        token=self.login_as(43)
        path=self.dashboard.session_store.path
        self.assertEqual(os.stat(path).st_mode & 0o777,0o600)
        text=path.read_text()
        self.assertNotIn(token,text)
        self.assertIn(self.dashboard.session_digest(token),text)
        for forbidden in ("access_token","refresh_token",fixtures.SECRET,fixtures.TOKEN,fixtures.REFRESH):
            self.assertNotIn(forbidden,text)
        second=Dashboard(self.bot,self.dashboard.config)
        try:
            self.assertEqual(second.session_user(self.request(token))["id"],"43")
        finally: await second.close()

    async def test_expired_cookie_removed_and_cannot_revive(self):
        token=self.login_as(43); key=self.dashboard.session_digest(token)
        self.dashboard.sessions[key]["expires"]=time.time()-1
        await self.call("/api/guilds",method="GET",status=401)
        self.assertNotIn(key,SessionStore(self.auth_temp.name).read())

    async def test_logout_all_revokes_own_other_devices_but_not_other_people(self):
        own=[self.dashboard.new_session({"id":"43","name":"Friend","avatar":""}) for _ in range(3)]
        other=self.dashboard.new_session({"id":"44","name":"Other","avatar":""})
        self.client.session.cookie_jar.update_cookies({self.dashboard.session_cookie:own[0]},response_url=self.client.make_url("/"))
        await self.call("/auth/logout-all",{})
        disk=SessionStore(self.auth_temp.name).read()
        for token in own:self.assertNotIn(self.dashboard.session_digest(token),disk)
        self.assertIn(self.dashboard.session_digest(other),disk)
        for token in own:self.assertIsNone(self.dashboard.session_user(self.request(token)))

    async def test_single_logout_remains_revoked_after_restart(self):
        token=self.login_as(43)
        await self.call("/auth/logout",{})
        second=Dashboard(self.bot,self.dashboard.config)
        try:self.assertIsNone(second.session_user(self.request(token)))
        finally:await second.close()

    async def test_logout_all_csrf_and_methods_unchanged(self):
        await self.call("/auth/logout-all",{},headers={},status=403)
        await self.call("/auth/logout-all",{},headers={"X-MusicBot-Dashboard":"1","Origin":"https://other.test"},status=403)
        await self.call("/auth/logout-all",method="GET",status=405)
        await self.call("/api/guilds",method="GET")

    async def test_removed_or_blocked_session_revoked_even_on_identity_endpoint(self):
        for blocked in (False,True):
            token=self.login_as(43)
            member=self.bot.members[43]
            if blocked:self.bot.blocked_users.add(43)
            else:self.bot.members.pop(43)
            response=await self.client.get("/auth/session");value=await response.json()
            self.assertFalse(value["authenticated"])
            self.bot.members[43]=member;self.bot.blocked_users.clear()
            self.assertIsNone(self.dashboard.session_user(self.request(token)))
            self.assertNotIn(self.dashboard.session_digest(token),SessionStore(self.auth_temp.name).read())

    async def test_daily_renewal_cookie_attributes_and_write_limit(self):
        token=self.login_as(43);key=self.dashboard.session_digest(token)
        record=self.dashboard.sessions[key]
        record["created"]=record["last_seen"]=time.time()-86401
        with patch.object(self.dashboard.session_store,"write",wraps=self.dashboard.session_store.write) as writes:
            response=await self.client.get("/auth/session")
            self.assertEqual(response.status,200)
            cookie=response.cookies[self.dashboard.session_cookie]
            self.assertEqual(int(cookie["max-age"]),30*86400)
            self.assertTrue(cookie["httponly"]);self.assertEqual(cookie["samesite"],"Lax");self.assertEqual(cookie["path"],"/")
            for _ in range(4):await self.client.get("/auth/session")
            self.assertEqual(writes.call_count,1)
        self.assertGreater(record["expires"],time.time()+29*86400)

    async def test_secure_cookie_retained_and_invalid_requests_do_not_renew(self):
        token=self.login_as(43);key=self.dashboard.session_digest(token)
        self.dashboard.sessions[key]["created"]=self.dashboard.sessions[key]["last_seen"]=time.time()-86401
        with patch.object(self.dashboard.session_store,"write") as write:
            await self.call("/api/guilds",method="GET",headers={"X-MusicBot-Dashboard":"1","Origin":"https://other.test"},status=403)
            write.assert_not_called()
        self.dashboard.config=dataclasses.replace(self.dashboard.config,public_url="https://music.example.com")
        from aiohttp import web
        response=web.Response()
        self.dashboard.set_cookie(response,self.dashboard.session_cookie,token,self.dashboard.SESSION_TTL)
        self.assertTrue(response.cookies[self.dashboard.session_cookie]["secure"])

    async def test_missing_or_corrupt_file_starts_empty(self):
        path=self.dashboard.session_store.path
        for content in (None,"broken","[]",'{"version":1,"sessions":{"raw-token":{}}}'):
            if content is None:path.unlink(missing_ok=True)
            else:path.write_text(content)
            other=Dashboard(self.bot,self.dashboard.config)
            self.assertEqual(other.sessions,{})
            await other.close()

    async def test_per_person_cap_oldest_removed_and_daily_cleanup(self):
        old=self.login_as(43)
        for _ in range(10):self.dashboard.new_session({"id":"43","name":"Friend","avatar":""})
        self.assertEqual(len(self.dashboard.sessions),10)
        self.assertNotIn(self.dashboard.session_digest(old),self.dashboard.sessions)
        first=next(iter(self.dashboard.sessions))
        self.dashboard.sessions[first]["expires"]=time.time()-1
        self.dashboard.session_cleanup_at=0;self.dashboard.prune_auth()
        self.assertNotIn(first,SessionStore(self.auth_temp.name).read())
