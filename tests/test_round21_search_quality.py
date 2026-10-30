"""Offline search ranking tests."""
import unittest
from musicbot import web_dashboard_search_quality as quality


def video(vid, title, artist='', allowed=True, extra=''):
    return dict(url=f'https://www.youtube.com/watch?v={vid}{extra}',title=title,artist=artist,allowed=allowed)



class SearchQualityTests(unittest.TestCase):
    def test_fullwidth_mixed_case(self):
        self.assertEqual(quality.normalize(' Ｏｆｆｉｃｉａｌ　Ａｕｄｉｏ '), 'official audio')

    def test_music_language_alias(self):
        tracks=[video('12345678901','晴天','Jay Chou'),video('12345678902','Other','Another')]
        self.assertEqual(quality.rank_search_results('周杰倫 晴天',tracks)[0]['url'].split('=')[1],'12345678901')

    def test_versions_not_collapsed_by_song_title(self):
        tracks=[video('12345678901','A - Blue (MV)'),video('12345678902','A - Blue (Live)')]
        self.assertEqual(len(quality.rank_search_results('A Blue',tracks)),2)

    def test_explicit_live_intent_wins(self):
        tracks=[video('12345678901','A Blue (Official Audio)'),video('12345678902','A Blue (Live)')]
        self.assertIn('Live',quality.rank_search_results('A Blue live',tracks)[0]['title'])

    def test_duplicate_youtube_id_not_title(self):
        tracks=[video('12345678901','First',extra='&list=abc'),dict(url='https://youtu.be/12345678901', title='Second',artist='',allowed=True),video('12345678902','First')]
        self.assertEqual(len(quality.rank_search_results('First',tracks)),2)

    def test_source_and_claim_only(self):
        row=quality.annotate_preview(video('12345678901','Song (Official Audio)'))
        self.assertEqual(row['source'],'YouTube')
        self.assertEqual(row['version'],'official_audio')
        self.assertNotIn('verified',row)

    def test_unknown_url_no_false_dedupe(self):
        tracks=[dict(title='Same',url='https://other.example/a',allowed=True),dict(title='Same',url='https://other.example/b',allowed=True)]
        self.assertEqual(len(quality.rank_search_results('Same',tracks)),2)

    def test_allowed_unchanged(self):
        row=video('12345678901','Song',allowed=False)
        quality.rank_search_results('Song',[row])
        self.assertIs(row['allowed'],False)

    def test_stable_order_for_same_title(self):
        tracks=[video('12345678901','Song'),video('12345678902','Song')]
        self.assertEqual([x['url'] for x in quality.rank_search_results('Song',tracks)],[x['url'] for x in tracks])

    def test_does_not_modify_preview_id(self):
        row=video('12345678901','Song')
        row['preview_id']='opaque-token'
        self.assertEqual(quality.rank_search_results('Song',[row])[0]['preview_id'],'opaque-token')

if __name__=='__main__':unittest.main()
