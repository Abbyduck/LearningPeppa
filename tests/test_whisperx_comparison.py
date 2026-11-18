"""Regression: transcription comparison must expose omissions and extra audio."""
import unittest
from alignment.whisperx_v2_report import edit_alignment


class TranscriptComparisonTests(unittest.TestCase):
    def test_extra_intro_and_outro_do_not_replace_wiki_rows(self):
        wiki = 'muddy puddles it is raining'.split()
        asr = 'peppa pig muddy puddles it is raining peppa pig'.split()
        pairs = edit_alignment(wiki, asr)
        self.assertEqual([p for p in pairs if p[0] is not None],
                         [(i,i+2,'equal') for i in range(5)])
        self.assertEqual(sum(p[2]=='asr_extra' for p in pairs),4)

    def test_unrecognized_wiki_words_remain_explicit(self):
        pairs = edit_alignment('haha run along you two'.split(), 'run along you two'.split())
        self.assertEqual(pairs[0],(0,None,'wiki_not_recognized'))
        self.assertEqual(len([p for p in pairs if p[0] is not None]),5)

    def test_substitution_keeps_original_recognized_word(self):
        pairs=edit_alignment('sorry mummy'.split(),'sorry daddy'.split())
        self.assertEqual(pairs,[(0,0,'equal'),(1,1,'substitution')])


if __name__=='__main__':
    unittest.main()
