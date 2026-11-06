"""Counterfactual process grids around joint67; never modifies frozen inputs/runs."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import itertools
import json
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration import single_season_n as legacy
from src.calibration import joint_n_objectives as joint
from src.dssat.forward_joint import inject_phosphorus
from src.dssat import run_dssat as runner
from src.common.param_registry import PHYSICAL_BOUNDS

OUT=ROOT/"workspace/experiments/joint67_water_n_diagnosis_20261012"
CONFIG=ROOT/"configs/runs/eggplant_26sp_n012_c31_joint67_20261011"
PARAMS=ROOT/"workspace/runs/eggplant_26sp_n012_c31_joint67_20261011/final_parameters.csv"


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def cases():
    rows=[dict(case_id="baseline",family="baseline")]
    for kep,rwu in itertools.product([.35,.50,.70,.85],[.008,.012,.020,.030,.040,.050,.060]):
        rows.append(dict(case_id=f"water_k{kep:.2f}_r{rwu:.3f}",family="KEP_RWUMX",KEP=kep,RWUMX=rwu))
    for kep,slu in itertools.product([.35,.50,.70,.85],[2.,5.5,8.,10.]):
        rows.append(dict(case_id=f"evap_k{kep:.2f}_s{slu:.1f}",family="KEP_SLU1",KEP=kep,SLU1=slu))
    for fn,stable in itertools.product([0.,.50,.75,1.,1.25],[None,.80,.90,.95,.98]):
        rows.append(dict(case_id=f"soil_n{fn:.2f}_c{stable if stable is not None else 'default'}",family="ICN_SASC",ICN_scale=fn,SASC_ratio=stable))
    for fu,ln in itertools.product([.5,.75,1.,1.25],[5.5,6.,6.5]):
        rows.append(dict(case_id=f"uptake_u{fu:.2f}_ln{ln:.1f}",family="N_uptake_LNREF",N_uptake_scale=fu,LNREF=ln))
    for key,levels in [("EORATIO",[.75,1.25,1.5]),("SLNF",[.5,1.5]),("NREXP",[.4,.8,1.])]:
        for v in levels:rows.append(dict(case_id=f"probe_{key}_{v}",family="method_effect_probe",**{key:v}))
    rows.extend([dict(case_id="IC_equal_water_0_100",family="IC_counterfactual",equal_water=True),
                 dict(case_id="IC_equal_water_25SP_only",family="IC_counterfactual",equal_water=True,only_season="25SP")])
    return rows


def patch_inputs(work,dataset,case):
    filex=work/(dataset["experiment_code"]+".TMX")
    text=filex.read_text();lines=text.splitlines(keepends=True)
    metadata=pd.read_csv(ROOT/dataset["bundle_path"]/"treatment_metadata.csv").set_index("treatment")
    ic={};section=None
    for line in lines:
        if line.startswith("*"):section=line.strip()
        if section=="*INITIAL CONDITIONS" and re.match(r"\s*\d+\s+\d+\s+[.\d]+\s+",line):
            parts=line.split()
            if len(parts)>=5:ic[(int(parts[0]),int(parts[1]))]=float(parts[2])
    edited=[];count={"initial_N":0,"initial_water":0,"stable_C":0}
    section=None
    for line in lines:
        if line.startswith("*"):section=line.strip()
        parts=line.split()
        if section=="*INITIAL CONDITIONS" and len(parts)>=5 and re.match(r"^\d+$",parts[0]) and re.match(r"^\d+$",parts[1]):
            tn,depth=int(parts[0]),int(parts[1]);water,nh4,no3=map(float,parts[2:5])
            if "ICN_scale" in case:
                nh4*=case["ICN_scale"];no3*=case["ICN_scale"];count["initial_N"]+=1
            if case.get("equal_water") and depth<=100 and (not case.get("only_season") or case["only_season"]==dataset["season_id"]):
                n=metadata.loc[tn,"nitrogen_level"]
                matched=int(metadata[(metadata.nitrogen_level==n)&(metadata.water_level=="W3")].index[0])
                water=ic[(matched,depth)];count["initial_water"]+=1
            if "ICN_scale" in case or case.get("equal_water"):
                line=f"{tn:2d}{depth:6d}{water:6.3f}{nh4:6.2f}{no3:6.2f}"+line[26:]
        if section=="*SOIL ANALYSIS" and case.get("SASC_ratio") is not None and len(parts)==10 and parts[0].isdigit() and parts[1].isdigit():
            stable=float(parts[3])*case["SASC_ratio"]
            line=line[:50]+f"{stable:6.3f}"+line[56:];count["stable_C"]+=1
        edited.append(line)
    filex.write_text("".join(edited))
    sol=work/"SOIL.SOL";lines=sol.read_text().splitlines(keepends=True)
    for i,line in enumerate(lines):
        if line.startswith("@ SCOM"):
            data=lines[i+1];parts=data.split()
            if "SLU1" in case:parts[2]=f"{case['SLU1']:.2f}"
            if "SLNF" in case:parts[5]=f"{case['SLNF']:.2f}"
            if "SLU1" in case or "SLNF" in case:
                lines[i+1]="".join(f"{v:>6}" for v in parts)+"\n"
    sol.write_text("".join(lines))
    return count


def patch_evap_spe(path,case):
    lines=Path(path).read_text().splitlines(keepends=True)
    for i,line in enumerate(lines):
        if "KEP, EORATIO" in line:
            old=[float(x) for x in line.split("KEP,")[0].split()]
            kep=case.get("KEP",old[0]);ratio=case.get("EORATIO",old[1])
            marker=line.index("KEP,");prefix=f"{kep:6.2f}{ratio:6.2f}".ljust(marker)
            lines[i]=prefix+line[marker:]
    Path(path).write_text("".join(lines))


def worker(case_id,season):
    manifest=json.loads((OUT/"experiment_manifest.json").read_text(encoding="utf-8"))
    case=next(x for x in manifest["cases"] if x["case_id"]==case_id)
    dataset=next(x for x in manifest["datasets"] if x["season_id"]==season)
    treatments=dataset["roles"].get("calibration",dataset["roles"].get("validation"))
    work=OUT/"cases"/case_id/season;work.mkdir(parents=True,exist_ok=True)
    runner.prepare_run_directory(work,["--input-dir",str(ROOT/dataset["bundle_path"]),"--batch","DSSBatch.v48"])
    # All operations below occur in this isolated worker process/directory.
    import os
    os.chdir(work)
    legacy.prepare_inputs(work,dataset,treatments)
    values=runner._read_param_dict(PARAMS)
    values.update(case.get("gene_overrides",{}))
    for name in ("RWUMX","LNREF","NREXP"):
        if name in case:values[name]=float(case[name])
    if "N_uptake_scale" in case:
        for name in ("RTNO3","RTNH4"):values[name]*=case["N_uptake_scale"]
    for name,val in values.items():
        if name in PHYSICAL_BOUNDS:
            low,high=PHYSICAL_BOUNDS[name]
            if not low<=val<=high:raise ValueError(f"Diagnostic outside physical hard bounds: {name}")
    pd.DataFrame(values.items(),columns=["name","value"]).to_csv("parameters.csv",index=False)
    runner.update_cul_file("parameters.csv",target_cultivar="TM0008")
    runner.update_eco_file("parameters.csv",target_ecotype="TM0001")
    runner.update_spe_file("parameters.csv")
    inject_phosphorus("TMGRO048.SPE",values)
    runner.update_soil_file("parameters.csv",batch_file="DSSBatch.v48")
    patch_evap_spe("TMGRO048.SPE",case)
    changes=patch_inputs(work,dataset,case)
    runner._write_dssatpro_with_crd("DSSATPRO.v48","DSSATPRO.v48",str(work))
    with (work/"native_model.log").open("w",encoding="utf-8") as handle:
        result=subprocess.run([str(work/"DSCSM048.EXE"),"CRGRO048","B","DSSBatch.v48"],cwd=work,input="\n"*8,
                              text=True,stdout=handle,stderr=subprocess.STDOUT,timeout=90)
    if result.returncode:raise RuntimeError(f"Native DSSAT exit {result.returncode}")
    joint.audit_extended_injection(work,values,[n for n in values if n in legacy.read_injected_parameters(work)] + [n for n in values if n.startswith('OPT') and n.endswith('_FS')])
    frames={n:legacy.read_native(work/f"{n}.OUT") for n in ["PlantGro","PlantN","FreshWt","SoilWat","SoilNi"]}
    etfile=next((f for f in work.glob("*.OUT") if "ETAC" in f.read_text(encoding="latin1",errors="replace")[:6000]),None)
    if etfile:frames["ET"]=legacy.read_native(etfile)
    rows=[]
    for tn in treatments:
        g=frames["PlantGro"].loc[tn];s=frames["SoilWat"].loc[tn];n=frames["SoilNi"].loc[tn];f=frames["FreshWt"].loc[tn]
        et=frames["ET"].loc[tn] if "ET" in frames else None
        row=dict(**case,season_id=season,trno=tn,
                 final_fresh=float(f.CHFPW.iloc[-1]),final_dry=float(f.CHPDT.iloc[-1]),
                 initial_SWTD=float(s.SWTD.iloc[0]),final_SWTD=float(s.SWTD.iloc[-1]),
                 irrigation=float(s.IRRC.iloc[-1]),rain=float(s.PREC.iloc[-1]),drainage=float(s.DRNC.iloc[-1]),runoff=float(s.ROFC.iloc[-1]),
                 initial_mineral_N=float(n.NIAD.iloc[0]),final_mineral_N=float(n.NIAD.iloc[-1]),fertilizer_N=float(n.NAPC.iloc[-1]),
                 net_mineralization=float(n.NNMNC.iloc[-1]),uptake_N=float(n.NUCM.iloc[-1]),leached_N=float(n.NLCC.iloc[-1]),
                 mean_WSPD=float(g.WSPD.mean()),max_WSPD=float(g.WSPD.max()),mean_WSGD=float(g.WSGD.mean()),
                 mean_NSTD=float(g.NSTD.mean()),max_NSTD=float(g.NSTD.max()),stress_days_W=int(g.WSPD.gt(.05).sum()),
                 stress_days_N=int(g.NSTD.gt(.05).sum()),maximum_root_depth=float(g.RDPD.max()))
        if et is not None:
            row.update(ET=float(et.ETAC.iloc[-1]),transpiration=float(et.EPAC.iloc[-1]),evaporation=float(et.ESAC.iloc[-1]),potential_ET=float(et.EOAC.iloc[-1]))
        row["ET_water_balance"]=row["initial_SWTD"]+row["irrigation"]+row["rain"]-row["drainage"]-row["runoff"]-row["final_SWTD"]
        rows.append(row)
    pd.DataFrame(rows).to_csv(work/"process_summary.csv",index=False)
    # Read every calibration target independently; incomplete mature pools are
    # diagnostic outcomes and never get a deceptively smaller partial Phi.
    if season=="26SP":
        obs=pd.read_csv(CONFIG/"calibration_observations.csv").fillna("")
        native={k:frames[k] for k in ["PlantGro","PlantN","FreshWt","SoilWat"]}
        anthesis=joint.read_anthesis(work/"Evaluate.OUT");comp=[]
        for _,item in obs.iterrows():
            try:
                row=joint.extract_observations(work,pd.DataFrame([item]),native_frames=native,anthesis=anthesis).iloc[0].to_dict()
                row["matched"]=True
            except (ValueError,KeyError) as error:row={**item.to_dict(),"simulated":np.nan,"matched":False,"error":str(error)}
            comp.append(row)
        pd.DataFrame(comp).to_csv(work/"calibration_diagnostic_comparison.csv",index=False)
    (work/"changes.json").write_text(json.dumps(changes),encoding="utf-8")
    return rows


def execute_one(pair):
    case_id,season=pair;work=OUT/"cases"/case_id/season;work.mkdir(parents=True,exist_ok=True)
    with (work/"worker.log").open("w",encoding="utf-8") as log:
        run=subprocess.run([sys.executable,"-X","utf8",str(Path(__file__).resolve()),"--worker",case_id,"--season",season],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    return dict(case_id=case_id,season_id=season,exit_code=run.returncode)


def initialize():
    if (OUT/"experiment_manifest.json").exists():return
    OUT.mkdir(parents=True,exist_ok=True)
    d=json.loads((CONFIG/"design.json").read_text(encoding="utf-8"))
    sources=[PARAMS,CONFIG/"design.json",CONFIG/"calibration_observations.csv"]
    sources.extend(ROOT/x["bundle_path"]/"input_manifest.json" for x in d["datasets"])
    manifest=dict(status="diagnostic_counterfactual_not_formal_calibration",parameter_reference=str(PARAMS),
                  cases=cases(),datasets=d["datasets"],output_policy="retain native ET/water/nutrient balances",
                  input_policy="isolated copies only; original soil/IC/weather/management remain frozen",
                  scope="26SP calibration used for range evidence; 25SP/25FA retrospective mechanism checks, no validation-based parameter selection",
                  source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sources})
    (OUT/"experiment_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--worker");parser.add_argument("--season");parser.add_argument("--probe",action="store_true")
    args=parser.parse_args()
    if args.worker:worker(args.worker,args.season);return
    initialize();manifest=json.loads((OUT/"experiment_manifest.json").read_text(encoding="utf-8"))
    selected=[x for x in manifest["cases"] if not args.probe or x["case_id"]=="baseline"]
    tasks=[(x["case_id"],s) for x in selected for s in ("26SP","25SP","25FA")]
    tasks=[x for x in tasks if not (OUT/"cases"/x[0]/x[1]/"process_summary.csv").exists()]
    status=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for future in concurrent.futures.as_completed([pool.submit(execute_one,x) for x in tasks]):
            result=future.result();status.append(result)
            (OUT/"execution_status.json").write_text(json.dumps(dict(completed=len(status),expected=len(tasks),failed=sum(x['exit_code']!=0 for x in status))),encoding="utf-8")
    pd.DataFrame(status).to_csv(OUT/("probe_status.csv" if args.probe else "execution_status.csv"),index=False)
    summaries=[pd.read_csv(f) for f in (OUT/"cases").glob('*/*/process_summary.csv')]
    if summaries:pd.concat(summaries,ignore_index=True).to_csv(OUT/"process_grid.csv",index=False,encoding="utf-8-sig")
    for rel,digest in manifest["source_hashes"].items():assert sha(ROOT/rel)==digest,rel
    print(json.dumps(dict(cases=len(selected),tasks=len(tasks),failed=sum(x['exit_code']!=0 for x in status),frozen_sources_unchanged=True)))


if __name__=="__main__":main()
