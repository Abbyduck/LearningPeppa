"""Check season outputs without models, inference, or timestamp repair."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import wave
from run_fixed_b12 import CONFIG,LOCK,ROOT


def read(p):return json.loads(p.read_text(encoding='utf-8'))


class Buttons(HTMLParser):
    def __init__(self):super().__init__();self.cards=0;self.words=[]
    def handle_starttag(self,tag,attrs):
        data=dict(attrs)
        if tag=='article':self.cards+=1
        if tag=='button' and data.get('class')=='word':self.words.append(data)


def main():
    out=ROOT/'output/whisperx_b12';manifest=read(out/'season1_manifest.json')
    digest=hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    assert digest==LOCK.read_text().strip()==manifest['config_sha256']
    records=[];errors=[]
    for job in manifest['jobs']:
        try:
            p=out/job['episode'];run=read(p/'run.json');raw=read(p/'result.whisperx.json')
            assert run['status']=='completed' and run['config_sha256']==digest
            aligned=[w for s in read(p/'aligned.raw.json')['segments'] for w in s.get('words',[])]
            words=[w for s in raw['segments'] for w in s.get('words',[])]
            assert [(w.get('word'),w.get('start'),w.get('end')) for w in aligned]==[(w.get('word'),w.get('start'),w.get('end')) for w in words]
            wiki=[r for r in read(Path(job['wiki']))['entries'] if r['type']=='utterance'];rows=read(p/'utterances.json')
            assert len(wiki)==len(rows)
            for old,new in zip(wiki,rows):
                assert all(new.get(k)==v for k,v in old.items()),old['id']
                assert len(new['words'])==len(new['raw_word_indices'])
                for index,w in zip(new['raw_word_indices'],new['words']):assert all(w.get(k)==v for k,v in words[index].items())
                ctx=new['playback_context'];assert 0<=ctx['start']<ctx['end']<=run['audio_seconds']+.001
            actual=read(p/'effective_asr_options.json');cfg=read(CONFIG);expected=dict(cfg['load_model']['asr_options']);expected.pop('suppress_numerals')
            assert actual['asr_options']==expected and actual['transcribe']==cfg['transcribe']
            with wave.open(str(p/'source_audio.wav'),'rb') as f:
                assert f.getframerate()==16000 and f.getnchannels()==1 and f.getsampwidth()==2
                frames=f.getnframes();assert len(f.readframes(frames))==frames*2
                assert abs(frames/16000-run['audio_seconds'])<.001
            parser=Buttons();parser.feed((p/'review.html').read_text(encoding='utf-8'))
            assert parser.cards==len(wiki)
            for b in parser.words:
                if 'data-start' in b:
                    w=words[int(b['data-index'])];assert float(b['data-start'])==w['start'] and float(b['data-end'])==w['end']
            records.append(dict(episode=job['episode'],wiki_utterances=len(rows),with_candidate=sum(r['candidate']['start'] is not None for r in rows),
                needs_review=sum(bool(r['anomaly_reasons']) for r in rows),raw_words=len(words),visible_word_buttons=len(parser.words),checks_passed=True))
        except Exception as error:errors.append(dict(episode=job['episode'],error=repr(error)))
    result=dict(config_sha256=digest,episodes_checked=len(records),errors=errors,
        wiki_utterances=sum(r['wiki_utterances'] for r in records),with_candidate=sum(r['with_candidate'] for r in records),
        needs_review=sum(r['needs_review'] for r in records),raw_words=sum(r['raw_words'] for r in records),
        raw_times_and_all_wiki_fields_preserved=not errors,human_listening_verified=False,episodes=records)
    (out/'season1_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='episodes'},ensure_ascii=False,indent=2))
    return int(bool(errors))


if __name__=='__main__':raise SystemExit(main())
