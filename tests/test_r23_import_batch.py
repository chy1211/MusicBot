"""R23 batch import semantics, using no database/network or fake timing sleeps."""
import unittest
from musicbot.web_dashboard_import_batch import append_preview_tracks


def make_track(raw):
    if not raw.get('url') or raw.get('allowed') is False:
        raise ValueError('not permitted')
    return {'title': raw.get('title','Track'), 'url': raw['url']}


def identity(url):
    return url.split('?')[0]


class BatchImportTests(unittest.TestCase):
    def test_existing_entries_retained_and_append_order_stable(self):
        dest={'tracks':[{'url':'original'}]}
        result=append_preview_tracks(dest,[{'url':'b'},{'url':'c'}],make_track=make_track,identity=identity)
        self.assertEqual(result,{'added':2,'skipped':0})
        self.assertEqual([x['url'] for x in dest['tracks']],['original','b','c'])

    def test_duplicate_video_is_skipped(self):
        dest={'tracks':[{'url':'video'}]}
        result=append_preview_tracks(dest,[{'url':'video?tracking=1'},{'url':'second'}],make_track=make_track,identity=identity)
        self.assertEqual(result,{'added':1,'skipped':1})
        self.assertEqual(len(dest['tracks']),2)

    def test_duplicate_inside_same_batch_is_skipped(self):
        dest={'tracks':[]}
        result=append_preview_tracks(dest,[{'url':'a'},{'url':'a'},{'url':'b'}],make_track=make_track,identity=identity)
        self.assertEqual(result,{'added':2,'skipped':1})

    def test_existing_199_only_adds_one(self):
        dest={'tracks':[{'url':str(i)} for i in range(199)]}
        result=append_preview_tracks(dest,[{'url':'new1'},{'url':'new2'}],make_track=make_track,identity=identity)
        self.assertEqual(result,{'added':1,'skipped':1})
        self.assertEqual(len(dest['tracks']),200)

    def test_full_200_only_skips(self):
        dest={'tracks':[{'url':str(i)} for i in range(200)]}
        result=append_preview_tracks(dest,[{'url':'next'}],make_track=make_track,identity=identity)
        self.assertEqual(result,{'added':0,'skipped':1})

    def test_invalid_selection_does_not_mutate_existing(self):
        dest={'tracks':[{'url':'keep'}]}
        with self.assertRaises(ValueError):
            append_preview_tracks(dest,[{'url':'valid'},{'url':'bad','allowed':False}],make_track=make_track,identity=identity)
        self.assertEqual(dest['tracks'],[{'url':'keep'}])

    def test_empty_selection_rejected(self):
        with self.assertRaises(ValueError):append_preview_tracks({'tracks':[]},[],make_track=make_track,identity=identity)

    def test_over_two_hundred_selection_rejected(self):
        with self.assertRaises(ValueError):append_preview_tracks({'tracks':[]},[{'url':str(i)} for i in range(201)],make_track=make_track,identity=identity)

    def test_source_synced_playlist_is_not_overwritten(self):
        dest={'tracks':[{'url':'old'}],'source_url':'https://www.youtube.com/playlist?list=test'}
        with self.assertRaises(ValueError):
            append_preview_tracks(dest,[{'url':'new'}],make_track=make_track,identity=identity)
        self.assertEqual(dest['tracks'],[{'url':'old'}])

    def test_repeat_import_skips_previous_items(self):
        dest={'tracks':[]}
        raw=[{'url':'a'},{'url':'b'}]
        append_preview_tracks(dest,raw,make_track=make_track,identity=identity)
        result=append_preview_tracks(dest,raw,make_track=make_track,identity=identity)
        self.assertEqual(result,{'added':0,'skipped':2})
        self.assertEqual(len(dest['tracks']),2)


if __name__=='__main__':unittest.main()
