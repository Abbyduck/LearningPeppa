"""Freeze the successful B experiment from source, then run that locked pipeline."""
import argparse
import ast
import dataclasses
import gc
import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import sys
import time
import traceback
import wave

ROOT=Path(__file__).resolve().parent
CONFIG=ROOT/'configs/whisperx_b12.fixed.json'
LOCK=CONFIG.with_suffix('.sha256')
CACHE=ROOT/'output/whisperx_models/hub'
B_RUN=ROOT/'output/local_timing_254_278/run.json'
B_SCRIPT=ROOT/'run_local_timing_experiment.py'
BASE_SCRIPT=ROOT/'run_whisperx_native.py'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def write(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def setup():
    os.environ['HF_HUB_CACHE']=str(CACHE)
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['PATH']='E:/Coding/videoEditing/.ffmpeg/Library/bin'+os.pathsep+str(Path(sys.prefix)/'Lib/site-packages/torch/lib')+os.pathsep+os.environ['PATH']


def source_call(path,method):
    calls=[n for n in ast.walk(ast.parse(path.read_text(encoding='utf-8'))) if isinstance(n,ast.Call)
        and isinstance(n.func,ast.Attribute) and n.func.attr==method]
    if method=='transcribe':calls=[c for c in calls if any(k.arg=='chunk_size' for k in c.keywords)]
    assert len(calls)==1,(method,len(calls))
    call=calls[0]
    values={}
    for k in call.keywords:
        try:values[k.arg]=ast.literal_eval(k.value)
        except ValueError:
            if k.arg in ['download_root','cache_dir']:values[k.arg]=str(CACHE)
            elif k.arg=='token':values[k.arg]=None
            else:raise
    return ([] if method=='transcribe' else [ast.literal_eval(v) for v in call.args]),values


def freeze():
    if CONFIG.exists() or LOCK.exists():raise RuntimeError('Fixed configuration already exists; never overwrite it implicitly.')
    import torch
    import numpy as np
    import whisperx
    from whisperx.vads.pyannote import Pyannote
    from whisperx.alignment import DEFAULT_ALIGN_MODELS_TORCH
    from whisperx.diarize import DiarizationPipeline,assign_word_speakers
    b=json.loads(B_RUN.read_text(encoding='utf-8'))
    assert b['status']=='completed' and b['parameters']['B']['chunk_size']==12
    load_args,load_kw=source_call(B_SCRIPT,'load_model')
    _,trans_kw=source_call(B_SCRIPT,'transcribe')
    _,align_load=source_call(B_SCRIPT,'load_align_model')
    diarize_kw={}
    # This constructor is a direct name in the original script, not an attribute.
    tree=ast.parse(BASE_SCRIPT.read_text(encoding='utf-8'))
    constructor=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='DiarizationPipeline')
    for k in constructor.keywords:
        if k.arg=='token':diarize_kw[k.arg]=None
        elif k.arg=='cache_dir':diarize_kw[k.arg]=str(CACHE)
        else:diarize_kw[k.arg]=ast.literal_eval(k.value)
    assert load_kw['asr_options']['beam_size']==b['parameters']['B']['beam_size']
    print('Resolving exact B defaults from the same installed implementation',flush=True)
    model=whisperx.load_model(*load_args,**load_kw)
    effective=dataclasses.asdict(model.options)
    effective['suppress_numerals']=model.suppress_numerals
    vad_effective=dict(model._vad_params)
    # Pin omitted signature defaults as well as the explicitly passed arguments.
    import whisperx.asr as asr_module
    bound=inspect.signature(asr_module.load_model).bind(*load_args,**load_kw);bound.apply_defaults()
    resolved=dict(bound.arguments);resolved.pop('whisper_arch');resolved.pop('device')
    resolved['asr_options']=effective
    resolved['vad_options']=vad_effective
    trans_defaults=inspect.signature(model.transcribe).bind(None,**trans_kw);trans_defaults.apply_defaults()
    trans_resolved={k:v for k,v in trans_defaults.arguments.items() if k not in ['audio','progress_callback']}
    checkpoint=Path(torch.hub.get_dir())/'checkpoints/wav2vec2_fairseq_base_ls960_asr_ls960.pth'
    snapshot=next((CACHE/'models--Systran--faster-whisper-large-v3/snapshots').iterdir())
    diar_snapshot=next((CACHE/'models--pyannote--speaker-diarization-community-1/snapshots').iterdir())
    weights=[snapshot/'model.bin',checkpoint,*diar_snapshot.rglob('*.bin'),*diar_snapshot.rglob('*.npz'),diar_snapshot/'config.yaml']
    vad_path=Path(asr_module.__file__).parent/'assets/pytorch_model.bin'
    weights.append(vad_path)
    import whisperx.alignment as am
    import whisperx.vads.pyannote as vm
    config=dict(name='successful_local_B12_v1',source_experiment=str(B_RUN.relative_to(ROOT)),
        source_experiment_sha256=sha(B_RUN),source_runner_sha256=sha(B_SCRIPT),
        source_diarization_runner_sha256=sha(BASE_SCRIPT),source_explicit_load_args=load_args,
        source_explicit_load_kwargs=load_kw,source_explicit_transcribe_kwargs=trans_kw,
        model=load_args[0],device=load_args[1],load_model=resolved,transcribe=trans_resolved,
        alignment=dict(load_model={**align_load,'model_name':DEFAULT_ALIGN_MODELS_TORCH['en']},
            align=dict(device='cuda',interpolate_method='ignore',return_char_alignments=False,print_progress=False,combined_progress=False)),
        diarization=dict(load=diarize_kw,run=dict(num_speakers=None,min_speakers=None,max_speakers=None,return_embeddings=False),
            assign=dict(fill_nearest=inspect.signature(assign_word_speakers).parameters['fill_nearest'].default)),
        runtime=dict(torch_num_threads=torch.get_num_threads(),torch_num_interop_threads=torch.get_num_interop_threads(),
            gpu=torch.cuda.get_device_name(0),python=sys.version.split()[0]),
        versions={p:importlib.metadata.version(p) for p in ['whisperx','faster-whisper','ctranslate2','torch','torchaudio','torchvision','pyannote.audio','numpy','transformers','huggingface-hub']},
        source_modules_sha256={str(Path(p).resolve()):sha(p) for p in [asr_module.__file__,am.__file__,vm.__file__]},
        weights_sha256={str(p.resolve()):sha(p) for p in weights},
        provenance_note='Explicit B arguments extracted from saved experiment source; omitted defaults resolved from the same pinned installed implementation. B reused prior diarization, whose original constructor defaults are pinned here.',
        validation_gate='S01E01 complete listening validation before running further episodes. No automatic score is a listening verdict.')
    CONFIG.parent.mkdir(exist_ok=True)
    write(CONFIG,config);LOCK.write_text(sha(CONFIG)+'\n',encoding='ascii')
    print('Fixed config:',CONFIG,'SHA256:',sha(CONFIG),flush=True)
    del model;gc.collect();torch.cuda.empty_cache()


def run_episode():
    import torch
    import numpy as np
    import whisperx
    from whisperx.diarize import DiarizationPipeline
    assert sha(CONFIG)==LOCK.read_text(encoding='ascii').strip(),'Fixed config checksum mismatch'
    cfg=json.loads(CONFIG.read_text(encoding='utf-8'))
    for package,version in cfg['versions'].items():assert importlib.metadata.version(package)==version,(package,'version drift')
    for path,digest in cfg['source_modules_sha256'].items():assert sha(path)==digest,(path,'source drift')
    for path,digest in cfg['weights_sha256'].items():assert sha(path)==digest,(path,'weight drift')
    torch.set_num_threads(cfg['runtime']['torch_num_threads'])
    torch.set_num_interop_threads(cfg['runtime']['torch_num_interop_threads'])
    base=json.loads((ROOT/'output/whisperx_s01e01_native/run.json').read_text(encoding='utf-8'))
    media=Path(base['media']);assert sha(media)==base['media_sha256']
    out=ROOT/'output/whisperx_b12/S01E01';out.mkdir(parents=True,exist_ok=True)
    if (out/'run.json').exists():raise RuntimeError('Output already exists; preserve prior run instead of overwriting.')
    os.environ['MPLCONFIGDIR']=str(out/'mpl')
    run=dict(status='running',episode='S01E01',config=str(CONFIG),config_sha256=sha(CONFIG),media=str(media),media_sha256=sha(media),
        wiki=str(ROOT/'output/wiki/season1/episodes/S01E01.json'),wiki_used_as_model_input=False,timings={},
        gpu=torch.cuda.get_device_name(0),parameters_from_locked_file=True,utc_started=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    write(out/'run.json',run);write(out/'config.snapshot.json',cfg)
    start=time.perf_counter()
    try:
        t=time.perf_counter();audio=whisperx.load_audio(str(media));run['timings']['audio_decode_seconds']=time.perf_counter()-t
        with wave.open(str(out/'source_audio.wav'),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(np.clip(audio*32768,-32768,32767).astype('<i2').tobytes())
        run['audio_seconds']=len(audio)/16000
        print('Running full episode from locked B12 config',flush=True)
        t=time.perf_counter();model=whisperx.load_model(cfg['model'],cfg['device'],**cfg['load_model']);run['timings']['asr_vad_model_load_seconds']=time.perf_counter()-t
        actual=dataclasses.asdict(model.options);expected=dict(cfg['load_model']['asr_options']);expected.pop('suppress_numerals')
        assert actual==expected,'Effective ASR options differ from fixed B configuration'
        write(out/'effective_asr_options.json',dict(asr_options=actual,vad_options=model._vad_params,transcribe=cfg['transcribe']))
        t=time.perf_counter();asr=model.transcribe(audio,**cfg['transcribe']);run['timings']['vad_and_transcription_seconds']=time.perf_counter()-t
        write(out/'asr.raw.json',asr)
        del model;gc.collect();torch.cuda.empty_cache()
        t=time.perf_counter();aligner,metadata=whisperx.load_align_model(**cfg['alignment']['load_model']);run['timings']['alignment_model_load_seconds']=time.perf_counter()-t
        t=time.perf_counter();aligned=whisperx.align(asr['segments'],aligner,metadata,audio,**cfg['alignment']['align']);run['timings']['alignment_seconds']=time.perf_counter()-t
        write(out/'aligned.raw.json',aligned)
        del aligner;gc.collect();torch.cuda.empty_cache()
        print('Running pinned pyannote community-1 diarization',flush=True)
        t=time.perf_counter();diarizer=DiarizationPipeline(**cfg['diarization']['load']);run['timings']['diarization_model_load_seconds']=time.perf_counter()-t
        t=time.perf_counter();diarized=diarizer(audio,**cfg['diarization']['run']);run['timings']['diarization_seconds']=time.perf_counter()-t
        write(out/'diarization.raw.json',diarized[['start','end','speaker']].to_dict(orient='records'))
        final=whisperx.assign_word_speakers(diarized,aligned,**cfg['diarization']['assign']);final['language']='en'
        write(out/'result.whisperx.json',final)
        run['status']='completed'
    except Exception:
        run['status']='failed';run['error']=traceback.format_exc();print(run['error'],flush=True)
    run['processing_wall_seconds']=time.perf_counter()-start
    write(out/'run.json',run)
    print(json.dumps(run,ensure_ascii=False,indent=2),flush=True)
    return 0 if run['status']=='completed' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--freeze-from-b',action='store_true');args=parser.parse_args()
    setup()
    if args.freeze_from_b:freeze()
    sys.exit(run_episode())
