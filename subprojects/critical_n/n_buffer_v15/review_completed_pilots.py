"""Independent post-run verification and interpretation, no new calibration."""
from pathlib import Path
import json,hashlib,sys
import pandas as pd
import numpy as np
V=Path(__file__).resolve().parent;ROOT=V.parent;OUT=V/'evidence/final'
sys.path.insert(0,str(V));import protocol as pr
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def main():
    audits=json.loads((OUT/'pilot_audits.json').read_text());plans=json.loads((V/'configs/registered_pilots.json').read_text())['pilots']
    old=json.loads((ROOT/'reports/leaf_n_valley_audit_20261028/reruns/latest_A/last_success.json').read_text())
    cases=[('V14_baseline',Path(old['trial']),old['parameters'])]
    verification={};contrib=[];valleys=[];parameters=[]
    for a,p in zip(audits,plans):
        d=json.loads(Path(p['design']).read_text());run=V/'runs'/p['run_id']
        assert all(sha(f)==h for f,h in d['frozen_hashes'].items())
        assert sha(d['binary'])==a['binary_sha256'] and sha(run/'best_parameters.csv')==a['parameter_sha256']
        values=pd.read_csv(run/'best_parameters.csv').set_index('name').value.to_dict();pr.validate(values,pd.read_csv(d['bounds']))
        q=json.loads((Path(a['selected_replay_trial'])/'receipt.json').read_text());assert q['success']
        verification[a['mechanism']]={s:pr.physics(Path(a['selected_replay_trial'])/s,ds['treatments'],True)for ds in d['datasets']for s in [ds['season_id']]}
        cases.append((a['mechanism'],Path(a['selected_replay_trial']),values))
    reference=pd.read_csv(cases[0][1]/'comparison.csv').set_index('obsnme').sort_index()
    for model,trial,params in cases:
        c=pd.read_csv(trial/'comparison.csv').set_index('obsnme').sort_index()
        assert len(c)==1079 and c.index.equals(reference.index)
        for name in ['observed','final_weight','fit_scale','huber_delta']:assert np.array_equal(c[name].values,reference[name].values),name
        encoded=pr.encode(c.reset_index());phi=float(encoded.phi_contribution.sum())
        expected=old['phi']if model=='V14_baseline'else next(a['selected_replay_phi']for a in audits if a['mechanism']==model)
        assert np.isclose(phi,expected,rtol=1e-12)
        z=encoded.groupby(['season_id','family']).phi_contribution.sum().reset_index();z['model']=model;contrib.append(z)
        for n in ['EM-V1','TRIFL','VSSINK','SIZLF','NB_KMOB','NB_KFILL','NB_ALPHA_H','NB_ALPHA_L','PROLFI','PROLFG','PROLFF','ICMP','TCMP']:
            parameters.append(dict(model=model,name=n,value=params[n]))
        for season,plant in [('26SP','2026-03-14'),('25SP','2025-03-16')]:
            state=pd.read_csv(trial/season/'OrganNState.csv');state['date']=pd.to_datetime(state.yrdoy.astype(int).astype(str),format='%Y%j');state['dap']=(state.date-pd.Timestamp(plant)).dt.days
            state['pct']=100*state.leaf_n/state.leaf_dm
            for trt,g in state.groupby('trt'):
                pre=g[g.dap.between(15,28)];mid=g[g.dap.between(29,45)];post=g[g.dap.between(46,70)]
                peak=pre.loc[pre.pct.idxmax()];low=mid.loc[mid.pct.idxmin()];high=post.loc[post.pct.idxmax()]
                valleys.append(dict(model=model,season_id=season,trt=int(trt),peak_DAP=int(peak.dap),low_DAP=int(low.dap),drop_pp=float(peak.pct-low.pct),rebound_pp=float(high.pct-low.pct)))
    val=pd.DataFrame(valleys);val.to_csv(OUT/'review_valley_by_treatment.csv',index=False)
    ranges=val.groupby(['model','season_id']).agg(drop_min=('drop_pp','min'),drop_max=('drop_pp','max'),drop_mean=('drop_pp','mean'),rebound_mean=('rebound_pp','mean')).reset_index();ranges.to_csv(OUT/'review_valley_ranges.csv',index=False)
    cont=pd.concat(contrib);cont.to_csv(OUT/'review_phi_by_family.csv',index=False)
    changes=cont.pivot(index=['season_id','family'],columns='model',values='phi_contribution')
    for m in [a['mechanism']for a in audits]:changes[m+'_delta']=changes[m]-changes.V14_baseline
    changes.to_csv(OUT/'review_phi_changes.csv')
    pd.DataFrame(parameters).pivot(index='name',columns='model',values='value').to_csv(OUT/'review_parameter_changes.csv')
    from finish_pilots import m
    final_rows=[]
    for model,trial,params in cases:
        c=pd.read_csv(trial/'comparison.csv');g=c[c.family.isin(['CANOPY_LAI','LEAF_DRY_MASS','STEM_DRY_MASS','HEIGHT'])].copy()
        g=g[g.date==g.groupby(['season_id','family','trno']).date.transform('max')]
        z=m.metrics(g);z['model']=model;z['scope']='last observed date per treatment, not necessarily physiological maturity';final_rows.append(z)
    pd.concat(final_rows).to_csv(OUT/'review_last_observation_metrics.csv',index=False)
    for name in ['data_manifest.json','figure_manifest.json']:
        man=json.loads((OUT/name).read_text())
        assert all(sha(OUT/a['path'])==a['sha256']for a in man['artifacts'])
    assert sha(ROOT/'n_buffer_v13/bin/capacity_a.exe')==old['binary_sha256']
    preserved=json.loads((ROOT/'reports/leaf_n_valley_audit_20261028/baseline_rerun_receipts.json').read_text())[0]
    assert sha(Path(preserved['parameter_source']))==preserved['parameter_sha256']
    dump(OUT/'independent_review_verification.json',dict(passed=True,physics_recomputed=verification,complete_common_1079_targets=True,identical_observed_weights_scales=True,Phi_recomputed=True,all_forward_dependencies_unchanged=True,data_and_figure_hashes_passed=True,no_new_guardrails=True))
    print(ranges.to_string(index=False));print('\nPhi changes biggest beneficial/adverse for combination:')
    column='v15_s2_weighted_joint_delta';print(changes.sort_values(column)[[column]].head(6).to_string());print(changes.sort_values(column)[[column]].tail(6).to_string())
    print('\nParameter changes:');print(pd.read_csv(OUT/'review_parameter_changes.csv').to_string(index=False))
if __name__=='__main__':main()
