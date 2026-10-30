import json
import time
import unittest
from unittest.mock import patch
from musicbot.web_dashboard_reuse import CompleteInfoCache
from musicbot.web_dashboard_preview import MAX_EXTRACTION_AGE

class CompleteInfoCacheTests(unittest.TestCase):
    def valid(self):
        url='https://www.youtube.com/watch?v=AbCdEf12345'
        return url, {'extractor':'youtube','_type':'video','__input_subject':url,
                     '__extracted_at':time.time(),'formats':[{'url':'https://example.invalid/audio'}]}
    def test_full_info_is_reused_but_context_isolated(self):
        cache=CompleteInfoCache();url,data=self.valid()
        owner_a=(1,11,'cookie1','settings1',url)
        owner_b=(1,12,'cookie1','settings1',url)
        self.assertTrue(cache.put(owner_a,url,data))
        self.assertEqual(cache.get(owner_a,url)[1],'hit')
        self.assertIsNone(cache.get(owner_b,url)[0])
        self.assertIsNone(cache.get((1,11,'cookie2','settings1',url),url)[0])
        self.assertIsNone(cache.get((1,11,'cookie1','settings2',url),url)[0])
    def test_flat_results_not_cached_and_bad_formats_fail(self):
        cache=CompleteInfoCache();url,data=self.valid()
        self.assertFalse(cache.put(('x',),url,{**data,'formats':[]}))
        self.assertFalse(cache.put(('x',),url,{**data,'entries':[data]}))
        self.assertFalse(cache.put(('x',),url,{**data,'__extracted_at':time.time()-3600}))
    def test_expiry_and_bounds(self):
        cache=CompleteInfoCache();url,data=self.valid()
        for i in range(11):self.assertTrue(cache.put((i,),url,data))
        self.assertEqual(len(cache._items),8)
        self.assertIsNone(cache.get((0,),url)[0])
        cache._items[(10,)]=(time.monotonic()-1,cache._items[(10,)][1])
        self.assertIsNone(cache.get((10,),url)[0])
    def test_invalidated_format_or_signature_is_not_reused(self):
        cache=CompleteInfoCache();url,data=self.valid()
        self.assertTrue(cache.put(('a',),url,data))
        copy,reason=cache.get(('a',),url)
        copy['formats'].clear()
        self.assertEqual(cache.get(('a',),url)[1],'hit') # defensive JSON copy
