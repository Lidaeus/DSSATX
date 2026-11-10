"""Independently audit completed paired cases and export review metrics, no rerun."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration import joint_n_objectives as model
from src.calibration import single_season_n as legacy

PAIR = ROOT/"workspace/runs/eggplant_26sp_n012_c31_joint_pair_20261011"
OUT = PAIR/"result_review_20261012"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metrics(part):
    valid=part[part.simulated.notna()].copy()
    y=valid.observed.to_numpy(dtype=float);s=valid.simulated.to_numpy(dtype=float)
    assert np.isfinite(y).all() and np.isfinite(s).all()
    if not len(valid):return dict(n_total=len(part),n=0,n_unmatched=len(part))
    residual=s-y;ss=float(np.square(residual).sum());mean=float(y.mean())
    rmse=float(np.sqrt(ss/len(y)));d_denom=float(np.square(np.abs(s-mean)+np.abs(y-mean)).sum())
    nse_denom=float(np.square(y-mean).sum())
    return dict(n_total=len(part),n=len(valid),n_unmatched=len(part)-len(valid),
                unit=valid.unit.iloc[0],observed_mean=mean,simulated_mean=float(s.mean()),
                rmse=rmse,nrmse_pct=100*rmse/abs(mean) if mean else None,
                d_index=1-ss/d_denom if d_denom else None,nse=1-ss/nse_denom if nse_denom else None,
                mean_bias=float(residual.mean()),relative_mean_bias_pct=100*float(residual.mean())/abs(mean) if mean else None,
                weighted_phi=float(np.square(residual*valid.final_weight.to_numpy(dtype=float)).sum())
                if "final_weight" in valid else None)


def main():
    OUT.mkdir(exist_ok=True)
    source=ROOT/"configs/calibration_proposals/eggplant_26sp_n012_review_20261011/observation_catalog.csv"
    catalog=pd.read_csv(source).fillna("")
    hashes={str(source.relative_to(ROOT)).replace("\\","/"):digest(source)}
    all_metrics=[];terminal_rows=[];responses=[];bounds_rows=[];events=[];failures=[];summaries=[];phi_families=[]
    for n in (42,67):
        run_id=f"eggplant_26sp_n012_c31_joint{n}_20261011"
        run=ROOT/"workspace/runs"/run_id;config=ROOT/"configs/runs"/run_id
        design,bounds,obs=model.load_design(config/"design.json")
        values=legacy.runner._read_param_dict(run/"final_parameters.csv")
        model.validate_parameters(values,bounds)
        compared=pd.read_csv(run/"selected_deterministic/last_comparison.csv").fillna("")
        reread=model.extract_observations(run/"selected_deterministic/_model",obs)
        assert compared.obsnme.tolist()==obs.obsnme.tolist() and np.allclose(compared.simulated,reread.simulated)
        assert np.allclose(compared.final_weight,obs.final_weight) and np.allclose(compared.observed,obs.observed)
        assert len(compared)==492
        phi=float(np.square((compared.simulated-compared.observed)*compared.final_weight).sum())
        selection=json.loads((run/"selection.json").read_text(encoding="utf-8"))
        assert np.isclose(phi,selection["phi"],rtol=1e-10)
        selected=pd.read_csv(run/f"joint/joint.{selection['iteration']}.obs.csv",index_col=0)
        selected.index=selected.index.astype(str)
        ensemble_values=selected.loc[selection["realization"],obs.obsnme].to_numpy(dtype=float)
        native_values=compared.simulated.to_numpy(dtype=float)
        # Some PEST ensemble exports print six significant digits; verify that
        # representation explicitly rather than allowing unexplained drift.
        printed_six=np.array([float(f"{x:.6g}") for x in native_values])
        assert (np.isclose(ensemble_values,native_values,rtol=1e-10,atol=1e-10)
                | np.isclose(ensemble_values,printed_six,rtol=1e-10,atol=1e-10)).all()
        selection_table=pd.read_csv(run/"selection_audit.csv")
        assert np.isclose(selection_table.phi.min(),phi,rtol=1e-6)
        initial=pd.read_csv(run/"preflight/baseline/last_comparison.csv")
        initial_phi=float(np.square((initial.simulated-initial.observed)*initial.final_weight).sum())
        extra=catalog[(catalog.season_id=="26SP")&(catalog.dataset_role=="calibration")&catalog.variable.isin(["CHFPW","HFPOW"])].copy()
        extra=legacy.extract_observations(run/"selected_deterministic/_model",extra)
        extra["final_weight"]=0.; extra["dataset_role"]="calibration_diagnostic"
        evaluated=pd.read_csv(run/"evaluation_comparison.csv")
        for label,frame in [("initial",initial),("calibration",compared),("calibration_diagnostic",extra),("evaluation",evaluated)]:
            for (season,role,variable),group in frame.groupby(["season_id","dataset_role","variable"]):
                all_metrics.append(dict(version=n,run_id=run_id,comparison=label,season_id=season,dataset_role=role,variable=variable,**metrics(group)))
        harvest=pd.concat([compared[compared.variable.eq("CHPDT")],extra[extra.variable.eq("CHFPW")],evaluated[evaluated.variable.isin(["CHPDT","CHFPW"])]],ignore_index=True)
        final=harvest.sort_values("date").groupby(["season_id","dataset_role","variable","trno"]).tail(1)
        final=final.assign(version=n,run_id=run_id)
        terminal_rows.append(final)
        for (season,role,var),g in final.groupby(["season_id","dataset_role","variable"]):
            all_metrics.append(dict(version=n,run_id=run_id,comparison="terminal_harvest",season_id=season,dataset_role=role,variable=var,**metrics(g)))
        responses.append(compared[compared.variable.isin(model.SIGNED|{"N2_SIGN_PENALTY"})].assign(version=n,run_id=run_id))
        for family,g in compared.groupby("family"):
            contribution=float(np.square((g.simulated-g.observed)*g.final_weight).sum())
            phi_families.append(dict(version=n,family=family,n=len(g),budget=g.phi_budget.iloc[0],phi=contribution,actual_phi_pct=100*contribution/phi))
        review=bounds.copy();review["value"]=review.name.map(values)
        review["position_in_range"]=(review.value-review.lower)/(review.upper-review.lower).replace(0,np.nan)
        review["near_bound_2pct"]=review.status.eq("active")&((review.position_in_range<=.02)|(review.position_in_range>=.98))
        review["version"]=n;bounds_rows.append(review)
        status=json.loads((run/"joint/run_status.json").read_text(encoding="utf-8"))
        quality=json.loads((run/"joint/ies_quality/ies_run_quality.json").read_text(encoding="utf-8"))
        member=pd.read_csv(run/"joint/ies_quality/joint.member_status.csv")
        assert member.initial_present.sum()==200
        per_iteration=pd.read_csv(run/"joint/joint.phi.actual.csv")
        for row in per_iteration.itertuples():
            count=len(pd.read_csv(run/f"joint/joint.{row.iteration}.obs.csv",index_col=0))
            events.append(dict(version=n,iteration=row.iteration,n_retained=count,total_runs=row.total_runs,mean_phi=row.mean,min_phi=row.min,max_phi=row.max))
        counts=Counter()
        for log in (run/"joint/_agents").glob("agent_*/panther_agent.stderr.log"):
            hashes[str(log.relative_to(ROOT)).replace("\\","/")]=digest(log)
            for line in log.read_text(encoding="utf-8",errors="replace").splitlines():
                if not re.match(r"^(ValueError|RuntimeError|KeyError|FileNotFoundError|PermissionError|OSError):",line):continue
                if "No mature fruit" in line:
                    if "treatment=" not in line:continue
                    kind="NoMatureFruit"
                elif "Malformed Evaluate" in line:kind="MalformedEvaluate"
                else:kind=line.split(":",1)[0]+":"+line.split(":",1)[1].strip().split(";")[0]
                counts[kind]+=1
        for reason,count in counts.items():failures.append(dict(version=n,reason=reason,exception_event_count=count,count_definition="terminal exception lines; includes rejected trial calls, not unique lost realizations"))
        summary=dict(version=n,run_id=run_id,process_status=status["status"],engineering_status=status["engineering_status"],
                     final_phi=phi,initial_anchor_phi=initial_phi,initial_to_final_reduction_pct=100*(1-phi/initial_phi),
                     iteration=selection["iteration"],realization=selection["realization"],validation_used_for_selection=selection["validation_used"],
                     retained=int(member.final_status.eq("retained").sum()),lost=int(member.final_status.eq("model_failed").sum()),
                     near_bound_parameters=int(review.near_bound_2pct.sum()),quality_failures=[x for x in quality["checks"] if x["status"]=="fail"],
                     exception_events=dict(counts),missing_evaluation_rows=int(evaluated.simulated.isna().sum()),
                     started_at=status["started_at"],finished_at=json.loads((run/"pipeline_status.json").read_text(encoding="utf-8"))["finished_at"],
                     final_parameters_sha256=digest(run/"final_parameters.csv"),scientific_review="needs_revision_candidate_only")
        summaries.append(summary)
        input_files=[config/"design.json",config/"calibration_observations.csv",run/"final_parameters.csv",run/"selection.json",run/"selection_audit.csv",
                     run/"selected_deterministic/last_comparison.csv",run/"evaluation_comparison.csv",run/"joint/run_status.json",
                     run/"joint/ies_quality/ies_run_quality.json",run/"joint/ies_quality/joint.member_status.csv",run/"joint/joint.phi.actual.csv"]
        for path in input_files:hashes[str(path.relative_to(ROOT)).replace("\\","/")]=digest(path)
    pd.DataFrame(all_metrics).to_csv(OUT/"metrics.csv",index=False,encoding="utf-8-sig")
    pd.concat(terminal_rows,ignore_index=True).to_csv(OUT/"terminal_harvest_pairs.csv",index=False,encoding="utf-8-sig")
    pd.concat(responses,ignore_index=True).to_csv(OUT/"response_pairs.csv",index=False,encoding="utf-8-sig")
    pd.concat(bounds_rows,ignore_index=True).to_csv(OUT/"parameter_review.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(events).to_csv(OUT/"iteration_events.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(failures).to_csv(OUT/"failure_events.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(phi_families).to_csv(OUT/"family_phi.csv",index=False,encoding="utf-8-sig")
    review=dict(status="completed_not_engineering_validated",scientific_review="needs_revision",cases=summaries,
                metrics_definition="NRMSE=100*RMSE/abs(mean observed); d=Willmott; residual=simulated-observed; unmatched retained in coverage counts",
                source_hashes=hashes,source_files_unchanged=True,no_new_calibration_launched=True)
    for rel,expected in hashes.items():assert digest(ROOT/rel)==expected,rel
    legacy.write_json(OUT/"result_summary.json",review)
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
