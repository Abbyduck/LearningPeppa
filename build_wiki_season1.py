"""Build the season archive offline from captured Wiki DOM and prior two exports."""
import argparse
from collections import Counter
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.parse import unquote, urljoin, urlsplit

from wiki_transcript import BeautifulSoup, body_records, normalize, run_batch, write_json

ROOT = Path(__file__).resolve().parent


def url_key(url):
    return unquote(urlsplit(url).path)


def build(output):
    output = Path(output)
    first_capture = json.loads((output / 'browser-capture.json').read_text(encoding='utf-8-sig'))
    captures = {}
    for path in sorted(output.glob('browser-capture*.json')):
        for item in json.loads(path.read_text(encoding='utf-8-sig'))['captures']:
            if not item.get('html'):
                continue
            captures[url_key(item['url'])] = item
    category = {url_key(item['url']): item for item in first_capture['episodeLinks']}
    assert len(category) == 52, 'Season category must have 52 distinct links'
    # The captured Tidying Up page has a numbered Series 1 transcript nav table.
    index_capture = next(c for c in captures.values() if c['title'] == 'Tidying Up')
    soup = BeautifulSoup(index_capture['html'], 'html.parser')
    nav = next(t for t in soup.find_all('table') if t.find('th') and
               normalize(t.find('th').get_text(' ', strip=True)) in {'Series 1', 'Expand Series 1'})
    ordered = []
    for cell in nav.find_all('td'):
        number = re.match(r'^(\d+)\.', normalize(cell.get_text(' ', strip=True)))
        if not number:
            continue
        link = cell.find('a', href=True)
        url = urljoin(index_capture['url'], link['href']) if link else index_capture['url']
        match = category[url_key(url)]
        ordered.append({'id': f'S01E{int(number[1]):02}', 'number': int(number[1]),
                        'title': match['title'].replace(' (episode)', ''), 'url': match['url']})
    ordered.sort(key=lambda x: x['number'])
    assert [x['number'] for x in ordered] == list(range(1, 53))
    assert {url_key(x['url']) for x in ordered} == set(category)
    write_json(output / 'episode_index.json', {
        'season': 1, 'category_url': first_capture['category_url'],
        'numbering_source_url': index_capture['url'],
        'numbering_source_capture': 'browser-capture-part2.json',
        'numbering_source_note': 'Numbered Series 1 table in the captured page DOM; not inferred from alphabetical order.',
        'episodes': ordered})

    original_files = [ROOT / 'output/wiki/episodes/S01E01.json', ROOT / 'output/wiki/episodes/Cleaning_the_Car.json']
    originals = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in original_files}
    old_data = {url_key(d['source']['url']): d for d in
                (json.loads(p.read_text(encoding='utf-8')) for p in original_files)}
    jobs, previous = [], {}
    for info in ordered:
        key = url_key(info['url'])
        if key in old_data:
            old = old_data[key]
            data = (ROOT / 'output/wiki' / old['source']['raw_file']).read_bytes()
            method = old['source']['capture_method']
            previous[info['id']] = old
            captured_at = None
        else:
            capture = captures.get(key)
            if not capture:
                raise ValueError(f'Missing capture: {info["url"]}')
            data = capture['html'].encode('utf-8')
            method = 'browser_rendered_body_dom'
            captured_at = capture.get('captured_at')
        raw_path = output / 'raw' / info['id'] / (hashlib.sha256(data).hexdigest() + '.html')
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if not raw_path.exists():
            raw_path.write_bytes(data)
        revision = re.search(r'\brevision id (\d+)', data.decode('utf-8'))
        jobs.append({'episode': {'id': info['id'], 'title': info['title'], 'season': 1, 'number': info['number']},
                     'url': info['url'], 'file': raw_path.relative_to(output).as_posix(),
                     'capture_method': method, 'captured_at': captured_at,
                     'revision_id': int(revision[1]) if revision else None})
    manifest = output / 'manifest.json'
    write_json(manifest, jobs)
    with contextlib.redirect_stdout(io.StringIO()):
        result = run_batch(manifest, output)
    reports, checks, issues = [], [], []
    for job in jobs:
        episode_id = job['episode']['id']
        path = output / 'episodes' / (episode_id + '.json')
        report_path = output / 'reports' / (episode_id + '.json')
        parsed = json.loads(path.read_text(encoding='utf-8'))
        report = json.loads(report_path.read_text(encoding='utf-8'))
        raw = (output / parsed['source']['raw_file']).read_text(encoding='utf-8')
        assert [text for _, text in body_records(raw)] == [e['raw_text'] for e in parsed['entries']]
        # Keep all existing record IDs, including the old title-based Car IDs.
        if episode_id in previous:
            old = previous[episode_id]
            assert [e['raw_text'] for e in old['entries']] == [e['raw_text'] for e in parsed['entries']]
            for entry, old_entry in zip(parsed['entries'], old['entries']):
                entry['id'] = old_entry['id']
            id_mapping = {a['id']: b['id'] for a, b in zip(
                json.loads(path.read_text(encoding='utf-8'))['entries'], old['entries'])}
            for warning in report['warnings']:
                warning['entry_id'] = id_mapping.get(warning['entry_id'], warning['entry_id'])
            if old['episode']['id'] != episode_id:
                parsed['episode']['previous_ids'] = [old['episode']['id']]
            parsed['source']['reused_previous_export'] = True
            write_json(path, parsed)
        assert len({e['id'] for e in parsed['entries']}) == len(parsed['entries'])
        assert all(e['text'].strip() for e in parsed['entries'] if e['type'] == 'utterance')
        report['unknown_annotations'] = sum(w['code'] == 'unknown_annotation' for w in report['warnings'])
        report['scene_description_events'] = sum(e['type'] == 'event' and e['event_type'] == 'scene_description' for e in parsed['entries'])
        write_json(report_path, report)
        reports.append(report)
        for e in parsed['entries']:
            codes = [w['code'] for w in report['warnings'] if w['entry_id'] == e['id']]
            if e['type'] == 'unparsed' or any(code in codes for code in
                    ['unknown_speaker', 'unknown_annotation', 'unknown_speaker_marker', 'possibly_unrelated_source_speaker']):
                issues.append({'episode_id': episode_id, 'title': parsed['episode']['title'],
                               'entry_id': e['id'], 'type': e['type'], 'codes': codes,
                               'raw_text': e['raw_text'], 'source_url': parsed['source']['url']})
        checks.append({'episode_id': episode_id, 'all_raw_records_retained': True,
                       'unique_ids': True, 'entries': len(parsed['entries'])})
        report_text = (f"# {episode_id} {parsed['episode']['title']}\n\n"
                       f"发言 {report['utterances']}；未知角色发言 {report['unknown_speaker_utterances']}；"
                       f"场景标题 {report['scenes']}；独立声音事件 {report['sound_events']}；"
                       f"未解析正文 {report['unparsed']}；未知括号说明 {report['unknown_annotations']}。\n\n"
                       f"疑似不完整：{report['possibly_incomplete']}；原因：{', '.join(report['incomplete_reasons']) or '无启发式标记'}。\n\n"
                       f"正文记录 {report['body_records']} 条，均保留。状态：{report['status']}。"
                       f"重复记录不删除，不完整标记不触发台词补写。\n\n来源：{parsed['source']['url']}\n")
        (output / 'reports' / (episode_id + '.md')).write_text(report_text, encoding='utf-8')
    assert originals == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in original_files}
    write_json(output / 'batch_report.json', reports)
    write_json(output / 'review_items.json', issues)
    summary = {'season': 1, 'expected_episodes': 52, 'collected_episodes': len(reports),
               'new_captures': len(captures), 'reused_episodes': len(previous), 'failed_episodes': result,
               'empty_transcripts': sum(r['utterances'] == 0 for r in reports),
               'totals': {key: sum(r[key] for r in reports) for key in
                          ['utterances', 'unknown_speaker_utterances', 'scenes', 'sound_events', 'unparsed', 'unknown_annotations', 'body_records']},
               'possibly_incomplete': [r['episode'] for r in reports if r['possibly_incomplete']],
               'source_anomalies': [x for x in issues if 'possibly_unrelated_source_speaker' in x['codes']],
               'previous_two_files_unchanged': True,
               'note': 'Collection complete for the Wiki category, not an assertion of official or error-free dialogue. Review items are retained.'}
    write_json(output / 'summary.json', summary)
    write_json(output / 'validation.json', {'episodes': checks, 'previous_two_files_unchanged': True})
    lines = ['# 第一季 Wiki 台词采集报告', '',
             f"目录 52 集，新增采集 {len(captures)} 集，复用原有 {len(previous)} 集。访问失败 {result} 集，空台词页面 {summary['empty_transcripts']} 集。", '',
             f"发言 {summary['totals']['utterances']}；未知角色发言 {summary['totals']['unknown_speaker_utterances']}；未解析正文 {summary['totals']['unparsed']}；未知括号说明 {summary['totals']['unknown_annotations']}。", '',
             '原文中的异常、不明说话人、未解析段落见 review_items.json。疑似不完整只标记，不补写。Wiki 正文未与原声核对。', '',
             '集序来自已保存 Tidying Up 页面中的 Series 1 编号导航表；52 个 URL 同第一季分类逐项匹配。两份浏览器采集分卷是原始归档，raw 目录按集与 SHA256 保存渲染后的正文 DOM。', '',
             '原有两集文件保持不变。Cleaning the Car 已确认集号为 S01E33，新结果沿用旧 entry ID，并记录旧 episode ID。', '',
             '| 集号 | 标题 | 发言 | 未知角色 | 场景 | 声音 | 未解析 | 疑似不完整 |',
             '|---|---|---:|---:|---:|---:|---:|---|']
    for r in reports:
        e = r['episode']
        lines.append(f"| [{e['id']}](episodes/{e['id']}.json) | {e['title']} | {r['utterances']} | {r['unknown_speaker_utterances']} | {r['scenes']} | {r['sound_events']} | {r['unparsed']} | {'是' if r['possibly_incomplete'] else '否'} |")
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/wiki/season1')
    args = parser.parse_args()
    build(args.output)
