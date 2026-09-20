import numpy as np
import pandas as pd
from sequence_strategy.study import confirmation_bucket,cooldown_times,matched_lift

def test_confirmation_buckets():
    assert confirmation_bucket(-.02)=='strong_down'
    assert confirmation_bucket(-.005)=='down'
    assert confirmation_bucket(0)=='flat'
    assert confirmation_bucket(.005)=='up'
    assert confirmation_bucket(.02)=='strong_up'

def test_cooldown_removes_overlaps():
    t=pd.to_datetime(['2024-01-01T00:00Z','2024-01-01T12:00Z','2024-01-02T00:00Z','2024-01-03T01:00Z'])
    out=cooldown_times(t,24)
    assert list(out)==[t[0],t[2],t[3]]

def test_matched_control_lift():
    rows=[]
    for q in ['2025Q1','2025Q2','2025Q3','2025Q4']:
        for i in range(80):
            rows.append({'quarter':q,'catalyst_family':'oi','target':2 if i<40 else 1})
    d=pd.DataFrame(rows)
    mask=np.zeros(len(d),bool)
    # 10 signal rows per quarter, 8 of them up; controls still >=20.
    for j,q in enumerate(['2025Q1','2025Q2','2025Q3','2025Q4']):
        base=j*80
        sel=list(range(base,base+8))+list(range(base+40,base+42))
        mask[sel]=True
    lift,ps,pc,cov=matched_lift(d,mask,2)
    assert ps>.75 and lift>0 and cov==1
