"""Run official NFA with a non-spoken utterance delimiter (NeMo 2.5 retains it).

Only the segment split excludes '|'; acoustic inference and Viterbi are official.
No ASR decoding result is used as target text.
"""
import inspect
from pathlib import Path
import runpy
import sys
import time
import json
import torch
import nemo.collections.asr.parts.utils.aligner_utils as au

source = inspect.getsource(au.get_utt_obj)
old = 'segments.append(text[last_sep_idx + 1 : i + 1].strip())'
new = 'segments.append(text[last_sep_idx + 1 : i].strip())'
assert source.count(old) == 1
exec(source.replace(old, new), au.__dict__)
vendor = Path(__file__).resolve().parents[1] / 'alignment/vendor/nemo_forced_aligner'
out = Path(__file__).resolve().parents[1]/'output/forced_alignment/S01E01'
timings = {}
original_batch = au.get_batch_variables
def batch(*args, **kwargs):
    t = time.perf_counter()
    result = original_batch(*args, **kwargs)
    timings['acoustic_inference_and_target_preparation_seconds'] = time.perf_counter()-t
    torch.save(dict(log_probs=result[0], targets=result[1], T=result[2], U=result[3],
                    utterances=result[4], timestep=result[5]), out/'acoustic_evidence.pt')
    (out/'stages.json').write_text(json.dumps(timings, indent=2))
    return result
au.get_batch_variables = batch
original_viterbi = au.viterbi_decoding
def viterbi(*args, **kwargs):
    t = time.perf_counter()
    result = original_viterbi(*args, **kwargs)
    timings['viterbi_seconds'] = time.perf_counter()-t
    torch.save(result, out/'viterbi_path.pt')
    (out/'stages.json').write_text(json.dumps(timings, indent=2))
    return result
au.viterbi_decoding = viterbi
sys.path.insert(0, str(vendor))
runpy.run_path(str(vendor / 'align.py'), run_name='__main__')
