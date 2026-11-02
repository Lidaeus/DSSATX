"""Independent submitted-source, recipient and donor ledger verification."""
import sys
import numpy as np
import pandas as pd
from workflow import OUT,dump
checks=[]
for name in sys.argv[1:]:
    w=OUT/'cases'/name
    d=pd.read_csv(w/'PlantNRemob.csv',float_precision='round_trip')
    a=pd.read_csv(w/'PlantABudget.csv',float_precision='round_trip')
    assert len(d)==1512 and not d.duplicated(['run','yrdoy']).any()
    actual=d.filter(regex='^(safe_|function_)').sum(axis=1)
    planned=d.filter(regex='^plan_').sum(axis=1);returned=d.filter(regex='^returned_').sum(axis=1)
    err=float(abs(planned-returned-actual).max());assert err<1e-13
    assert (actual<=d.new_growth_N_actual+1e-6).all()
    assert d.filter(regex='^returned_').min().min()>=-1e-12
    for organ in ['leaf','stem','root']:
        assert np.max(np.abs(d['safe_'+organ]+d['function_'+organ]-a['mobilized_'+organ]))<1e-13
    checks.append(dict(case=name,passed=True,source_residual_max=err,
        returned_total=float(returned.sum()),functional_total=float(d.filter(regex='^function_').sum().sum()),
        native_shell_actual_total=float(d.safe_shell.sum())))
dump(OUT/('C2_verification_'+sys.argv[1]+'.json'),checks)
print(checks)
