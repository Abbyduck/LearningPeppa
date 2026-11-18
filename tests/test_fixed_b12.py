"""Artifact regressions for the pinned B12 run and complete Wiki export."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'output/whisperx_b12/S01E01'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))


@unittest.skipUnless((P/'utterances.json').is_file(),
                     'Local B12 run artifacts are not included in the source repository')
class FixedB12Tests(unittest.TestCase):
    def test_config_lock_and_actual_effective_options_match(self):
        path=ROOT/'configs/whisperx_b12.fixed.json';cfg=read(path)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(digest,path.with_suffix('.sha256').read_text().strip())
        self.assertEqual(digest,read(P/'run.json')['config_sha256'])
        actual=read(P/'effective_asr_options.json')
        expected=dict(cfg['load_model']['asr_options']);expected.pop('suppress_numerals')
        self.assertEqual(actual['asr_options'],expected)
        self.assertEqual(actual['transcribe']['chunk_size'],12)
        self.assertEqual(cfg['source_explicit_transcribe_kwargs']['chunk_size'],12)

    def test_all_wiki_records_fields_and_roles_survive(self):
        original=[r for r in read(ROOT/'output/wiki/season1/episodes/S01E01.json')['entries'] if r['type']=='utterance']
        exported=read(P/'utterances.json')
        self.assertEqual(len(exported),43)
        for old,new in zip(original,exported):
            for key,value in old.items():self.assertEqual(new[key],value,(old['id'],key))
            self.assertLess(new['playback_context']['start'],new['playback_context']['end'])
            self.assertEqual(new['start'] is None,new['end'] is None)

    def test_original_word_times_not_repaired(self):
        aligned=[w for s in read(P/'aligned.raw.json')['segments'] for w in s['words']]
        final=[w for s in read(P/'result.whisperx.json')['segments'] for w in s['words']]
        self.assertEqual([(w.get('word'),w.get('start'),w.get('end')) for w in aligned],
                         [(w.get('word'),w.get('start'),w.get('end')) for w in final])
        for row in read(P/'utterances.json'):
            for index,word in zip(row['raw_word_indices'],row['words']):
                for key,value in final[index].items():self.assertEqual(word[key],value)

    def test_end_dialogue_stays_near_user_accepted_local_b(self):
        local=read(ROOT/'output/local_timing_254_278/comparison.json')
        expected={r['source_record']:r['candidates']['B12'] for r in local['utterances']}
        for row in read(P/'utterances.json'):
            if row['source_record'] in [86,87]:
                previous=expected[row['source_record']]
                for key in ['start','end']:self.assertLess(abs(row['candidate'][key]-previous[key]),.05)


if __name__=='__main__':unittest.main()
