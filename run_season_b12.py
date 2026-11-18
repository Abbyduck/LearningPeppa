"""Resume a season batch using the unchanged, checksum-locked B12 configuration."""
import argparse
import dataclasses
import gc
import hashlib
import html
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
import wave
from run_fixed_b12 import CONFIG,LOCK,ROOT,setup,sha

RAW_FILES={'asr':'asr.raw.json','alignment':'aligned.raw.json','diarization':'diarization.raw.json','result':'result.whisperx.json'}
ACTIVE_OUTPUT=None


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,data):
    path=Path(path);tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');os.replace(tmp,path)


def media_episode(name):
    match=re.match(r'^S(\d{1,2})E(\d{1,2})(?:\D|$)',name,re.I)
    if match:return f'S{int(match[1]):02d}E{int(match[2]):02d}'
    match=re.match(r'^S(\d)(\d{2})(?:\D|$)',name,re.I)
    return f'S{int(match[1]):02d}E{int(match[2]):02d}' if match else None


def discover(wiki_dir,video_dir):
    videos={}
    for path in sorted(Path(video_dir).iterdir()):
        if path.is_file() and path.suffix.lower() in ['.mp4','.mkv','.mov','.avi']:
            episode=media_episode(path.stem)
            if episode:
                if episode in videos:raise ValueError(f'Duplicate media for {episode}: {videos[episode]} / {path}')
                videos[episode]=path.resolve()
    jobs=[];ids=set()
    for path in sorted(Path(wiki_dir).glob('S??E??.json')):
        data=read(path);episode=data['episode']['id']
        if episode!=path.stem or episode in ids:raise ValueError(f'Invalid/duplicate Wiki episode ID: {path}')
        ids.add(episode)
        if episode not in videos:raise ValueError(f'Missing media for {episode}')
        count=sum(r['type']=='utterance' for r in data['entries'])
        if not count:raise ValueError(f'No Wiki utterances in {path}')
        jobs.append(dict(episode=episode,title=data['episode']['title'],wiki=str(path.resolve()),media=str(videos[episode]),wiki_utterances=count))
    if not jobs:raise ValueError('No matching Wiki episodes found')
    unmatched=sorted(set(videos)-ids)
    if unmatched:raise ValueError(f'Media without Wiki: {unmatched}')
    return jobs


def check_reuse(out,job,digest):
    """Only reuse complete artifacts matching config, exact media and Wiki fields."""
    run=read(out/'run.json')
    if run['config_sha256']!=digest:raise ValueError('Existing output uses another fixed configuration')
    if run['media_sha256']!=sha(job['media']):raise ValueError('Existing output media content changed')
    if run.get('wiki_sha256') and run['wiki_sha256']!=sha(job['wiki']):raise ValueError('Existing output Wiki changed')
    for stage,filename in RAW_FILES.items():
        path=out/filename
        if path.exists():
            read(path)
            expected=run.get('artifact_sha256',{}).get(filename)
            if expected and sha(path)!=expected:raise ValueError(f'Existing artifact changed: {path}')
    if run['status']=='completed' and all((out/f).is_file() for f in [*RAW_FILES.values(),'source_audio.wav','utterances.json','verification.json','review.html']):
        original=[r for r in read(job['wiki'])['entries'] if r['type']=='utterance']
        actual=read(out/'utterances.json')
        if len(original)!=len(actual):raise ValueError('Existing Wiki row count changed')
        for old,new in zip(original,actual):
            if any(new.get(k)!=v for k,v in old.items()):raise ValueError('Existing Wiki text/roles/IDs differ')
        return run,True
    return run,False


def run(args):
    global ACTIVE_OUTPUT
    jobs=discover(args.wiki_dir,args.video_dir)
    digest=sha(CONFIG)
    if digest!=LOCK.read_text(encoding='ascii').strip():raise ValueError('Fixed configuration checksum mismatch')
    cfg=read(CONFIG);outroot=Path(args.output_dir).resolve();outroot.mkdir(parents=True,exist_ok=True)
    if args.episodes:
        requested=set(args.episodes.split(','));known={j['episode'] for j in jobs}
        if requested-known:raise ValueError(f'Unknown episodes: {requested-known}')
        jobs=[j for j in jobs if j['episode'] in requested]
    manifest=dict(wiki_dir=str(Path(args.wiki_dir).resolve()),video_dir=str(Path(args.video_dir).resolve()),
        config=str(CONFIG),config_sha256=digest,jobs=jobs,authorization='User approved B12 version and explicitly requested season 1 on 2026-11-18.')
    if args.dry_run:
        print(json.dumps(manifest,ensure_ascii=False,indent=2));return 0
    # An OS-held lock is automatically released on process exit; no stale PID guessing.
    import msvcrt
    lock=(outroot/'season1.batch.lock').open('a+b')
    lock.seek(0)
    if not lock.read(1):lock.write(b'1');lock.flush()
    lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:raise RuntimeError('Another season batch owns the output lock')
    ACTIVE_OUTPUT=outroot
    start=time.perf_counter()
    runner_digest=sha(__file__);snapshots=outroot/'runner_snapshots';snapshots.mkdir(exist_ok=True)
    snapshot=snapshots/(runner_digest+'.py');snapshot.write_bytes(Path(__file__).read_bytes())
    manifest.update(batch_runner_sha256=runner_digest,batch_runner_snapshot=str(snapshot))
    write(outroot/'season1_manifest.json',manifest)
    state=dict(status='running',phase='preflight',config_sha256=digest,started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        shared_model_load_seconds={},episodes=[],automatic_processing_is_not_human_verification=True)
    def publish():
        state['elapsed_wall_seconds']=time.perf_counter()-start
        state['counts']={s:sum(j['status']==s for j in state['episodes']) for s in ['pending','asr_complete','alignment_complete','diarization_complete','completed','reused','failed']}
        write(outroot/'season1_summary.json',state)
        rows=[]
        for job in state['episodes']:
            summary=job.get('verification',{})
            target=f"{job['episode']}/review.html"
            link=f'<a href="{target}">{job["episode"]}</a>' if job['status'] in ['completed','reused'] else job['episode']
            if job['status'] in ['completed','reused'] and (outroot/job['episode']/'source_compare.html').exists():
                link+=f' <a href="{job["episode"]}/source_compare.html">原始 / Wiki 对照</a>'
            rows.append(f'<tr><td>{link}</td><td>{html.escape(job["title"])}</td><td>{job["status"]}</td><td>{job["wiki_utterances"]}</td><td>{summary.get("rows_with_candidate","—")}</td><td>{summary.get("needs_review","—")}</td><td>{job.get("active_seconds","—")}</td><td>{html.escape(job.get("error",""))}</td></tr>')
        page='<!doctype html><meta charset="utf-8"><title>第一季 B12 批处理</title><style>body{font:15px/1.6 system-ui;max-width:1350px;margin:25px auto;padding:0 15px}table{border-collapse:collapse;width:100%}td,th{padding:7px;border:1px solid #ddd;text-align:left}a{color:#225d9e}</style><h1>第一季 · 固定 B12</h1><p>阶段：'+state['phase']+'；状态：'+state['status']+'。自动处理完成不代表人工听验通过；异常与无候选发言全部保留。</p><p><a href="season1_summary.json">运行汇总与耗时</a> · <a href="season1_manifest.json">输入清单</a></p><table><tr><th>集数</th><th>标题</th><th>运行状态</th><th>Wiki发言</th><th>有候选</th><th>需复查</th><th>活跃处理秒</th><th>错误</th></tr>'+''.join(rows)+'</table>'
        temp=outroot/'season1.html.tmp';temp.write_text(page,encoding='utf-8');os.replace(temp,outroot/'season1.html')
    for job in jobs:
        entry=dict(job,status='pending');state['episodes'].append(entry)
        out=outroot/job['episode'];out.mkdir(exist_ok=True)
        try:
            if (out/'run.json').exists():
                meta,reused=check_reuse(out,job,digest)
                if reused:
                    if not (out/'source_compare.html').exists():
                        from build_source_comparison import build as build_source_compare
                        build_source_compare(out)
                    entry.update(status='reused',verification=read(out/'verification.json'),active_seconds=round(meta['processing_wall_seconds'],3))
                    continue
                entry['meta']=meta
                for stage,status in [('diarization','diarization_complete'),('alignment','alignment_complete'),('asr','asr_complete')]:
                    if (out/RAW_FILES[stage]).exists():
                        entry['status']=status
                        break
            else:
                entry['meta']=dict(status='processing',episode=job['episode'],config=str(CONFIG),config_sha256=digest,
                    media=job['media'],media_sha256=sha(job['media']),wiki=job['wiki'],wiki_sha256=sha(job['wiki']),wiki_used_as_model_input=False,
                    timings={},artifact_sha256={},parameters_from_locked_file=True,timing_scope='Sum of active episode stage work; excludes shared model loads and waiting for other episodes.',processing_wall_seconds=0,
                    utc_started=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
                write(out/'run.json',entry['meta']);write(out/'config.snapshot.json',cfg)
        except Exception:
            entry.update(status='failed',error=traceback.format_exc())
    publish()
    if all(j['status'] in ['reused','failed'] for j in state['episodes']):
        state.update(status='completed' if not any(j['status']=='failed' for j in state['episodes']) else 'completed_with_errors',phase='done');publish();return int(state['status']!='completed')
    setup();os.environ['MPLCONFIGDIR']=str(outroot/'mpl')
    import torch
    import numpy as np
    import whisperx
    from whisperx.diarize import DiarizationPipeline
    if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable; no CPU/precision fallback permitted')
    for p,v in cfg['versions'].items():
        if importlib.metadata.version(p)!=v:raise RuntimeError(f'Pinned package version drift: {p}')
    for path,value in {**cfg['source_modules_sha256'],**cfg['weights_sha256']}.items():
        if sha(path)!=value:raise RuntimeError(f'Pinned source/weight changed: {path}')
    torch.set_num_threads(cfg['runtime']['torch_num_threads']);torch.set_num_interop_threads(cfg['runtime']['torch_num_interop_threads'])
    state['gpu']=torch.cuda.get_device_name(0);state['preflight_seconds']=time.perf_counter()-start;publish()
    def pending(stage):
        return [j for j in state['episodes'] if j['status'] not in ['reused','failed'] and not (outroot/j['episode']/RAW_FILES[stage]).exists()]
    def audio_for(job):
        out=outroot/job['episode'];wav=out/'source_audio.wav'
        if wav.exists():
            with wave.open(str(wav),'rb') as f:
                if f.getframerate()!=16000 or f.getnchannels()!=1 or f.getsampwidth()!=2:raise ValueError('Unexpected cached PCM format')
                frames=f.getnframes();pcm=f.readframes(frames)
                if len(pcm)!=frames*2 or frames==0:raise ValueError('Cached PCM is truncated or empty')
                return np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
        t=time.perf_counter();audio=whisperx.load_audio(job['media'])
        temporary=wav.with_suffix('.wav.tmp')
        with wave.open(str(temporary),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(np.clip(audio*32768,-32768,32767).astype('<i2').tobytes())
        os.replace(temporary,wav)
        job['meta']['audio_seconds']=len(audio)/16000;job['meta']['timings']['audio_decode_seconds']=time.perf_counter()-t
        return audio
    def episode_stage(job,stage,operation):
        out=outroot/job['episode'];meta=job['meta'];t=time.perf_counter()
        try:
            audio=audio_for(job);op_start=time.perf_counter();data=operation(audio,out);torch.cuda.synchronize()
            meta['timings'][stage+'_seconds']=time.perf_counter()-op_start
            write(out/RAW_FILES[stage],data);meta.setdefault('artifact_sha256',{})[RAW_FILES[stage]]=sha(out/RAW_FILES[stage])
            meta['processing_wall_seconds']=meta.get('processing_wall_seconds',0)+time.perf_counter()-t
            meta.pop('error',None);meta.pop('failed_stage',None)
            meta['status']=stage+'_complete';job['status']=stage+'_complete';meta['gpu']=state['gpu']
            write(out/'run.json',meta)
            print(f"{stage}: {job['episode']} complete ({meta['timings'][stage+'_seconds']:.2f}s)",flush=True)
        except Exception:
            error=traceback.format_exc();job.update(status='failed',error=error);meta.update(status='failed',failed_stage=stage,error=error)
            meta.setdefault('failure_history',[]).append(dict(stage=stage,error=error,utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
            write(out/'run.json',meta);print(f"FAILED {job['episode']} {stage}: {error}",flush=True)
        finally:gc.collect();torch.cuda.empty_cache();publish()
    if pending('asr'):
        state['phase']='asr';publish();t=time.perf_counter()
        model=whisperx.load_model(cfg['model'],cfg['device'],**cfg['load_model'])
        expected=dict(cfg['load_model']['asr_options']);expected.pop('suppress_numerals')
        if dataclasses.asdict(model.options)!=expected:raise RuntimeError('Effective ASR parameters differ from fixed B12')
        state['shared_model_load_seconds']['asr_vad']=time.perf_counter()-t
        for job in pending('asr'):
            write(outroot/job['episode']/'effective_asr_options.json',dict(asr_options=dataclasses.asdict(model.options),vad_options=model._vad_params,transcribe=cfg['transcribe']))
            episode_stage(job,'asr',lambda audio,out:model.transcribe(audio,**cfg['transcribe']))
        del model;gc.collect();torch.cuda.empty_cache()
    if pending('alignment'):
        state['phase']='alignment';publish();t=time.perf_counter();aligner,metadata=whisperx.load_align_model(**cfg['alignment']['load_model'])
        state['shared_model_load_seconds']['alignment']=time.perf_counter()-t
        for job in pending('alignment'):
            episode_stage(job,'alignment',lambda audio,out:whisperx.align(read(out/'asr.raw.json')['segments'],aligner,metadata,audio,**cfg['alignment']['align']))
        del aligner;gc.collect();torch.cuda.empty_cache()
    if pending('diarization'):
        state['phase']='diarization';publish();t=time.perf_counter();diarizer=DiarizationPipeline(**cfg['diarization']['load'])
        state['shared_model_load_seconds']['diarization']=time.perf_counter()-t
        for job in pending('diarization'):
            episode_stage(job,'diarization',lambda audio,out:diarizer(audio,**cfg['diarization']['run'])[['start','end','speaker']].to_dict(orient='records'))
        del diarizer;gc.collect();torch.cuda.empty_cache()
    state['phase']='reports';publish()
    import pandas as pd
    from alignment.b12_report import build
    from build_source_comparison import build as build_source_compare
    for job in state['episodes']:
        if job['status'] in ['reused','failed']:continue
        out=outroot/job['episode'];meta=job['meta'];t=time.perf_counter()
        try:
            final=whisperx.assign_word_speakers(pd.DataFrame(read(out/'diarization.raw.json')),read(out/'aligned.raw.json'),**cfg['diarization']['assign']);final['language']='en'
            write(out/'result.whisperx.json',final);meta.setdefault('artifact_sha256',{})['result.whisperx.json']=sha(out/'result.whisperx.json')
            meta['status']='completed';meta.pop('error',None);meta.pop('failed_stage',None);write(out/'run.json',meta)
            build(out,job['wiki'],batch_authorized=True)
            build_source_compare(out)
            meta['report_seconds']=time.perf_counter()-t;meta['completed_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());write(out/'run.json',meta)
            job.update(status='completed',verification=read(out/'verification.json'),active_seconds=round(meta['processing_wall_seconds'],3))
            print(f"REPORT {job['episode']}: {job['verification']['wiki_utterances']} Wiki utterances, {job['verification']['needs_review']} review flags",flush=True)
        except Exception:
            error=traceback.format_exc();job.update(status='failed',error=error);meta.update(status='failed',failed_stage='report',error=error);write(out/'run.json',meta)
        publish()
    state['phase']='done';state['status']='completed_with_errors' if any(j['status']=='failed' for j in state['episodes']) else 'completed'
    state['total_active_episode_seconds']=sum(j.get('active_seconds',0) for j in state['episodes'] if j['status']=='completed')
    state['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());publish()
    print(json.dumps(dict(status=state['status'],counts=state['counts'],wall_seconds=state['elapsed_wall_seconds']),ensure_ascii=False),flush=True)
    lock.close();return int(state['status']!='completed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wiki-dir',type=Path,default=ROOT/'output/wiki/season1/episodes')
    parser.add_argument('--video-dir',type=Path,default=Path('F:/小孩动画片/英文/peppa/第1季52集'))
    parser.add_argument('--output-dir',type=Path,default=ROOT/'output/whisperx_b12')
    parser.add_argument('--episodes',help='Optional comma-separated subset, e.g. S01E02,S01E03')
    parser.add_argument('--dry-run',action='store_true',help='Check all episode mappings without loading models or running inference')
    args=parser.parse_args()
    try:sys.exit(run(args))
    except Exception:
        error=traceback.format_exc();print(error,file=sys.stderr,flush=True)
        summary=Path(args.output_dir)/'season1_summary.json'
        if not args.dry_run and ACTIVE_OUTPUT==Path(args.output_dir).resolve() and summary.exists():
            state=read(summary);state.update(status='failed',fatal_error=error);write(summary,state)
        sys.exit(1)
