"""Synthetic real HTTP import routes; no external provider requests."""
import unittest,time,copy
from unittest.mock import patch
import test_web_dashboard_imports as original
from musicbot.web_dashboard_library import song

class BatchRoutes(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=original.ImportTests.asyncSetUp
    asyncTearDown=original.ImportTests.asyncTearDown
    provider_token=original.ImportTests.provider_token
    provider_me=original.ImportTests.provider_me
    login_as=original.ImportTests.login_as
    call=original.ImportTests.call
    library=original.ImportTests.library
    preview=original.ImportTests.preview

    async def setup_preview(self, existing=0):
        self.bot.downloader.extract_info.return_value={'title':'Batch','entries':[original.video(1),original.video(2)]}
        def seed(value):
            value['playlists'][0]['tracks']=[song({'title':'Existing '+str(i),'url':'https://youtu.be/v'+str(i).zfill(10),'duration':120}) for i in range(existing)]
        await self.dashboard.playlist_store.transact(43,seed)
        return await self.preview()

    async def append(self, preview, *, status=200, selected=None, target='favorites'):
        data={'preview_id':preview['preview_id'],'revision':preview['revision'],'target_playlist_id':target}
        if selected is not None:data['selected_items']=selected
        return await self.call('/api/library/import',data,status=status)

    async def test_append_keeps_original_order_and_consumes_token_once(self):
        p=await self.setup_preview(1);v=await self.append(p,selected=['2','1'])
        tracks=v['playlists'][0]['tracks'];self.assertEqual([t['title'] for t in tracks],['Existing 0','Video 1','Video 2'])
        self.assertEqual((v['added'],v['skipped']),(2,0));await self.append(p,status=409)
        self.bot.downloader.extract_info.assert_awaited_once()

    async def test_capacity_199_and_200_is_bounded(self):
        for existing in (199,200):
            p=await self.setup_preview(existing);v=await self.append(p)
            self.assertEqual(len(v['playlists'][0]['tracks']),200)
            self.assertEqual((v['added'],v['skipped']),(200-existing,2-(200-existing)))

    async def test_invalid_selection_preserves_token_and_data(self):
        p=await self.setup_preview(1);before=await self.library();await self.append(p,selected=['1','missing'],status=400)
        self.assertEqual(await self.library(),before);self.assertIn(p['preview_id'],self.dashboard.import_previews)

    async def test_stale_revision_is_rejected(self):
        p=await self.setup_preview();await self.dashboard.playlist_store.transact(43,lambda v:v['playlists'][0].update(name='Changed'))
        await self.append(p,status=409)
        self.assertIn(p['preview_id'],self.dashboard.import_previews)

    async def test_other_owner_and_expired_tokens_are_rejected(self):
        p=await self.setup_preview();self.login_as(44);await self.append(p,status=409)
        self.login_as(43);self.dashboard.import_previews[p['preview_id']]['expires']=time.monotonic()-1
        await self.append(p,status=409)

    async def test_source_linked_destination_rejected(self):
        created=await self.call('/api/library',{'name':'Source'})
        target=created['playlists'][-1]['id']
        def source(value):value['playlists'][-1].update(source_url=original.YT,source_type='youtube')
        await self.dashboard.playlist_store.transact(43,source);p=await self.setup_preview()
        await self.append(p,status=400,target=target)

    async def test_storage_failure_keeps_preview_and_original_file(self):
        p=await self.setup_preview(1);before=await self.library()
        with patch('musicbot.web_dashboard_library.atomic_write',side_effect=OSError('synthetic disk failure')):
            await self.append(p,status=500)
        self.assertEqual(await self.library(),before);self.assertIn(p['preview_id'],self.dashboard.import_previews)
        self.assertEqual((await self.append(p))['added'],2)

    async def test_member_block_after_preview_prevents_confirmation(self):
        p=await self.setup_preview();self.bot.blocked_users.add(43)
        await self.append(p,status=403)

    async def test_membership_removed_after_preview_is_rejected(self):
        p=await self.setup_preview();self.bot.guild.get_member=lambda uid:None
        await self.append(p,status=403)

    async def test_new_playlist_reports_added_and_preserves_selection(self):
        p=await self.setup_preview()
        value=await self.call('/api/library/import',{'preview_id':p['preview_id'],'revision':p['revision'],'name':'New batch','selected_items':['2']})
        self.assertEqual((value['added'],value['skipped']),(1,0))
        self.assertEqual([t['title'] for t in value['playlists'][-1]['tracks']],['Video 2'])

    async def test_concurrent_confirmation_is_one_time(self):
        import asyncio
        p=await self.setup_preview()
        data={'preview_id':p['preview_id'],'revision':p['revision'],'target_playlist_id':'favorites'}
        from test_web_dashboard import HEADERS
        async def send():
            response=await self.client.post('/api/library/import',json=data,headers=dict(HEADERS,Origin=self.origin))
            await response.read();return response.status
        self.assertEqual(sorted(await asyncio.gather(send(),send())),[200,409])
        self.assertEqual(len((await self.library())['playlists'][0]['tracks']),2)

    async def test_youtube_url_variants_are_one_identity(self):
        def seed(value):value['playlists'][0]['tracks']=[song({'title':'Already saved','url':'https://youtu.be/video000001','duration':123})]
        await self.dashboard.playlist_store.transact(43,seed)
        self.bot.downloader.extract_info.return_value={'title':'Batch','entries':[original.video(1),original.video(2)]}
        value=await self.append(await self.preview())
        self.assertEqual((value['added'],value['skipped']),(1,1))
