"""Evaluate SASC/SAOC with the locked second-trial representative and SLPF .90."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration.sa98_joint40 import expected_filex, extract
from tools.calibration import run_dual_morris98_trial_20261105 as trial
from tools.calibration.grid_dual_morris98_bounds_20261105 import fast_compare
from tools.calibration.restart_dual_morris98_trial_ranges_20261105 import RUN
from tools.reporting.report_sa98_joint40_20261031 import metrics

OUT = RUN / "25sp_sasc_scan"
SCENARIOS = {"default":None} | {f"{code/100:.2f}":code/100 for code in range(70,91,2)}
PROCESS_FAMILIES = (("LAID",),("LWAD","SWAD"),("CHTD",),("LEAF_N_PCT","STEM_N_PCT"),("VWC",),("HFPOW","HPODW"))


def write_sasc(source, target, ratio, *, expected_layers=80):
    original = source.read_bytes().splitlines(keepends=True)
    if ratio is None:
        target.write_bytes(b"".join(original))
        return []
    expected = expected_filex(source.read_text(encoding="utf-8"), ratio).splitlines()
    assert len(expected)==len(original)
    result, layers = [], []
    for before, after in zip(original, expected):
        text = before.rstrip(b"\r\n")
        value = after.encode("utf-8")
        if text != value:
            fields = text.split()
            assert len(fields)==10 and float(text[51:56])==-99
            assert text[:51]==value[:51] and len(text)==len(value)==56
            trt, depth, saoc = int(fields[0]),int(fields[1]),float(fields[3])
            sasc = float(value[51:56])
            assert 0 < sasc <= saoc and abs(sasc - saoc*ratio)<=.005000001
            layers.append(dict(trno=trt,depth_bottom_cm=depth,SAOC=saoc,SASC=sasc))
        result.append(value+before[len(text):])
    assert len(layers)==expected_layers
    assert len({(v["trno"],v["depth_bottom_cm"]) for v in layers})==expected_layers
    target.write_bytes(b"".join(result))
    return layers


def main():
    OUT.mkdir(exist_ok=True)
    design = trial.read(RUN/"design.json")
    assert trial.read(RUN/"sealed_design.json")["sha256"]==trial.native.sha(RUN/"design.json")
    for path, digest in design["source_hashes"].items():
        assert trial.native.sha(Path(path))==digest, path
    assert design["SLPF"]["25SP"]==.90 and design["SASC"]==-99
    b = pd.read_csv(design["frozen_bounds"]).rename(columns={"name":"registry_name","native_name":"name"})
    ctx = trial.contexts(RUN,design,b,("25SP",))["25SP"]
    original = ctx.payload/ctx.filex
    profile = ctx.payload/"SOIL.SOL"
    assert profile.read_text(encoding="utf-8").splitlines()[5].split()[6]==".900"
    obs = pd.read_csv(RUN/"locked_validation_observations.csv").fillna("")
    saved = pd.read_csv(RUN/"validation_comparison.csv").fillna("")
    selection = trial.read(RUN/"selection.json")
    p = RUN/"best_calibration_parameters.csv"
    assert trial.native.sha(p)==selection["parameters_sha256"]
    values = trial.values_for(b,pd.read_csv(p).set_index("name").value.to_dict())
    fruit = obs.variable.eq("FRUIT_N_PCT")

    def run(scenario):
        name, ratio = scenario
        case = OUT/name
        case.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix=f"sasc_{name}_",dir=OUT) as tmp:
            root = Path(tmp)
            payload, work = root/"inputs",root/"model"
            work.mkdir()
            shutil.copytree(ctx.payload,payload)
            layers = write_sasc(original,payload/ctx.filex,ratio)
            for f in ctx.payload.iterdir():
                if f.name!=ctx.filex:
                    assert trial.native.sha(f)==trial.native.sha(payload/f.name)
            trial.simulate(RUN,work,replace(ctx,payload=payload),values)
            q,_ = fast_compare(work,obs[~fruit])
            f = extract(work,obs[fruit],strict=False)
            f.index = obs.index[fruit]
            q = pd.concat([q.assign(comparison_status="matched",model_error=""),f]).sort_index()
            if ratio is None:
                assert q.comparison_status.tolist()==saved.comparison_status.tolist()
                np.testing.assert_allclose(pd.to_numeric(q.simulated,errors="coerce"),
                                           pd.to_numeric(saved.simulated,errors="coerce"))
            shutil.copy2(work/ctx.filex,case/ctx.filex)
            q = q.assign(scenario=name,SASC_ratio=ratio,SLPF=.90)
            q.to_csv(case/"pairs.csv",index=False)
        print(name,"complete",flush=True)
        return q, [dict(scenario=name,SASC_ratio=ratio,**row) for row in layers]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run,SCENARIOS.items()))
    pairs = pd.concat([q for q,_ in results],ignore_index=True)
    pd.DataFrame([row for _,layers in results for row in layers]).to_csv(OUT/"sasc_layer_audit.csv",index=False)
    terminal = pairs[pairs.variable.isin(("CHFPW","CHPDT"))].sort_values("date").groupby(
        ["scenario","trno","variable"]).tail(1)
    def scores(q):
        return pd.DataFrame([dict(scenario=s,variable=v,**metrics(f))
                             for (s,v),f in q.groupby(["scenario","variable"],sort=False)])
    variable, yields = scores(pairs),scores(terminal)
    variable.to_csv(OUT/"variable_metrics.csv",index=False)
    yields.to_csv(OUT/"terminal_yield_metrics.csv",index=False)
    terminal.to_csv(OUT/"terminal_yield_pairs.csv",index=False)
    score = yields.pivot(index="scenario",columns="variable",values="RRMSE").reindex(SCENARIOS)
    score["terminal_mean_NRMSE"] = score.mean(axis=1)
    v = variable.pivot(index="scenario",columns="variable",values="RRMSE")
    ratios = v/v.loc["default"]
    score["process_mean_relative_NRMSE"] = sum(ratios[list(f)].mean(axis=1) for f in PROCESS_FAMILIES)/len(PROCESS_FAMILIES)
    score.to_csv(OUT/"scores.csv")
    files = [OUT/name for name in ("sasc_layer_audit.csv","variable_metrics.csv","terminal_yield_metrics.csv",
                                   "terminal_yield_pairs.csv","scores.csv")]
    files.extend(OUT/s/f for s in SCENARIOS for f in ("pairs.csv",ctx.filex))
    trial.native.write(OUT/"audit.json",dict(selection=selection,SLPF=.9,scenarios=SCENARIOS,
        original_TMX_sha256=trial.native.sha(original),original_SOL_sha256=trial.native.sha(profile),
        source_design_sha256=trial.native.sha(RUN/"design.json"),
        artifacts={f.relative_to(OUT).as_posix():trial.native.sha(f) for f in files}))
    print(score.to_string(),flush=True)


if __name__=="__main__":
    main()
