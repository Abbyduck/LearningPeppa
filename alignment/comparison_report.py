"""Publish every Wiki row, including rejected NeMo and WhisperX candidates."""
from pathlib import Path
import hashlib
import html
import json
import shutil
import statistics

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'output/comparison/S01E01'
N = ROOT / 'output/forced_alignment/S01E01'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    wiki_path = ROOT / 'output/wiki/episodes/S01E01.json'
    wiki = [r for r in read(wiki_path)['entries'] if r['type'] == 'utterance']
    nemo, whisper = read(N/'utterances.json'), read(P/'whisperx_wiki.json')
    run = read(P/'run.json')
    assert len(wiki) == len(nemo) == len(whisper) == 43
    assert run['wiki_sha256'] == hashlib.sha256(wiki_path.read_bytes()).hexdigest()
    assert run['audio_sha256'] == hashlib.sha256((N/'source_audio.wav').read_bytes()).hexdigest()
    snapshot = P / 'nemo_snapshot'
    snapshot.mkdir(exist_ok=True)
    for name in ['utterances.json', 'quality_summary.json', 'inputs.json', 'run.json', 'stages.json', 'REPORT.md', 'word_tail_character_check.json']:
        shutil.copy2(N/name, snapshot/name)
    shutil.copy2(N/'source_audio.wav', P/'source_audio.wav')
    combined = []
    for w, n, x in zip(wiki, nemo, whisper):
        assert w['id'] == n['id'] == x['id'] and w['text'] == n['text'] == x['text']
        delta = dict(start=None, end=None)
        if x['start'] is not None:
            delta = {key: round(x[key]-n['nfa_candidate'][key], 4) for key in ['start', 'end']}
        combined.append(dict(id=w['id'], source_record=w['source_record'], text=w['text'],
            speakers=w.get('speakers'), nemo=n, whisperx=x, raw_delta_seconds=delta,
            large_difference=any(v is not None and abs(v)>.25 for v in delta.values()),
            human_verdict=None))
    differences = [abs(r['raw_delta_seconds']['end']) for r in combined if r['raw_delta_seconds']['end'] is not None]
    summary = dict(total=43, nemo_automatic=sum(r['start'] is not None for r in nemo),
        nemo_null=sum(r['start'] is None for r in nemo),
        whisperx_with_timing=sum(r['start'] is not None for r in whisper),
        whisperx_flagged=sum(bool(r['issues']) for r in whisper),
        large_difference_rows=sum(r['large_difference'] for r in combined),
        raw_end_absolute_difference_median=statistics.median(differences),
        raw_end_absolute_difference_max=max(differences), human_verified=0,
        warning='Automatic gates and inter-model differences are not accuracy. Every rejected row is included.',
        all_wiki_ids_preserved=True, all_nemo_null_rows_included=True)
    (P/'comparison.json').write_text(json.dumps(dict(summary=summary, run=run, rows=combined), ensure_ascii=False, indent=2), encoding='utf-8')
    payload = json.dumps(dict(summary=summary, rows=combined), ensure_ascii=False).replace('<', '\\u003c')
    page = TEMPLATE.replace('__DATA__', payload)
    (P/'review.html').write_text(page, encoding='utf-8')
    table = '\n'.join(f"| {r['source_record']} | {r['text']} | {r['nemo']['nfa_candidate']['start']:.3f}–{r['nemo']['nfa_candidate']['end']:.3f} | {'null' if r['nemo']['start'] is None else str(r['nemo']['start'])+'–'+str(r['nemo']['end'])} | {r['whisperx']['start']}–{r['whisperx']['end']} | {'; '.join(r['nemo']['rejection_reasons']) or r['nemo']['status']} | {'; '.join(r['whisperx']['issues']) or '自动候选，未听验'} |" for r in combined)
    report = f'''# S01E01 · NeMo / WhisperX 全量对比

43 句全部保留。NeMo 自动保留 {summary['nemo_automatic']}，null {summary['nemo_null']}；WhisperX 有时间 {summary['whisperx_with_timing']}，规则提示 {summary['whisperx_flagged']}。人工听验 0，不能据此认定哪一方准确率更好。

两边原始起点或终点相差超过 250 ms 的有 {summary['large_difference_rows']} 句。原始终点绝对差中位数 {statistics.median(differences):.3f} s，最大 {max(differences):.3f} s。这是差异统计，不是误差率。

## 方法与限制

- 同一份 Wiki 43 句、同一份原音频（SHA256 在 run.json）；NeMo 使用已有结果，完整快照保存在 nemo_snapshot，不覆盖旧结果。
- 本次重新运行 faster-whisper large-v3，CPU int8、beam=5、4 线程，使用原生单词时间作为独立定位锚点；不使用旧 ASR 或 NeMo 时间。
- 本机 TorchAudio 和 ONNX Runtime DLL 无法加载，因此这次不是 WhisperX 默认 VAD 批处理流程：ASR 使用其 faster-whisper 后端的 native transcribe，关闭 VAD；已完整保存转写，包括 Wiki 未收录的片头/片尾。
- 用大小写/标点归一化的全文顺序匹配将 Wiki 定位到本次 ASR 单词，窗口各扩 0.8 s；覆盖不足 70% 明示为待检查，无锚点则保留 null。输入、锚点和窗口逐句保存在 whisperx_wiki.json。
- 对窗口内的 Wiki **原文**重新调用已安装 WhisperX 3.8.6 的原始 align()；默认英文 WAV2VEC2_ASR_BASE_960H，模型按官方 TorchAudio 纯 Python 结构加载缓存权重；未改写对齐算法。
- interpolate_method=ignore，无补造单词时间；任何失败、缺词、异常长词均保留。评分为模型内部值，不是正确概率。
- NeMo 原始候选对比 WhisperX 原始候选；另列 NeMo 词尾复核后的正式 nullable 时间及带余量播放，避免混淆。Wiki 的 Haha/Ho-Ho 保留；WhisperX 另提供去前缀语词起点供试听。
- 两边定位方法不同；NeMo 的词尾复核还使用了相同 wav2vec2 权重，因此复核结果也不是独立真值。优劣需要用人工标注边界/逐句试听判定，当前未作人工通过结论。

本次 ASR 耗时 {run['asr_seconds']:.2f} s；Wiki 对齐（含模型加载）{run['alignment_seconds']:.2f} s。NeMo 历史耗时见快照，不作为同一次硬件基准。

## 全部句子（含失败）

| Wiki 记录 | 台词 | NeMo 原始 | NeMo 复核后 | WhisperX 原始 | NeMo 状态/原因 | WhisperX 提示 |
|---|---|---|---|---|---|---|
{table}
'''
    (P/'REPORT.md').write_text(report, encoding='utf-8')
    (P/'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


TEMPLATE = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>S01E01 · NeMo / WhisperX 全量试听</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f7;color:#18232e;font:15px/1.65 system-ui,sans-serif}main{max-width:1240px;margin:auto;padding:26px 24px}h1{font-size:28px;margin:0}p{margin:8px 0}.lead{max-width:1000px;color:#485766}.stats{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}.stat{background:white;border:1px solid #dce2e8;border-radius:10px;padding:12px 20px}.stat strong{font-size:26px;display:block}.toolbar{position:sticky;top:0;background:#f3f5f7f5;padding:12px 0;z-index:3;border-bottom:1px solid #cad3dc}button,select{font:inherit;border:1px solid #bdc9d4;border-radius:6px;padding:7px 10px;background:white;cursor:pointer;margin:3px}button:hover{background:#e5f0ff}button:disabled{opacity:.4;cursor:default}#status{margin-left:12px;color:#355b81}article{background:white;border:1px solid #d9e0e7;border-radius:10px;margin:18px 0;overflow:hidden}article>header{padding:14px 18px;border-bottom:1px solid #d9e0e7}article h2{font-size:17px;margin:0}.id{font:12px monospace;color:#66798a}.columns{display:grid;grid-template-columns:1fr 1fr}.col{padding:16px 18px;min-width:0}.col+.col{border-left:1px solid #d9e0e7}.engine{font-weight:700;font-size:17px}.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;background:#fff1cc;color:#755400;margin-left:8px}.bad{background:#ffe0e0;color:#9e2525}.time{font:20px/1.6 ui-monospace,monospace;margin:9px 0}.reason{color:#9b3333;overflow-wrap:anywhere}.note{font-size:13px;color:#617284}.diff{padding:8px 18px;background:#f1f5f9;font-size:13px}details{margin-top:12px}pre{max-height:380px;overflow:auto;white-space:pre-wrap;font:12px/1.5 monospace}table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid #e3e8ed;text-align:left;padding:4px}a{color:#225c99}.warning{padding:12px 16px;background:#fff4db;border-radius:8px}input{font:inherit;padding:8px;border:1px solid #bdc9d4;border-radius:6px;width:240px}audio{width:100%;height:35px}#empty{display:none}@media(max-width:750px){main{padding:18px 12px}.columns{grid-template-columns:1fr}.col+.col{border-left:0;border-top:1px solid #d9e0e7}h1{font-size:23px}.toolbar{position:relative}.stat{padding:8px 12px}}</style></head><body><main>
<h1>S01E01 · NeMo / WhisperX 全量对比</h1><p class="lead">同一音频 · 同一 Wiki 台词 · 43 句完整展示 · 默认包含所有失败候选</p>
<p class="warning">人工听验 0。自动保留、分数较高、两边时间接近，都不能当作准确。红色标记的 NeMo 仍可播放原始切点。原始播放无额外余量，可直接检查截头、截尾和夹入笑声。</p>
<div id="stats" class="stats"></div><details><summary>本次运行方法与限制（与默认 WhisperX 流程的差别）</summary><p>重新运行 faster-whisper large-v3 native transcribe（CPU int8，beam 5，4 线程）；本机 ONNX Runtime DLL 不可用，关闭 VAD。用本次单词时间独立定位 Wiki，每侧加 0.8 秒窗口，再用 WhisperX 3.8.6 原始 align() 对齐 Wiki 原文。TorchAudio 原生 DLL 不可用，使用官方纯 Python 结构与同一缓存 WAV2VEC2_ASR_BASE_960H 权重。不使用 NeMo 时间或旧 ASR；不插值补时间。NeMo 使用已有结果，原始候选、复核后正式时间和播放余量分别显示。NeMo 词尾复核也用了 wav2vec2，不能当成独立真值。</p><a href="REPORT.md">完整方法与全量表</a> · <a href="comparison.json">全部 JSON</a> · <a href="asr.raw.json">本次完整 ASR（含 Wiki 外内容）</a> · <a href="run.json">参数、耗时、来源哈希</a></details>
<div class="toolbar"><select id="filter"><option value="all">全部 43 句（默认）</option><option value="null">NeMo null / 未保留</option><option value="diff">原始切点差异 &gt;250 ms</option><option value="xissue">WhisperX 有提示</option></select><input id="search" placeholder="搜索台词或 Wiki 记录号"><button id="stop">停止</button><span id="status">选择任一原始候选试听</span><p class="note">上下文按钮覆盖两边候选范围并各扩 1 秒；原始候选可能很糟，仍完整保留。完整音轨可在下方自由拖动。</p><audio id="fallback" controls src="source_audio.wav" preload="metadata"></audio></div>
<div id="rows"></div><p id="empty">没有匹配句子。</p></main>
<script>const DATA=__DATA__;const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const t=(s,e)=>s==null||e==null?'null':`${s.toFixed(3)} – ${e.toFixed(3)} s`;const btn=(label,s,e)=>`<button ${s==null||e==null||e<=s?'disabled':''} onclick="playClip(${s},${e},'${label}')">${label}</button>`;
let ctx,buffer,node,timer;async function playClip(s,e,label){stop();$('#status').textContent='正在加载音频…';try{ctx=ctx||new AudioContext();await ctx.resume();buffer=buffer||await ctx.decodeAudioData(await(await fetch('source_audio.wav')).arrayBuffer());stop();node=ctx.createBufferSource();node.buffer=buffer;node.connect(ctx.destination);const end=Math.min(e,buffer.duration);node.start(0,Math.max(0,s),end-Math.max(0,s));$('#status').textContent=`${label} · ${t(s,end)}`;}catch(err){const a=$('#fallback');a.currentTime=s;await a.play();timer=setInterval(()=>{if(a.currentTime>=e)stop()},15);$('#status').textContent=`兼容播放 · ${t(s,e)}`}}function stop(){if(node){try{node.stop()}catch{}node=null}clearInterval(timer);$('#fallback').pause()}$('#stop').onclick=stop;
const stats=DATA.summary;$('#stats').innerHTML=[['全部 Wiki 句子',stats.total],['NeMo 自动保留 / null',`${stats.nemo_automatic} / ${stats.nemo_null}`],['WhisperX 有时间 / 提示',`${stats.whisperx_with_timing} / ${stats.whisperx_flagged}`],['切点差异 >250 ms',stats.large_difference_rows],['人工听验',0]].map(([s,n])=>`<div class="stat"><strong>${n}</strong>${s}</div>`).join('');
function words(ws){return '<table><tr><th>词</th><th>起点</th><th>终点</th><th>分数</th></tr>'+ws.map(w=>`<tr><td>${esc(w.word||w.text)}</td><td>${w.start??'null'}</td><td>${w.end??'null'}</td><td>${w.score??'—'}</td></tr>`).join('')+'</table>'}
function render(){const filter=$('#filter').value,q=$('#search').value.toLowerCase();const rows=DATA.rows.filter(r=>(filter==='all'||filter==='null'&&r.nemo.start==null||filter==='diff'&&r.large_difference||filter==='xissue'&&r.whisperx.issues.length)&&(!q||r.text.toLowerCase().includes(q)||String(r.source_record).includes(q)));$('#rows').innerHTML=rows.map(r=>{const n=r.nemo,x=r.whisperx,c=n.nfa_candidate,p=n.playback||{},valid=[c.start,c.end,x.start,x.end].filter(v=>v!=null),lo=Math.max(0,Math.min(...valid)-1),hi=Math.max(...valid)+1;return `<article id="record-${r.source_record}"><header><h2>#${r.source_record} · ${esc(r.text)}</h2><div class="id">${esc((r.speakers||[]).join(', '))} · ${esc(r.id)}</div></header><div class="columns"><div class="col"><div class="engine">NeMo <span class="badge ${n.start==null?'bad':''}">${n.start==null?'null · 未保留':'自动候选 · 未听验'}</span></div><p class="note">原始 NFA 候选（全部保留）</p><div class="time">${t(c.start,c.end)}</div>${btn('NeMo 原始切点',c.start,c.end)}${btn('共同上下文',lo,hi)}<p>复核后正式时间：${t(n.start,n.end)}</p>${btn('NeMo 复核后＋原有余量',p.start,p.end)}<p class="reason">${esc(n.rejection_reasons.join('; ')||(n.start==null?'词尾复核证据不足':''))}</p><details><summary>NeMo 逐词时间与完整拒绝证据</summary>${words(n.words)}<pre>${esc(JSON.stringify({status:n.status,tail_check:n.tail_check,rejection_reasons:n.rejection_reasons,playback:n.playback},null,2))}</pre></details></div><div class="col"><div class="engine">WhisperX <span class="badge ${x.issues.length?'bad':''}">${x.issues.length?'有提示 · 未听验':'自动候选 · 未听验'}</span></div><p class="note">Wiki 原文重新对齐（无播放余量）</p><div class="time">${t(x.start,x.end)}</div>${btn('WhisperX 原始切点',x.start,x.end)}${btn('共同上下文',lo,hi)}${x.lexical_start!=null&&x.lexical_start!==x.start?btn('WhisperX 去笑声前缀',x.lexical_start,x.end):''}<p>独立 ASR 锚点：${x.matched_tokens}/${x.total_tokens} 词（${(100*x.anchor_coverage).toFixed(0)}%）</p><p class="reason">${esc(x.issues.join('; '))}</p><details><summary>WhisperX 逐词时间与完整证据</summary>${words(x.words)}<pre>${esc(JSON.stringify({window:x.window,issues:x.issues,anchor_words:x.anchor_words},null,2))}</pre></details></div></div><div class="diff">WhisperX − NeMo 原始：起点 ${r.raw_delta_seconds.start??'null'} s / 终点 ${r.raw_delta_seconds.end??'null'} s ${r.large_difference?' · 差异超过 250 ms':''} · 差异不代表哪一方正确</div></article>`}).join('');$('#empty').style.display=rows.length?'none':'block'}$('#filter').onchange=render;$('#search').oninput=render;render();</script></body></html>'''


if __name__ == '__main__':
    main()
