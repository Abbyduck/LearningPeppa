"""Prepare Wiki utterances and run NeMo alignment for S01E01."""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/forced_alignment/S01E01'


def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    wiki = ROOT / 'output/wiki/episodes/S01E01.json'
    audio = OUT / 'source_audio.wav'
    if not audio.is_file():
        raise FileNotFoundError('Missing source_audio.wav; extract the original audio as described in README.md.')
    data = json.loads(wiki.read_text(encoding='utf-8'))
    rows = []
    for i, entry in enumerate(data['entries']):
        if entry['type'] != 'utterance':
            continue
        rows.append(dict(entry, entry_index=i, start=None, end=None,
                         status='pending', timing_source=None))
    assert len(rows) == 43
    # A separator is metadata, not speech; NFA splits it before tokenization.
    # Citrinet's uncased vocabulary needs orthographic normalization only.
    for r in rows:
        r['alignment_text'] = ' '.join(re.sub(r"[^a-z' ]", ' ', r['text'].lower()).split())
    text = ' | '.join(r['alignment_text'] for r in rows)
    manifest = dict(audio_filepath=str(audio), text=text)
    (OUT / 'manifest.jsonl').write_text(json.dumps(manifest, ensure_ascii=False)+'\n', encoding='utf-8')
    save('utterances.json', rows)
    with wave.open(str(audio)) as w:
        duration = w.getnframes()/w.getframerate()
    save('inputs.json', dict(episode='S01E01', wiki=str(wiki), wiki_sha256=sha(wiki),
        audio=str(audio), audio_sha256=sha(audio), duration_seconds=duration,
        utterance_count=len(rows), old_asr_used=False, separator='|',
        text_policy='Wiki only. Original preserved; lowercase/punctuation-only normalization for uncased Citrinet. Events excluded.',
        sources=['https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tools/nemo_forced_aligner.html',
                 'https://github.com/NVIDIA/NeMo/tree/v2.5.3/tools/nemo_forced_aligner']))


def run():
    if not (OUT/'citrinet.nemo').is_file():
        raise FileNotFoundError('Missing local Citrinet checkpoint: ' + str(OUT/'citrinet.nemo'))
    if (OUT/'nfa.log').exists():
        history = OUT/'attempts'
        history.mkdir(exist_ok=True)
        stamp = time.time_ns()
        for name in ['nfa.log', 'run.json']:
            if (OUT/name).exists():
                (history/f'{stamp}_{name}').write_bytes((OUT/name).read_bytes())
    prepare()
    args = [str(ROOT / '.nemo-venv/Scripts/python.exe'), '-m', 'alignment.nemo_bootstrap',
        f'model_path={OUT / "citrinet.nemo"}', f'manifest_filepath={OUT / "manifest.jsonl"}',
        f'output_dir={OUT / "nfa"}', 'align_using_pred_text=false',
        'transcribe_device=cpu', 'viterbi_device=cpu', 'batch_size=1', 'use_local_attention=false',
        'additional_segment_grouping_separator=["|"]',
        'save_output_file_formats=[ctm]', 'ctm_file_config.minimum_timestamp_duration=0']
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    (OUT/'tmp').mkdir(exist_ok=True)
    env.update(MPLCONFIGDIR=str(OUT/'mpl'), HF_HOME=str(OUT/'cache/huggingface'),
               NEMO_CACHE_DIR=str(OUT/'cache/nemo'), HYDRA_FULL_ERROR='1',
               TMP=str(OUT/'tmp'), TEMP=str(OUT/'tmp'), WANDB_MODE='disabled',
               OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', PYTHONUTF8='1')
    t = time.perf_counter()
    with (OUT/'nfa.log').open('w', encoding='utf-8') as log:
        p = subprocess.run(args, env=env, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    save('run.json', dict(command=args, exit_code=p.returncode,
                         wall_seconds=time.perf_counter()-t, includes_model_download=False))
    if p.returncode:
        rows = json.loads((OUT/'utterances.json').read_text(encoding='utf-8'))
        for r in rows:
            r.update(status='alignment_not_run_environment_failure')
        save('utterances.json', rows)
    print((OUT/'nfa.log').read_text(encoding='utf-8')[-10000:])
    return p.returncode


if __name__ == '__main__':
    if '--prepare' in sys.argv:
        prepare()
    else:
        sys.exit(run())
