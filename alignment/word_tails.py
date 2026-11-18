"""Check reported NFA tails against fresh character CTC forced alignment; no ASR."""
import json
import os
from pathlib import Path
import time
import sys
import types
import importlib
import numpy as np
from alignment.ctc import ctc_states
os.environ['OMP_NUM_THREADS']='4'
os.environ['MPLCONFIGDIR']=str(Path(__file__).resolve().parents[1]/'output/forced_alignment/S01E01/mpl')
import torch
import soundfile as sf

P=Path(__file__).resolve().parents[1]/'output/forced_alignment/S01E01'
rows=json.loads((P/'utterances.json').read_text(encoding='utf-8'))
audio,sr=sf.read(str(P/'source_audio.wav'),dtype='float32')
torch.set_num_threads(4)
t=time.perf_counter()
# Load the official pure-PyTorch architecture; native TorchAudio DLL is unavailable.
package=types.ModuleType('local_wav2vec2')
package.__path__=[str(Path(sys.prefix)/'Lib/site-packages/torchaudio/models/wav2vec2')]
sys.modules[package.__name__]=package
factory=importlib.import_module('local_wav2vec2.model')
model=factory.wav2vec2_base(aux_num_out=29).eval()
state=torch.load(Path(torch.hub.get_dir())/'checkpoints/wav2vec2_fairseq_base_ls960_asr_ls960.pth',weights_only=True)
for key in ['aux.weight','aux.bias']:
    state[key]=torch.stack([v for i,v in enumerate(state[key]) if i not in [1,2,3]])
model.load_state_dict(state,strict=True)
labels=['-']+list('|ETAONIHSRDLUMWCFGYPBVK\'XJQZ')
vocab={c:i for i,c in enumerate(labels)}

results=[]
for index,r in enumerate(rows):
    if r.get('status')=='rejected_needs_review':continue
    start=max(0,r['nfa_candidate']['start']-.6)
    following=rows[index+1]['nfa_candidate']['start'] if index+1<len(rows) else len(audio)/sr
    end=min(r['nfa_candidate']['end']+1.2,following-.1,len(audio)/sr)
    a,b=round(start*sr),round(end*sr)
    prefix=len(r.get('excluded_laughter_prefix_words',[]))
    text='|'.join(w['text'].upper() for w in r['words'][prefix:])
    with torch.inference_mode():
        logits,_=model(torch.from_numpy(audio[a:b]).unsqueeze(0))
        probs=logits.log_softmax(-1)
    states=ctc_states(probs[0].numpy(),[vocab[c] for c in text])
    step=(b-a)/sr/probs.shape[1]
    chars=[]
    for i,c in enumerate(text):
        frames=np.flatnonzero(states==2*i+1)
        assert len(frames)>0
        chars.append(dict(char=c,start=round(start+frames[0]*step,4),end=round(start+(frames[-1]+1)*step,4),score=float(probs[0,frames,vocab[c]].exp().mean())))
    last=text.rfind('|')+1
    tail=chars[last:]
    result=dict(source_record=r['source_record'],text=r['text'],window=[start,end],nfa=r['nfa_candidate'],chars=chars,
                character_alignment_end=chars[-1]['end'],final_word=r['alignment_text'].split()[-1],
                last_word_mean_score=sum(c['score'] for c in tail)/len(tail),last_char_score=tail[-1]['score'],
                final_word_chars=tail)
    results.append(result)
    print(r['source_record'],result['character_alignment_end'],result['last_word_mean_score'],result['last_char_score'],flush=True)
(P/'word_tail_character_check.json').write_text(json.dumps(dict(engine='torchaudio/WAV2VEC2_ASR_BASE_960H',old_asr_used=False,wall_seconds=time.perf_counter()-t,results=results),ensure_ascii=False,indent=2),encoding='utf-8')
