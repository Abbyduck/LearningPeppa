"""Render unmodified WhisperX output as clickable words; no transcript matching."""
import base64
import hashlib
import html
import json
from pathlib import Path


def build(folder):
    folder = Path(folder)
    original_path = folder/'S101 Muddy Puddles.json'
    result = json.loads(original_path.read_text(encoding='utf-8'))
    asr = json.loads((folder/'asr.raw.json').read_text(encoding='utf-8'))
    run = json.loads((folder/'run.json').read_text(encoding='utf-8'))
    assert run['status'] == 'completed' and run['external_transcript_used'] is False
    escape = html.escape
    cards, words_flat = [], []
    def time_label(s,e):
        return '缺少词时间' if s is None or e is None else f'{s:.3f}–{e:.3f} s'
    def button(label,s,e,extra=''):
        valid = isinstance(s,(int,float)) and isinstance(e,(int,float)) and 0<=s<e
        attrs = f'data-start="{s}" data-end="{e}"' if valid else 'disabled'
        return f'<button {attrs} {extra}>{escape(label)}</button>'
    missing = 0
    for si, segment in enumerate(result['segments']):
        buttons=[]
        for wi, word in enumerate(segment.get('words',[])):
            index=len(words_flat)
            words_flat.append(word)
            start,end=word.get('start'),word.get('end')
            if start is None or end is None or end<=start:
                missing+=1
            tip=f"#{index+1} · {time_label(start,end)} · score={word.get('score','无')} · {word.get('speaker','无说话人')}"
            buttons.append(button(word['word'],start,end,
                f'class="word" data-index="{index}" title="{escape(tip,quote=True)}"'))
        start,end=segment.get('start'),segment.get('end')
        controls=button('播放原始句段',start,end)
        if start is not None and end is not None:
            controls+=button('前后各 1 秒',max(0,start-1),end+1)
        raw=escape(json.dumps(segment,ensure_ascii=False,indent=2))
        cards.append(f'''<article id="segment-{si+1}" data-text="{escape(segment['text'].lower(),quote=True)}">
<div class="line"><b>#{si+1}</b><span>{time_label(start,end)}</span><span>{escape(segment.get('speaker','未分配说话人'))}</span></div>
<p class="transcript">{escape(segment['text'])}</p><div class="controls">{controls}</div>
<div class="words">{''.join(buttons)}</div><details><summary>原始 JSON</summary><pre>{raw}</pre></details></article>''')
    chunks=[]
    for i,segment in enumerate(asr['segments']):
        chunks.append(f"<section><b>ASR 大段 #{i+1} · {time_label(segment['start'],segment['end'])}</b>"
            +button('播放此大段',segment['start'],segment['end'])
            +f"<p>{escape(segment['text'])}</p></section>")
    audio='data:audio/wav;base64,'+base64.b64encode((folder/'source_audio.wav').read_bytes()).decode('ascii')
    metadata=dict(segments=len(result['segments']),words=len(words_flat),missing_or_invalid_word_times=missing,
        original_json_sha256=hashlib.sha256(original_path.read_bytes()).hexdigest(),
        external_transcript_used=False,word_timestamps_modified=False,default_playback_padding_seconds=0,
        original_word_sequence_preserved=True)
    payload=json.dumps(words_flat,ensure_ascii=False).replace('<','\\u003c')
    page=TEMPLATE.replace('__WORDS__',payload).replace('__AUDIO__',json.dumps(audio))
    page=page.replace('__CARDS__',''.join(cards)).replace('__CHUNKS__',''.join(chunks))
    page=page.replace('__COUNT__',str(len(result['segments']))).replace('__WORDCOUNT__',str(len(words_flat)))
    page=page.replace('__MISSING__',str(missing)).replace('__SECONDS__',f"{run['wall_seconds']:.2f}")
    (folder/'review.html').write_text(page,encoding='utf-8')
    (folder/'review_verification.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(metadata,ensure_ascii=False,indent=2))
    print('Review: '+str((folder/'review.html').resolve()))


TEMPLATE='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>S01E01 · WhisperX 原始逐词试听</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f5f8;color:#172b3d;font:16px/1.65 system-ui,sans-serif}main{max-width:1120px;margin:auto;padding:24px}h1{font-size:28px;margin:0}p{margin:8px 0}.muted{color:#5a6b7d;font-size:14px}.stats{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}.stats span{background:#fff;border:1px solid #d8e0e8;padding:8px 14px;border-radius:7px}.player{position:sticky;top:0;background:#edf3f9f7;border:1px solid #c7d5e2;border-radius:8px;padding:12px;z-index:2}audio{width:100%;height:36px}button,input{font:inherit;border:1px solid #bdcddd;background:white;border-radius:6px;padding:7px 12px;margin:3px;cursor:pointer}button:hover{background:#e4efff}button:disabled{color:#8996a4;background:#eee;cursor:default}.word{padding:8px 12px;min-width:44px}.word.active{background:#175ab4;color:white;border-color:#175ab4}.words{display:flex;flex-wrap:wrap;gap:3px;margin:15px 0}.line{display:flex;gap:16px;flex-wrap:wrap;color:#61758a;font-size:14px}.line b{color:#1c3c5e}article,section{background:white;border:1px solid #d8e2eb;border-radius:8px;margin:16px 0;padding:18px}article{scroll-margin-top:230px}.transcript{font-size:19px}.controls button{font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 monospace;max-height:350px;overflow:auto}a{color:#235ca0}#selection{font-family:ui-monospace,monospace;font-size:14px;min-height:25px}#status{font-size:14px;color:#365d85}#search{width:260px;max-width:100%;cursor:text}.notice{padding:10px 14px;background:#fff3d9;border-radius:7px}.chunkbox{margin:18px 0}summary{cursor:pointer}#empty{display:none}@media(max-width:700px){main{padding:14px}h1{font-size:23px}article{padding:12px}.player{position:relative}.word{padding:9px}}
</style></head><body><main>
<h1>S01E01 · WhisperX 原始逐词试听</h1>
<p class="muted">全新运行 · large-v3 · CUDA float16 · batch 4 · pyannote VAD + community-1 说话人分离</p>
<div class="stats"><span>原始句段 __COUNT__</span><span>原始词 __WORDCOUNT__</span><span>缺失／无效词时间 __MISSING__</span><span>模型流程 __SECONDS__ 秒</span></div>
<p class="notice">点击任意词，只播放该词原始起止时间之间的声音，默认余量为 0。原始输出可能有错词、错位或缺失时间，均照原样展示。句段按 WhisperX 输出顺序排列。</p>
<p><a href="S101%20Muddy%20Puddles.json">最终原始 JSON</a> · <a href="asr.raw.json">ASR 原始大段</a> · <a href="aligned.raw.json">原始对齐结果</a> · <a href="run.json">本次参数与耗时</a></p>
<div class="player"><audio id="audio" controls preload="metadata"></audio><div><button id="stop">停止</button><button id="prev" disabled>上一词</button><button id="repeat" disabled>重播该词</button><button id="next" disabled>下一词</button></div><div id="selection">点击下方任意词</div><div id="status">音频已内嵌，直接打开此 HTML 即可试听。</div></div>
<p><input id="search" placeholder="筛选原始识别文本"><button id="clear">清空筛选</button><span id="visible" class="muted"></span></p>
<details class="chunkbox"><summary>查看并播放 ASR 原始大段（尚未词级对齐）</summary>__CHUNKS__</details>
<div id="segments">__CARDS__</div><p id="empty">没有匹配句段。</p>
</main><script>
const WORDS=__WORDS__, AUDIO_URL=__AUDIO__;
const audio=document.getElementById('audio'),status=document.getElementById('status'),selection=document.getElementById('selection');audio.src=AUDIO_URL;
let ctx,buffer,source,selected=-1,generation=0;
function stop(){generation++;if(source){try{source.stop()}catch{}source=null}audio.pause()}
async function play(s,e,label){stop();const ticket=generation;status.textContent='加载音频…';try{ctx=ctx||new AudioContext();await ctx.resume();if(!buffer)buffer=await ctx.decodeAudioData(await(await fetch(AUDIO_URL)).arrayBuffer());if(ticket!==generation)return;source=ctx.createBufferSource();source.buffer=buffer;source.connect(ctx.destination);const a=Math.max(0,s),b=Math.min(e,buffer.duration);if(b<=a)throw Error('原始时间范围无效');source.start(0,a,b-a);status.textContent=`${label} · ${s.toFixed(3)}–${e.toFixed(3)} s · 播放余量 0`;source.onended=()=>{if(ticket===generation)status.textContent=`播放结束 · ${s.toFixed(3)}–${e.toFixed(3)} s`}}catch(error){status.textContent='播放失败：'+error.message}}
function choose(index){if(index<0||index>=WORDS.length)return;selected=index;const w=WORDS[index];document.querySelectorAll('.word.active').forEach(b=>b.classList.remove('active'));const button=document.querySelector(`.word[data-index="${index}"]`);if(button)button.classList.add('active');selection.textContent=`词 #${index+1} · ${w.word} · ${w.start??'null'}–${w.end??'null'} s · score=${w.score??'无'} · ${w.speaker??'未分配说话人'}`;document.getElementById('prev').disabled=index===0;document.getElementById('next').disabled=index===WORDS.length-1;document.getElementById('repeat').disabled=w.start==null||w.end==null||w.end<=w.start;if(w.start!=null&&w.end>w.start)play(w.start,w.end,w.word);else{stop();status.textContent='原始输出没有有效的词时间，未补造时间。'}}
document.addEventListener('click',event=>{const b=event.target.closest('button[data-start]');if(!b)return;if(b.dataset.index!==undefined)choose(Number(b.dataset.index));else play(Number(b.dataset.start),Number(b.dataset.end),b.textContent)});
document.getElementById('stop').onclick=()=>{stop();status.textContent='已停止'};document.getElementById('prev').onclick=()=>choose(selected-1);document.getElementById('next').onclick=()=>choose(selected+1);document.getElementById('repeat').onclick=()=>choose(selected);audio.addEventListener('play',()=>{generation++;if(source){try{source.stop()}catch{}source=null}status.textContent='正在播放完整音轨'});
function filter(){const q=document.getElementById('search').value.toLowerCase();let count=0;document.querySelectorAll('#segments article').forEach(a=>{const show=!q||a.dataset.text.includes(q);a.hidden=!show;if(show)count++});document.getElementById('visible').textContent=`显示 ${count} / __COUNT__ 个句段`;document.getElementById('empty').style.display=count?'none':'block'}document.getElementById('search').oninput=filter;document.getElementById('clear').onclick=()=>{document.getElementById('search').value='';filter()};filter();
</script></body></html>'''
