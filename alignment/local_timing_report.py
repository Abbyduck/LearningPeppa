"""One Markdown comparison and exact audio excerpts for the local experiment."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import time
import wave

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'output/local_timing_254_278'
BASE=ROOT/'output/whisperx_s01e01_native'


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def norm(text):return re.findall(r"[a-z]+(?:'[a-z]+)?",text.lower().replace('’',"'"))


def main():
    started=time.perf_counter()
    run=read(P/'run.json');assert run['status']=='completed'
    wiki_path=ROOT/'output/wiki/season1/episodes/S01E01.json'
    wiki=read(wiki_path)
    originals={r['source_record']:r for r in wiki['entries'] if r['type']=='utterance'}
    a=read(BASE/'aligned.raw.json')
    b=read(P/'B12.aligned.raw.json')
    c=read(P/'C.native.raw.json')
    groups={'A':a,'B12':b,'C':c}
    absolute={}
    for name,data in groups.items():
        offset=0 if name=='A' else 253
        rows=[]
        for segment in data['segments']:
            if name=='A' and not (segment['end']>253 and segment['start']<279):continue
            row=dict(segment)
            row['start']=round(row['start']+offset,6);row['end']=round(row['end']+offset,6)
            row['words']=[dict(w,**{key:round(w[key]+offset,6) for key in ['start','end'] if key in w}) for w in segment.get('words',[])]
            rows.append(row)
        absolute[name]=rows
    baseline_read_seconds=time.perf_counter()-started
    entries=[]
    for record in [84,86,87]:
        original=originals[record]
        entry=dict(id=original['id'],source_record=record,text=original['text'],speakers=original.get('speakers'),candidates={})
        for group,segments in absolute.items():
            ranked=sorted(segments,key=lambda s:difflib.SequenceMatcher(None,norm(original['text']),norm(s['text']),autojunk=False).ratio(),reverse=True)
            match=ranked[0]
            ratio=difflib.SequenceMatcher(None,norm(original['text']),norm(match['text']),autojunk=False).ratio()
            assert ratio>.7, (record,group,ranked)
            entry['candidates'][group]=dict(start=match['start'],end=match['end'],recognized_text=match['text'],words=match['words'],
                text_differs_from_wiki=norm(match['text'])!=norm(original['text']),text_correspondence_only=True,
                acoustic_listening_verdict='not_independently_listened',clip=f'{group}_record_{record}.wav')
        entries.append(entry)
    laugh={}
    for group,segments in absolute.items():
        matches=[s for s in segments if len(norm(s['text']))>0 and set(norm(s['text'])) <= {'ha','haha','ho'} and s['start']>259]
        if matches:
            words=[w for s in matches for w in s['words']]
            laugh[group]=dict(start=matches[0]['start'],end=matches[-1]['end'],
                recognized_text=' '.join(s['text'] for s in matches),word_count=len(words),
                zero_or_negative_duration_words=[w for w in words if w.get('end',0)<=w.get('start',0)],clip=f'{group}_laughter.wav')
    # All excerpts use only recorded absolute candidate times, with zero padding.
    with wave.open(str(BASE/'source_audio.wav'),'rb') as source:
        params=source.getparams();sr=source.getframerate()
        for clip in [r for e in entries for r in e['candidates'].values()]+list(laugh.values()):
            begin,end=round(clip['start']*sr),round(clip['end']*sr)
            source.setpos(begin);pcm=source.readframes(end-begin)
            with wave.open(str(P/clip['clip']),'wb') as dest:
                dest.setparams(params);dest.writeframes(pcm)
            clip['audio_frames']=end-begin
        # Two boundary contexts permit the listener to detect missing onsets/offsets.
        for name,start,end in [('dialogue_context_264_272.wav',264,272),('speaker_switch_268_271.7.wav',268,271.7),('narration_context_253_258.wav',253,258)]:
            source.setpos(round(start*sr));pcm=source.readframes(round((end-start)*sr))
            with wave.open(str(P/name),'wb') as dest:
                dest.setparams(params);dest.writeframes(pcm)
    diarization=[r for r in read(BASE/'diarization.raw.json') if r['end']>253 and r['start']<279]
    vad=read(P/'B12.vad_boundaries.json')
    natural=vad['natural_activity_local']
    chunks=vad['merged_chunks_local']
    natural_boundaries=all(any(abs(s['start']-a)<.002 for a,b in natural) and any(abs(s['end']-b)<.002 for a,b in natural) for s in chunks)
    assert natural_boundaries
    result=dict(scope=run['input_window_absolute'],wiki=str(wiki_path),wiki_sha256=hashlib.sha256(wiki_path.read_bytes()).hexdigest(),
        utterances=entries,laughter= laugh,reused_diarization=diarization,run=run,
        B12_all_chunk_edges_match_natural_vad_edges=natural_boundaries,B8_run=False,
        human_verified=False,A86_wrong_audio_confirmed_by_user_in_prior_conversation=True,
        baseline_read_and_candidate_preparation_seconds=baseline_read_seconds,
        source_results_modified=False,excerpt_padding_seconds=0)
    (P/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    def timecell(candidate):return f"{candidate['start']:.3f}–{candidate['end']:.3f}"
    lines=[]
    notes={84:'B/C 均把 muddy 识别成 mud；Wiki 原文保留。三组起点也有差异，需听旁白首音。',
        86:'A：用户已试听确认是笑声，错误。B/C 移回后方对白附近；C 起点比 B 早 0.620 秒，需听是否含前导非语词声、B 是否截首音。',
        87:'A：仍位于真实对白之前，需与参考音频对照。B 的首词 It\'s 长 1.162 秒，疑似含停顿／前句尾。C 结束比 B 早 0.391 秒，是否截尾须试听。'}
    for e in entries:
        cells=' | '.join(timecell(e['candidates'][g]) for g in ['A','B12','C'])
        lines.append(f"| {e['source_record']} | {e['text']} | {cells} | {notes[e['source_record']]} |")
    clips=[]
    for e in entries:
        clips.append(f"\n### Wiki #{e['source_record']} · {e['text']}\n")
        for group in ['A','B12','C']:
            candidate=e['candidates'][group]
            clips.append(f"- [{group} 原始切点 · {timecell(candidate)} 秒]({(P/candidate['clip']).as_posix()})")
    laugh_lines=[]
    for group,l in laugh.items():
        laugh_lines.append(f"| {group} | {timecell(l)} | {l['word_count']} | {len(l['zero_or_negative_duration_words'])} | [试听]({(P/l['clip']).as_posix()}) |")
    vd='\n'.join(f"| {s['start']+253:.3f}–{s['end']+253:.3f} | {s['text']} |" for s in chunks)
    ds='\n'.join(f"| {r['start']:.3f}–{r['end']:.3f} | {r['speaker']} |" for r in diarization)
    t=run['timings'];old=read(BASE/'run.json')
    report=f'''# S01E01 · 254–278 秒局部 A/B/C 时间定位实验

实验仅处理 **253.000–279.000 秒，共 26 秒**；目标为 254.017–278.047，前后分别留 1.017 / 0.953 秒上下文。使用同一原视频已验证一致的 16 kHz PCM、同一 large-v3 本地权重、RTX 2070 SUPER、CUDA float16。A 复用原始结果；B/C 仅在该局部推理，未重复说话人分离。

## 三组对照

所有时间为原视频绝对秒。Wiki 原文和发言结构保持不变。B/C 原始文件中的时间为局部相对秒，对照表只加 253 秒；没有校正词时间。文本对应只用于找到候选，不作为听验通过依据。

| Wiki记录 | 正式 Wiki 台词 | A 原始 WhisperX | B chunk_size=12 | C 原生词时间 | 是否异常／需要核听的边界 |
|---|---|---|---|---|---|
{chr(10).join(lines)}

**结论边界：** A 的 #86 已由用户试听确认错位。B/C 已不再输出在 A 的 256–260 秒笑声区间，但这只能说明候选位置变化，不能替代听验。当前没有把 B 或 C 标为“听验成功”。对精确首音、尾音、夹入笑声的判断，请以以下原音频为准。模型分数未参与成功判定。

## 原始切点试听

[完整局部输入 253–279 秒]({(P/'local_input_253_279.wav').as_posix()}) · [对白参考 264–272 秒]({(P/'dialogue_context_264_272.wav').as_posix()}) · [旁白参考 253–258 秒]({(P/'narration_context_253_258.wav').as_posix()})

以下所有 A/B/C 小片段严格按候选起止时间裁剪，**前后余量为 0**。参考音频另存，未用参考音频位置修改候选。
{chr(10).join(clips)}

## 笑声及异常词

这里的“笑声”一栏是模型输出的 Ha/ha 序列，不是独立音频标签；A 可能同样放错位置。

| 组别 | 模型给笑声的范围（秒） | 原始词条数 | 零／负时长词数 | 音频 |
|---|---|---:|---:|---|
{chr(10).join(laugh_lines)}

- B12 #87 的 `It's`：269.007–270.169，**1.162 秒**，显著长于 B 的另两个词 only（0.320 秒）和 mud（0.521 秒），原样保留为边界疑点；未按人为门限删除。
- C 的笑声生成大量连写 ha，并出现零时长词；这是本次 C 的实际异常，完整原始文本与所有零时长词见 comparison.json 和 C.native.raw.json，未去重、合并或修补。
- C #86 以 265.200 开始，B 为 265.820；C #87 结束 270.800，B 为 271.191。三组音频与参考音频用于确认是否夹入非语词声或截掉真实发音。

## B12 实际 VAD 分块与截句检查

| 实际合并块（绝对秒） | 原始 ASR 文本 |
|---|---|
{vd}

所有块的起止点都能对应本次 VAD 的自然活动边界（舍入误差小于 2 ms），没有触发对连续活动的 12 秒内部强制切分，也未手工给定台词切点。没有把 #86/#87 在句中切开；但 **两种角色的对白仍合在同一块 265.620–271.492**，因此不能据此声称已解决所有跨角色问题。文本边界与真实发音是否吻合仍须试听。

本轮不继续跑 B8：B12 已避免已知约 9 秒整体提前，残留的 #87 词首问题仍需试听；该对白块仅 5.872 秒，单纯从 12 改 8 不一定会拆开它。未据此调整其他参数。

## 复用 pyannote 的换人检查

| 原始范围（秒） | 原始说话人编号 |
|---|---|
{ds}

Wiki #86 的角色为 {', '.join(originals[86].get('speakers',[]))}，#87 为 {', '.join(originals[87].get('speakers',[]))}。现有 pyannote 在 265.559–269.052 与 269.862–271.347 两段都给 SPEAKER_02，**没有用不同编号表达两句之间的角色切换**。这只是模型聚类与 Wiki 角色不一致的线索，不能单凭 Wiki 或分离结果宣称真实换人已验证。

[试听原音中的换人附近 268–271.7 秒]({(P/'speaker_switch_268_271.7.wav').as_posix()})。真实声音是否换人，以及 pyannote 边界是否合适，当前未作独立人工听验判断。

## 实际运行时间

| 组别 | 本次推理总耗时（含各组模型加载及释放） | 模型／VAD加载 | 对齐器加载 | 纯处理阶段 |
|---|---:|---:|---:|---|
| A | **0 秒推理，复用** | — | — | 原始文件读取与候选准备 {baseline_read_seconds:.4f} 秒 |
| B12（26秒音频） | {t['B12_wall_seconds']:.3f} 秒 | {t['B12_model_and_vad_load_seconds']:.3f} 秒 | {t['B12_aligner_load_seconds']:.3f} 秒 | VAD+ASR {t['B12_vad_and_asr_seconds']:.3f} 秒；对齐 {t['B12_alignment_seconds']:.3f} 秒 |
| C（26秒音频） | {t['C_wall_seconds']:.3f} 秒 | {t['C_model_load_seconds']:.3f} 秒 | 不使用 | 转写+原生词时间 {t['C_transcription_and_word_timing_seconds']:.3f} 秒 |

A 的历史整集运行耗时为 {old['wall_seconds']:.3f} 秒（310.962 秒音频），其中 ASR+VAD及加载 {old['asr_seconds']:.3f} 秒、wav2vec2及加载 {old['alignment_seconds']:.3f} 秒、说话人分离及加载 {old['diarization_seconds']:.3f} 秒。这是历史整集测量，**不能与 B/C 局部耗时直接作速度排名**。本次 B/C 均未计入新的说话人分离，因为没有重跑。

局部输入截取改变了 A 原来的上下文与 VAD 起算位置，C 也按要求未用 VAD，因此这不是严格排除所有混杂因素的同块解码实验；结果支持局部候选对比，不能直接外推 52 集准确率或线性估算包含加载的全季成本。

## 原始记录

- A：复用 `output/whisperx_s01e01_native/asr.raw.json`、`aligned.raw.json`。
- B：本目录 `B12.asr.raw.json`、`B12.aligned.raw.json`、`B12.vad_boundaries.json`，原始 VAD 得分也已保留；得分不用于判定成功。
- C：`C.native.raw.json`，保留原生 segment、word、重复笑声和零时长词。
- `run.json`：参数、耗时和来源；`comparison.json`：同一份表的可追溯数据、原词、试听片段范围和复用的 pyannote 时间线。

未生成新网页，未重跑整集，未改写 Wiki 或 A/B/C 原始输出。
'''
    (P/'REPORT.md').write_text(report,encoding='utf-8')
    print(report[:2200]);print('Report:',(P/'REPORT.md').resolve())
    print('C zero-duration laughter words:',len(laugh['C']['zero_or_negative_duration_words']))


if __name__=='__main__':main()
