"""Native-extension-free CTC Viterbi for character alignment."""
import numpy as np

def ctc_states(log_probs, target):
    """Standard full-utterance CTC Viterbi, blank=0; no native extension."""
    y=np.zeros(2*len(target)+1,dtype=int)
    y[1::2]=target
    T,S=len(log_probs),len(y)
    back=np.zeros((T,S),dtype=np.int8)
    score=np.full(S,-np.inf)
    score[:2]=log_probs[0,y[:2]]
    skip=(y!=0)&(y!=np.roll(y,2))
    skip[:2]=False
    for i in range(1,T):
        choices=np.stack([score,np.r_[-np.inf,score[:-1]],np.r_[[-np.inf]*2,score[:-2]]])
        choices[2,~skip]=-np.inf
        best=choices.argmax(axis=0)
        back[i]=best
        score=choices[best,np.arange(S)]+log_probs[i,y]
    pos=S-1 if score[-1]>score[-2] else S-2
    states=np.zeros(T,dtype=int)
    for i in range(T-1,-1,-1):
        states[i]=pos
        pos-=int(back[i,pos])
    return states

