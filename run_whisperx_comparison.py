"""Re-run S01E01 ASR and Wiki alignment independently of NeMo timing.

ASR: faster-whisper large-v3 (the WhisperX ASR backend), native word anchors.
Alignment: installed WhisperX align(), unchanged, with its default English
wav2vec2 weights loaded through TorchAudio's pure Python model definition.
The adapter avoids this machine's unloadable TorchAudio native DLL only.
"""
import argparse
import gc
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
import types
from difflib import SequenceMatcher

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output/comparison/S01E01'
NEMO = ROOT / 'output/forced_alignment/S01E01'
WIKI = ROOT / 'output/wiki/episodes/S01E01.json'


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def tokens(text):
    return re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower().replace('’', "'"))


def mark_overlaps(output):
    for previous, current in zip(output, output[1:]):
        if previous['end'] is not None and current['start'] is not None and previous['end'] > current['start']:
            for item, reason in [(previous, 'overlap_with_next_wiki_utterance'), (current, 'overlap_with_previous_wiki_utterance')]:
                if reason not in item['issues']:
                    item['issues'].append(reason)
    for item in output:
        item['status'] = 'needs_review' if item['issues'] else 'automatic_candidate_unverified'
    return output


def load_alignment():
    import torch
    # Native libtorchaudio raises WinError 5 on this machine. No inference code
    # is replaced: load its official Python architecture and cached checkpoint.
    package = types.ModuleType('comparison_wav2vec2')
    package.__path__ = [str(Path(sys.prefix) / 'Lib/site-packages/torchaudio/models/wav2vec2')]
    sys.modules[package.__name__] = package
    factory = importlib.import_module(package.__name__ + '.model')
    model = factory.wav2vec2_base(aux_num_out=29).eval()
    checkpoint = Path(torch.hub.get_dir()) / 'checkpoints/wav2vec2_fairseq_base_ls960_asr_ls960.pth'
    state = torch.load(checkpoint, weights_only=True)
    for key in ('aux.weight', 'aux.bias'):
        state[key] = torch.stack([v for i, v in enumerate(state[key]) if i not in (1, 2, 3)])
    model.load_state_dict(state, strict=True)
    adapter = types.ModuleType('torchaudio')
    adapter.__spec__ = importlib.util.spec_from_loader('torchaudio', loader=None)
    adapter.__version__ = '2.8.0'
    sys.modules['torchaudio'] = adapter
    from whisperx.alignment import align
    labels = ['-'] + list("|ETAONIHSRDLUMWCFGYPBVK'XJQZ")
    return model, {'language': 'en', 'type': 'torchaudio',
                   'dictionary': {c.lower(): i for i, c in enumerate(labels)}}, align


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['all', 'asr', 'align', 'check'], default='all')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage == 'check':
        save('whisperx_wiki.json', mark_overlaps(json.loads((OUT/'whisperx_wiki.json').read_text(encoding='utf-8'))))
        return
    os.environ['OMP_NUM_THREADS'] = '4'
    import torch
    import soundfile as sf
    torch.set_num_threads(4)
    wiki = json.loads(WIKI.read_text(encoding='utf-8'))
    rows = [r for r in wiki['entries'] if r['type'] == 'utterance']
    audio_path = NEMO / 'source_audio.wav'
    audio, sr = sf.read(audio_path, dtype='float32')
    assert sr == 16000 and audio.ndim == 1
    duration = len(audio) / sr
    if args.stage in ('all', 'asr'):
        from faster_whisper import WhisperModel
        manifest = json.loads((ROOT / 'output/whisperx_large_v3/manifest.json').read_text(encoding='utf-8'))
        started = time.perf_counter()
        model = WhisperModel(manifest['asr_model'], device='cpu', compute_type='int8', cpu_threads=4, local_files_only=True)
        segments, info = model.transcribe(audio, language='en', beam_size=5,
            word_timestamps=True, vad_filter=False, condition_on_previous_text=False)
        result = []
        for segment in segments:
            result.append(segment._asdict())
            result[-1]['words'] = [w._asdict() for w in segment.words or []]
            print(f"ASR {segment.start:.2f}-{segment.end:.2f}: {segment.text}", flush=True)
        save('asr.raw.json', {'segments': result, 'language': info.language})
        save('run.json', dict(audio_sha256=hashlib.sha256(audio_path.read_bytes()).hexdigest(),
            wiki_sha256=hashlib.sha256(WIKI.read_bytes()).hexdigest(),
            asr_model=manifest['asr_model'], asr_seconds=time.perf_counter()-started,
            device='cpu', compute_type='int8', threads=4, beam_size=5,
            asr_backend='faster-whisper native transcribe; VAD disabled (ONNX Runtime DLL unavailable); native word anchors',
            alignment='WhisperX align() / WAV2VEC2_ASR_BASE_960H',
            adapter='Official TorchAudio Python architecture/checkpoint; native DLL unavailable (WinError 5)',
            nemo_timing_used=False, old_asr_used=False, interpolation='ignore', human_verified_count=0,
            versions={p: importlib.metadata.version(p) for p in ['whisperx', 'faster-whisper', 'torch', 'torchaudio']},
            utc_started=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
        del model
        gc.collect()
    if args.stage == 'asr':
        return
    started = time.perf_counter()
    asr = json.loads((OUT / 'asr.raw.json').read_text(encoding='utf-8'))
    asr_tokens, anchors = [], []
    for s in asr['segments']:
        for w in s['words']:
            for token in tokens(w['word']):
                asr_tokens.append(token)
                anchors.append(w)
    wiki_tokens, spans = [], []
    for r in rows:
        start = len(wiki_tokens)
        wiki_tokens.extend(tokens(r['text']))
        spans.append((start, len(wiki_tokens)))
    mapping = {}
    for block in SequenceMatcher(None, wiki_tokens, asr_tokens, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            mapping[block.a+k] = block.b+k
    model, metadata, align = load_alignment()
    output = []
    for r, (a, b) in zip(rows, spans):
        matches = [anchors[mapping[i]] for i in range(a, b) if i in mapping]
        item = dict(id=r['id'], source_record=r['source_record'], text=r['text'],
                    speakers=r.get('speakers'), matched_tokens=len(matches), total_tokens=b-a,
                    anchor_coverage=len(matches)/(b-a), start=None, end=None, words=[],
                    human_verified=False, issues=[])
        if not matches:
            item['issues'].append('no_independent_asr_anchor')
        else:
            # Pad for partial ASR omissions, never borrow NeMo boundaries.
            start = max(0, min(w['start'] for w in matches) - .8)
            end = min(duration, max(w['end'] for w in matches) + .8)
            item['window'] = {'start': start, 'end': end}
            item['anchor_words'] = matches
            if item['anchor_coverage'] < .7:
                item['issues'].append('low_asr_anchor_coverage')
            result = align([dict(start=start, end=end, text=r['text'])], model, metadata,
                           audio, 'cpu', interpolate_method='ignore', return_char_alignments=True)
            item['raw_alignment'] = result
            words = result['word_segments']
            item['words'] = words
            valid = [w for w in words if w.get('start') is not None and w.get('end') is not None]
            if valid:
                item['start'], item['end'] = valid[0]['start'], valid[-1]['end']
            if len(valid) != len(r['text'].split()):
                item['issues'].append('missing_word_timing')
            for w in valid:
                if w['end'] <= w['start']:
                    item['issues'].append('invalid_word_boundary:' + w['word'])
                elif w['end']-w['start'] > max(1.2, len(w['word'])*.2+.4):
                    item['issues'].append('implausibly_long_word:' + w['word'])
            lexical = 1 if tokens(r['text'])[:1] == ['haha'] else 2 if tokens(r['text'])[:2] == ['ho','ho'] else 0
            item['lexical_start'] = words[lexical].get('start') if len(words)>lexical else None
        item['status'] = 'needs_review' if item['issues'] else 'automatic_candidate_unverified'
        output.append(item)
        save('whisperx_wiki.json', output)
        print(f"WIKI #{r['source_record']} {item['start']}-{item['end']} {item['issues']}", flush=True)
    save('whisperx_wiki.json', mark_overlaps(output))
    run = json.loads((OUT / 'run.json').read_text(encoding='utf-8'))
    run.update(alignment_seconds=time.perf_counter()-started, total_rows=len(output))
    save('run.json', run)


if __name__ == '__main__':
    main()
