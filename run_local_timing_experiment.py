"""S01E01 local A/B/C timing experiment. Never re-run A or diarization."""
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import traceback
import wave

ROOT=Path(__file__).resolve().parent
P=ROOT/'output/local_timing_254_278'
BASE=ROOT/'output/whisperx_s01e01_native'
CACHE=ROOT/'output/whisperx_models/hub'
OFFSET,STOP=253.0,279.0


def save(name,value):
    (P/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    P.mkdir(parents=True,exist_ok=True)
    os.environ['HF_HUB_CACHE']=str(CACHE)
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['MPLCONFIGDIR']=str(P/'mpl')
    os.environ['PATH']='E:/Coding/videoEditing/.ffmpeg/Library/bin'+os.pathsep+str(Path(sys.prefix)/'Lib/site-packages/torch/lib')+os.pathsep+os.environ['PATH']
    import torch
    import numpy as np
    import whisperx
    from whisperx.vads.pyannote import Pyannote,Binarize
    from faster_whisper import WhisperModel
    assert torch.cuda.is_available()
    with wave.open(str(BASE/'source_audio.wav'),'rb') as src:
        assert src.getframerate()==16000 and src.getnchannels()==1
        src.setpos(round(OFFSET*16000))
        pcm=src.readframes(round((STOP-OFFSET)*16000))
    with wave.open(str(P/'local_input_253_279.wav'),'wb') as dst:
        dst.setnchannels(1);dst.setsampwidth(2);dst.setframerate(16000);dst.writeframes(pcm)
    audio=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
    base_run=json.loads((BASE/'run.json').read_text(encoding='utf-8'))
    run=dict(status='running',input_window_absolute=[OFFSET,STOP],target_window=[254.017,278.047],
        local_audio_sha256=hashlib.sha256(pcm).hexdigest(),media=base_run['media'],media_sha256=base_run['media_sha256'],
        gpu=torch.cuda.get_device_name(0),device='cuda',compute_type='float16',model='large-v3',
        baseline_A='Reused native/aligned.raw.json; no inference',diarization='Reused native/diarization.raw.json; no inference',
        local_timestamp_policy='Raw B/C files use crop-relative seconds. Absolute times are derived by adding 253.0 only.',
        wiki_used_as_model_input=False,versions={p:importlib.metadata.version(p) for p in ['torch','whisperx','faster-whisper','pyannote.audio']},
        timings={},parameters=dict(B=dict(chunk_size=12,batch_size=4,language='en',beam_size=5,temperature=0,
            condition_on_previous_text=False,vad_method='pyannote',vad_onset=.5,vad_offset=.363,aligner='WAV2VEC2_ASR_BASE_960H',interpolate_method='ignore'),
            C=dict(language='en',beam_size=5,temperature=0,condition_on_previous_text=False,word_timestamps=True,vad_filter=False)))
    save('run.json',run)
    class CaptureVad(Pyannote):
        """Record exactly the existing VAD output, with no segmentation changes."""
        def __init__(self,original):
            self.original=original
            self.scores=None
        def __call__(self,*args,**kwargs):
            self.scores=self.original(*args,**kwargs)
            return self.scores
    started=time.perf_counter()
    try:
        print('B12: loading original WhisperX pipeline',flush=True)
        total=time.perf_counter();t=time.perf_counter()
        model=whisperx.load_model('large-v3','cuda',compute_type='float16',language='en',task='transcribe',
            download_root=str(CACHE),local_files_only=True,vad_method='pyannote',
            vad_options={'vad_onset':.50,'vad_offset':.363},
            asr_options={'beam_size':5,'temperatures':[0.0],'condition_on_previous_text':False})
        run['timings']['B12_model_and_vad_load_seconds']=time.perf_counter()-t
        capture=CaptureVad(model.vad_model);model.vad_model=capture
        t=time.perf_counter()
        asr=model.transcribe(audio,batch_size=4,language='en',task='transcribe',chunk_size=12,print_progress=True)
        run['timings']['B12_vad_and_asr_seconds']=time.perf_counter()-t
        save('B12.asr.raw.json',asr)
        np.savez_compressed(P/'B12.vad_scores.npz',data=capture.scores.data,
            frame_start=capture.scores.sliding_window.start,frame_step=capture.scores.sliding_window.step,
            frame_duration=capture.scores.sliding_window.duration)
        natural=Binarize(max_duration=float('inf'),onset=.5,offset=.363)(capture.scores)
        save('B12.vad_boundaries.json',dict(natural_activity_local=[[s.start,s.end] for s in natural.get_timeline()],
             merged_chunks_local=[dict(start=s['start'],end=s['end'],text=s['text']) for s in asr['segments']],
             policy='Official Pyannote.merge_chunks(chunk_size=12); no manually supplied cuts. Natural activity includes laughter.'))
        del capture,model
        gc.collect();torch.cuda.empty_cache()
        print('B12: original wav2vec2 alignment',flush=True)
        t=time.perf_counter()
        aligner,metadata=whisperx.load_align_model(language_code='en',device='cuda')
        run['timings']['B12_aligner_load_seconds']=time.perf_counter()-t
        t=time.perf_counter()
        aligned=whisperx.align(asr['segments'],aligner,metadata,audio,'cuda',interpolate_method='ignore')
        run['timings']['B12_alignment_seconds']=time.perf_counter()-t
        save('B12.aligned.raw.json',aligned)
        del aligner
        gc.collect();torch.cuda.empty_cache()
        run['timings']['B12_wall_seconds']=time.perf_counter()-total
        save('run.json',run)
        print('C: same large-v3, native word_timestamps, no wav2vec2 or VAD',flush=True)
        total=time.perf_counter();t=time.perf_counter()
        snapshot=next((CACHE/'models--Systran--faster-whisper-large-v3/snapshots').iterdir())
        model=WhisperModel(str(snapshot),device='cuda',compute_type='float16',cpu_threads=4,local_files_only=True)
        run['timings']['C_model_load_seconds']=time.perf_counter()-t
        t=time.perf_counter()
        stream,info=model.transcribe(audio,language='en',beam_size=5,temperature=0,
            condition_on_previous_text=False,word_timestamps=True,vad_filter=False)
        rows=[]
        from dataclasses import asdict
        for segment in stream:
            rows.append(asdict(segment))
            print('C',segment.start+OFFSET,segment.end+OFFSET,segment.text,flush=True)
        run['timings']['C_transcription_and_word_timing_seconds']=time.perf_counter()-t
        save('C.native.raw.json',dict(segments=rows,language=info.language))
        del model
        gc.collect();torch.cuda.empty_cache()
        run['timings']['C_wall_seconds']=time.perf_counter()-total
        run['status']='completed'
    except Exception:
        run['status']='failed';run['error']=traceback.format_exc();print(run['error'],flush=True)
    run['experiment_wall_seconds']=time.perf_counter()-started
    save('run.json',run)
    return 0 if run['status']=='completed' else 1


if __name__=='__main__':
    sys.exit(main())
