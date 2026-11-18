"""Run official WhisperX APIs with the user's CUDA/pyannote parameters."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import gc
import traceback

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output/whisperx_s01e01_v2'
CACHE = ROOT / 'output/whisperx_models/hub'
SOURCE_CACHE = Path('E:/Coding/videoEditing/.cache/huggingface/hub')
MEDIA = Path('F:/小孩动画片/英文/peppa/第1季52集/S101 Muddy Puddles.mp4')
WIKI = ROOT / 'output/wiki/season1/episodes/S01E01.json'


def prepare_cache():
    for repo in ['models--Systran--faster-whisper-large-v3', 'models--pyannote--speaker-diarization-community-1']:
        snapshots = [p for p in (SOURCE_CACHE/repo/'snapshots').iterdir() if p.is_dir()]
        assert len(snapshots) == 1, snapshots
        snapshot = snapshots[0]
        destination = CACHE/repo/'snapshots'/snapshot.name
        if not destination.exists():
            shutil.copytree(snapshot, destination)
        refs = CACHE/repo/'refs'
        refs.mkdir(parents=True, exist_ok=True)
        (refs/'main').write_text(snapshot.name, encoding='utf-8')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    prepare_cache()
    env = os.environ.copy()
    env['HF_HUB_CACHE'] = str(CACHE)
    env['HF_HUB_OFFLINE'] = '1'
    env['MPLCONFIGDIR'] = str(OUT/'mpl')
    env['PATH'] = str(Path(sys.prefix)/'Lib/site-packages/torch/lib') + os.pathsep + env['PATH']
    env['PATH'] = 'E:/Coding/videoEditing/.ffmpeg/Library/bin' + os.pathsep + env['PATH']
    os.environ.update(env)
    args = [str(MEDIA), '--model', 'large-v3', '--language', 'en', '--task', 'transcribe',
        '--device', 'cuda', '--compute_type', 'float16', '--batch_size', '4', '--beam_size', '5',
        '--temperature', '0', '--vad_method', 'pyannote', '--vad_onset', '0.50', '--vad_offset', '0.363',
        '--diarize', '--diarize_model', 'pyannote/speaker-diarization-community-1',
        '--condition_on_previous_text', 'False', '--interpolate_method', 'ignore',
        '--output_format', 'json', '--output_dir', str(OUT)]
    run = dict(status='running', equivalent_cli_arguments=args, invocation='official WhisperX Python APIs',
        hf_token_present=bool(env.get('HF_TOKEN')), local_model_cache=str(CACHE), offline_cache=True,
        token_note='Token is None when absent; complete locally cached model used without network authentication.',
        wiki=str(WIKI), wiki_sha256=hashlib.sha256(WIKI.read_bytes()).hexdigest(),
        media=str(MEDIA), media_sha256=hashlib.sha256(MEDIA.read_bytes()).hexdigest(),
        utc_started=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        versions={p: importlib.metadata.version(p) for p in ['torch','torchaudio','torchvision','whisperx','faster-whisper','pyannote.audio','ctranslate2']})
    (OUT/'run.json').write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding='utf-8')
    started = time.perf_counter()
    def save(name, data):
        (OUT/name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    def stage(name):
        print(name, flush=True)
        with (OUT/'whisperx.log').open('a', encoding='utf-8') as log:
            log.write(name+'\n')
    try:
        import torch
        import whisperx
        from whisperx.diarize import DiarizationPipeline
        assert torch.cuda.is_available(), 'CUDA PyTorch is required; no CPU fallback.'
        run['gpu'] = torch.cuda.get_device_name(0)
        run['parameters'] = dict(model='large-v3', language='en', task='transcribe', device='cuda', compute_type='float16',
            batch_size=4, beam_size=5, temperature=0, vad_method='pyannote', vad_onset=.50, vad_offset=.363,
            diarize=True, diarize_model='pyannote/speaker-diarization-community-1',
            condition_on_previous_text=False, interpolate_method='ignore')
        stage('Loading WhisperX large-v3 / CUDA float16 / pyannote VAD')
        t = time.perf_counter()
        model = whisperx.load_model('large-v3', 'cuda', compute_type='float16', language='en', task='transcribe',
            download_root=str(CACHE), local_files_only=True, vad_method='pyannote',
            vad_options={'vad_onset': .50, 'vad_offset': .363},
            asr_options={'beam_size': 5, 'temperatures': [0.0], 'condition_on_previous_text': False})
        audio = whisperx.load_audio(str(MEDIA))
        result = model.transcribe(audio, batch_size=4, language='en', task='transcribe', print_progress=True)
        save('asr.raw.json', result)
        run['asr_seconds'] = time.perf_counter()-t
        del model
        gc.collect()
        torch.cuda.empty_cache()
        stage('Running official WhisperX phoneme alignment / interpolate=ignore')
        t = time.perf_counter()
        aligner, metadata = whisperx.load_align_model(language_code='en', device='cuda')
        aligned = whisperx.align(result['segments'], aligner, metadata, audio, 'cuda', interpolate_method='ignore')
        save('aligned.raw.json', aligned)
        run['alignment_seconds'] = time.perf_counter()-t
        del aligner
        gc.collect()
        torch.cuda.empty_cache()
        stage('Running pyannote/speaker-diarization-community-1 on CUDA')
        t = time.perf_counter()
        diarizer = DiarizationPipeline(model_name='pyannote/speaker-diarization-community-1',
            token=env.get('HF_TOKEN'), device='cuda', cache_dir=str(CACHE))
        diarized = diarizer(audio)
        save('diarization.raw.json', diarized[['start','end','speaker']].to_dict(orient='records'))
        result = whisperx.assign_word_speakers(diarized, aligned)
        result['language'] = 'en'
        save('S101 Muddy Puddles.json', result)
        run['diarization_seconds'] = time.perf_counter()-t
        code = 0
        stage('Completed ASR + alignment + diarization; original result saved.')
    except Exception:
        error = traceback.format_exc()
        stage(error)
        run['error'] = error
        code = 1
    run.update(status='completed' if code == 0 else 'failed', exit_code=code, wall_seconds=time.perf_counter()-started)
    (OUT/'run.json').write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding='utf-8')
    return code


if __name__ == '__main__':
    sys.exit(main())
