"""Single-factor adapter response checks; never used to rank/filter initial members."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration import cnc_joint_20261014 as model

def main():
    run=ROOT/'workspace/runs'/model.ID;d,b,obs=model.load_design(model.CONFIG/'design.json')
    base=dict(zip(b.name,b.init));reference=pd.read_csv(run/'preflight/seed_yield/last_comparison.csv')
    rows=[]
    for name,value in [('CNC_A',4.20),('CNC_B',.45),('CNC_W0',1.50),('CNC_NC_INF',2.00)]:
        out=run/'adapter_response_checks'/name;out.mkdir(parents=True,exist_ok=True)
        values=base|{name:value};model.validate_parameters(values,b)
        file=out/'parameters.csv';pd.DataFrame(values.items(),columns=['name','value']).to_csv(file,index=False)
        compared=model.evaluate(model.CONFIG/'design.json',file,out)
        delta=compared.simulated.to_numpy()-reference.simulated.to_numpy()
        leaf=compared.variable.eq('LEAF_N_PCT');yieldmask=compared.family.eq('FINAL_FRESH_YIELD')
        rows.append(dict(parameter=name,reference_value=base[name],changed_value=value,complete_targets=len(compared),
           changed_target_count=int((abs(delta)>1e-9).sum()),max_leaf_N_difference_pp=float(abs(delta[leaf]).max()),
           max_terminal_fresh_difference_kg_ha=float(abs(delta[yieldmask]).max()),
           maximum_normalized_prediction_change=float(np.max(abs(delta)/compared.fit_scale)),used_for_initial_member_selection=False))
        print(rows[-1],flush=True)
    result=pd.DataFrame(rows);result.to_csv(run/'adapter_response_checks/native_single_factor_response.csv',index=False)
    if not result.changed_target_count.gt(0).all():raise ValueError('One or more CNC parameters did not affect native predictions')
    model.legacy.write_json(run/'adapter_response_checks/receipt.json',dict(status='passed',independent_native_perturbations=4,
        all_parameters_change_native_predictions=True,used_to_rank_or_screen_initial_ensemble=False))

if __name__=='__main__':main()
