"""Compare actual PST bounds and scan validation-only 2025 soil fertility."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import re
import shutil
import sys

import numpy as np
import pandas as pd
import pyemu
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration.sa98_joint40 import extract
from tools.calibration import run_dual_morris98_trial_20261105 as trial
from tools.calibration.grid_dual_morris98_bounds_20261105 import fast_compare
from tools.calibration.restart_dual_morris98_trial_ranges_20261105 import RUN
from tools.reporting.report_sa98_joint40_20261031 import metrics

C31 = "full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927"
OLD = ROOT/"workspace/runs"/C31
OUT = RUN/"c31_bounds_and_25sp_slpf"


def adjustable(row):
    return row.partrans not in {"fixed","tied"} and row.parubnd > row.parlbnd


def compare_bounds(design):
    previous = OLD/f"{C31}.pst"
    current = RUN/"joint/joint.pst"
    manifest = yaml.safe_load((OLD/"run_manifest.yaml").read_text(encoding="utf-8"))
    registry = Path(manifest["bounds_csv"])
    assert trial.native.sha(registry)==manifest["bounds_sha256"]
    old, new = (pyemu.Pst(str(p)).parameter_data for p in (previous,current))
    b = pd.read_csv(design["frozen_bounds"])
    frozen_old = pd.read_csv(registry).set_index("name")
    frozen_old.index = frozen_old.index.str.lower()
    old.index = old.index.str.lower()
    new.index = new.index.str.lower()
    assert set(b.pest_name)==set(new.index)
    rows = []
    for row in b[b.status.eq("active")].itertuples():
        key = row.pest_name
        n = new.loc[key]
        assert adjustable(n) and np.allclose([n.parlbnd,n.parubnd],[row.lower,row.upper],atol=1e-10,rtol=0)
        info = dict(parameter=row.native_name,c31_parameter=key,location=row.location,
                    current_lower=n.parlbnd,current_upper=n.parubnd,current_initial=n.parval1)
        if key not in old.index:
            info["comparison"] = "not_listed_in_c31_pst"
        else:
            o = old.loc[key]
            info.update(c31_transform=o.partrans,c31_initial=o.parval1,c31_lower=o.parlbnd,c31_upper=o.parubnd)
            if key in frozen_old.index:
                f = frozen_old.loc[key]
                info.update(c31_registry_lower=f.lower,c31_registry_upper=f.upper)
            if not adjustable(o):
                info["comparison"] = "current_active_c31_fixed_or_tied"
            else:
                dl,du = n.parlbnd-o.parlbnd,n.parubnd-o.parubnd
                info.update(delta_lower=dl,delta_upper=du,width_ratio=(n.parubnd-n.parlbnd)/(o.parubnd-o.parlbnd))
                if np.allclose([dl,du],[0,0],atol=1e-10,rtol=0):
                    label = "same"
                elif n.parlbnd>o.parubnd or o.parlbnd>n.parubnd:
                    label = "disjoint"
                elif dl<=1e-10 and du>=-1e-10:
                    label = "current_encloses_c31"
                elif dl>=-1e-10 and du<=1e-10:
                    label = "current_within_c31"
                else:
                    label = "overlap_shifted"
                info["comparison"] = label
        if key=="senpor_late":
            info["mapping_note"] = "Same terminal node; C31 also interpolated node 3, current updates node 4 only."
        elif key in ("swbar_rec","yswbar_mid"):
            info["mapping_note"] = "C31 curve anchor corresponds to native node 3; companion settings may differ."
        rows.append(info)
    detail = pd.DataFrame(rows)
    detail.to_csv(OUT/"active_bounds_c31_comparison.csv",index=False)
    only_old = old[old.apply(adjustable,axis=1) & ~old.index.isin(detail.c31_parameter)].copy()
    named = b.set_index("pest_name")
    only_old["current_status"] = only_old.index.map(named.status).fillna("not an independent PST parameter")
    only_old[["partrans","parval1","parlbnd","parubnd","pargp","current_status"]].to_csv(OUT/"c31_only_active.csv")
    return dict(c31_pst=str(previous),current_pst=str(current),c31_manifest_n_params=manifest["n_params"],
                c31_registry_rows=len(frozen_old),
                c31_pst_rows=len(old),c31_adjustable=int(old.apply(adjustable,axis=1).sum()),
                current_adjustable=int(new.apply(adjustable,axis=1).sum()),c31_only_adjustable=len(only_old),
                counts=detail.comparison.value_counts().to_dict(),
                hashes={str(p):trial.native.sha(p) for p in (previous,current,registry)})


def change_profile(path,value):
    rows = path.read_bytes().splitlines(keepends=True)
    header = next(i for i,row in enumerate(rows) if row.startswith(b"@ SCOM"))
    field = list(re.finditer(rb"\S+",rows[header+1]))[6]
    end = field.end()
    assert float(field.group())==.900
    token = f"{value:.3f}".lstrip("0").encode("ascii")
    rows[header+1] = rows[header+1][:end-6]+token.rjust(6)+rows[header+1][end:]
    path.write_bytes(b"".join(rows))


def scan(design,start,stop):
    b = pd.read_csv(design["frozen_bounds"]).rename(columns={"name":"registry_name","native_name":"name"})
    ctx = trial.contexts(RUN,design,b,("25SP",))["25SP"]
    obs = pd.read_csv(RUN/"locked_validation_observations.csv").fillna("")
    saved = pd.read_csv(RUN/"validation_comparison.csv").fillna("")
    values = pd.read_csv(RUN/"best_calibration_parameters.csv").set_index("name").value.to_dict()
    selection = trial.read(RUN/"selection.json")
    assert trial.native.sha(RUN/"best_calibration_parameters.csv")==selection["parameters_sha256"]
    values = trial.values_for(b,values)
    fruit = obs.variable.eq("FRUIT_N_PCT")
    (OUT/"scenarios").mkdir(exist_ok=True)
    (OUT/"scratch").mkdir(exist_ok=True)

    def run_one(code):
        slpf = code/1000
        case = OUT/"scenarios"/str(code)
        case.mkdir(exist_ok=True)
        path = case/"pairs.csv"
        if path.exists():
            return pd.read_csv(path)
        with TemporaryDirectory(prefix=f"slpf{code}_",dir=OUT/"scratch") as tmp:
            scratch = Path(tmp)
            payload, work = scratch/"inputs",scratch/"dssat"
            work.mkdir()
            shutil.copytree(ctx.payload,payload)
            change_profile(payload/"SOIL.SOL",slpf)
            for original in ctx.payload.iterdir():
                if original.name!="SOIL.SOL":
                    assert trial.native.sha(original)==trial.native.sha(payload/original.name)
            trial.simulate(RUN,work,replace(ctx,payload=payload),values)
            q,_ = fast_compare(work,obs[~fruit])
            f = extract(work,obs[fruit],strict=False)
            f.index = obs.index[fruit]
            q = pd.concat([q.assign(comparison_status="matched",model_error=""),f]).sort_index()
            if code==900:
                assert q.comparison_status.tolist()==saved.comparison_status.tolist()
                np.testing.assert_allclose(pd.to_numeric(q.simulated,errors="coerce"),
                                           pd.to_numeric(saved.simulated,errors="coerce"))
            shutil.copy2(work/"SOIL.SOL",case/"SOIL.SOL")
            q = q.assign(SLPF=slpf)
            q.to_csv(path,index=False)
            return q

    with ThreadPoolExecutor(max_workers=6) as pool:
        for code,_ in zip(range(start,stop+1,5),pool.map(run_one,range(start,stop+1,5))):
            print(f"SLPF {code/1000:.3f} complete",flush=True)
    frames = [pd.read_csv(p) for p in sorted((OUT/"scenarios").glob("*/pairs.csv"))]
    pairs = pd.concat(frames,ignore_index=True)
    q = pairs[pairs.variable.isin(("CHFPW","CHPDT"))]
    terminal = q.sort_values("date").groupby(["SLPF","trno","variable"]).tail(1)
    variable = pd.DataFrame([dict(SLPF=s,variable=v,**metrics(f)) for (s,v),f in pairs.groupby(["SLPF","variable"])])
    yield_metrics = pd.DataFrame([dict(SLPF=s,variable=v,**metrics(f)) for (s,v),f in terminal.groupby(["SLPF","variable"])])
    variable.to_csv(OUT/"slpf_variable_metrics.csv",index=False)
    yield_metrics.to_csv(OUT/"slpf_terminal_yield_metrics.csv",index=False)
    terminal.to_csv(OUT/"slpf_terminal_yield_pairs.csv",index=False)
    score = yield_metrics.pivot(index="SLPF",columns="variable",values="RRMSE")
    score["terminal_mean_NRMSE"] = score.mean(axis=1)
    # Equal weights across process families; repeated cumulative outputs and
    # conditional fruit-N stay separate from this process comparison.
    process = [["LAID"],["LWAD","SWAD"],["CHTD"],["LEAF_N_PCT","STEM_N_PCT"],["VWC"],["HFPOW","HPODW"]]
    vm = variable.pivot(index="SLPF",columns="variable",values="RRMSE")
    ratios = vm/vm.loc[.9]
    score["process_mean_relative_NRMSE"] = sum(ratios[f].mean(axis=1) for f in process)/len(process)
    score.to_csv(OUT/"slpf_scores.csv")
    return score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start",type=int,default=900)
    parser.add_argument("--stop",type=int,default=1000)
    args = parser.parse_args()
    assert 900<=args.start<=args.stop<=1050 and args.start%5==args.stop%5==0
    OUT.mkdir(exist_ok=True)
    design = trial.read(RUN/"design.json")
    assert trial.read(RUN/"sealed_design.json")["sha256"]==trial.native.sha(RUN/"design.json")
    for path,digest in design["source_hashes"].items():
        assert trial.native.sha(Path(path))==digest,path
    comparison = compare_bounds(design)
    score = scan(design,args.start,args.stop)
    trial.native.write(OUT/"audit.json",dict(bounds=comparison,selection=trial.read(RUN/"selection.json"),
        design_sha256=trial.native.sha(RUN/"design.json"),slpf_values=score.index.tolist(),
        primary_terminal_best=float(score.terminal_mean_NRMSE.idxmin()),
        process_best=float(score.process_mean_relative_NRMSE.idxmin())))
    print(comparison,flush=True)
    print(score.to_string(),flush=True)


if __name__=="__main__":
    main()
