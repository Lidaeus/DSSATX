"""Verify and aggregate the completed paired, single-seed Morris experiment."""
import argparse
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from run_dual_spring_morris_20261105 import ROOT, RUN_ID, SEED, TRAJECTORIES, sha, status, write


def read_points(run, season, x):
    responses = None
    values = []
    for i, expected in enumerate(x.to_dict("records")):
        p = run/"records"/season/f"point_{i:04d}.json"
        record = json.loads(p.read_text(encoding="utf-8"))
        if record["status"]!="ok" or record["actual"]!=expected:
            raise ValueError(f"Native parameter/point mismatch: {p}")
        keys = list(record["responses"])
        if responses is None:
            responses = keys
        if keys!=responses:
            raise ValueError(f"Response identities changed: {p}")
        values.append(list(record["responses"].values()))
    y = np.asarray(values,dtype=float)
    if not np.isfinite(y).all():
        raise ValueError(f"Invalid required responses in {season}")
    return responses, y


def elementary_effects(x, y, widths):
    k = x.shape[1]
    z = x.reshape(TRAJECTORIES,k+1,k)
    dy = np.diff(y.reshape(TRAJECTORIES,k+1,-1),axis=1)
    dx = np.diff(z,axis=1)/widths
    out = np.empty_like(dy)
    for i, trajectory in enumerate(dx):
        changed = np.abs(trajectory)>1e-12
        if not ((changed.sum(axis=0)==1).all() and (changed.sum(axis=1)==1).all()):
            raise ValueError(f"Incomplete elementary effects in trajectory {i}")
        params = np.argmax(changed,axis=1)
        out[i,params,:] = dy[i]/trajectory[np.arange(k),params,None]
    return out


def weights_for(responses, supported):
    group_families = {}
    for i, key in enumerate(responses):
        process, family, _ = key.split("|")
        group_families.setdefault(process,{}).setdefault(family,[])
        if supported[i]:
            group_families[process][family].append(i)
    weights = np.zeros((len(responses),len(group_families)))
    for j, families in enumerate(group_families.values()):
        nonempty = [ids for ids in families.values() if ids]
        for ids in nonempty:
            weights[ids,j] = 1/(len(nonempty)*len(ids))
    return list(group_families), weights


def relative(effects):
    totals = effects.sum(axis=-2,keepdims=True)
    return np.divide(effects,totals,out=np.zeros_like(effects),where=totals>0)


def stability(a,b):
    ra,rb = rankdata(-a,method="average",axis=-1),rankdata(-b,method="average",axis=-1)
    da,db = ra-ra.mean(axis=-1,keepdims=True),rb-rb.mean(axis=-1,keepdims=True)
    norm = np.sqrt((da**2).sum(axis=-1)*(db**2).sum(axis=-1))
    rho = np.divide((da*db).sum(axis=-1),norm,out=np.full(norm.shape,np.nan),where=norm>0)
    topa = (a>=np.sort(a,axis=-1)[...,-10,None]) & (a>0)
    topb = (b>=np.sort(b,axis=-1)[...,-10,None]) & (b>0)
    intersection = (topa&topb).sum(axis=-1)
    union = (topa|topb).sum(axis=-1)
    j = np.divide(intersection,union,out=np.full(norm.shape,np.nan),where=union>0)
    return ra,rb,rho,topa,topb,intersection,j


def interval(x):
    if not np.isfinite(x).any():
        return np.nan,np.nan
    return np.nanquantile(x,[.025,.975])


def main(run):
    state=json.loads((run/"campaign_status.json").read_text(encoding="utf-8"))
    if state["status"] not in {"simulation_complete","completed"}:
        raise ValueError(f"Model gate incomplete: {state['status']}")
    manifest=json.loads((run/"run_manifest.json").read_text(encoding="utf-8"))
    x_path=run/"morris_X_serialized.csv"
    b_path=run/"approved_bounds.csv"
    assert sha(x_path)==manifest["design_sha256"] and sha(b_path)==manifest["bounds_sha256"]
    b=pd.read_csv(b_path)
    x=pd.read_csv(x_path,index_col="point_id",float_precision="round_trip")
    assert len(x)==TRAJECTORIES*(len(b)+1) and list(x.columns)==b.name.tolist()
    seasons=("25SP","26SP")
    keys, arrays = [], []
    for s in seasons:
        names,y=read_points(run,s,x)
        keys.append(names)
        arrays.append(elementary_effects(x.to_numpy(),y,(b.upper-b.lower).to_numpy()))
    assert keys[0]==keys[1]
    responses=keys[0]
    effects=np.stack(arrays)
    abs_effect=np.abs(effects)
    mu=effects.mean(axis=1)
    ms=abs_effect.mean(axis=1)
    sigma=effects.std(axis=1,ddof=1)
    supported=(ms.sum(axis=1)>0).all(axis=0)
    groups,weights=weights_for(responses,supported)
    scores=(relative(ms)@weights).transpose(0,2,1)
    rank_a,rank_b,rho,top_a,top_b,overlap,j=stability(*scores)
    counts=np.random.default_rng(SEED).multinomial(TRAJECTORIES,np.full(TRAJECTORIES,1/TRAJECTORIES),size=1000)
    boot=[]
    stat_bounds=[]
    boot_valid=np.ones(1000,dtype=bool)
    for season in range(2):
        boot_ms=(counts@abs_effect[season].reshape(TRAJECTORIES,-1)/TRAJECTORIES).reshape(1000,len(b),len(responses))
        stat_bounds.append(np.quantile(boot_ms,[.025,.975],axis=0))
        # A resample that loses a shared response cannot use the original weights.
        boot_valid &= (boot_ms[:,:,supported].sum(axis=1)>0).all(axis=1)
        boot.append((relative(boot_ms)@weights).transpose(0,2,1))
    _,_,rho_boot,_,_,overlap_boot,j_boot=stability(*boot)
    boot = np.asarray(boot)
    boot[:,~boot_valid]=np.nan
    rho_boot[~boot_valid]=np.nan
    overlap_boot=overlap_boot.astype(float)
    overlap_boot[~boot_valid]=np.nan
    j_boot[~boot_valid]=np.nan
    out=run/"results"
    out.mkdir(exist_ok=True)
    pd.DataFrame(dict(response=responses,signal_25SP=ms[0].sum(axis=0)>0,
                      signal_26SP=ms[1].sum(axis=0)>0,paired_ranked=supported)).to_csv(
                          out/"response_signal_audit.csv",index=False)
    np.savez_compressed(out/"elementary_effects.npz",effects=effects,parameters=b.name.to_numpy(str),
                        responses=np.array(responses),seasons=np.array(seasons))
    response_rows=[]
    group_rows=[]
    stability_rows=[]
    for k,g in enumerate(groups):
        lo,hi=interval(rho_boot[:,k])
        jl,jh=interval(j_boot[:,k])
        ol,oh=interval(overlap_boot[:,k])
        stability_rows.append(dict(response_group=g,rho=rho[k],rho_ci_low=lo,rho_ci_high=hi,
                                   overlap=overlap[k],overlap_ci_low=ol,overlap_ci_high=oh,
                                   jaccard=j[k],jaccard_ci_low=jl,jaccard_ci_high=jh,
                                   n_top25=top_a[k].sum(),n_top26=top_b[k].sum(),
                                   shared_top10=";".join(b.name[top_a[k]&top_b[k]]),
                                   valid_paired_bootstrap=int(boot_valid.sum())))
    for i,s in enumerate(seasons):
        rank=(rank_a,rank_b)[i]
        for jpar,name in enumerate(b.name):
            for jresp,response in enumerate(responses):
                response_rows.append(dict(season_id=s,parameter=name,response=response,mu=mu[i,jpar,jresp],
                                          mu_star=ms[i,jpar,jresp],sigma=sigma[i,jpar,jresp],
                                          mu_star_ci_low=stat_bounds[i][0,jpar,jresp],
                                          mu_star_ci_high=stat_bounds[i][1,jpar,jresp],
                                          n_effects=TRAJECTORIES))
            for jgroup,group in enumerate(groups):
                lo,hi=interval(boot[i,:,jgroup,jpar])
                d_lo,d_hi=interval(boot[1,:,jgroup,jpar]-boot[0,:,jgroup,jpar])
                group_rows.append(dict(season_id=s,response_group=group,parameter=name,
                                       group_score=scores[i,jgroup,jpar],rank=rank[jgroup,jpar],
                                       score_ci_low=lo,score_ci_high=hi,
                                       difference_26_minus_25=scores[1,jgroup,jpar]-scores[0,jgroup,jpar],
                                       difference_ci_low=d_lo,difference_ci_high=d_hi,n_seeds=1))
    pd.DataFrame(response_rows).to_csv(out/"morris_response_effects.csv",index=False)
    pd.DataFrame(group_rows).to_csv(out/"morris_process_scores.csv",index=False)
    pd.DataFrame(stability_rows).to_csv(out/"morris_cross_season_stability.csv",index=False)
    selection=manifest.get("conditional_trajectory_selection")
    write(out/"result_manifest.json",dict(status="engineering_reviewed",data_status="science_pending",
          paired_seed=SEED,trajectories_per_season=TRAJECTORIES,n_parameters=len(b),
          paired_responses=int(supported.sum()),total_responses=len(responses),
          valid_paired_bootstrap=int(boot_valid.sum()),conditional_trajectory_selection=selection,
          sha256={p.name:sha(p) for p in sorted(out.iterdir())
                                                          if p.name!="result_manifest.json"}))
    condition={} if selection is None else {"conditional":True,"attempted":selection["attempted"],
                "accepted":TRAJECTORIES,"rejected":selection["rejected"],"coverage":selection["coverage"]}
    status(run,"completed",formal_forward_calls=len(x)*2,pilot_reused=True,
           data_status="science_pending",result_directory=str(out),**condition)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",type=Path,default=ROOT/"workspace/runs"/RUN_ID)
    args=parser.parse_args()
    main(args.run.resolve())
