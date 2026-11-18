"""Apply conservative, independently aligned word tails; preserve native CTM."""
import json
from pathlib import Path
import wave

P=Path(__file__).resolve().parents[1]/'output/forced_alignment/S01E01'

def apply():
    rows=json.loads((P/'utterances.json').read_text(encoding='utf-8'))
    evidence=json.loads((P/'word_tail_character_check.json').read_text(encoding='utf-8'))
    checks={c['source_record']:c for c in evidence['results']}
    expected={r['source_record'] for r in rows if not r['rejection_reasons']}
    assert set(checks)==expected, 'Tail evidence does not cover the current NFA candidates'
    with wave.open(str(P/'source_audio.wav')) as audio:
        duration=audio.getnframes()/audio.getframerate()
    for i,r in enumerate(rows):
        r.pop('playback',None)
        if r['rejection_reasons']:continue
        c=checks[r['source_record']]
        prefix=len(r.get('excluded_laughter_prefix_words',[]))
        start=r['words'][prefix]['start']
        nfa_end=r['nfa_candidate']['end']
        delta=c['character_alignment_end']-nfa_end
        ok=c['last_word_mean_score']>=.45 and c['last_char_score']>=.1 and -.2<=delta<=.8
        r['tail_check']=dict(engine=evidence['engine'],mean_score=c['last_word_mean_score'],
            last_char_score=c['last_char_score'],character_end=c['character_alignment_end'],
            endpoint_delta_seconds=round(delta,4),status='supported_automatic_unverified' if ok else 'insufficient_evidence',
            policy='mean final-word character score >= .45, final character >= .1, endpoint difference -0.2 to +0.8 s; heuristic, not calibrated accuracy')
        if not ok:
            r.update(start=None,end=None,status='tail_check_needs_review',timing_source=None)
            continue
        end=round(max(nfa_end,c['character_alignment_end']),4)
        r.update(start=start,end=end,status='aligned_automatic_unverified',
            timing_source='NeMo-CTC onset + independent wav2vec2 character-CTC tail check')
        following=rows[i+1]['nfa_candidate']['start'] if i+1<len(rows) else duration
        play_end=round(min(end+.12,following-.05),4)
        assert play_end>=end
        r['playback']=dict(start=start,end=play_end,trailing_padding_seconds=round(play_end-end,4),
            policy='Up to 120 ms playback-only margin, capped before next utterance; not an alignment boundary')
    (P/'utterances.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    accepted=sum(r['start'] is not None for r in rows)
    summary=dict(total=43,automatic_accepted=accepted,null_count=43-accepted,
        baseline_nfa_accepted=len(expected),baseline_nfa_null_count=43-len(expected),tail_check_count=len(checks),
        tail_check_needs_review=sum(r['status']=='tail_check_needs_review' for r in rows),
        human_verified_count=0,old_asr_used=False,character_check_wall_seconds=evidence['wall_seconds'],
        warning='CTC character endpoints are automatic estimates; playback padding is stored separately.')
    (P/'quality_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(summary)

if __name__=='__main__':apply()
