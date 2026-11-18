"""CTC path correctness and regressions for the retained S01E01 results."""
import itertools
import json
from pathlib import Path
import unittest

import numpy as np

from alignment.ctc import ctc_states

ROOT = Path(__file__).resolve().parents[1]


def collapse(labels):
    return [v for i, v in enumerate(labels) if v and (i == 0 or v != labels[i-1])]


class CTCPathTests(unittest.TestCase):
    def test_viterbi_matches_exhaustive_paths_including_repeated_letters(self):
        for target in ([1, 1], [1, 2], [2, 1, 2]):
            with self.subTest(target=target):
                scores = np.random.default_rng(123).normal(size=(6, 3))
                states = ctc_states(scores, target)
                expanded = np.zeros(len(target)*2+1, dtype=int)
                expanded[1::2] = target
                labels = expanded[states]
                self.assertEqual(collapse(labels), target)
                obtained = scores[np.arange(6), labels].sum()
                best = max(scores[np.arange(6), path].sum()
                           for path in itertools.product(range(3), repeat=6)
                           if collapse(path) == target)
                self.assertAlmostEqual(obtained, best)

    def test_long_utterances_do_not_overflow_backtrace_state(self):
        target = [1, 2]*36
        scores = np.random.default_rng(42).normal(size=(150, 3))
        states = ctc_states(scores, target)
        expanded = np.zeros(len(target)*2+1, dtype=int)
        expanded[1::2] = target
        self.assertGreater(states.max(), 127)
        self.assertEqual(collapse(expanded[states]), target)


@unittest.skipUnless((ROOT/'output/forced_alignment/S01E01/utterances.json').is_file(),
                     'Local generated alignment artifacts are not included in the source repository')
class SavedAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = ROOT/'output/forced_alignment/S01E01'
        cls.rows = json.loads((cls.folder/'utterances.json').read_text(encoding='utf-8'))

    def test_original_utterance_order_and_text_are_preserved(self):
        wiki = json.loads((ROOT/'output/wiki/episodes/S01E01.json').read_text(encoding='utf-8'))
        original = [r for r in wiki['entries'] if r['type'] == 'utterance']
        self.assertEqual([(r['id'], r['text']) for r in self.rows],
                         [(r['id'], r['text']) for r in original])

    def test_reported_cutoff_words_retain_tail_and_separate_playback_margin(self):
        expected = {39: (140.3146, 140.4346), 57: (192.7164, 192.8364)}
        for record, (end, play_end) in expected.items():
            row = next(r for r in self.rows if r['source_record'] == record)
            self.assertEqual(row['end'], end)
            self.assertEqual(row['playback']['end'], play_end)
            self.assertGreater(row['end'], row['nfa_candidate']['end'])
            self.assertAlmostEqual(row['playback']['end']-row['end'], .12)

    def test_uncertain_boundaries_remain_null_and_accepted_rows_do_not_overlap(self):
        accepted = [r for r in self.rows if r['start'] is not None]
        self.assertEqual(len(accepted), 26)
        self.assertTrue(all((r['start'] is None) == (r['end'] is None) for r in self.rows))
        self.assertTrue(all(a['end'] <= b['start'] for a, b in zip(accepted, accepted[1:])))
        self.assertTrue(all('playback' not in r for r in self.rows if r['start'] is None))


if __name__ == '__main__':
    unittest.main()
