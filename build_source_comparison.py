"""Display original WhisperX and Wiki-derived data side by side, without edits."""
import argparse
import base64
import hashlib
import html
import json
from pathlib import Path
import re
from alignment.native_word_review import TEMPLATE

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output/whisperx_b12'


def build(folder):
    folder=Path(folder);read=lambda name:json.loads((folder/name).read_text(encoding='utf-8'))
    sources=['asr.raw.json','aligned.raw.json','result.whisperx.json','utterances.json','source_audio.wav']
    before={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in sources}
    raw=read('result.whisperx.json');asr=read('asr.raw.json');wiki=read('utterances.json');episode=read('run.json')['episode']
    esc=html.escape;words=[];left=[];right=[];word_segment={}
    def interval(s,e):return 'null' if s is None or e is None else f'{s:.3f}–{e:.3f} s'
    def button(label,s,e,extra=''):
        valid=s is not None and e is not None and 0<=s<e
        return f'<button {f"data-start={s} data-end={e}" if valid else "disabled"} {extra}>{esc(label)}</button>'
    def json_detail(data):return '<details><summary>原始 JSON</summary><pre>'+esc(json.dumps(data,ensure_ascii=False,indent=2))+'</pre></details>'
    for si,segment in enumerate(raw['segments']):
        indices=[];buttons=[]
        for word in segment.get('words',[]):
            index=len(words);words.append(word);indices.append(index);word_segment[index]=si
            buttons.append(button(word['word'],word.get('start'),word.get('end'),f'class="word" data-index="{index}" title="原始词索引 {index}"'))
        s,e=segment.get('start'),segment.get('end')
        chunks=[(i,x) for i,x in enumerate(asr['segments']) if s is not None and x['start']<=s+.003 and x['end']>=e-.003]
        chunk_html=''.join(f'<details><summary>上一步 ASR 块 #{i+1} · {interval(x["start"],x["end"])}</summary><p>{esc(x["text"])}</p>{button("播放 ASR 整块",x["start"],x["end"])}{json_detail(x)}</details>' for i,x in chunks)
        left.append(f'''<article id="raw-{si}" data-start="{s if s is not None else -1}" data-end="{e if e is not None else -1}"><div class="line"><b>原始段 #{si+1}</b><span>{interval(s,e)}</span></div><p class="transcript">{esc(segment['text'])}</p>{button('播放原始段',s,e)}<p class="muted">原始词索引：{', '.join(map(str,indices))}</p><div class="words">{''.join(buttons)}</div>{chunk_html}{json_detail(segment)}</article>''')
    for row in wiki:
        c=row['candidate'];s,e=c['start'],c['end'];ctx=row['playback_context']
        indices=row['raw_word_indices'];source_segments=sorted({word_segment[i] for i in indices})
        buttons=''.join(button(words[i]['word'],words[i].get('start'),words[i].get('end'),f'class="word" data-index="{i}" title="原始词索引 {i}"') for i in indices)
        refs=''.join(f'<button class="locate" data-segment="{si}">定位左侧原始段 #{si+1}</button>' for si in source_segments)
        detail=dict(wiki_id=row['id'],candidate=c,start=row['start'],end=row['end'],raw_word_indices=indices,text_correspondence=row['text_correspondence'],anomaly_reasons=row['anomaly_reasons'])
        right.append(f'''<article id="wiki-{row['source_record']}" data-start="{s if s is not None else ctx['start']}" data-end="{e if e is not None else ctx['end']}"><div class="line"><b>Wiki #{row['source_record']}</b><span>{interval(s,e)}</span><span>{esc(', '.join(row.get('speakers',[])))}</span></div><p class="transcript">{esc(row['text'])}</p><p class="warning">{esc('; '.join(row['anomaly_reasons']) or '无机械提示；未听验')}</p>{button('播放合并后候选',s,e)}{button('播放上下文',ctx['start'],ctx['end'])}<p>对应的模型原文：{esc(row['recognized_text']) or '无'}</p><p class="muted">引用原始词索引：{', '.join(map(str,indices)) or '无'}</p>{refs}<div class="words">{buttons}</div>{json_detail(detail)}</article>''')
    audio='data:audio/wav;base64,'+base64.b64encode((folder/'source_audio.wav').read_bytes()).decode('ascii')
    player=TEMPLATE.split('<script>',1)[1].split('function filter()',1)[0]
    player=player.replace('__WORDS__',json.dumps(words,ensure_ascii=False).replace('<','\\u003c')).replace('__AUDIO__',json.dumps(audio))
    player=player.replace('const button=document.querySelector(`.word[data-index="${index}"]`);if(button)button.classList.add(\'active\');', 'document.querySelectorAll(`.word[data-index="${index}"]`).forEach(b=>b.classList.add(\'active\'));')
    style=TEMPLATE.split('<style>',1)[1].split('</style>',1)[0]
    default='focus' if episode=='S01E02' else 'all'
    filter_js='''
const mode=document.getElementById('mode');
function filter(){let counts=[];document.querySelectorAll('.pane').forEach(p=>{let count=0;p.querySelectorAll('article').forEach(a=>{let show=mode.value==='all'||Number(a.dataset.end)>41&&Number(a.dataset.start)<55;a.hidden=!show;if(show)count++});counts.push(count)});document.getElementById('counts').textContent=`当前显示：原始 ${counts[0]} 段 / Wiki ${counts[1]} 条`;}
mode.onchange=filter;filter();document.addEventListener('click',event=>{const b=event.target.closest('button.locate');if(!b)return;mode.value='all';filter();const a=document.getElementById('raw-'+b.dataset.segment);a.scrollIntoView({block:'center'});a.classList.add('highlight');setTimeout(()=>a.classList.remove('highlight'),1800)});
'''
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{episode} 原始 / Wiki 对照</title><style>{style}
main{{max-width:1600px}}.columns{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.pane{{height:68vh;overflow:auto;padding:0 5px 20px}}.pane article{{scroll-margin-top:10px}}h2{{font-size:20px}}.warning{{color:#9b3f26;font-size:14px}}article.highlight{{outline:3px solid #d08a00}}select{{font:inherit;padding:8px}}@media(max-width:850px){{.columns{{grid-template-columns:1fr}}.pane{{height:60vh}}}}</style><main>
<h1>{episode} · WhisperX 原始输出 / 合并 Wiki 后</h1><p class="notice">左右是两套独立的原始列表，没有为了排版重新对齐或修正时间。左侧时间已经过原 wav2vec2 对齐，但尚未合并 Wiki；展开左侧的 ASR 块，可以检查更早的转写结果。右侧保留现有 Wiki 对应，包括错误对应和异常。</p>
<p><a href="asr.raw.json">ASR 原始大段</a> · <a href="aligned.raw.json">原始词级对齐 JSON</a> · <a href="result.whisperx.json">含说话人的原始输出</a> · <a href="utterances.json">合并 Wiki 的 JSON</a> · <a href="review.html">原 Wiki 试听页</a></p>
<div class="player"><audio id="audio" controls preload="metadata"></audio><button id="stop">停止</button><button id="prev" disabled>上一词</button><button id="repeat" disabled>重播该词</button><button id="next" disabled>下一词</button><div id="selection">两侧引用同一原始词时，点击会同时高亮</div><div id="status">所有候选播放均为零余量；两侧共用同一原音频。</div></div>
<p><select id="mode"><option value="focus" {'selected' if default=='focus' else ''}>争议区间 41–55 秒</option><option value="all" {'selected' if default=='all' else ''}>显示整集全部数据</option></select> <span id="counts"></span></p>
<div class="columns"><div><h2>① WhisperX 原始输出 · {len(raw['segments'])} 段 / {len(words)} 词</h2><div class="pane" id="raw-pane">{''.join(left)}</div></div><div><h2>② 合并 Wiki 后 · {len(wiki)} 条发言</h2><div class="pane" id="wiki-pane">{''.join(right)}</div></div></div>
</main><script>{player}{filter_js}</script></html>'''
    (folder/'source_compare.html').write_text(page,encoding='utf-8')
    after={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in sources}
    assert before==after
    verification=dict(episode=episode,raw_segments=len(raw['segments']),raw_words=len(words),wiki_rows=len(wiki),source_sha256=before,
        source_files_unchanged=True,word_timestamps_modified=False,model_rerun=False)
    (folder/'source_compare.verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
    return verification


def update_index(root):
    path=root/'season1.html'
    if not path.exists():return
    page=path.read_text(encoding='utf-8')
    for folder in sorted(root.glob('S01E??')):
        if not (folder/'source_compare.html').exists():continue
        marker=f'<a href="{folder.name}/review.html">{folder.name}</a>'
        extra=f' <a href="{folder.name}/source_compare.html">原始 / Wiki 对照</a>'
        if extra not in page:page=page.replace(marker,marker+extra)
    path.write_text(page,encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--all',action='store_true');parser.add_argument('--episode',default='S01E02');args=parser.parse_args()
    folders=sorted(OUT.glob('S01E??')) if args.all else [OUT/args.episode]
    for folder in folders:
        if (folder/'utterances.json').exists():print(json.dumps(build(folder),ensure_ascii=False))
    update_index(OUT)
