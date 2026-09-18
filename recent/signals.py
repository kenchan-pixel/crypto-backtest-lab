"""Volatility-conditioned hypotheses frozen using 2024 only; no future labels."""
import pandas as pd
PRIMARY=['V1','V2','V3']
HOURS={'V1':48,'V2':48,'V3':48,'OLD_D4':24}
def mask(f, key, factor=1.):
    quiet=(f.r720<=0)&(f.vol_ratio<.8*factor)&(f.vwap_distance<-.01*factor)
    leader=(f.r720>0)&(f.vol_ratio>=1.2*factor)&(f.relative24>.02*factor)
    if key=='V1':return quiet.fillna(False)
    if key=='V2':return leader.fillna(False)
    if key=='V3':return (quiet|leader).fillna(False)
    if key=='OLD_D4':return ((f.other_r24>=.02)&(f.relative24<=-.02)&(f.r720>0)).fillna(False)
    raise ValueError(key)
