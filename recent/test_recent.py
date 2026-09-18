import numpy as np,pandas as pd
from recent.signals import mask

def test_three_disjoint_masks_and_union():
 f=pd.DataFrame({'r720':[-.1,.1,-.1,.1], 'vol_ratio':[.7,1.3,1.3,.7], 'vwap_distance':[-.02,.02,-.02,.02], 'relative24':[0,.03,0,.03], 'other_r24':[0,.03,0,.03]})
 assert mask(f,'V1').tolist()==[True,False,False,False]
 assert mask(f,'V2').tolist()==[False,True,False,False]
 assert mask(f,'V3').tolist()==[True,True,False,False]

def test_missing_features_fail_closed():
 f=pd.DataFrame({x:[np.nan] for x in ['r720','vol_ratio','vwap_distance','relative24','other_r24']})
 for k in ['V1','V2','V3','OLD_D4']:assert not mask(f,k).any()

def test_future_row_changes_cannot_alter_prior_signal():
 rng=np.random.default_rng(1)
 f=pd.DataFrame({x:rng.normal(size=100) for x in ['r720','vol_ratio','vwap_distance','relative24','other_r24']})
 g=f.copy();g.iloc[60:]=100
 for k in ['V1','V2','V3','OLD_D4']:pd.testing.assert_series_equal(mask(f,k).iloc[:60],mask(g,k).iloc[:60])
