"""Compare original WhisperX transcription to Wiki, without re-aligning Wiki audio."""
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import statistics
import base64
from alignment.comparison_report import TEMPLATE

ROOT = Path(__file__).resolve().parents[1]
P = ROOT/'output/whisperx_s01e01_v2'
N = ROOT/'output/forced_alignment/S01E01'
WIKI = ROOT/'output/wiki/season1/episodes/S01E01.json'


def tokens(text):
    return re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower().replace('’', "'"))


def edit_alignment(wiki, recognized):
    """Global Levenshtein alignment; return index pairs and explicit omissions."""
    m, n = len(wiki), len(recognized)
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m+1):
        dp[i][0] = i
    for j in range(n+1):
        dp[0][j] = j
    for i in range(1, m+1):
        for j in range(1, n+1):
            dp[i][j] = min(dp[i-1][j-1]+(wiki[i-1]!=recognized[j-1]), dp[i-1][j]+1, dp[i][j-1]+1)
    pairs, i, j = [], m, n
    while i or j:
        if i and j and dp[i][j] == dp[i-1][j-1]+(wiki[i-1]!=recognized[j-1]):
            pairs.append((i-1, j-1, 'equal' if wiki[i-1]==recognized[j-1] else 'substitution'))
            i, j = i-1, j-1
        elif i and dp[i][j] == dp[i-1][j]+1:
            pairs.append((i-1, None, 'wiki_not_recognized'))
            i -= 1
        else:
            pairs.append((None, j-1, 'asr_extra'))
            j -= 1
    return pairs[::-1]


def main():
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    run = read(P/'run.json')
    assert run['status'] == 'completed', 'Cannot publish a failed/incomplete run as a completed comparison.'
    result = read(P/'S101 Muddy Puddles.json')
    wiki = [r for r in read(WIKI)['entries'] if r['type']=='utterance']
    nemo = read(N/'utterances.json')
    assert [(r['id'],r['text']) for r in wiki] == [(r['id'],r['text']) for r in nemo]
    assert run['wiki_sha256'] == hashlib.sha256(WIKI.read_bytes()).hexdigest()
    asr_words = []
    for s in result['segments']:
        for w in s.get('words', []):
            asr_words.append(dict(w, segment_speaker=s.get('speaker')))
    rec_tokens, token_word = [], []
    for index, w in enumerate(asr_words):
        for token in tokens(w['word']):
            rec_tokens.append(token)
            token_word.append(index)
    wiki_tokens, spans = [], []
    for row in wiki:
        begin = len(wiki_tokens)
        wiki_tokens.extend(tokens(row['text']))
        spans.append((begin, len(wiki_tokens)))
    pairs = edit_alignment(wiki_tokens, rec_tokens)
    mapping = {a:(b,status) for a,b,status in pairs if a is not None}
    extra = [dict(token=rec_tokens[b], asr_word_index=token_word[b], word=asr_words[token_word[b]])
             for a,b,status in pairs if a is None]
    combined = []
    for row, n, (a,b) in zip(wiki, nemo, spans):
        evidence = []
        assigned = []
        for i in range(a,b):
            j,status = mapping[i]
            evidence.append(dict(wiki_token=wiki_tokens[i], status=status,
                asr_token=rec_tokens[j] if j is not None else None,
                asr_word_index=token_word[j] if j is not None else None,
                original_asr_word=asr_words[token_word[j]] if j is not None else None))
            if j is not None:
                assigned.append(token_word[j])
        matched = sum(e['status']=='equal' for e in evidence)
        issues = []
        if any(e['status']=='wiki_not_recognized' for e in evidence):
            issues.append('wiki_words_not_recognized')
        if any(e['status']=='substitution' for e in evidence):
            issues.append('asr_text_differs_from_wiki')
        # Keep all source words within the assigned span, including extra ASR words.
        source_words = asr_words[min(assigned):max(assigned)+1] if assigned else []
        timed = [w for w in source_words if 'start' in w and 'end' in w]
        start, end = (timed[0]['start'], timed[-1]['end']) if timed else (None,None)
        if not assigned:
            issues.append('no_asr_words_assigned')
        if len(timed) != len(source_words):
            issues.append('missing_original_whisperx_word_timing')
        for w in timed:
            if w['end']<=w['start']:
                issues.append('invalid_word_boundary:'+w['word'])
            elif w['end']-w['start']>max(1.2,len(w['word'])*.2+.4):
                issues.append('implausibly_long_word:'+w['word'])
        x = dict(id=row['id'], source_record=row['source_record'], text=row['text'],
            recognized_text=' '.join(w['word'] for w in source_words), start=start,end=end,
            lexical_start=start, words=source_words, matched_tokens=matched,total_tokens=b-a,
            anchor_coverage=matched/(b-a), issues=issues, word_comparison=evidence,
            speaker_ids=sorted({w['speaker'] for w in source_words if w.get('speaker')}),
            source_word_range=[min(assigned), max(assigned)] if assigned else None,
            human_verified=False, timing_source='Original WhisperX ASR-aligned word timestamps; no Wiki forced alignment')
        delta = {key:round(x[key]-n['nfa_candidate'][key],4) if x[key] is not None else None for key in ['start','end']}
        combined.append(dict(id=row['id'],source_record=row['source_record'],text=row['text'],speakers=row.get('speakers'),
            nemo=n,whisperx=x,raw_delta_seconds=delta,large_difference=any(v is not None and abs(v)>.25 for v in delta.values()),human_verdict=None))
    for prev,cur in zip(combined,combined[1:]):
        if prev['whisperx']['end'] is not None and cur['whisperx']['start'] is not None and prev['whisperx']['end']>cur['whisperx']['start']:
            prev['whisperx']['issues'].append('overlap_with_next_wiki_utterance')
            cur['whisperx']['issues'].append('overlap_with_previous_wiki_utterance')
    differences = [abs(r['raw_delta_seconds']['end']) for r in combined if r['raw_delta_seconds']['end'] is not None]
    summary = dict(total=len(wiki), nemo_automatic=sum(r['start'] is not None for r in nemo),
        nemo_null=sum(r['start'] is None for r in nemo), whisperx_with_timing=sum(r['whisperx']['start'] is not None for r in combined),
        whisperx_flagged=sum(bool(r['whisperx']['issues']) for r in combined),
        large_difference_rows=sum(r['large_difference'] for r in combined),human_verified=0,
        all_nemo_null_rows_included=True,original_whisperx_word_timestamps_unchanged=True,
        wiki_path=str(WIKI),wiki_sha256=run['wiki_sha256'],nemo_snapshot_sha256=hashlib.sha256((N/'utterances.json').read_bytes()).hexdigest(),
        warning='Text-mapping flags, inter-model differences and automatic acceptance counts are not accuracy.')
    data = dict(summary=summary,run=run,rows=combined,asr_extra_tokens=extra)
    (P/'comparison.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    snapshot = P/'nemo_snapshot'
    snapshot.mkdir(exist_ok=True)
    for name in ['utterances.json','quality_summary.json','inputs.json','run.json','REPORT.md']:
        shutil.copy2(N/name,snapshot/name)
    shutil.copy2(N/'source_audio.wav',P/'source_audio.wav')
    payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c')
    page=TEMPLATE.replace('__DATA__',payload)
    old_start=page.index('<details><summary>本次运行方法与限制')
    old_end=page.index('<div class="toolbar">',old_start)
    method='''<details><summary>运行参数、来源与对照方法</summary><p>本次使用官方 WhisperX 接口：large-v3 / en / transcribe / CUDA float16 / batch 4 / beam 5 / temperature 0 / condition_on_previous_text False；pyannote VAD onset 0.50、offset 0.363；WhisperX 原生对齐 interpolate=ignore；pyannote/speaker-diarization-community-1 说话人分离。使用本地完整缓存，不需要重新登录。没有替换 VAD、对齐器或说话人分离。</p><p>对照指定 output/wiki/season1/episodes/S01E01.json 的全部 43 句。全文单词编辑距离匹配只用于关联文本；网页直接使用 WhisperX 原始词时间，未拿 Wiki 再做强制对齐，也未借用 NeMo 时间。漏词、错词、ASR 额外词和无时间的词全部保留。SPEAKER 编号未擅自映射成角色。</p><a href="REPORT.md">报告</a> · <a href="comparison.json">全部对比与逐词差异</a> · <a href="S101%20Muddy%20Puddles.json">WhisperX 原始输出</a> · <a href="run.json">实际参数与运行记录</a></details>'''
    page=page[:old_start]+method+page[old_end:]
    page=page.replace('Wiki 原文重新对齐（无播放余量）','WhisperX 原始识别词时间（无播放余量）')
    page=page.replace('<p>独立 ASR 锚点：','<p><b>实际识别：</b>${esc(x.recognized_text)}</p><p>说话人编号：${esc(x.speaker_ids.join(", "))}</p><p>Wiki 原词匹配：')
    page=page.replace('JSON.stringify({window:x.window,issues:x.issues,anchor_words:x.anchor_words}', 'JSON.stringify({word_comparison:x.word_comparison,issues:x.issues,source_word_range:x.source_word_range}')
    # Keep exact WebAudio slicing available when the user double-clicks the HTML.
    # A data URL avoids file:// fetch restrictions without requiring a server.
    audio_url='data:audio/wav;base64,'+base64.b64encode((P/'source_audio.wav').read_bytes()).decode('ascii')
    page=page.replace('<script>const DATA=', '<script>const AUDIO_URL='+json.dumps(audio_url)+';const DATA=')
    page=page.replace("fetch('source_audio.wav')",'fetch(AUDIO_URL)')
    (P/'review.html').write_text(page,encoding='utf-8')
    table='\n'.join(f"| {r['source_record']} | {r['text']} | {r['whisperx']['recognized_text']} | {r['nemo']['nfa_candidate']} | {r['whisperx']['start']}–{r['whisperx']['end']} | {r['nemo']['status']} | {', '.join(r['whisperx']['issues'])} |" for r in combined)
    (P/'REPORT.md').write_text(f'''# S01E01 · WhisperX 指定参数 / NeMo 全量对比

本次为正式 WhisperX ASR → 原生 alignment → pyannote diarization；所有参数见 run.json。没有对 Wiki 重新做强制对齐，没有修改 WhisperX 词时间，没有借用 NeMo 时间。

Wiki：`{WIKI}`，43 句逐句关联。关联算法为全文单词编辑距离；错词、漏词和额外词显式保留，文本关联仍可能出错，需按原始输出复查。说话人编号未经人工角色对应。WhisperX 原始识别的全部片头/片尾仍保留在 S101 Muddy Puddles.json，无法关联 Wiki 的额外词在 comparison.json/asr_extra_tokens。

NeMo 使用现有 43 句结果，快照位于 nemo_snapshot；自动保留 {summary['nemo_automatic']}，null {summary['nemo_null']}，均展示原始候选。WhisperX {summary['whisperx_with_timing']} 句有关联时间，{summary['whisperx_flagged']} 句有文本/时间规则提示。两边原始起点或终点差异超过 250 ms 共 {summary['large_difference_rows']} 句。人工听验 0；这些数字不是准确率，不能据此判定胜负。

| Wiki记录 | Wiki原文 | WhisperX实际识别 | NeMo原始时间 | WhisperX原始时间 | NeMo状态 | WhisperX提示 |
|---|---|---|---|---|---|---|
{table}
''',encoding='utf-8')
    (P/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
