"""Reconstruct actual hourly sun/shade mass and N; no inferred leaf cohorts."""
import sys
import numpy as np
import pandas as pd
from workflow import OUT,dump

results=[]
for name in sys.argv[1:]:
    work=OUT/'cases'/name
    selected=[]
    for chunk in pd.read_csv(work/'P0Trace.csv',chunksize=200000,usecols=['event','key','value']):
        selected.append(chunk[chunk.event.eq('c4_canopy_n')])
    data=pd.concat(selected).copy()
    assert len(data)>0
    data['call']=data.key.eq('LAISL').cumsum()
    assert data.groupby('call').size().eq(8).all()
    p=data.pivot(index='call',columns='key',values='value')
    area=p.LAISL+p.LAISH
    target_mass=area/p.SLAAD
    actual_mass=p.LAISL*p.SLWSL+p.LAISH*p.SLWSH
    target_n=p.RNITP/100*target_mass
    actual_n=(p.LAISL*p.SLWSL*p.PCNLSL+p.LAISH*p.SLWSH*p.PCNLSH)/100
    tolerance=16*np.finfo(np.float32).eps
    assert (abs(actual_mass-target_mass)<=tolerance*np.maximum(1e-12,target_mass)).all()
    assert (abs(actual_n-target_n)<=tolerance*np.maximum(1e-12,target_n)).all()
    assert p[['SLWSL','SLWSH','PCNLSL','PCNLSH']].min().min()>=0
    results.append(dict(case=name,calls=len(p),passed=True,
        max_relative_mass_error=float((abs(actual_mass-target_mass)/target_mass.clip(1e-12)).max()),
        max_relative_N_error=float((abs(actual_n-target_n)/target_n.clip(1e-12)).max())))
dump(OUT/('C4_photo_verification_'+sys.argv[1]+'.json'),results)
print(results)
