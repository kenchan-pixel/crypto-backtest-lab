import numpy as np
import pandas as pd
from payoff_strategy.study import cost_net,weekly_bootstrap

def test_cost_net_penalizes_return():
    assert cost_net(.01,.001,.0005)<.01
    assert cost_net(.01,.0015,.0015)<cost_net(.01,.001,.0005)

def test_weekly_bootstrap_positive_and_limited():
    t=pd.date_range('2025-01-01',periods=20,freq='7D',tz='UTC')
    tr=pd.DataFrame({'entry_hkt':t.astype(str),'net_return':np.full(20,.01)})
    r=weekly_bootstrap(tr,1999,7)
    assert not r['limited'] and r['ci_low']>0 and r['p']<.01
    s=weekly_bootstrap(tr.iloc[:5],1999,7)
    assert s['limited'] and s['p']==1
