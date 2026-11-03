"""R24 popularity periods: inclusive 180 days, preserving legacy semantics.

No Discord/YouTube/network. Use a fake UTC day and in-memory store.
"""
import asyncio
import datetime as dt
import tempfile
import unittest
from musicbot.web_dashboard_stats import PopularityStore, normalized_url


class Popular180Tests(unittest.IsolatedAsyncioTestCase):
    async def test_180_includes_today_and_179_days_ago(self):
        now=dt.date(2026,10,31)
        with tempfile.TemporaryDirectory() as tmp:
            store=PopularityStore(tmp,flush_interval=0,clock=lambda:now)
            guild=42
            u=normalized_url('https://www.youtube.com/watch?v=FoufxW6WE4U')
            store.cache[guild]={"version":1,"tracks":{u:{"url":u,"title":"Test","duration":200,
                "days":{(now-dt.timedelta(days=179)).isoformat():2,now.isoformat():3}}}}
            rows=await store.top(guild,'180')
            self.assertEqual(rows[0]['count'],5)
            self.assertEqual((await store.top(guild,'7'))[0]['count'],3)
            self.assertEqual((await store.top(guild,'all'))[0]['count'],5)
            await store.close()

    async def test_old_days_not_counted_and_validation(self):
        now=dt.date(2026,10,31)
        with tempfile.TemporaryDirectory() as tmp:
            store=PopularityStore(tmp,flush_interval=0,clock=lambda:now)
            u=normalized_url('https://www.youtube.com/watch?v=FoufxW6WE4U')
            store.cache[42]={"version":1,"tracks":{u:{"url":u,"title":"Test","duration":200,
                "days":{(now-dt.timedelta(days=180)).isoformat():10,now.isoformat():1}}}}
            self.assertEqual((await store.top(42,'180'))[0]['count'],1)
            with self.assertRaises(ValueError):await store.top(42,'bad')
            await store.close()

    async def test_default_is_180_days(self):
        now=dt.date(2026,10,31)
        with tempfile.TemporaryDirectory() as tmp:
            store=PopularityStore(tmp,flush_interval=0,clock=lambda:now)
            u=normalized_url('https://www.youtube.com/watch?v=FoufxW6WE4U')
            store.cache[42]={"version":1,"tracks":{u:{"url":u,"title":"Test","duration":200,
                "days":{(now-dt.timedelta(days=50)).isoformat():1}}}}
            self.assertEqual(len(await store.top(42)),1)
            self.assertEqual(await store.top(42,'7'),[])
            await store.close()

if __name__=='__main__':unittest.main()
