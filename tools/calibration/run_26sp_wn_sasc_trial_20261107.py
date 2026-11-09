"""2026-only IES trial with one shared stable-carbon ratio and revised NMOBMX bounds."""

import argparse
from dataclasses import replace
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import pyemu
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.input_manifest import verify_calibrated_input_bundle
from tools.calibration import run_26sp_wn_gradient_trial_20261106 as parent

trial, native = parent.trial, parent.native
ID = "eggplant_26sp_cal25sp_val_wn_nmobmx_sasc_80x3_20261107"
RUN = ROOT / "workspace/runs" / ID
SNAPSHOT = ROOT / "workspace/runs/xxql_both_springs_nmobmx0035_diagnostics_20261107"
RATIO = "SASC_RATIO"
WORKERS, UPDATES = 8, 3
GENOTYPE_VALUES, GENOTYPE_CONTEXTS, GENOTYPE_SIMULATE = trial.values_for, trial.contexts, trial.simulate


def values_for(bounds, values):
    ratio = float(values[RATIO])
    row = bounds[bounds.name.eq(RATIO)].iloc[0]
    if not row.lower - 1e-10 <= ratio <= row.upper + 1e-10:
        raise ValueError(f"SASC/SAOC outside the interval: {ratio}")
    genetic = GENOTYPE_VALUES(bounds[bounds.name.ne(RATIO)], {k:v for k,v in values.items() if k != RATIO})
    return genetic | {RATIO:round(ratio,4)}


def contexts(run, design, bounds, seasons=("26SP",)):
    return GENOTYPE_CONTEXTS(run,design,bounds[bounds.name.ne(RATIO)],seasons)


def sasc_fields(source, ratio):
    lines = source.splitlines(keepends=True)
    section = table = False
    count = 0
    for i,line in enumerate(lines):
        if line.startswith(b"*"):
            section = line.startswith(b"*SOIL ANALYSIS")
            table = False
        if line.startswith(b"@"):
            table = section and b"SABL" in line and b"SASC" in line
        if not table or not line[:3].strip().isdigit():
            continue
        carbon = float(line[15:20])
        assert carbon > 0 and len(line.rstrip(b"\r\n")) == 56
        stable = carbon*ratio
        field = f"{stable:.4f}".removeprefix("0")
        if len(field)>5:
            field = f"{stable:.3f}"
        assert len(field)<=5 and abs(float(field)-stable)<=.00050001
        # IPSLAN reads SASC as F6.0 starting at byte 51. Keep a blank separator.
        lines[i] = line[:51]+field.rjust(6).encode("ascii")+line[56:]
        count += 1
    assert count in (80,120)
    return b"".join(lines)


def simulate(run, work, ctx, values):
    ratio = values[RATIO]
    genotype = {k:v for k,v in values.items() if k != RATIO}
    with TemporaryDirectory(prefix="sasc_",dir=work) as tmp:
        payload = Path(tmp)
        for p in ctx.payload.iterdir():
            if p.name == ctx.filex:
                (payload / p.name).write_bytes(sasc_fields(p.read_bytes(),ratio))
            else:
                shutil.copy2(p,payload/p.name)
        return GENOTYPE_SIMULATE(run,work,replace(ctx,payload=payload),genotype)


def configure():
    trial.WORKERS, trial.UPDATES = WORKERS, UPDATES
    trial.values_for, trial.contexts, trial.simulate = values_for, contexts, simulate


def prepare():
    src = parent.RUN
    design_path = src/"design.json"
    design = trial.read(design_path)
    assert trial.read(src/"sealed_design.json")["sha256"] == native.sha(design_path)
    assert trial.read(src/"pipeline_status.json")["status"] == "completed"
    snapshot = trial.read(SNAPSHOT/"replay_manifest.json")
    assert snapshot["source_run"] == str(src) and design["SLPF"] == snapshot["SLPF"]
    trial.DATES = design["anthesis_dates"]
    retired = {Path(d["path"])/"input_manifest.json" for d in design["datasets"].values()}
    hashes = {p:h for p,h in design["source_hashes"].items()
              if not Path(p).is_relative_to(src) and Path(p) not in retired}
    assert all(native.sha(Path(p))==h for p,h in hashes.items())
    for s, ds in snapshot["datasets"].items():
        manifest = verify_calibrated_input_bundle(ds["path"])
        assert manifest.manifest_sha256 == ds["manifest_sha256"]
        payload = RUN/f"{s}_inputs"
        shutil.copytree(SNAPSHOT/payload.name,payload)
        for p in payload.iterdir():
            assert native.sha(p) == snapshot["payload_sha256"][s][p.name]
            hashes[str(p)] = native.sha(p)
        hashes[str(manifest.manifest_path)] = manifest.manifest_sha256
    for name in ("calibration_observations.csv","objective_policy.csv","gradient_objectives.csv",
                 "anthesis_diagnostic_observations.csv","organ_n_diagnostic_observations.csv"):
        p=src/name
        assert native.sha(p)==design["source_hashes"][str(p)]
        shutil.copy2(p,RUN/name)
    fresh = trial.observation_catalog(Path(snapshot["datasets"]["26SP"]["path"]),"26SP").fillna("")
    old = pd.read_csv(SNAPSHOT/"all_observed_simulated_pairs.csv").query('season_id=="26SP"').fillna("")
    keys=["trno","date","variable","depth_label","observed"]
    pd.testing.assert_frame_equal(fresh[keys].reset_index(drop=True),old[keys].reset_index(drop=True),check_dtype=False)
    val=trial.observation_catalog(Path(snapshot["datasets"]["25SP"]["path"]),"25SP")
    val.to_csv(RUN/"locked_validation_observations.csv",index=False)
    obs = pd.read_csv(RUN/"calibration_observations.csv").fillna("")
    assert len(obs)==511 and obs.season_id.eq("26SP").all() and np.isclose(obs.final_weight.pow(2).sum(),89)
    b = pd.read_csv(design["frozen_bounds"])
    b.loc[b.native_name.eq("NMOBMX"),["init","lower","upper","basis"]] = [.025,.010,.035,"User-specified interval"]
    ratio = dict(name=RATIO,native_name=RATIO,pest_name="sasc_ratio",init=.70,lower=.70,upper=.90,
                 status="active",pargp="soil",location="INIT",file="FileX.TMX",mode="eggplant_stage2",
                 basis="User-specified shared ratio; SASC=SAOC*ratio in both seasons")
    b = pd.concat([b,pd.DataFrame([ratio])],ignore_index=True)
    assert b.status.eq("active").sum()==59
    proposal = RUN/"approved_trial_bounds.csv"
    b.to_csv(proposal,index=False)
    frozen=Path(design["frozen_bounds"]).with_name(f"{ID}.csv")
    subprocess.run([sys.executable,"-X","utf8",str(ROOT/"tools/freeze_bounds.py"),
        "--proposal",str(proposal),"--crop","eggplant","--bounds-id",ID,"--notes",
        "User specified NMOBMX 0.010-0.035 and shared SASC/SAOC 0.70-0.90."],cwd=ROOT,check=True)
    for p in (*RUN.glob("*.csv"), frozen,frozen.with_suffix(".yaml"), Path(__file__),design_path,
              src/"joint/joint.pst",SNAPSHOT/"replay_manifest.json"):
        hashes[str(p)] = native.sha(p)
    design.update(run_id=ID,parent_trial=src.name,parent_design_sha256=native.sha(design_path),
                  datasets=snapshot["datasets"],updates=UPDATES,workers=WORKERS,frozen_bounds=str(frozen),
                  bounds_id=ID,active_parameters=[*design["active_parameters"],RATIO],source_hashes=hashes,
                  SASC={"parameter":RATIO,"bounds":[.7,.9],"initial":.7,"scope":"shared",
                        "expression":"layer SASC = layer SAOC * SASC_RATIO"})
    design.pop("SASC_ratio_by_season",None)
    for k in ("initial_members","initial_ensemble_base"):
        design.pop(k,None)
    native.write(RUN/"design.json",design)
    return design,parent.dual.bounds(design),obs


def make_case(design,b,obs,params,outputs):
    work = RUN/"joint"
    work.mkdir()
    (work/"parameters.tpl").write_text("ptf ~\nname,value\n"+"".join(
        f"{p},~ {p:<22} ~\n" for p in b.pest_name),encoding="ascii")
    shutil.copy2(parent.RUN/"joint/objectives.ins",work/"objectives.ins")
    params.to_csv(work/"initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work/"parameters.csv",index_label="name")
    trial.write_outputs(work/"FormalObjectives.OUT",obs.obsnme,outputs.loc["base"])
    pst=pyemu.Pst.from_io_files([str(work/"parameters.tpl")],[str(work/"parameters.csv")],
        [str(work/"objectives.ins")],[str(work/"FormalObjectives.OUT")],pst_path=".")
    previous=pyemu.Pst(str(parent.RUN/"joint/joint.pst"))
    pst.observation_data=previous.observation_data.copy()
    for r in b.itertuples():
        pst.parameter_data.loc[r.pest_name,["partrans","parval1","parlbnd","parubnd","pargp"]]=[
            "none" if r.status=="active" else "fixed",params.loc["base",r.pest_name],r.lower,r.upper,r.pargp]
    pst.model_command=[f'"{sys.executable}" -X utf8 "{Path(__file__)}" --forward "{RUN}"']
    pst.control_data.noptmax=UPDATES
    pst.pestpp_options=previous.pestpp_options.copy()
    pst.write(str(work/"joint.pst"),version=1)
    actual=pyemu.Pst(str(work/"joint.pst"))
    assert (actual.npar_adj,actual.nnz_obs,actual.control_data.noptmax)==(59,511,3)
    assert set(actual.adj_par_names)==set(b.loc[b.status.eq("active"),"pest_name"])
    np.testing.assert_allclose(actual.observation_data.loc[obs.obsnme,"weight"],obs.final_weight)
    for key,col in (("parlbnd","lower"),("parubnd","upper")):
        np.testing.assert_allclose(actual.parameter_data.loc[b.pest_name,key],b[col])
    manifest=yaml.safe_load((parent.RUN/"joint/run_manifest.yaml").read_text(encoding="utf-8"))
    manifest.pop("sasc_ratio_by_season",None)
    manifest.update(run_id=ID,design=str(RUN/"design.json"),parent_trial=parent.RUN.name,
        bounds_id=ID,n_params_active=59,noptmax=UPDATES,agents=WORKERS,shared_sasc_ratio=design["SASC"])
    (work/"run_manifest.yaml").write_text(yaml.safe_dump(manifest,sort_keys=False),encoding="utf-8")


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN/"design.json").exists():
        raise FileExistsError(RUN)
    try:
        trial.status(RUN,"preparing")
        design,b,obs=prepare()
        params,outputs,base=trial.initial_ensemble(RUN,b,obs,contexts(RUN,design,b)["26SP"])
        design.update(initial_members=len(params),initial_ensemble_base=base)
        native.write(RUN/"design.json",design)
        native.write(RUN/"sealed_design.json",dict(sha256=native.sha(RUN/"design.json")))
        make_case(design,b,obs,params,outputs)
        trial.status(RUN,"running",phase="pest_ies",initial_members=len(params),n_targets=len(obs))
        with (RUN/"parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable,"-X","utf8",str(ROOT/"tools/parallel/run_parallel.py"),
                "--run-dir",str(RUN/"joint"),"--case","joint","--mode","ies","--n-agents",str(WORKERS),"--wait"],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        assert trial.read(RUN/"joint/run_status.json")["status"]=="completed"
        for d in design["datasets"].values():
            assert verify_calibrated_input_bundle(d["path"]).manifest_sha256==d["manifest_sha256"]
        trial.status(RUN,"postprocessing")
        trial.finalize(RUN,b,obs,design,params)
    except Exception as exc:
        phase=trial.read(RUN/"pipeline_status.json")["status"]
        trial.status(RUN,"failed",phase=phase,error=f"{type(exc).__name__}: {exc}")
        raise


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--forward",type=Path)
    args=parser.parse_args()
    configure()
    if args.forward:
        trial.forward(args.forward)
    else:
        main()
