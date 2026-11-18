"""Wiki-preserving full utterance list over locked B12 raw word timestamps."""
import base64
import hashlib
import html
import json
from pathlib import Path
import re
import time
import wave
from alignment.whisperx_v2_report import edit_alignment,tokens
from alignment.native_word_review import TEMPLATE

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'output/whisperx_b12/S01E01'
WIKI=ROOT/'output/wiki/season1/episodes/S01E01.json'


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def build(folder=P,wiki_path=WIKI,batch_authorized=False):
    P=Path(folder);WIKI=Path(wiki_path)
    started=time.perf_counter();run=read(P/'run.json');assert run['status']=='completed'
    episode=run['episode']
    original_hash=hashlib.sha256((P/'result.whisperx.json').read_bytes()).hexdigest()
    result=read(P/'result.whisperx.json');asr=read(P/'asr.raw.json');wiki=read(WIKI)
    original=[r for r in wiki['entries'] if r['type']=='utterance']
    words=[]
    for si,seg in enumerate(result['segments']):
        for wi,w in enumerate(seg.get('words',[])):words.append(dict(w,source_segment_index=si,source_word_index=wi))
    recognized,word_index=[],[]
    for i,w in enumerate(words):
        for token in tokens(w['word']):recognized.append(token);word_index.append(i)
    target,spans=[],[]
    for r in original:
        a=len(target);target.extend(tokens(r['text']));spans.append((a,len(target)))
    pairs=edit_alignment(target,recognized)
    mapping={i:(j,status) for i,j,status in pairs if i is not None}
    rows=[]
    for r,(a,b) in zip(original,spans):
        assigned=[];correspondence=[];issues=[]
        for i in range(a,b):
            j,status=mapping[i]
            windex=word_index[j] if j is not None else None
            correspondence.append(dict(wiki_token=target[i],asr_token=recognized[j] if j is not None else None,status=status,raw_word_index=windex))
            if windex is not None:assigned.append(windex)
        if any(c['status']=='wiki_not_recognized' for c in correspondence):issues.append('wiki_words_missing_in_asr')
        if any(c['status']=='substitution' for c in correspondence):issues.append('asr_text_differs_from_wiki')
        selected=list(range(min(assigned),max(assigned)+1)) if assigned else []
        candidates=[words[i] for i in selected]
        timed=[w for w in candidates if w.get('start') is not None and w.get('end') is not None]
        candidate=dict(start=timed[0]['start'],end=timed[-1]['end']) if timed else dict(start=None,end=None)
        if not assigned:issues.append('no_candidate_words')
        if len(timed)!=len(candidates):issues.append('missing_word_timestamps')
        for w in timed:
            duration=w['end']-w['start'];lex=''.join(tokens(w['word']))
            if duration<=0:issues.append('invalid_word_duration:'+w['word'])
            elif duration>max(1.2,len(lex)*.2+.4):issues.append('unusually_long_word:'+w['word'])
            elif len(lex)<=4 and duration>.8:issues.append('short_word_over_0.8s:'+w['word'])
        if timed and any(x['end']>y['start']+.005 for x,y in zip(timed,timed[1:])):issues.append('overlapping_words')
        covered_chunks=[i for i,c in enumerate(asr['segments']) if timed and c['start']<candidate['end'] and c['end']>candidate['start']]
        if len(covered_chunks)>1:issues.append('utterance_spans_multiple_asr_chunks')
        if candidate['start'] is not None and candidate['end']<=candidate['start']:issues.append('invalid_candidate_interval')
        if candidate['start'] is not None and not (0<=candidate['start']<candidate['end']<=run['audio_seconds']+.001):issues.append('candidate_outside_audio_or_invalid')
        row=dict(r,candidate=candidate,start=None,end=None,status='candidate_unverified',human_verified=False,
            anomaly_reasons=list(dict.fromkeys(issues)),raw_word_indices=selected,words=candidates,
            recognized_text=' '.join(w['word'] for w in candidates),text_correspondence=correspondence,
            pyannote_speaker_ids=sorted({w['speaker'] for w in candidates if w.get('speaker')}),
            original_asr_chunk_indices=covered_chunks,timing_source='B12 original word timestamps; no boundary correction')
        rows.append(row)
    for previous,current in zip(rows,rows[1:]):
        p,c=previous['candidate'],current['candidate']
        if p['end'] is not None and c['start'] is not None and p['end']>c['start']:
            previous['anomaly_reasons'].append('overlap_with_next_wiki_utterance')
            current['anomaly_reasons'].append('overlap_with_previous_wiki_utterance')
    for r in rows:
        if r['anomaly_reasons']:r['status']='needs_listening_review'
        else:r.update(start=r['candidate']['start'],end=r['candidate']['end'])
    for index,r in enumerate(rows):
        c=r['candidate']
        if c['start'] is not None and 0<=c['start']<c['end']<=run['audio_seconds']:
            r['playback_context']=dict(start=max(0,c['start']-1),end=min(run['audio_seconds'],c['end']+1),source='candidate +/- 1 second; not model boundaries')
        else:
            previous=next((x['candidate']['end'] for x in reversed(rows[:index]) if x['candidate']['end'] is not None),0)
            following=next((x['candidate']['start'] for x in rows[index+1:] if x['candidate']['start'] is not None),run['audio_seconds'])
            r['playback_context']=dict(start=max(0,previous-.5),end=min(run['audio_seconds'],following+.5),source='neighbor context only; no candidate or interpolated boundary')
        r['inspection_cues']=[]
        # Unlocated VAD activity after the final aligned word can be laughter or
        # omitted/misplaced speech. Expose it for listening, never repair timing.
        for chunk in asr['segments']:
            chunk_words=[w for w in words if w.get('start',-1)>=chunk['start']-.003 and w.get('end',1e9)<=chunk['end']+.003]
            if chunk_words and r['words'] and r['words'][-1]==chunk_words[-1]:
                gap=round(chunk['end']-r['candidate']['end'],3)
                if gap>1.5:r['inspection_cues'].append(dict(type='unlocated_vad_activity_after_last_word',seconds=gap,chunk_end=chunk['end'],note='May be laughter or missed/misplaced speech; requires listening.'))
    assert [(r['id'],r['text'],r.get('speakers')) for r in rows]==[(r['id'],r['text'],r.get('speakers')) for r in original]
    extra=[dict(asr_token=recognized[j],raw_word_index=word_index[j]) for i,j,status in pairs if i is None]
    for name,data in [('utterances.json',rows),('asr_extra_tokens.json',extra)]:
        (P/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    old_needs={r['source_record'] for r in read(ROOT/'output/forced_alignment/S01E01/utterances.json') if r['start'] is None} if episode=='S01E01' else set()
    focus=({4,39,57,84,86,87} if episode=='S01E01' else set())|old_needs|{r['source_record'] for r in rows if r['inspection_cues'] or r['anomaly_reasons']}
    local=read(ROOT/'output/local_timing_254_278/comparison.json') if episode=='S01E01' else {'utterances':[]}
    local_candidates={r['source_record']:r['candidates']['B12'] for r in local['utterances']}
    checks=[]
    with wave.open(str(P/'source_audio.wav'),'rb') as src:
        sr=src.getframerate();params=src.getparams()
        for r in rows:
            if r['source_record'] not in focus:continue
            c=r['candidate'];entry=dict(source_record=r['source_record'],text=r['text'],candidate=c,
                anomaly_reasons=r['anomaly_reasons'],inspection_cues=r['inspection_cues'],human_listening_verdict=None)
            if r['source_record'] in local_candidates and c['start'] is not None:
                old=local_candidates[r['source_record']]
                entry['vs_user_accepted_local_B12']=dict(start_delta=round(c['start']-old['start'],4),end_delta=round(c['end']-old['end'],4),local_start=old['start'],local_end=old['end'])
            if c['start'] is not None and 0<=c['start']<c['end']<=run['audio_seconds']:
                filename=f"focus_record_{r['source_record']}.wav"
                src.setpos(round(c['start']*sr));pcm=src.readframes(round(c['end']*sr)-round(c['start']*sr))
                with wave.open(str(P/filename),'wb') as dst:dst.setparams(params);dst.writeframes(pcm)
                entry['exact_clip']=filename
            checks.append(entry)
    (P/'focus_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    # Reuse the existing lightweight audio player, retaining all Wiki utterances.
    escape=html.escape;cards=[]
    def button(label,s,e,attrs=''):
        valid=s is not None and e is not None and 0<=s<e<=run['audio_seconds']
        return f'<button {f"data-start={s} data-end={e}" if valid else "disabled"} {attrs}>{escape(label)}</button>'
    for r in rows:
        c=r['candidate'];label='无候选时间' if c['start'] is None else f"{c['start']:.3f}–{c['end']:.3f} s"
        wordbuttons=''.join(button(words[i]['word'],words[i].get('start'),words[i].get('end'),f'class="word" data-index="{i}"') for i in r['raw_word_indices'])
        controls=button('播放原始候选',c['start'],c['end'])
        ctx=r['playback_context']
        controls+=button('前后各 1 秒' if c['start'] is not None else '无候选：播放相邻原音',ctx['start'],ctx['end'])
        warning='；'.join(r['anomaly_reasons']) or '自动对应，未逐句人工听验'
        if r['inspection_cues']:warning+='；块尾仍有 VAD 活动未被文字定位，可能为笑声或遗漏／错位对白，请听上下文'
        cards.append(f'''<article id="record-{r['source_record']}" data-text="{escape(r['text'].lower(),quote=True)}"><div class="line"><b>Wiki #{r['source_record']}</b><span>{label}</span><b>{escape(', '.join(r.get('speakers',[])))}</b></div>
<p class="transcript">{escape(r['text'])}</p><p style="color:#934020">{escape(warning)}</p><div>{controls}</div>
<p class="muted">模型原文：{escape(r['recognized_text'])}</p><p class="muted">pyannote 编号（不替代 Wiki 角色）：{escape(', '.join(r['pyannote_speaker_ids']))}</p>
<div class="words">{wordbuttons}</div><details><summary>原始词时间与文本对应</summary><pre>{escape(json.dumps(dict(candidate=c,formal_start=r['start'],formal_end=r['end'],text_correspondence=r['text_correspondence'],words=r['words']),ensure_ascii=False,indent=2))}</pre></details></article>''')
    chunks=''.join(f"<section><b>原始 ASR 块 #{i+1} · {s['start']:.3f}–{s['end']:.3f}</b>{button('播放原始块',s['start'],s['end'])}<p>{escape(s['text'])}</p></section>" for i,s in enumerate(asr['segments']))
    audio='data:audio/wav;base64,'+base64.b64encode((P/'source_audio.wav').read_bytes()).decode('ascii')
    page=TEMPLATE.replace('__WORDS__',json.dumps(words,ensure_ascii=False).replace('<','\\u003c')).replace('__AUDIO__',json.dumps(audio))
    page=page.replace('__CARDS__',''.join(cards)).replace('__CHUNKS__',chunks).replace('__COUNT__',str(len(rows))).replace('__WORDCOUNT__',str(len(words)))
    page=page.replace('__MISSING__',str(sum(bool(r['anomaly_reasons']) for r in rows))).replace('__SECONDS__',f"{run['processing_wall_seconds']:.2f}")
    page=page.replace('S01E01 · WhisperX 原始逐词试听',f'{episode} · 固定 B12 · Wiki 完整发言试听').replace('原始句段 '+str(len(rows)),'Wiki 发言 '+str(len(rows))).replace('缺失／无效词时间','有异常提示的发言')
    page=page.replace('句段按 WhisperX 输出顺序排列。','全部发言按 Wiki 原顺序保留，角色以 Wiki 为准；异常项仍可播放原始候选。').replace('全新运行 · large-v3','固定配置 · chunk_size 12 · large-v3')
    page=page.replace('href="S101%20Muddy%20Puddles.json"','href="result.whisperx.json"').replace('最终原始 JSON','模型原始 JSON')
    page=page.replace('<div class="player">','<p><a href="utterances.json">Wiki 完整发言 JSON</a> · <a href="config.snapshot.json">固定配置</a> · <a href="REPORT.md">运行与重点检查报告</a></p><div class="player">')
    (P/'review.html').write_text(page,encoding='utf-8')
    assert hashlib.sha256((P/'result.whisperx.json').read_bytes()).hexdigest()==original_hash
    summary=dict(wiki_utterances=len(rows),all_original_ids_text_and_roles_preserved=True,rows_with_candidate=sum(r['candidate']['start'] is not None for r in rows),
        automatic_candidates=sum(not r['anomaly_reasons'] for r in rows),needs_review=sum(bool(r['anomaly_reasons']) for r in rows),
        human_verified_count=0,raw_words=len(words),raw_asr_chunks=len(asr['segments']),config_sha256=run['config_sha256'],
        raw_results_unchanged=True,score_used_as_acceptance_gate=False,processing_wall_seconds=run['processing_wall_seconds'],
        report_builder_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        report_seconds=time.perf_counter()-started,validation_status='Batch authorized by user; automatic output, not a human listening verdict.' if batch_authorized else 'Await full-episode listening validation; do not start other episodes yet.')
    (P/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    focus_table='\n'.join(f"| {r['source_record']} | {r['text']} | {r['candidate']['start']}–{r['candidate']['end']} | {', '.join(r['anomaly_reasons']) or '无机械异常提示，未听验'}{'；需检查块尾未定位活动' if r['inspection_cues'] else ''} | {r.get('vs_user_accepted_local_B12','—')} |" for r in checks)
    report=f'''# 固定 B12 · S01E01 整集运行

配置来自已成功局部 B 组的保存脚本和运行记录；显式参数按 AST 提取，默认值从相同锁定版本解析，未凭记忆重设。固定文件 `configs/whisperx_b12.fixed.json`，SHA256 `{run['config_sha256']}`。运行时校验配置、软件版本、源代码与模型权重，且校验实际生效的 ASR 选项。

完整流水线：原视频 → pyannote VAD / chunk_size=12 → large-v3 / CUDA float16 / batch=4 / beam=5 / temperature=0 → 原 wav2vec2 alignment / ignore 插值 → pyannote community-1 diarization。Wiki 仅作输出文本、角色与发言结构主数据，未传入声学模型、未改写原文、未合并或删除发言。原始模型结果未修正。

Wiki {len(rows)} 条全部保留，有候选时间 {summary['rows_with_candidate']} 条；无机械异常提示 {summary['automatic_candidates']}，有提示 {summary['needs_review']}。正式 start/end 在异常时为 null，同时 candidate 和原始词时间完整保留。所有自动候选仍未逐句人工听验，不能将机械检查当作准确率。

## 耗时

整集音频 {run['audio_seconds']:.3f} 秒，模型完整流程 {run['processing_wall_seconds']:.3f} 秒；配置／源文件／模型权重预检不计入模型流程，页面生成另计 {summary['report_seconds']:.3f} 秒。

```json
{json.dumps(run['timings'],ensure_ascii=False,indent=2)}
```

## 重点检查

旧 NeMo null 项及 #4、#39 first、#57 doing、#84、#86、#87 均列出。局部 B12 已由用户确认试听最好，但整集改变了前文上下文与 VAD 起算位置，不能直接把局部听验结论转移到整集。下表记录新候选与局部 B12 的边界变化；focus_record_*.wav 均按新候选零余量导出，不修复或补齐。

| Wiki记录 | 原文 | 新候选秒 | 异常提示 | 与局部B12比较（若有） |
|---|---|---|---|---|
{focus_table}

## 交付文件

- `review.html`：沿用轻量逐句／逐词播放器，全部 Wiki 发言可见，候选、原模型文字、角色与 pyannote 编号分开显示，音频内嵌。
- `utterances.json`：保留 Wiki 原始字段、id、文本、角色；追加 nullable 时间、candidate、异常原因、原词索引和纯文本对应记录。
- `asr.raw.json` / `aligned.raw.json` / `diarization.raw.json` / `result.whisperx.json`：本次完整中间数据，未经修补。
- `config.snapshot.json` / `effective_asr_options.json` / `run.json` / `verification.json` / `focus_checks.json`：配置、生效参数、耗时与重点检查记录。

文本对应基于全文词序列编辑距离；不一致、缺词、异常时长、跨 ASR 块和重叠均提示复查。短词超过 0.8 秒只作异常提示，不修改其时间；未使用模型分数作为通过门限。重复句与非语词笑声仍可能产生文本对应歧义，保留候选及原始输出以供试听。

## 下一步门槛

当前只完成 S01E01 重跑及机械验证，整集试听验证待完成。**尚未处理其他集数**。在确认完整第一集没有新的错位后，再用同一锁定配置测试另外两三集，不批量运行全季。
'''
    report=report.replace('# 固定 B12 · S01E01 整集运行',f'# 固定 B12 · {episode} 整集运行')
    if episode!='S01E01':
        report=report.replace('旧 NeMo null 项及 #4、#39 first、#57 doing、#84、#86、#87 均列出。局部 B12 已由用户确认试听最好，但整集改变了前文上下文与 VAD 起算位置，不能直接把局部听验结论转移到整集。下表记录新候选与局部 B12 的边界变化；','本集所有异常提示和块尾未定位活动均列入重点检查，不依赖第一集或旧 NeMo 数据；')
    if run.get('timing_scope'):
        report=report.replace('## 耗时\n','## 耗时\n\n批量模式：本集耗时是各阶段活跃处理时间的合计，不含共享模型加载和等待其他集数的时间；共享加载、全批次墙钟时间见季汇总。\n')
    if batch_authorized:
        report=report.split('## 下一步门槛')[0]+'## 运行范围\n\n用户已确认第一集版本并授权处理第一季。模型配置保持锁定，异常候选完整保留；自动处理完成不代表每条发言已人工听验。\n'
    (P/'REPORT.md').write_text(report,encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':build()
