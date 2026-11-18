"""Synthetic acceptance fixtures, NOT downloaded episode transcripts."""
import json
from pathlib import Path
import tempfile
import unittest

from wiki_transcript import clean, run_batch


def parse(body):
    return clean('<div class="mw-parser-output">' + body + '</div>',
                 {'id': 'TEST', 'title': 'Synthetic fixture'}, {'type': 'test_fixture'})


class WikiTranscriptTests(unittest.TestCase):
    def test_episode_intro_and_named_santa_alias(self):
        data, _ = parse('<p>This is the transcript for "The Rainbow".</p><p>Santa Claus: Hello!</p>')
        self.assertEqual(len(data['entries']), 1)
        self.assertEqual(data['entries'][0]['speakers'], ['Father Christmas'])
        self.assertEqual(data['entries'][0]['raw_speaker'], 'Santa Claus')
    def test_star_sound_bullet_event_and_incomplete_notice(self):
        data, report = parse('<div class="notice metadata"><p>This page needs a transcript to be written.</p></div>'
                             '<p>Peppa: *snorts* Hello. *laughing*</p><p>- (horn beeps)</p>')
        self.assertEqual(data['entries'][0]['text'], 'Hello.')
        self.assertEqual([p['type'] for p in data['entries'][0]['parts']], ['sound', 'speech', 'sound'])
        self.assertEqual(data['entries'][1]['type'], 'event')
        self.assertEqual(data['entries'][1]['event_type'], 'sound')
        self.assertEqual(data['entries'][1]['raw_text'], '- (horn beeps)')
        self.assertIn('source_incompleteness_notice', report['incomplete_reasons'])
        self.assertEqual(report['unparsed'], 0)

    def test_stub_table_scene_caption_and_unknown_direction(self):
        data, report = parse('<table><tr><td><a href="/wiki/Template:Stub">This page is a stub.</a></td></tr></table>'
                             '<p>(Transcript: Playgroup)</p><p>Peppa: Hello. *unclear direction* Yes.</p>')
        self.assertEqual(len(data['entries']), 2)
        self.assertEqual(data['entries'][0]['type'], 'scene')
        self.assertEqual(data['entries'][0]['text'], 'Playgroup')
        self.assertEqual(data['entries'][1]['text'], 'Hello. Yes.')
        self.assertEqual(data['entries'][1]['parts'][1]['type'], 'unknown')
        self.assertTrue(report['possibly_incomplete'])
        self.assertTrue(report['source_notices'])

    def test_footer_season_navigation_without_live_links(self):
        data, report = parse('<p>Peppa: Hello!</p><table class="mw-collapsible">'
                             '<tr><th>Expand Series 8</th></tr>'
                             '<tr><td>25. "<span class="new">Leafy Walk</span>": 26. "Another"</td></tr></table>')
        self.assertEqual(len(data['entries']), 1)
        self.assertEqual(data['entries'][0]['text'], 'Hello!')
        self.assertEqual(report['unparsed'], 0)

    def test_colon_inside_direction_and_leading_direction(self):
        data, report = parse('<p>[Animal calls: Suzy bleats and Danny barks.]</p>'
                             '<p>[We begin at the house.]Narrator: Here is Peppa.</p>'
                             '<p>(The pig family gets in the car).</p>')
        self.assertEqual([e['type'] for e in data['entries']], ['event', 'utterance', 'event'])
        self.assertEqual(data['entries'][1]['speakers'], ['Narrator'])
        self.assertEqual(data['entries'][1]['text'], 'Here is Peppa.')
        self.assertEqual(report['unparsed'], 0)
    def test_navigation_and_source_newlines_are_not_dialogue(self):
        data, report = parse('<div><table><tr><td>Info</td><td>Gallery</td><td>Transcript</td></tr></table></div>'
                             '<p>The following is a transcript for the episode, "Example".</p>'
                             '<p><b>Peppa:</b> First sentence.\nSecond sentence.<br>Third sentence.</p>'
                             '<p>Peppa: One.<br>George: Two.</p>')
        self.assertEqual([e['text'] for e in data['entries']], ['First sentence. Second sentence. Third sentence.', 'One.', 'Two.'])
        self.assertEqual(report['unparsed'], 0)

    def test_nested_list_and_adjacent_indented_turn(self):
        data, report = parse('<ul><li><b>Peppa:</b><ul><li>Oh.</li><li>(points right)</li><li>Look!</li></ul></li>'
                             '<li>Daddy Pig: Yes.</li></ul><p>George:</p><dl><dd>One.</dd><dd>(laughs)</dd><dd>Two.</dd></dl>')
        self.assertEqual([e['text'] for e in data['entries']], ['Oh. Look!', 'Yes.', 'One. Two.'])
        self.assertEqual(report['unparsed'], 0)

    def test_advertising_navigation_and_unknown_groups(self):
        data, report = parse('<cnx class="cnx-player-wrapper"><cnx>Skip Ad</cnx></cnx>'
                             '<table class="mw-collapsible"><tr><th>Expand Series 1</th></tr>'
                             '<tr><td><a href="/wiki/Other/Transcript">Other episode</a></td></tr></table>'
                             '<p><a href="/wiki/Template:Null">Template:Null</a></p>'
                             '<p>Mummy Pig, Peppa Pig, and George: Yes!</p>'
                             '<p>All: Hurrah!</p><p>Squidward Tentacles: Anomalous source text.</p>')
        self.assertEqual(len(data['entries']), 3)
        self.assertEqual(data['entries'][0]['speakers'], ['Mummy Pig', 'Peppa', 'George'])
        self.assertEqual(data['entries'][1]['speakers'], [])
        self.assertIn('possibly_unrelated_source_speaker', data['entries'][2]['review_flags'])
        self.assertEqual(report['unparsed'], 0)
    def test_full_turn_os_and_onscreen(self):
        data, _ = parse('<p><b>Peppa (OS):</b> George! (onscreen) If you jump in muddy puddles, you must wear your boots.</p>')
        entry = data['entries'][0]
        self.assertEqual(entry['speakers'], ['Peppa'])
        self.assertEqual(entry['raw_speaker'], 'Peppa (OS)')
        self.assertEqual(entry['speaker_markers'], ['OS'])
        self.assertEqual(entry['text'], 'George! If you jump in muddy puddles, you must wear your boots.')
        self.assertEqual([p['type'] for p in entry['parts']], ['speech', 'presentation', 'speech'])

    def test_inline_action_sound_and_interjections(self):
        data, _ = parse("<p>Peppa Pig: (laughs) Look George! (points right) There's a really big puddle. Ooh! Whee!</p>")
        entry = data['entries'][0]
        self.assertEqual(entry['speakers'], ['Peppa'])
        self.assertEqual(entry['text'], "Look George! There's a really big puddle. Ooh! Whee!")
        self.assertEqual([p['type'] for p in entry['parts']], ['sound', 'speech', 'action', 'speech'])

    def test_alternating_fragments_table(self):
        data, _ = parse('<table><tr><th>Character</th><th>Dialogue</th></tr><tr><td>Peppa</td><td>First fragment,</td></tr><tr><td>Daddy Pig</td><td>second fragment.</td></tr></table>')
        self.assertEqual([e['text'] for e in data['entries']], ['First fragment,', 'second fragment.'])
        self.assertEqual([e['speakers'] for e in data['entries']], [['Peppa'], ['Daddy Pig']])

    def test_pure_sound_and_multiple_speakers(self):
        data, report = parse('<ul><li>Peppa and George: (laugh)</li><li>Peppa and George: Yes!</li></ul>')
        self.assertEqual(data['entries'][0]['type'], 'event')
        self.assertEqual(data['entries'][0]['speakers'], ['Peppa', 'George'])
        self.assertEqual(report['sound_events'], 1)
        self.assertEqual(report['utterances'], 1)

    def test_empty_and_unparsed(self):
        data, report = parse('')
        self.assertEqual(data['entries'], [])
        self.assertTrue(report['possibly_incomplete'])
        data, report = parse('<p>Who knows what this line means?</p><p>Unknown person: Hello.</p><p>George: (xyz)</p><p>Peppa: broken (annotation</p>')
        self.assertEqual(report['unparsed'], 2)
        self.assertEqual(report['unknown_speaker_utterances'], 1)
        self.assertEqual(len(data['entries']), 4)
        self.assertTrue(any(w['code'] == 'unknown_annotation' for w in report['warnings']))

    def test_repeat_and_insertion_stability(self):
        body = '<p>Peppa: A.</p><p>George: B.</p>'
        first = parse(body)
        self.assertEqual(first, parse(body))
        new, _ = parse('<p>Narrator: Added.</p>' + body)
        self.assertEqual([e['id'] for e in first[0]['entries']], [e['id'] for e in new['entries'][1:]])

    def test_dom_boundaries_entities_and_definition_list(self):
        data, _ = parse('<p>Introduction</p><h2>Transcript</h2><h3>Interior, Kitchen</h3><dl><dt>Peppa</dt><dd>Hello&nbsp;George!</dd></dl><h2>References</h2><p>Footer</p>')
        self.assertEqual([e['text'] for e in data['entries']], ['Interior, Kitchen', 'Hello George!'])

    def test_batch_failure_isolation_and_raw_archive(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            root = Path(temp)
            source = b'<div class="mw-parser-output"><p>Peppa: Hello!</p></div>'
            (root / 'input.html').write_bytes(source)
            jobs = [{'episode': {'id': 'FAILED'}, 'file': 'missing.html', 'url': 'https://example.invalid'},
                    {'episode': {'id': 'OK'}, 'file': 'input.html', 'url': 'https://example.invalid'}]
            (root / 'jobs.json').write_text(json.dumps(jobs))
            self.assertEqual(run_batch(root / 'jobs.json', root / 'out'), 1)
            data = json.loads((root / 'out/episodes/OK.json').read_text())
            self.assertEqual((root / 'out' / data['source']['raw_file']).read_bytes(), source)
            self.assertTrue((root / 'out/errors/FAILED.json').exists())
            before = (root / 'out/episodes/OK.json').read_bytes()
            run_batch(root / 'jobs.json', root / 'out')
            self.assertEqual(before, (root / 'out/episodes/OK.json').read_bytes())

    def test_actual_dom_exports(self):
        root = Path(__file__).resolve().parents[1] / 'wiki-input'
        if not all((root/name).is_file() for name in ['Muddy_Puddles.dom.html','Cleaning_the_Car.dom.html']):
            self.skipTest('Local captured Wiki pages are not included in the source repository')
        muddy = (root / 'Muddy_Puddles.dom.html').read_text(encoding='utf-8')
        car = (root / 'Cleaning_the_Car.dom.html').read_text(encoding='utf-8')
        first, report = clean(muddy, {'id': 'S01E01'}, {})
        self.assertEqual(report['body_records'], 88)
        self.assertEqual(report['utterances'], 43)
        self.assertEqual(report['unparsed'], 0)
        condition = next(e for e in first['entries'] if e.get('raw_speaker') == 'Peppa (OS)')
        self.assertEqual(condition['text'], 'George! If you jump in muddy puddles, you must wear your boots.')
        direction = next(e for e in first['entries'] if 'points right;' in e['raw_text'])
        self.assertEqual([p['type'] for p in direction['parts']], ['sound', 'speech', 'action', 'action', 'presentation', 'speech'])
        second, report2 = clean(car, {'id': 'CAR'}, {})
        self.assertEqual(report2['body_records'], 76)
        self.assertEqual(report2['utterances'], 62)
        self.assertEqual(report2['unparsed'], 0)
        fragment = next(i for i,e in enumerate(second['entries']) if e.get('text') == 'Peppa, don’t use the...')
        self.assertEqual(second['entries'][fragment+1]['type'], 'event')
        self.assertEqual(second['entries'][fragment+2]['text'], '...muddy water.')
        group = next(e for e in second['entries'] if e.get('raw_speaker') == 'Mummy Pig and Peppa Pig')
        self.assertEqual(group['speakers'], ['Mummy Pig', 'Peppa'])
        self.assertEqual(clean(muddy, {'id': 'S01E01'}, {}), (first, report))


if __name__ == '__main__':
    unittest.main()
