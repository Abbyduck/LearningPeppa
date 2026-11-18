"""Offline-first Wiki transcript cleaner; no audio or language model dependencies."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).parent / '.wiki-deps'))
from bs4 import BeautifulSoup, Comment, NavigableString, Tag


def normalize(text):
    return re.sub(r'\s+', ' ', re.sub('[\u200b\u200e\u200f\ufeff]', '', text)).strip()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


ALIASES = {
    'peppa': 'Peppa', 'peppa pig': 'Peppa', 'george': 'George', 'george pig': 'George',
    'mummy pig': 'Mummy Pig', 'daddy pig': 'Daddy Pig', 'narrator': 'Narrator',
    'granny pig': 'Granny Pig', 'grandpa pig': 'Grandpa Pig',
    'suzy': 'Suzy', 'suzy sheep': 'Suzy',
    'danny': 'Danny Dog', 'danny dog': 'Danny Dog',
    'candy': 'Candy Cat', 'candy cat': 'Candy Cat',
    'pedro': 'Pedro Pony', 'pedro pony': 'Pedro Pony',
    'rebecca': 'Rebecca Rabbit', 'rebecca rabbit': 'Rebecca Rabbit',
    'madame gazelle': 'Madame Gazelle', 'miss rabbit': 'Miss Rabbit',
    'auntie pig': 'Auntie Pig', 'uncle pig': 'Uncle Pig',
    'chloé': 'Chloé', 'chloé pig': 'Chloé', 'chloe': 'Chloé', 'chloe pig': 'Chloé',
    'mr. zebra': 'Mr Zebra', 'mr zebra': 'Mr Zebra',
    'granddad dog': 'Granddad Dog',
    'mommy': 'Mummy Pig', 'daddy': 'Daddy Pig',
    'cousin chloé': 'Chloé',
    'doctor brown bear': 'Doctor Brown Bear', 'dr. brown bear': 'Doctor Brown Bear',
    'mrs sheep': 'Mrs Sheep',
    'polly': 'Polly Parrot', 'polly parrot': 'Polly Parrot',
    'mummy dog': 'Mummy Dog', 'mummy pony': 'Mummy Pony', 'mummy rabbit': 'Mummy Rabbit',
    'grandad dog': 'Granddad Dog',
    'emily elephant': 'Emily Elephant', 'emily': 'Emily Elephant',
    'richard rabbit': 'Richard Rabbit', 'richard': 'Richard Rabbit',
    'zoë zebra': 'Zoë Zebra', 'zoe zebra': 'Zoë Zebra', 'zoe': 'Zoë Zebra', 'zoë': 'Zoë Zebra',
    'mr. rabbit': 'Mr Rabbit', 'mr rabbit': 'Mr Rabbit',
    'mummy cat': 'Mummy Cat', 'mummy sheep': 'Mummy Sheep',
    'grandpa dog': 'Granddad Dog',
    'mummy': 'Mummy Pig', 'mama pig': 'Mummy Pig', 'papa pig': 'Daddy Pig',
    'mr. bull': 'Mr Bull', 'mr bull': 'Mr Bull', 'father christmas': 'Father Christmas',
    'delphine': 'Delphine Donkey', 'delphine donkey': 'Delphine Donkey',
    'papa donkey': 'Papa Donkey', 'mama donkey': 'Mama Donkey', 'didier': 'Didier',
    'detective potato': 'Detective Potato', 'mademoiselle potato': 'Mademoiselle Potato',
    'mummy zebra': 'Mummy Zebra', 'daddy zebra': 'Daddy Zebra', 'daddy elephant': 'Daddy Elephant',
    'zuzu zebra': 'Zuzu Zebra', 'zuzu': 'Zuzu Zebra', 'zaza zebra': 'Zaza Zebra', 'zaza': 'Zaza Zebra',
    'baby alexander': 'Baby Alexander', 'grandma pig': 'Granny Pig', 'madam gazelle': 'Madame Gazelle',
    'mrs. duck': 'Mrs Duck', 'mrs duck': 'Mrs Duck',
    'mr pony': 'Mr Pony', 'mr. pony': 'Mr Pony',
    'dr. elephant': 'Doctor Elephant', 'doctor elephant': 'Doctor Elephant',
    'mrs. zebra': 'Mummy Zebra', 'mrs zebra': 'Mummy Zebra',
    'mrs. rabbit': 'Mummy Rabbit', 'mrs rabbit': 'Mummy Rabbit',
    'doctor hamster': 'Doctor Hamster', 'dr. hamster': 'Doctor Hamster',
    'freddy': 'Freddy Fox', 'freddy fox': 'Freddy Fox',
    'mr. fox': 'Mr Fox', 'mr fox': 'Mr Fox',
    'mummy elephant': 'Mummy Elephant', 'edmond': 'Edmond Elephant', 'edmond elephant': 'Edmond Elephant',
    'grampy rabbit': 'Grampy Rabbit', 'mr. potato': 'Mr Potato', 'mr potato': 'Mr Potato',
    'cousin chloe': 'Chloé',
    'santa': 'Father Christmas', 'santa claus': 'Father Christmas',
    'daddy rabbit': 'Daddy Rabbit', 'mrs. sheep': 'Mummy Sheep', 'mrs. cat': 'Mummy Cat',
}
PRESENTATION = re.compile(r'^(?:OS|VO|O\.S\.|V\.O\.|onscreen|on screen|offscreen|off screen|voice[- ]over|singing|narrating|as .+)$', re.I)
STOP_HEADINGS = {'categories', 'comments', 'references', 'external links', 'navigation', 'gallery', 'see also', 'trivia'}
SCENE = re.compile(r'^(?:interior|exterior|int\.|ext\.|scene\b|cut to\b|fade (?:in|out)\b)', re.I)


def annotation_type(text):
    if PRESENTATION.fullmatch(text):
        return 'presentation'
    # Multiple kinds in a single annotation are retained verbatim for review.
    sound = bool(re.search(r'\b(?:laugh\w*|snort\w*|cr(?:y|ies|ying)|giggl\w*|sobb?\w*|oink\w*|squeal\w*|splash\w*|beep\w*|ring\w*|hiss\w*|honk\w*|bark\w*|meow\w*|quack\w*|bleat\w*|squawk\w*|clunk\w*|gasp\w*|cough\w*|yawn\w*|pant\w*|whistl\w*|roar\w*|growl\w*|grunt\w*|clang\w*|clatter\w*|ding\w*|blare\w*|sputter\w*)\b', text, re.I))
    action = bool(re.search(r'\b(?:point\w*|walk\w*|look\w*|run\w*|jump\w*|nod\w*|shak\w*|smil\w*|turn\w*|enter\w*|leav\w*|sit\w*|hold\w*|clean\w*|think\w*|lean\w*|exit\w*|open\w*|get\w*|rub\w*|dip\w*|grab\w*|throw\w*|splash\w*|lose\w*|drive\w*|does the same)\b', text, re.I))
    if sound and action:
        return 'unknown'
    if sound:
        return 'sound'
    if SCENE.match(text) or len(text.split()) > 18:
        return 'scene_description'
    if action:
        return 'action'
    return 'unknown'


def split_parts(text):
    """Balanced bracket scanner; preserve order and flag malformed brackets."""
    # Paired star directions follow the same conservative classification rules.
    # Unknown directions remain in parts for review, outside spoken English.
    text = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', lambda m: '(' + m[1] + ')', text)
    parts, buf, stack = [], '', []
    malformed = False
    for char in text:
        if char in '([':
            if not stack and buf.strip():
                parts.append({'type': 'speech', 'text': normalize(buf)})
                buf = ''
            stack.append(char)
            buf += char
        elif char in ')]':
            if not stack or (stack[-1], char) not in {('(', ')'), ('[', ']')}:
                malformed = True
                buf += char
                continue
            stack.pop()
            buf += char
            if not stack:
                value = normalize(buf[1:-1])
                # Semicolons explicitly separate simultaneous directions and status
                # markers in the actual Wiki source. The complete bracket survives
                # in the record's raw_text.
                for clause in value.split(';'):
                    clause = normalize(clause)
                    if clause:
                        parts.append({'type': annotation_type(clause), 'text': clause})
                buf = ''
        else:
            buf += char
    if stack:
        malformed = True
    if buf.strip():
        parts.append({'type': 'unknown' if stack else 'speech', 'text': normalize(buf)})
    return parts, malformed


def speaker_info(label):
    markers = re.findall(r'\(([^()]*)\)|\[([^\[\]]*)\]', label)
    markers = [normalize(a or b) for a, b in markers]
    name = normalize(re.sub(r'\([^()]*\)|\[[^\[\]]*\]', '', label))
    name = re.sub(r',\s*(?:and|&)\s+', ', ', name, flags=re.I)
    names = [n for n in re.split(r'\s+(?:and|&)\s+|\s*,\s*', name, flags=re.I) if n and n.casefold() != 'and']
    speakers = [ALIASES[n.casefold()] for n in names if n.casefold() in ALIASES]
    # A partly recognized group is still an unknown speaker group.
    unknown = len(speakers) != len(names)
    return ([] if unknown else speakers), markers, unknown


def parse_record(kind, raw):
    raw = normalize(raw)
    if kind == 'heading':
        return {'type': 'scene', 'text': raw}, []
    if re.fullmatch(r'\(Transcript:\s*.+\)', raw, re.I):
        return {'type': 'scene', 'text': normalize(raw[1:-1].split(':', 1)[1])}, []
    if re.match(r'^[\[(]Note:', raw, re.I):
        return {'type': 'unparsed', 'raw_text': raw, 'reason': 'source_editorial_note'}, ['source_editorial_note']
    if re.fullmatch(r'-\s*[\[(].*[\])]', raw):
        raw = raw[1:].lstrip()
    if re.fullmatch(r'\(.*\)\.', raw):
        raw = raw[:-1]
    leading_parts = []
    parse_text = raw
    # A direction may precede an explicitly labeled voice within one paragraph.
    # Colons INSIDE directions are never speaker delimiters.
    if raw.startswith(('(', '[')):
        stack = []
        for pos, char in enumerate(raw):
            if char in '([':
                stack.append(char)
            elif char in ')]':
                if not stack or (stack[-1], char) not in {('(', ')'), ('[', ']')}:
                    break
                stack.pop()
                if not stack:
                    tail = raw[pos + 1:].strip()
                    if re.match(r'^[A-Z][^:]{0,99}:', tail):
                        leading_parts, _ = split_parts(raw[:pos + 1])
                        parse_text = tail
                    break
    match = None if parse_text.startswith(('(', '[')) else re.match(r'^([^:]{1,100}):\s*(.*)$', parse_text)
    warnings = []
    if match and not SCENE.match(raw):
        label, body = match.groups()
        speakers, markers, unknown = speaker_info(label)
        parts, malformed = split_parts(body)
        parts = leading_parts + parts
        if unknown:
            warnings.append('unknown_speaker')
        if re.search(r'Squidward|Tentacles', label, re.I):
            warnings.append('possibly_unrelated_source_speaker')
        if malformed:
            return {'type': 'unparsed', 'raw_text': raw, 'reason': 'unbalanced_brackets'}, warnings + ['unbalanced_brackets']
        if any(p['type'] == 'unknown' for p in parts):
            warnings.append('unknown_annotation')
        if re.search(r'\*[^*]+\*', body) and any('*' in p['text'] for p in parts if p['type'] == 'speech'):
            warnings.append('unknown_star_annotation')
        base = {'speakers': speakers, 'raw_speaker': label, 'speaker_markers': markers, 'parts': parts}
        if any(not PRESENTATION.fullmatch(m) for m in markers):
            warnings.append('unknown_speaker_marker')
        speech = normalize(' '.join(p['text'] for p in parts if p['type'] == 'speech'))
        if speech:
            return {'type': 'utterance', **base, 'text': speech}, warnings
        if parts:
            types = {p['type'] for p in parts}
            return {'type': 'event', **base, 'event_type': next(iter(types)) if len(types) == 1 else 'mixed',
                    'text': ' '.join(p['text'] for p in parts)}, warnings
        return {'type': 'unparsed', 'raw_text': raw, 'reason': 'empty_speaker_record'}, warnings + ['empty_speaker_record']
    if SCENE.match(raw):
        return {'type': 'scene', 'text': raw}, []
    parts, malformed = split_parts(raw)
    if parts and not malformed and all(p['type'] != 'speech' for p in parts):
        # Standalone narrative paragraphs describe a scene. Only short, clear
        # sound-only cues become sound events; mixed narrative remains context.
        pure_sound = all(p['type'] == 'sound' for p in parts) and all(re.fullmatch(
                r'(?:(?:Peppa|George|Pig|Daddy|Mummy|Everyone|They|Both|and)\s+)*(?:laugh\w*|snort\w*|cr(?:y|ies|ying)|giggl\w*|oink\w*)(?:\s+a bit)?\.?',
                p['text'], re.I) for p in parts)
        if not pure_sound and (len(raw.split()) > 5 or any(p['type'] in {'action', 'scene_description'} for p in parts)):
            parts = [{'type': 'scene_description', 'text': normalize(raw[1:-1])}]
        types = {p['type'] for p in parts}
        return {'type': 'event', 'event_type': next(iter(types)) if len(types) == 1 else 'mixed',
                'speakers': [], 'text': ' '.join(p['text'] for p in parts), 'parts': parts}, (
                    ['unknown_annotation'] if 'unknown' in types else [])
    return {'type': 'unparsed', 'raw_text': raw, 'reason': 'unrecognized_body_record'}, ['unrecognized_body_record']


def body_records(html):
    soup = BeautifulSoup(html, 'html.parser')
    root = soup.select_one('.mw-parser-output')
    if root is None:
        raise ValueError('No .mw-parser-output content region; do not parse the entire page')
    for node in root.select('script, style, aside, nav, cnx, fandom-video-ad, .notice.metadata, .toc, #toc, .mw-editsection, .navbox, .portable-infobox, .wikia-ad, .reference, .printfooter, .catlinks'):
        if node.parent is not None:
            node.decompose()
    for node in list(root.find_all('table')):
        if node.find('a', href='/wiki/Template:Stub'):
            node.decompose()
            continue
        header = node.find('th')
        title = normalize(header.get_text(' ', strip=True)) if header else ''
        if title in {'Peppa Pig TV Series episode transcripts', 'Peppa Pig Tales episode transcripts'} or (
                re.fullmatch(r'(?:(?:Expand|Collapse) )?Series \d+', title) and
                ('mw-collapsible' in node.get('class', []) or
                 any('/Transcript' in a.get('href', '') for a in node.find_all('a')))):
            node.decompose()
    for node in list(root.find_all(['a', 'p'])):
        if node.parent is not None and normalize(node.get_text(' ', strip=True)) == 'Template:Null':
            node.decompose()
    # Fandom's episode tabs are sometimes an unclassed div containing tables.
    for node in list(root.find_all('div', recursive=False)):
        if normalize(node.get_text(' ', strip=True)) == 'Info Gallery Transcript':
            node.decompose()
    for node in list(root.find_all('p')):
        if re.fullmatch(r'(?:The following is a transcript for the episode,?|This is the transcript for) .+\.', normalize(node.get_text(' ', strip=True)), re.I):
            node.decompose()
            continue
        # Some pages indent the parts of ONE labeled turn into a following DL.
        # DOM adjacency and a label-only paragraph establish the relation; do
        # not attach arbitrary unlabeled paragraphs to a preceding speaker.
        if re.fullmatch(r'[^:]{1,100}:', normalize(node.get_text(' ', strip=True))):
            following = node.find_next_sibling()
            if following and following.name == 'dl' and not following.find('dt'):
                items = following.find_all('dd', recursive=False)
                if items and not any(re.match(r'^[A-Z][^:]{0,99}:', normalize(x.get_text(' ', strip=True))) for x in items):
                    node.append(' ' + following.get_text(' ', strip=True))
                    following.decompose()

    records = []
    started = False
    stopped = False

    def emit(kind, text):
        value = normalize(text)
        if value:
            records.append((kind, value))

    def walk(node):
        nonlocal started, stopped
        if stopped:
            return
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            if str(node).strip():
                emit('body', str(node))
            return
        if not isinstance(node, Tag):
            return
        if re.fullmatch(r'h[1-6]', node.name):
            text = normalize(node.get_text(' ', strip=True))
            if text.casefold() in STOP_HEADINGS:
                stopped = True
            elif text.casefold() in {'transcript', 'transcription'}:
                # Drop only the introduction preceding the explicit transcript heading.
                if not started:
                    records.clear()
                started = True
            else:
                emit('heading', text)
            return
        if node.name == 'tr':
            cells = node.find_all(['td', 'th'], recursive=False)
            values = [normalize(c.get_text(' ', strip=True)) for c in cells]
            if [x.casefold() for x in values] in [['character', 'dialogue'], ['speaker', 'text']]:
                return
            if len(values) == 2:
                emit('body', values[0].rstrip(':') + ': ' + values[1])
            else:
                emit('body', node.get_text(' ', strip=True))
            return
        if node.name == 'dl':
            pending = None
            for child in node.find_all(['dt', 'dd'], recursive=False):
                text = child.get_text(' ', strip=True)
                if child.name == 'dt':
                    if pending:
                        emit('body', pending)
                    pending = text
                elif pending:
                    emit('body', pending.rstrip(':') + ': ' + text)
                    pending = None
                else:
                    emit('body', text)
            if pending:
                emit('body', pending)
            return
        if node.name == 'li' and node.find(['ul', 'ol']):
            own = BeautifulSoup(str(node), 'html.parser')
            for nested in own.find_all(['ul', 'ol']):
                nested.decompose()
            own_text = normalize(own.get_text(' ', strip=True))
            nested_items = node.select('ul > li, ol > li')
            if re.match(r'^[A-Z][^:]{0,99}:', own_text) and not any(
                    re.match(r'^[A-Z][^:]{0,99}:', normalize(x.get_text(' ', strip=True))) for x in nested_items):
                emit('body', node.get_text(' ', strip=True))
                return
        if node.name in {'p', 'li', 'blockquote'} and not node.find(['p', 'li', 'table', 'dl', 'blockquote']):
            # BR represents a source record break, never split on punctuation.
            clone = BeautifulSoup(str(node), 'html.parser')
            for br in clone.find_all('br'):
                br.replace_with('\u241e')
            # Source-code whitespace is not a record boundary. BR inside one
            # speaker's sentence is also layout; split only explicit new records.
            lines = []
            for chunk in clone.get_text('').split('\u241e'):
                chunk = normalize(chunk)
                if not chunk:
                    continue
                new_record = re.match(r'^[A-Z][^:]{0,99}:', chunk) or chunk.startswith(('(', '['))
                if lines and not new_record:
                    lines[-1] += ' ' + chunk
                else:
                    lines.append(chunk)
            for line in lines:
                emit('body', line)
            return
        if node.name not in {'table', 'thead', 'tbody', 'tfoot', 'ul', 'ol'} and not node.find(['p', 'li', 'table', 'dl', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div']):
            emit('body', node.get_text(' ', strip=True))
            return
        for child in node.children:
            walk(child)

    for child in root.children:
        walk(child)
    return records


def clean(content, episode, source, plain_text=False):
    notices = []
    if not plain_text:
        source_soup = BeautifulSoup(content, 'html.parser')
        notices = [normalize(n.get_text(' ', strip=True)) for n in source_soup.select('.notice.metadata')]
        notices += [normalize(n.get_text(' ', strip=True)) for n in source_soup.find_all('table')
                    if n.find('a', href='/wiki/Template:Stub')]
        notices = list(dict.fromkeys(notices))
    records = [('body', line) for line in content.splitlines() if line.strip()] if plain_text else body_records(content)
    entries, warnings, seen = [], [], Counter()
    for index, (kind, raw) in enumerate(records, 1):
        entry, issues = parse_record(kind, raw)
        entry['raw_text'] = raw
        # IDs derive from the complete source record, not its current position.
        key = fingerprint([kind, raw])[:16]
        seen[key] += 1
        suffix = f'_{seen[key]:02}' if seen[key] > 1 else ''
        entry['id'] = f"{episode['id']}_E{key}{suffix}"
        entry['source_record'] = index
        if issues:
            entry['review_flags'] = list(issues)
        entries.append(entry)
        warnings.extend({'entry_id': entry['id'], 'code': code} for code in issues)
        if seen[key] > 1:
            warnings.append({'entry_id': entry['id'], 'code': 'duplicate_record',
                             'detail': 'Retained; identical duplicates use occurrence suffixes, identity ambiguous if duplicates move.'})
    counts = Counter(e['type'] for e in entries)
    reasons = []
    if not counts['utterance']:
        reasons.append('no_spoken_dialogue')
    if counts['unparsed']:
        reasons.append('unparsed_body')
    if counts['utterance'] < 10:
        reasons.append('very_short_transcript')
    if re.search(r'\b(?:incomplete|unfinished|to be added|stub|work in progress|WIP)\b', content, re.I):
        reasons.append('source_incompleteness_marker')
    if any(re.search(r'needs a transcript|transcript to be written|incomplete|unfinished', notice, re.I) for notice in notices):
        reasons.append('source_incompleteness_notice')
    report = {
        'episode': episode, 'status': 'needs_review' if warnings or reasons else 'parsed',
        'utterances': counts['utterance'],
        'unknown_speaker_utterances': sum(e['type'] == 'utterance' and not e['speakers'] for e in entries),
        'scenes': counts['scene'],
        'sound_events': sum(e['type'] == 'event' and any(p['type'] == 'sound' for p in e.get('parts', [])) for e in entries),
        'inline_sound_annotations': sum(p['type'] == 'sound' for e in entries if e['type'] == 'utterance' for p in e['parts']),
        'unparsed': counts['unparsed'], 'body_records': len(records),
        'possibly_incomplete': bool(reasons), 'incomplete_reasons': reasons,
        'completeness_note': 'Heuristic flags only; absence of flags does not prove completeness against the episode.',
        'warnings': warnings,
    }
    if notices:
        report['source_notices'] = notices
    return {'schema_version': 1, 'episode': episode, 'source': source, 'entries': entries,
            'possibly_incomplete': bool(reasons)}, report


def run_batch(manifest_path, output):
    manifest_path, output = Path(manifest_path), Path(output)
    results = []
    for job in json.loads(manifest_path.read_text(encoding='utf-8-sig')):
        episode = job['episode']
        try:
            if job.get('file'):
                input_path = (manifest_path.parent / job['file']).resolve()
                data = input_path.read_bytes()
                suffix = input_path.suffix
            else:
                # Ordinary public request only; stop on denial, no bypass or retries.
                with urllib.request.urlopen(job['url'], timeout=30) as response:
                    data = response.read()
                suffix = '.html'
            digest = hashlib.sha256(data).hexdigest()
            raw_path = output / 'raw' / episode['id'] / (digest + suffix)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            if not raw_path.exists():
                raw_path.write_bytes(data)
            source = {'type': 'peppa_wiki', 'url': job['url'],
                      'raw_file': raw_path.relative_to(output).as_posix(), 'sha256': digest}
            if job.get('capture_method'):
                source['capture_method'] = job['capture_method']
                source['capture_note'] = ('Browser DOM paragraph/heading text exported into minimal HTML; not the original HTTP response or original markup.'
                    if job['capture_method'] == 'browser_dom_text_export' else
                    'Rendered .mw-parser-output outerHTML captured through normal browser access; not original HTTP response bytes.')
            for key in ('captured_at', 'revision_id'):
                if job.get(key):
                    source[key] = job[key]
            parsed, report = clean(data.decode(job.get('encoding', 'utf-8-sig')), episode, source,
                                   plain_text=job.get('format') == 'transcript_text')
            write_json(output / 'episodes' / (episode['id'] + '.json'), parsed)
            write_json(output / 'reports' / (episode['id'] + '.json'), report)
            results.append(report)
        except Exception as error:
            failure = {'episode': episode, 'url': job.get('url'), 'status': 'failed',
                       'error_type': type(error).__name__, 'error': str(error),
                       'http_status': getattr(error, 'code', None)}
            if isinstance(error, urllib.error.HTTPError):
                body = error.read()
                path = output / 'errors' / (episode['id'] + '.response.html')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
                failure['error_response'] = path.relative_to(output).as_posix()
            write_json(output / 'errors' / (episode['id'] + '.json'), failure)
            results.append(failure)
    write_json(output / 'batch_report.json', results)
    print(json.dumps(results, ensure_ascii=True, indent=2))
    return int(any(r['status'] == 'failed' for r in results))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', help='JSON array of episode/url/file jobs')
    parser.add_argument('--output', default='output/wiki')
    args = parser.parse_args()
    raise SystemExit(run_batch(args.manifest, args.output))
