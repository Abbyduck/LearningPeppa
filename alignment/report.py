"""Build a reviewable local S01E01 pilot report; no inference."""
from pathlib import Path
import hashlib
import html
import json

P = Path(__file__).resolve().parents[1]/'output/forced_alignment/S01E01'
read = lambda name: json.loads((P/name).read_text(encoding='utf-8'))
rows, inputs, stages, run = map(read, ['utterances.json','inputs.json','stages.json','run.json'])
wiki_path = Path(inputs['wiki'])
wiki = json.loads(wiki_path.read_text(encoding='utf-8'))
assert hashlib.sha256(wiki_path.read_bytes()).hexdigest() == inputs['wiki_sha256']
original = [x for x in wiki['entries'] if x['type']=='utterance']
assert [(r['id'],r['text'],r['source_record']) for r in rows] == [(r['id'],r['text'],r['source_record']) for r in original]
assert all((r['start'] is None)==(r['end'] is None) for r in rows)
accepted = [r for r in rows if r['start'] is not None]
assert all(0<=r['start']<r['end']<=inputs['duration_seconds'] for r in accepted)
assert all(a['end']<=b['start'] for a,b in zip(accepted,accepted[1:]))
for r in rows:
    for w in r['words']:
        assert w['start'] is not None and 0<=w['start']<w['end']<=inputs['duration_seconds']
pcm_equal=inputs.get('fresh_pcm_matches_cached_audio')

focus_records = {11,29,49,63,67,86}
focus = []
for r in rows:
    if r['source_record'] in focus_records:
        i = r['entry_index']
        focus.append(dict(source_record=r['source_record'], id=r['id'], text=r['text'],
            preceding_wiki_context=wiki['entries'][max(0,i-2):i],
            nfa_candidate=r['nfa_candidate'], speech_start=r['start'], speech_end=r['end'],
            first_word=r['words'][0], excluded_laughter_prefix_words=r['excluded_laughter_prefix_words'],
            status=r['status'], human_laughter_annotation=None,
            assessment='Suspicious first word spans 5.44 s; rejected, requires listening.' if r['source_record']==49
            else 'Automatic token boundary only; audio context provided for human verification.'))
(P/'laughter_checks.json').write_text(json.dumps(focus,ensure_ascii=False,indent=2),encoding='utf-8')

summary=read('quality_summary.json')
assert summary['automatic_accepted']==len(accepted)
rejected='\n'.join(f"| {r['source_record']} | {r['text']} | {', '.join(r['rejection_reasons']) or '词尾复核证据不足'} |" for r in rows if r['start'] is None)
examples='\n'.join(f"| {r['source_record']} | {r['words'][-1]['text']} | {r['nfa_candidate']['end']:.3f} | {r['end']:.4f} | {r['playback']['end']:.4f} |" for r in rows if r['source_record'] in {39,57})
body=Path(__file__).with_name('report_template.md').read_text(encoding='utf-8').format(
    total=len(rows),accepted=len(accepted),null_count=len(rows)-len(accepted),examples=examples,rejected=rejected,
    acoustic_seconds=stages['acoustic_inference_and_target_preparation_seconds'],viterbi_seconds=stages['viterbi_seconds'],
    run_seconds=run['wall_seconds'],tail_seconds=summary['character_check_wall_seconds'])
(P/'REPORT.md').write_text(body,encoding='utf-8')

blocks = []
for r in rows:
    c = r['nfa_candidate']
    label = 'null（待核查）' if r['start'] is None else f"{r['start']:.3f}–{r['end']:.3f}"
    playback=r.get('playback',dict(start=r['start'],end=r['end']))
    buttons = '' if r['start'] is None else f'<button onclick="play({playback["start"]},{playback["end"]})">播放语词发言（含尾部余量）</button>'
    context_end=max(c['end'],r.get('tail_check',{}).get('character_end',c['end']))+1
    buttons += f'<button onclick="play({max(0,c["start"]-2)},{context_end})">前后文</button><button onclick="play({c["start"]},{c["end"]})">原始候选（未验证）</button>'
    play_label='' if r['start'] is None else f'<small>实际试听：{playback["start"]:.3f}–{playback["end"]:.4f} 秒；对齐边界不含播放余量</small>'
    warning='<p>词尾复核证据不足，正式时间保留 null；可播放前后文检查。</p>' if r['status']=='tail_check_needs_review' else ''
    detail = html.escape(json.dumps(dict(words=r['words'], rejection_reasons=r['rejection_reasons'], excluded_laughter_prefix_words=r['excluded_laughter_prefix_words'],tail_check=r.get('tail_check'),playback=r.get('playback')),ensure_ascii=False,indent=2))
    blocks.append(f'<article id="record-{r["source_record"]}"><b>#{r["source_record"]} · {label}</b><p>{html.escape(r["text"])}</p>{play_label}{warning}<div>{buttons}</div><details><summary>词与声学证据</summary><pre>{detail}</pre></details></article>')
page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>S01E01 Wiki 强制对齐试听</title><style>body{max-width:1000px;margin:30px auto;font:16px/1.6 system-ui;padding:0 20px;background:#f7f7f7}header{position:sticky;top:0;background:white;padding:12px;border-bottom:1px solid #aaa}article{background:white;margin:12px 0;padding:16px;border-radius:8px}button{margin:5px;padding:8px}pre{white-space:pre-wrap;font-size:12px}audio{width:100%}</style><h1>S01E01 · Wiki + 原音频 Forced Alignment</h1><p>43 条 · 自动保留 39 · null 4 · 人工听验 0。原始候选不等于可信边界；未使用旧 ASR 时间。显式 Haha/Ho-Ho 保留原文，语词播放从后续实词开始。</p><header><audio id="audio" controls src="source_audio.wav"></audio><div id="status">请选择句子</div></header>''' + ''.join(blocks) + '''<script>const a=document.getElementById('audio');let stop=null;function play(s,e){stop=e;a.currentTime=s;document.getElementById('status').textContent=s.toFixed(3)+'–'+e.toFixed(3)+' 秒';a.play()}a.addEventListener('timeupdate',()=>{if(stop!==null&&a.currentTime>=stop){a.pause();stop=null}});</script></html>'''
page=page.replace('自动保留 39 · null 4',f'自动候选 {len(accepted)} · null {43-len(accepted)}')
page=page.replace('原始候选不等于可信边界；','已追加字符级词尾复核；试听余量与对齐时间分开。原始候选不等于可信边界；')
(P/'review.html').write_text(page,encoding='utf-8')
(P/'verification.json').write_text(json.dumps(dict(wiki_original_preserved=True, count=43, accepted=len(accepted),null_count=43-len(accepted), accepted_monotonic_in_bounds=True,original_pcm_match=pcm_equal, old_asr_used=False, preview_rows=len(blocks)),indent=2),encoding='utf-8')
print(body[:500])
