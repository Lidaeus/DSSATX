"""Read-only v49 result audit. Writes only new analytical summaries, never runs models."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.calibration.run_v49_mechanism_multiarm_20260902 import OUT, ARMS, COMMON, paths, anchor_values
from tools.analysis.evaluate_v49_mechanism_20260902 import guard, mechanism_gate

DEST = OUT / "result_review"


def scores(o, s):
    o, s = np.array(o, float), np.array(s, float)
    valid = np.isfinite(o) & np.isfinite(s) & (o != -99) & (s != -99)
    o, s = o[valid], s[valid]
    e = s-o
    rmse = np.sqrt(np.mean(e*e))
    sst = np.sum((o-o.mean())**2)
    return dict(n=len(o), rmse=rmse, nse=1-np.sum(e*e)/sst if sst>0 else np.nan,
                rrmse_pct=100*rmse/o.mean() if o.mean()>0 else np.nan, bias=e.mean())


def member_metrics(reg, pred, meta):
    raw = pred.reindex(reg.index).astype(float).copy()
    log = reg["transform"].eq("log")
    raw.loc[log] = np.exp(raw.loc[log])*reg.loc[log,"transform_reference"]-reg.loc[log,"transform_offset"]
    rows=[]
    for season,g in reg.groupby("season_id"):
        for label, mask in {
            "FRESH_CUM": g.sim_token.isin(["CHFPWS","CHFPWS_T"]),
            "FRESH_TERMINAL":g.sim_token.eq("CHFPWS"), "LAID":g.sim_token.eq("LAIDS")}.items():
            subset=g[mask]
            rows.append(dict(season=season,variable=label,**scores(subset.raw_obsval,raw.loc[subset.index])))
        lai=g[g.sim_token.eq("LAIDS")].copy()
        lai["date"]=lai.index.str.extract(r"_d(\d+)",expand=False).astype(int)
        dates=sorted(lai.date.unique())
        for label,days in {"LAID_early":dates[:1],"LAID_late":dates[-2:]}.items():
            ss=lai[lai.date.isin(days)]
            rows.append(dict(season=season,variable=label,**scores(ss.raw_obsval,raw.loc[ss.index])))
        for token,dim in [("NRESPS","water_level"),("WRESPS","nitrogen_level")]:
            ss=g[g.sim_token.eq(token)].copy()
            ss["stratum"]=[meta.loc[(season,int(t)),dim] for t in ss.treatment]
            for stratum, gg in ss.groupby("stratum"):
                rows.append(dict(season=season,variable=token+"_"+stratum,**scores(gg.raw_obsval,raw.loc[gg.index])))
    result = pd.DataFrame(rows)
    result.loc[result.variable.eq('FRESH_TERMINAL'), 'nse'] = np.nan
    return result


def main():
    DEST.mkdir(exist_ok=True)
    state=json.loads((OUT/'queue_status.json').read_text(encoding='utf-8'))
    seal=json.loads((OUT/'execution_seal.json').read_text(encoding='utf-8'))
    changed=[x['path'] for x in seal['files'] if hashlib.sha256(Path(x['path']).read_bytes()).hexdigest()!=x['sha256']]
    meta=pd.read_csv(ROOT/'configs/runs/e02_mapping_26sp_w2_w1_20260830.csv').set_index(['season_id','treatment'])
    base=pd.read_csv(OUT/'A_ic_control/anchor/fit_metrics.csv')
    control=pd.read_csv(OUT/'A_ic_control/lowest_phi/fit_metrics.csv')
    overview=[]; pressures=[]; all_metrics=[]; families=[]; checks=[]; screen=[]; history=[]
    root=OUT/'A_ic_control/anchor'
    f=pd.read_csv(root/'objective_residuals.csv')
    anchor_phi=float(f.actual_phi.sum())
    for arm in ['anchor']+list(ARMS):
        if arm=='F_water_podset': continue
        det=root if arm=='anchor' else OUT/arm/'lowest_phi'
        fit=pd.read_csv(det/'fit_metrics.csv'); fit.insert(0,'arm',arm); all_metrics.append(fit)
        res=pd.read_csv(det/'objective_residuals.csv')
        res['family']=res.sim_token.str.replace(r'^SW\d+S$','SOIL_WATER',regex=True)
        group=res.groupby(['season_id','family']).actual_phi.sum().reset_index();group.insert(0,'arm',arm);families.append(group)
        summ={} if arm=='anchor' else json.loads((OUT/arm/'candidate_summary.json').read_text(encoding='utf-8'))
        record=dict(arm=arm,member='55' if arm=='anchor' else summ['member'],phi=res.actual_phi.sum())
        for season in ['25SP','26SP']:
            for var,metric in [('FRESH_CUM','nse'),('FRESH_TERMINAL','rrmse_pct'),('LAID','nse'),('LAID_late','rmse')]:
                record[f'{season}_{var}_{metric}']=float(fit[(fit.season==season)&(fit.variable==var)][metric].iloc[0])
        if arm!='anchor':
            case,run,_,_=paths(arm)
            status=json.loads((run/'run_status.json').read_text(encoding='utf-8'))
            pst=pyemu.Pst(str(run/(case+'.pst')))
            p=pd.read_csv(run/f'{case}.3.par.csv',index_col=0);p.index=p.index.astype(str)
            obs=pd.read_csv(run/f'{case}.3.obs.csv',index_col=0);obs.index=obs.index.astype(str)
            ph=pd.read_csv(run/f'{case}.phi.actual.csv')
            for rr in ph.itertuples(): history.append(dict(arm=arm,iteration=rr.iteration,mean=rr.mean,min=rr.min,max=rr.max,total_runs=rr.total_runs))
            active=pst.parameter_data[pst.parameter_data.partrans.ne('fixed')]
            fixed=pst.parameter_data[pst.parameter_data.partrans.eq('fixed')]
            drift=max(float((p[n]-anchor_values()[n]).abs().max()) for n in fixed.index)
            selected=str(summ['member'])
            ens=obs.loc[selected,res.obsnme].to_numpy(float)
            replay=res.simulated.to_numpy(float)
            calc=float(np.sum(((ens-res.obsval.to_numpy(float))*res.weight.to_numpy(float))**2))
            check=dict(arm=arm,status=status['status'],engineering=status['engineering_status'],scientific=status['scientific_status'],final_n=len(p),n_active=len(active),fixed_max_drift=drift,
                       replay_max_difference=float(np.max(np.abs(ens-replay))),ensemble_phi_recomputed=calc,deterministic_phi=record['phi'],phi_reported=summ['ensemble_phi'])
            checks.append(check)
            for name,pr in active.iterrows():
                v=p.loc[p.index!='base',name].astype(float);pos=(v-pr.parlbnd)/(pr.parubnd-pr.parlbnd)
                q=v.quantile([.05,.5,.95])
                pressures.append(dict(arm=arm,name=name,anchor=anchor_values()[name],best=p.loc[selected,name],lower=pr.parlbnd,upper=pr.parubnd,p05=q.loc[.05],median=q.loc[.5],p95=q.loc[.95],lower_5pct=float((pos<=.05).mean()),upper_5pct=float((pos>=.95).mean()),std=float(v.std())))
            reg=res.set_index('obsnme')
            iterations=[]
            for iteration in range(4):
                it_obs=pd.read_csv(run/f'{case}.{iteration}.obs.csv',index_col=0)
                it_obs.index=it_obs.index.astype(str)
                it_obs['audit_iteration']=iteration
                iterations.append(it_obs)
            for member,pred in pd.concat(iterations).iterrows():
                mm=member_metrics(reg,pred,meta)
                guard0=guard(mm,base); guardA=guard(mm,control)
                mech0=mechanism_gate(arm,mm,base); mechA=mechanism_gate(arm,mm,control)
                fresh_phi=float(np.sum(((pred[reg.index].to_numpy(float)-reg.obsval.to_numpy(float))*reg.weight.to_numpy(float))**2))
                grad=reg.sim_token.isin(['NG12S','NG23S','NGCVS'])
                grad_phi=float(np.sum(((pred[reg.index[grad]].to_numpy(float)-reg.loc[grad,'obsval'].to_numpy(float))*reg.loc[grad,'weight'].to_numpy(float))**2))
                row=dict(arm=arm,iteration=int(pred['audit_iteration']),member=member,phi=fresh_phi,gradient_phi=grad_phi,scale_pass_anchor=guard0['scale_canopy_pass'],scale_pass_A=guardA['scale_canopy_pass'],target_pass_anchor=mech0['mechanism_target_pass'],target_pass_A=mechA['mechanism_target_pass'])
                for tag,mech in [('anchor',mech0),('A',mechA)]:
                    nr=[r['rmse_improvement_fraction'] for r in mech['response_changes'] if r['season']=='26SP' and r['variable'].startswith('NRESPS')]
                    row[f'n26_improve_{tag}']=np.mean(nr)
                    row[f'lai26_late_improve_{tag}']=mech['26SP_late_LAI_rmse_improvement_fraction']
                screen.append(row)
            if summ['gates'].get('fixed_member55'):
                g=summ['gates']['fixed_member55'];record['scale_pass']=g['scale_canopy_pass'];record['target_pass']=g['mechanism_target_pass']
        overview.append(record)
    for name,frame in [('overview',pd.DataFrame(overview)),('posterior_pressure',pd.DataFrame(pressures)),('fit_metrics',pd.concat(all_metrics)),('phi_components',pd.concat(families)),('audit',pd.DataFrame(checks)),('ensemble_screen',pd.DataFrame(screen)),('phi_history',pd.DataFrame(history))]:
        frame.to_csv(DEST/(name+'.csv'),index=False)
    (DEST/'provenance.json').write_text(json.dumps(dict(source=str(OUT),seal_changed_files=changed,anchor_phi=anchor_phi,scope='read-only analysis, no new DSSAT or PEST runs; final ensemble screen is provisional until deterministic replay'),ensure_ascii=False,indent=2),encoding='utf-8')
    print(pd.DataFrame(overview).to_string(index=False))
    print('\nAUDIT\n',pd.DataFrame(checks).to_string(index=False))
    print('\nPRESSURE\n',pd.DataFrame(pressures).round(5).to_string(index=False))
    sc=pd.DataFrame(screen)
    print('\nSCREEN\n',sc.groupby('arm').agg(n=('member','size'),scale=('scale_pass_anchor','sum'),best_n26=('n26_improve_anchor','max'),best_lai26late=('lai26_late_improve_anchor','max'),target=('target_pass_anchor','sum')).to_string())
    print('\nSEALED CHANGES',changed)


if __name__=='__main__': main()
