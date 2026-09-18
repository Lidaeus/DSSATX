"""Evaluate two deterministic parameter averages against the three-season design."""
from __future__ import annotations
import json, shutil, subprocess, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASE = ROOT / "workspace/runs/e02_joint62_posterior_soil_wnresponse_200x5_20260802"
A = BASE / "best_member_metrics_rawscale/best_member_parameters.csv"
B = ROOT / "workspace/runs/e02_joint61_25sp25fa_validic_n012_no_nresponse_formal_200x5_20260801/best_member_diagnostics/best_member_55_parameters.csv"
C = ROOT / "workspace/runs/e02_wnstress_fourcorner_layermeanic_formal_200x5_20260801_114300/best_member_long_params.csv"
OUT = ROOT / "workspace/runs/average_parameter_evaluations_20260802"
DESIGN = BASE / "runtime_multiseason_design.json"

def read_wide(path: Path):
    row = pd.read_csv(path).iloc[0]
    return {str(k).upper(): float(v) for k,v in row.items() if str(k).lower() != 'real_name' and pd.notna(v)}
def read_long(path: Path):
    d = pd.read_csv(path)
    return {str(r['name']).upper(): float(r['value']) for _,r in d.iterrows() if pd.notna(r['value'])}
def write_params(path, vals):
    pd.DataFrame({'name':list(vals), 'value':[vals[k] for k in vals]}).to_csv(path,index=False)
def metric(comp):
    rows=[]
    for keys,g in comp.groupby(['season','variable']): rows.append({'season':keys[0],'variable':keys[1],**calc(g)})
    for var,g in comp.groupby('variable'): rows.append({'season':'ALL','variable':var,**calc(g)})
    return pd.DataFrame(rows)
def calc(g):
    o=g.observed.to_numpy(float); s=g.simulated.to_numpy(float); e=s-o
    den=((o-o.mean())**2).sum(); r=np.corrcoef(o,s)[0,1]**2 if len(g)>1 else np.nan
    return {'n':len(g),'rmse':float(np.sqrt(np.mean(e**2))),'rrmse_pct':float(100*np.sqrt(np.mean(e**2))/abs(o.mean())) if o.mean()!=0 else np.nan,'nse':float(1-(e@e)/den) if den>0 else np.nan,'r2':float(r),'bias':float(e.mean())}
def main():
    from src.reporting.validation_metrics import build_comparison_from_rerun
    from src.reporting.analyze_results import _parse_batch_entries
    designs=json.loads(DESIGN.read_text()); a=read_wide(A); b=read_long(B); c=read_long(C)
    common={k:(a[k]+b[k])/2 for k in a if k in b}; p1={**a,**common}
    selected={'RTNO3','RTNH4','RTEXF','RWUMX','NSTFAC','DSWBAR','PORMIN','SENDAY','CMOBMX','SOIL_SLPF'}
    p2={**a,**{k:(a[k]+c[k])/2 for k in selected if k in a and k in c}}
    for label,params in [('avg_joint61',p1),('avg_selected_layermeanic',p2)]:
        out=OUT/label; out.mkdir(parents=True,exist_ok=True); pc=out/'parameters.csv'; write_params(pc,params)
        dd=json.loads(json.dumps(designs)); dd['design_id']=f'{dd["design_id"]}_{label}_20260802'; dp=out/'design.json'; dp.write_text(json.dumps(dd,ensure_ascii=False,indent=2))
        subprocess.run([sys.executable,str(ROOT/'src/calibration/run_multiseason.py'),'--design',str(dp),'--param-csv',str(pc),'--prefix',label],cwd=out,check=True)
        comps=[]
        for s in dd['seasons']:
            sd=out/'_seasons'/s['season_id']; bundle=ROOT/s['bundle_path']; batch=sd/'DSSBatch.selected.v48'; entries=_parse_batch_entries(str(batch)); roles={int(x):'diagnostic' for x in s['treatments']}
            comps.append(build_comparison_from_rerun(sd,case=label,data_status='engineering_validated_diagnostic',roles=roles,tmt_path=bundle/f"{s['experiment_code']}.TMT",entries=entries).assign(season=s['season_id']))
        comp=pd.concat(comps,ignore_index=True); comp.to_csv(out/'comparison.csv',index=False); metric(comp).to_csv(out/'metrics.csv',index=False)
        # Final cumulative dry-yield contrasts by water x N, using treatment mapping audit if available later.
        (out/'parameter_source.json').write_text(json.dumps({'source_a':str(A),'source_b':str(B),'source_c':str(C),'averaged_all_common':label=='avg_joint61','selected_for_second':sorted(selected)},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
