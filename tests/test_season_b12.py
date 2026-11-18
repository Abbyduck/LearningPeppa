import json
from pathlib import Path
import tempfile
import unittest
import wave
from run_season_b12 import discover,media_episode,check_reuse
from run_fixed_b12 import sha
from alignment.b12_report import build
TEST_ROOT=Path(__file__).resolve().parents[1]


class SeasonB12Tests(unittest.TestCase):
    def test_numeric_episode_matching_does_not_depend_on_title(self):
        self.assertEqual(media_episode('S151 Daddy’s Movie Camera'),'S01E51')
        self.assertEqual(media_episode('S01E02 arbitrary title'),'S01E02')
        self.assertIsNone(media_episode('random'))

    def test_discovery_rejects_missing_or_duplicate_media(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as tmp:
            self.assertTrue(Path(tmp).resolve().is_relative_to(TEST_ROOT))
            root=Path(tmp);w=root/'wiki';v=root/'video';w.mkdir();v.mkdir()
            (w/'S01E02.json').write_text(json.dumps(dict(episode=dict(id='S01E02',title='Mr Dinosaur'),entries=[dict(type='utterance',text='Hi')])))
            with self.assertRaisesRegex(ValueError,'Missing media'):discover(w,v)
            (v/'S102 different title.mp4').write_bytes(b'1')
            self.assertEqual(discover(w,v)[0]['episode'],'S01E02')
            (v/'S01E02 duplicate.mp4').write_bytes(b'2')
            with self.assertRaisesRegex(ValueError,'Duplicate media'):discover(w,v)

    def test_generic_report_keeps_missing_utterance_and_roles(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as tmp:
            self.assertTrue(Path(tmp).resolve().is_relative_to(TEST_ROOT))
            p=Path(tmp)
            def put(name,data):(p/name).write_text(json.dumps(data),encoding='utf-8')
            put('run.json',dict(status='completed',episode='S01E08',audio_seconds=5,processing_wall_seconds=.1,config_sha256='test',timings={},timing_scope='batch'))
            put('wiki.json',dict(entries=[dict(type='utterance',id='one',text='Hello.',speakers=['Peppa'],source_record=1),dict(type='utterance',id='two',text='Ooh...',speakers=['George'],source_record=2)]))
            seg=dict(text='Hello.',start=1.,end=1.5,words=[dict(word='Hello.',start=1.,end=1.5,score=.7)])
            put('result.whisperx.json',dict(segments=[seg]));put('asr.raw.json',dict(segments=[seg]))
            with wave.open(str(p/'source_audio.wav'),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*80000)
            build(p,p/'wiki.json',batch_authorized=True)
            rows=json.loads((p/'utterances.json').read_text(encoding='utf-8'))
            self.assertEqual([r['id'] for r in rows],['one','two'])
            self.assertEqual(rows[1]['speakers'],['George'])
            self.assertIsNone(rows[1]['candidate']['start'])
            self.assertLess(rows[1]['playback_context']['start'],rows[1]['playback_context']['end'])
            page=(p/'review.html').read_text(encoding='utf-8')
            self.assertIn('S01E08 · 固定 B12',page)
            self.assertNotIn('先完成这一集', (p/'REPORT.md').read_text(encoding='utf-8'))

    def test_reuse_requires_matching_inputs_and_complete_outputs(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as tmp:
            p=Path(tmp);self.assertTrue(p.resolve().is_relative_to(TEST_ROOT))
            media=p/'S102.mp4';media.write_bytes(b'video')
            wiki=p/'wiki.json';original=dict(type='utterance',id='x',text='Hello.',speakers=['Peppa'],source_record=1)
            wiki.write_text(json.dumps(dict(entries=[original])),encoding='utf-8')
            for name in ['asr.raw.json','aligned.raw.json','diarization.raw.json','result.whisperx.json','verification.json']:
                (p/name).write_text('{}',encoding='utf-8')
            (p/'source_audio.wav').write_bytes(b'fixture');(p/'review.html').write_text('review')
            (p/'utterances.json').write_text(json.dumps([original]))
            meta=dict(status='completed',config_sha256='fixed',media_sha256=sha(media),wiki_sha256=sha(wiki))
            (p/'run.json').write_text(json.dumps(meta))
            job=dict(media=str(media),wiki=str(wiki))
            self.assertTrue(check_reuse(p,job,'fixed')[1])
            (p/'review.html').unlink()
            self.assertFalse(check_reuse(p,job,'fixed')[1])
            with self.assertRaisesRegex(ValueError,'another fixed'):check_reuse(p,job,'changed')
            media.write_bytes(b'other video')
            with self.assertRaisesRegex(ValueError,'media content changed'):check_reuse(p,job,'fixed')


if __name__=='__main__':unittest.main()
