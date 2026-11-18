"""Export NFA candidates and conservative speech-only boundaries, with evidence."""
import json
import os
from pathlib import Path
os.environ['MPLCONFIGDIR'] = str(Path(__file__).resolve().parents[1]/'output/forced_alignment/S01E01/mpl')
import torch
from nemo.collections.asr.parts.utils import aligner_utils as au

P = Path(__file__).resolve().parents[1]/'output/forced_alignment/S01E01'
e = torch.load(P/'acoustic_evidence.pt', weights_only=False)
path = torch.load(P/'viterbi_path.pt', weights_only=False)[0]
u = au.add_t_start_end_to_utt_obj(e['utterances'][0], path, e['timestep'])
rows = json.loads((P/'utterances.json').read_text(encoding='utf-8'))
segments = [s for s in u.segments_and_tokens if isinstance(s, au.Segment)]
assert len(segments) == len(rows) == 43
for r, s in zip(rows, segments):
    assert r['alignment_text'] == s.text
    words = []
    for w in s.words_and_tokens:
        if not isinstance(w, au.Word):
            continue
        tokens = []
        for token in w.tokens:
            if token.text == au.BLANK_TOKEN:
                continue
            frames = [i for i, state in enumerate(path) if state == token.s_start]
            peak = float(e['log_probs'][0, frames, token.token_id].exp().max()) if frames else 0
            tokens.append(dict(text=token.text, start=token.t_start, end=token.t_end,
                               peak_posterior=peak))
        words.append(dict(text=w.text, start=round(w.t_start,3), end=round(w.t_end,3), tokens=tokens))
    r['nfa_candidate'] = dict(start=round(s.t_start,3), end=round(s.t_end,3))
    r['words'] = words
    r['rejection_reasons'] = []
    for w in words:
        if w['start'] is None or w['start'] < 0 or w['end'] <= w['start']:
            r['rejection_reasons'].append('invalid_or_missing_word_boundary')
        elif w['end']-w['start'] > max(1.2, len(w['text'])*0.2+0.4):
            r['rejection_reasons'].append('implausibly_long_word:'+w['text'])
    lexical = 0
    # Preserve original utterance and ID, but start speech after explicit laughter.
    if words and words[0]['text'] == 'haha':
        lexical = 1
    elif len(words)>2 and [w['text'] for w in words[:2]] == ['ho','ho']:
        lexical = 2
    r['excluded_laughter_prefix_words'] = words[:lexical]
    r['human_verified'] = False
    if r['rejection_reasons']:
        r.update(start=None, end=None, status='rejected_needs_review', timing_source=None)
    else:
        r.update(start=words[lexical]['start'], end=words[-1]['end'],
                 status='aligned_automatic_unverified', timing_source='NeMo-2.5.3/Citrinet-256/CTC-Viterbi')
    print(r['source_record'],r['start'],r['end'],r['rejection_reasons'],r['text'])
(P/'utterances.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
(P/'quality_summary.json').write_text(json.dumps(dict(
    total=len(rows), automatic_accepted=sum(r['start'] is not None for r in rows),
    null_count=sum(r['start'] is None for r in rows),
    human_verified_count=0, frame_seconds=e['timestep'],
    warning='Duration gate is a heuristic, not calibrated accuracy or proof of laughter exclusion.',
    rejection_policy='Reject entire utterance if any word is invalid or longer than max(1.2 s, letters*0.2+0.4 s). No interpolation or boundary repair.',
    old_asr_used=False),ensure_ascii=False,indent=2),encoding='utf-8')
