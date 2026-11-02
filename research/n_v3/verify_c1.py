"""Independent day-state reconstruction and same-input legacy regression."""
import json,sys
import numpy as np
import pandas as pd
from workflow import OUT,dump

results=[]
names=sys.argv[1:] or ['c1_timing','c1_pods','c1_both']
for name in names:
    w=OUT/'cases'/name
    d=pd.read_csv(w/'PlantNV3.csv',float_precision='round_trip').sort_values(['run','yrdoy'])
    assert len(d)==1512 and not d.duplicated(['run','yrdoy']).any()
    previous=d.groupby('run')[['yrdoy','growth_end','z_leaf_end','z_stem_end']].shift()
    valid=d.valid.eq(1)
    assert valid.sum()==1500 and not d.groupby('run').valid.first().any()
    assert (d.loc[valid,'source_yrdoy']==previous.loc[valid,'yrdoy']).all()
    assert (d.loc[valid,'source_yrdoy']<d.loc[valid,'yrdoy']).all()
    errors={}
    for col,old in [('growth_day','growth_end'),('z_leaf_day','z_leaf_end'),('z_stem_day','z_stem_end')]:
        errors[col]=float(np.max(np.abs(d.loc[valid,col]-previous.loc[valid,old])))
        assert errors[col]<1e-13
    assert np.max(np.abs(d.pod_n_factor-(1-(1-d.z_leaf_day.clip(0,1))**2)))<1e-13
    n=pd.read_csv(w/'PlantNIntegration.csv',float_precision='round_trip')
    assert np.max(np.abs(d.z_leaf_end.to_numpy()-n.NNI_functional_leaf.to_numpy()))<1e-13
    if d.state_timing.eq(1).all():
        trace=[]
        for chunk in pd.read_csv(w/'P0Trace.csv',chunksize=200000,usecols=['run','yrdoy','event','key','value']):
            trace.append(chunk[chunk.event.eq('cg_veg')&chunk.key.eq('NSTRES')])
        t=pd.concat(trace)
        joined=d.merge(t[['run','yrdoy','value']],on=['run','yrdoy'],validate='one_to_one')
        active=joined.valid.eq(1)
        error=np.abs(joined.loc[active,'growth_day'].astype('float32').astype(float)-joined.loc[active,'value'])
        assert error.max()<1e-13
    results.append(dict(case=name,passed=True,valid_previous_end_days=int(valid.sum()),errors=errors))
dump(OUT/('C1_state_verification_'+names[0]+'.json'),results)
print(f'PASS: {1500*len(names)} valid day snapshots reconstructed; first-day resets, growth consumer and PODS mapping verified.')
