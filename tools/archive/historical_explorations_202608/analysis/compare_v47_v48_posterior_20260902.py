"""Read-only run audit: compare actual PST bounds and IES ensemble distributions."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "workspace/reports/v47_v48_posterior_comparison_20260902"
CASES = {
    "v47": ("e02_formal_v47_free_nscale_200x6_20260901", 6),
    "v48": ("e02_formal_v48_n_gradient_water2x_200x4_20260902", 4),
}


def family(name, group):
    if name.startswith("soil_"):
        return "soil"
    if name.startswith(("icns_", "page_", "penv_")):
        return "initial_conditions"
    return "genetic_" + group


def ensemble(path):
    frame = pd.read_csv(path)
    frame.columns = frame.columns.str.lower()
    frame["real_name"] = frame.real_name.astype(str).str.lower()
    frame = frame[frame.real_name.ne("base")].set_index("real_name")
    assert frame.index.is_unique
    assert np.isfinite(frame.to_numpy(float)).all()
    return frame


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frames, loaded, sources, summaries = {}, {}, [], {}
    iteration_rows = []
    derived_rows = []
    for version, (case, final_iteration) in CASES.items():
        run = ROOT / "workspace/runs" / f"{case}_r2"
        pst = pyemu.Pst(str(run / f"{case}.pst"))
        pars = pst.parameter_data[pst.parameter_data.partrans.ne("fixed")].copy()
        prior = ensemble(run / f"{case}.0.par.csv")
        post = ensemble(run / f"{case}.{final_iteration}.par.csv")
        phi = pd.read_csv(run / f"{case}.phi.actual.csv")
        phi_row = phi[phi.iteration.eq(final_iteration)].iloc[-1]
        phi_values = pd.to_numeric(phi_row.reindex(post.index), errors="raise")
        best = str(phi_values.idxmin())
        # These runs save 200 rows including the deterministic base, so there
        # are 199 stochastic members for posterior quantiles and edge mass.
        assert len(prior) == len(post) == 199
        records = []
        for name, p in pars.iterrows():
            lo, hi = float(p.parlbnd), float(p.parubnd)
            span = hi-lo
            v, v0 = post[name], prior[name]
            q = v.quantile([.05, .25, .5, .75, .95])
            z = (v-lo)/span
            rec = dict(name=name, family=family(name, str(p.pargp)),
                       lower=lo, upper=hi, init=p.parval1, best=v.loc[best],
                       mean=v.mean(), sd=v.std(), q05=q.loc[.05], q25=q.loc[.25],
                       median=q.loc[.5], q75=q.loc[.75], q95=q.loc[.95],
                       prior_mean=v0.mean(), prior_median=v0.median(), prior_sd=v0.std(),
                       sd_ratio=v.std()/v0.std(), iqr_span=(q.loc[.75]-q.loc[.25])/span,
                       p90_span=(q.loc[.95]-q.loc[.05])/span,
                       within_update_span=(v.median()-v0.median())/span,
                       best_position=(v.loc[best]-lo)/span,
                       median_position=(v.median()-lo)/span)
            for pct in [2, 5, 10]:
                rec[f"lower_frac_{pct}"] = (z<=pct/100).mean()
                rec[f"upper_frac_{pct}"] = (z>=1-pct/100).mean()
            rec["pressure_5"] = max(rec["lower_frac_5"],rec["upper_frac_5"])
            rec["direction"] = "lower" if rec["lower_frac_5"]>rec["upper_frac_5"] else "upper"
            records.append(rec)
        frame = pd.DataFrame(records).set_index("name")
        frame.to_csv(OUT/f"{version}_posterior_stats.csv",encoding="utf-8-sig")
        frames[version]=frame
        loaded[version]=(run,pst,post,phi_values)
        derived = {
            "NMOBMX_times_NVSMOB": post.nmobmx*post.nvsmob,
            "RTNH4_div_RTNO3": post.rtnh4/post.rtno3,
            "FNPGN2_minus_FNPGN1": post.fnpgn2-post.fnpgn1,
            "initial_SLA_F": post.slavr/post.slaref*post.finref,
        }
        for name, values in derived.items():
            derived_rows.append({"version": version,"quantity": name,
                "q05": values.quantile(.05),"median": values.median(),"q95": values.quantile(.95)})
        for i in range(final_iteration+1):
            e=ensemble(run/f"{case}.{i}.par.csv")
            for name,p in pars.iterrows():
                z=(e[name]-p.parlbnd)/(p.parubnd-p.parlbnd)
                iteration_rows.append(dict(version=version,iteration=i,name=name,
                    median=e[name].median(),q05=e[name].quantile(.05),q95=e[name].quantile(.95),
                    lower_frac_5=(z<=.05).mean(),upper_frac_5=(z>=.95).mean(),sd=e[name].std()))
        summaries[version]={"final_iteration":final_iteration,"n":len(post),"best_member":best,
                            "best_phi":float(phi_values.min()),"mean_phi":float(phi_values.mean()),
                            "family_counts":frame.family.value_counts().to_dict()}
        for suffix in ["pst","0.par.csv",f"{final_iteration}.par.csv","phi.actual.csv"]:
            f=run/f"{case}.{suffix}"
            sources.append({"file":str(f),"sha256":hashlib.sha256(f.read_bytes()).hexdigest()})
    comparison=frames["v47"].join(frames["v48"],lsuffix="_v47",rsuffix="_v48",how="outer")
    assert len(comparison)==120 and comparison.family_v48.notna().all()
    comparison["best_delta"] = comparison.best_v48-comparison.best_v47
    comparison["median_delta"] = comparison.median_v48-comparison.median_v47
    comparison["median_delta_v47_span"] = comparison.median_delta/(comparison.upper_v47-comparison.lower_v47)
    comparison["bounds_changed"] = ~(
        np.isclose(comparison.lower_v47,comparison.lower_v48) &
        np.isclose(comparison.upper_v47,comparison.upper_v48))
    post=loaded["v48"][2]
    comparison["post48_below_old_bound"]=[(post[n]<r.lower_v47-1e-8).mean() for n,r in comparison.iterrows()]
    comparison["post48_above_old_bound"]=[(post[n]>r.upper_v47+1e-8).mean() for n,r in comparison.iterrows()]
    comparison.to_csv(OUT/"parameter_comparison_all.csv",encoding="utf-8-sig")
    genetic=comparison[comparison.family_v48.str.startswith("genetic_")]
    genetic.to_csv(OUT/"genetic_parameter_comparison.csv",encoding="utf-8-sig")
    pd.DataFrame(iteration_rows).to_csv(OUT/"iteration_trajectories.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(derived_rows).to_csv(OUT/"derived_parameter_combinations.csv",index=False,encoding="utf-8-sig")
    corr=post[genetic.index].corr(method="spearman")
    pairs=[{"parameter_1":a,"parameter_2":b,"spearman":corr.loc[a,b]} for j,a in enumerate(corr.index) for b in corr.index[j+1:] if abs(corr.loc[a,b])>=.65]
    pd.DataFrame(pairs,columns=["parameter_1","parameter_2","spearman"]).sort_values("spearman",key=abs,ascending=False).to_csv(OUT/"genetic_correlations.csv",index=False,encoding="utf-8-sig")
    run,pst,post,phi=loaded["v48"]
    case,iteration=CASES["v48"]
    obs=ensemble(run/f"{case}.{iteration}.obs.csv")
    reg=pd.read_csv(run/f"{case}_observation_registry.csv")
    reg.index=reg.obsnme.str.lower()
    residual_phi=obs.sub(reg.obsval,axis=1).mul(reg.weight,axis=1).pow(2)
    assert np.allclose(residual_phi.sum(axis=1).reindex(phi.index),phi,rtol=2e-5)
    scores=pd.DataFrame(index=post.index)
    scores["phi_total"]=residual_phi.sum(axis=1)
    for family_name,tokens in {"phi_N_dose":["NG12S","NG23S","NGCVS"],
                              "phi_N_response":["NRESPS"],"phi_W_response":["WRESPS"],
                              "phi_fresh_cum":["CHFPWS"],"phi_LAI":["LAIDS"]}.items():
        scores[family_name]=residual_phi[reg.index[reg.sim_token.isin(tokens)]].sum(axis=1)
    corr_scores=post[genetic.index].join(scores).corr(method="spearman").loc[genetic.index,scores.columns]
    corr_scores.to_csv(OUT/"genetic_objective_correlations.csv",encoding="utf-8-sig")
    (OUT/"provenance.json").write_text(json.dumps({"runs":summaries,"sources":sources,
        "definitions":{"edge":"within 5% of actual PST range; >=25% members indicates substantial ensemble pressure",
        "quantiles":"empirical 5-95% of retained non-base members, not Bayesian credible interval",
        "sd_ratio":"final ensemble SD / iteration-0 SD in same run",
        "causality":"correlations and multi-parameter changes do not establish causal effects"}},indent=2),encoding="utf-8")
    print(json.dumps(summaries,indent=2))
    print("GENETIC EDGE PRESSURE >=25%")
    print(genetic[genetic.pressure_5_v48.ge(.25)][["best_v47","best_v48","median_v47","median_v48","lower_v48","upper_v48","q05_v48","q95_v48","pressure_5_v48","direction_v48","sd_ratio_v48"]].sort_values("pressure_5_v48",ascending=False).to_string())
    print("LARGEST MEDIAN CHANGES")
    print(genetic.sort_values("median_delta_v47_span",key=abs,ascending=False)[["best_v47","best_v48","median_v47","median_v48","median_delta_v47_span","within_update_span_v48","bounds_changed"]].head(22).to_string())


if __name__=="__main__":
    main()
