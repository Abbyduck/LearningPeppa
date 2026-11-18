"""Offline season 3 build from captured Wiki transcript DOM."""
import argparse
import contextlib
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


def episode_index(output):
    archive = json.loads((output / 'browser-capture.json').read_text(encoding='utf-8-sig'))
    category = {url_key(item['url']): item for item in archive['episodeLinks']}
    soup = BeautifulSoup((output / 'numbering-source.html').read_text(encoding='utf-8'), 'html.parser')
    episodes = []
    for cell in soup.find_all('td'):
        match = re.match(r'^(\d+(?:\s*\+\s*\d+)*)\.', normalize(cell.get_text(' ', strip=True)))
        if not match:
            continue
        link = cell.find('a', href=True)
        url = urljoin('https://peppapig.fandom.com', link['href'])
        item = category[url_key(url)]
        numbers = [int(n) for n in re.findall(r'\d+', match[1])]
        episode_id = f'S03E{numbers[0]:02}' + (f'-E{numbers[-1]:02}' if len(numbers) > 1 else '')
        episodes.append({'id': episode_id, 'title': item['title'].replace(' (episode)', ''),
                         'season': 3, 'number': numbers[0], 'numbers': numbers, 'url': item['url']})
    episodes.sort(key=lambda x: x['number'])
    assert len(episodes) == len(category) == 52
    assert [n for e in episodes for n in e['numbers']] == list(range(1, 53))
    assert {url_key(e['url']) for e in episodes} == set(category)
    write_json(output / 'episode_index.json', {
        'season': 3, 'category_url': archive['category_url'], 'transcript_pages': 52,
        'regular_episodes': 52, 'combined_special': None,
        'numbering_source_file': 'numbering-source.html',
        'numbering_source_url': 'https://peppapig.fandom.com/wiki/Tidying_Up/Transcript',
        'numbering_source_note': 'Series 3 numbered navigation table in the previously captured Wiki DOM.',
        'episodes': episodes})
    return episodes


def build(output):
    output = Path(output)
    ordered = episode_index(output)
    captures = {}
    for path in sorted(output.glob('browser-capture*.json')):
        for item in json.loads(path.read_text(encoding='utf-8-sig'))['captures']:
            key = url_key(item['url'])
            # A successful checkpoint takes precedence over a later error record.
            if key not in captures or item.get('html'):
                captures[key] = item
    jobs = []
    for info in ordered:
        item = captures.get(url_key(info['url']))
        episode = {k: v for k, v in info.items() if k != 'url'}
        if not item or not item.get('html'):
            jobs.append({'episode': episode, 'url': info['url'],
                         'file': f'missing-capture/{info["id"]}.html'})
            continue
        data = item['html'].encode('utf-8')
        digest = hashlib.sha256(data).hexdigest()
        raw_path = output / 'raw' / info['id'] / (digest + '.html')
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if not raw_path.exists():
            raw_path.write_bytes(data)
        revision = re.search(r'\brevision id (\d+)', item['html'])
        jobs.append({'episode': episode, 'url': info['url'],
                     'file': raw_path.relative_to(output).as_posix(),
                     'capture_method': 'browser_rendered_body_dom',
                     'captured_at': item.get('captured_at'),
                     'revision_id': int(revision[1]) if revision else None})
    manifest = output / 'manifest.json'
    write_json(manifest, jobs)
    with contextlib.redirect_stdout(io.StringIO()):
        run_batch(manifest, output)
    latest = json.loads((output / 'batch_report.json').read_text(encoding='utf-8'))
    reports, issues, checks, failures = [], [], [], []
    for job, outcome in zip(jobs, latest):
        if outcome['status'] == 'failed':
            failures.append(outcome)
            continue
        episode_id = job['episode']['id']
        path = output / 'episodes' / (episode_id + '.json')
        data = json.loads(path.read_text(encoding='utf-8'))
        report = outcome
        raw_path = output / data['source']['raw_file']
        assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == data['source']['sha256']
        assert [t for _, t in body_records(raw_path.read_text(encoding='utf-8'))] == [e['raw_text'] for e in data['entries']]
        assert len({e['id'] for e in data['entries']}) == len(data['entries'])
        assert all(e['text'].strip() for e in data['entries'] if e['type'] == 'utterance')
        report['unknown_annotations'] = sum(w['code'] == 'unknown_annotation' for w in report['warnings'])
        report['scene_description_events'] = sum(e['type'] == 'event' and e['event_type'] == 'scene_description' for e in data['entries'])
        write_json(output / 'reports' / (episode_id + '.json'), report)
        reports.append(report)
        for entry in data['entries']:
            codes = entry.get('review_flags', [])
            if entry['type'] == 'unparsed' or codes:
                issues.append({'episode_id': episode_id, 'title': data['episode']['title'],
                               'entry_id': entry['id'], 'type': entry['type'], 'codes': codes,
                               'raw_text': entry['raw_text'], 'source_url': data['source']['url']})
        checks.append({'episode_id': episode_id, 'all_raw_records_retained': True,
                       'unique_ids': True, 'raw_sha256_verified': True, 'entries': len(data['entries'])})
        text = (f"# {episode_id} {data['episode']['title']}\n\n"
                f"发言 {report['utterances']}；未知角色发言 {report['unknown_speaker_utterances']}；场景标题 {report['scenes']}；"
                f"独立声音事件 {report['sound_events']}；未解析正文 {report['unparsed']}；未知括号说明 {report['unknown_annotations']}。\n\n"
                f"疑似不完整：{report['possibly_incomplete']}；原因：{', '.join(report['incomplete_reasons']) or '无启发式标记'}。\n\n"
                f"正文记录 {report['body_records']} 条均保留。原始内容单独归档，不补写。\n\n来源：{data['source']['url']}\n")
        (output / 'reports' / (episode_id + '.md')).write_text(text, encoding='utf-8')
    baseline = json.loads((output / 'previous_seasons_baseline.json').read_text(encoding='utf-8'))
    base = ROOT / 'output/wiki'
    assert baseline == {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for folder in ['season1', 'season2'] for p in (base / folder).rglob('*') if p.is_file()}, 'Previous season files changed'
    all_ids = [e['id'] for r in reports for e in json.loads((output / 'episodes' / (r['episode']['id'] + '.json')).read_text(encoding='utf-8'))['entries']]
    assert len(all_ids) == len(set(all_ids))
    summary = {'season': 3, 'expected_transcript_pages': 52, 'collected_transcript_pages': len(reports),
               'regular_episodes': 52, 'combined_special': None, 'failed_pages': len(failures),
               'empty_transcripts': sum(r['utterances'] == 0 for r in reports),
               'totals': {key: sum(r[key] for r in reports) for key in
                          ['utterances', 'unknown_speaker_utterances', 'scenes', 'sound_events', 'unparsed', 'unknown_annotations', 'body_records']},
               'possibly_incomplete': [r['episode'] for r in reports if r['possibly_incomplete']],
               'very_short_transcripts': [{'episode': r['episode'], 'utterances': r['utterances']}
                                          for r in reports if 'very_short_transcript' in r['incomplete_reasons']],
               'source_notice_pages': [r['episode'] for r in reports if r.get('source_notices')],
               'previous_seasons_files_unchanged': True,
               'note': 'Wiki coverage only; source text may be incomplete or incorrect. No missing lines inferred.'}
    write_json(output / 'batch_report.json', reports + failures)
    write_json(output / 'review_items.json', issues)
    write_json(output / 'summary.json', summary)
    write_json(output / 'validation.json', {'episodes': checks, 'previous_seasons_files_unchanged': True, 'global_unique_ids': True})
    lines = ['# 第三季 Wiki 台词采集报告', '',
             f"目录 52 个剧本页面。已采集 {len(reports)} 页；失败 {len(failures)} 页；空正文 {summary['empty_transcripts']} 页。", '',
             f"发言 {summary['totals']['utterances']}；未知角色发言 {summary['totals']['unknown_speaker_utterances']}；未解析正文 {summary['totals']['unparsed']}；未知括号说明 {summary['totals']['unknown_annotations']}。", '',
             f"疑似不完整 {len(summary['possibly_incomplete'])} 页（包括格式问题、站内待补写提示与过短正文）。其中 {len(summary['very_short_transcripts'])} 页正文明显过短：" +
             '；'.join(f"{x['episode']['id']} {x['episode']['title']}：{x['utterances']} 条发言" for x in summary['very_short_transcripts']) + '。', '',
             '集序来自保存的 Wiki Series 3 编号表，与第三季分类逐项匹配。每个来源页面对应一个 JSON。', '',
             'raw/ 保存浏览器正常加载后的正文 DOM，browser-capture*.json 为原始检查点。疑似不完整、未知角色和括号说明保留在 review_items.json。未与原声核对，未补写台词。前两季文件保持不变。', '',
             '| 集号 | 标题 | 发言 | 未知角色 | 场景 | 声音 | 未解析 | 疑似不完整 |',
             '|---|---|---:|---:|---:|---:|---:|---|']
    for r in reports:
        e = r['episode']
        lines.append(f"| [{e['id']}](episodes/{e['id']}.json) | {e['title']} | {r['utterances']} | {r['unknown_speaker_utterances']} | {r['scenes']} | {r['sound_events']} | {r['unparsed']} | {'是' if r['possibly_incomplete'] else '否'} |")
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/wiki/season3')
    args = parser.parse_args()
    build(args.output)
