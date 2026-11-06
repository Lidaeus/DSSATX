"""Paired forward-only grid around the 80x4 representative and low-XFPHT basin."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.calibration import run_dual_morris98_trial_20261105 as trial
from src.calibration.all12_joint import check_relations
from src.calibration.sa98_joint40 import encode, extract, read_anthesis
from src.calibration.single_season_n import read_native
from src.common.param_registry import PHYSICAL_BOUNDS

RUN = ROOT/"workspace/runs"/trial.ID
OUT = RUN/"boundary_grid_20261105"
GRID = {
    "XFPHT":[30,32.5,35,37.5,40,45], "PM06":[.05,.075,.125,.15,.20],
    "TO22":[27,27.5,28,28.5,29], "PROLFI":[.26,.27,.28,.31],
    "PROLFG":[.21,.25,.26,.27], "XFINT":[.30,.35,.365,.38,.40],
    "EM-FL":[26,27,29,30], "TO12":[23,25,26,27], "TB2":[10.5,11.25,12.25,12.5],
    "TM2":[36,38,42,44], "FL-SH":[1.7,2.2,3.2,3.7], "FL-SD":[18,20,23,25],
    "PODUR":[6,7.5,10,12], "SFDUR":[40,44,52,56], "XMAGE":[7.5,8.5,10.5,12],
    "XFRT":[.90,.925,.95,.97], "SD-PM":[380,420],
}


def round_field(value):
    for decimals in range(5,-1,-1):
        field = trial.genotype_field(round(float(value),decimals))
        if field.startswith(" "):
            return float(field)
    raise ValueError(f"Does not fit native field: {value}")


def build_grid(b, center, extend=False):
    trial_outputs = pd.read_csv(RUN/"joint/joint.4.obs.csv",index_col=0)
    params = pd.read_csv(RUN/"joint/joint.4.par.csv",index_col=0)
    low = params.index[params.xfpht.le(35 + .005*(70-35))]
    assert len(low)==22
    obs = pd.read_csv(RUN/"calibration_observations.csv")
    phi = (trial_outputs.loc[low,obs.obsnme]*obs.final_weight.to_numpy()).pow(2).sum(axis=1)
    anchor = phi.idxmin()
    other = trial.values_for(b,dict(zip(b.name,params.loc[anchor,b.pest_name])))
    center["SD-PM"] = other["SD-PM"] = 400.
    rows = []
    def case(group, baseline, changes):
        reference = center if baseline=="selected" else other
        v = reference | {n:round_field(x) for n,x in changes.items()}
        assert all(PHYSICAL_BOUNDS[n][0]<=v[n]<=PHYSICAL_BOUNDS[n][1] for n in changes)
        check_relations(v | {f"FNPGN{i}":v[f"FNPGN({i})"] for i in (1,2,3)})
        assert v["PROSHF"]<=v["PROSHG"]<=v["PROSHI"] and v["LNREF"]>v["FNPGN(1)"]
        rows.append(dict(case=f"g{len(rows):03d}", group=group, baseline=baseline, changes=changes, vector=v))
    case("reference","selected",{})
    case("reference","low_xfpht",{})
    for name, values in GRID.items():
        for v in values:
            case(name,"selected",{name:v})
    for v in (30,32.5,35,37.5,40):
        if v!=other["XFPHT"]:
            case("XFPHT","low_xfpht",{"XFPHT":v})
    for x in (32.5,35,40):
        for m in (8.5,10.5):
            case("XFPHT_x_XMAGE","selected",{"XFPHT":x,"XMAGE":m})
    for p in (.075,.125):
        for t in (27.5,28.5):
            case("PM06_x_TO22","selected",{"PM06":p,"TO22":t})
    for e in (27,29):
        for f in (1.7,3.7):
            case("EM-FL_x_FL-SH","selected",{"EM-FL":e,"FL-SH":f})
    if extend:
        first_extension = len(rows)
        for baseline in ("selected","low_xfpht"):
            for x in (24,26,28,29):
                case("XFPHT",baseline,{"XFPHT":x})
        for f in (.42,.45):
            case("XFINT","selected",{"XFINT":f})
        for x in (28,32.5):
            for f in (.35,.40,.45):
                case("XFPHT_x_XFINT","selected",{"XFPHT":x,"XFINT":f})
        for i in (.27,.28):
            case("PROLFI_x_PROLFG","selected",{"PROLFI":i,"PROLFG":.26})
        return rows[:2]+rows[first_extension:], anchor
    return rows, anchor


def init_worker():
    global CTX, OBS
    d = trial.read(RUN/"design.json")
    b = pd.read_csv(d["frozen_bounds"]).rename(columns={"name":"registry_name","native_name":"name"})
    CTX = trial.contexts(RUN,d,b,("26SP","25SP"))
    for ctx in CTX.values():
        i,j = trial.native.field_map(ctx.templates["CUL"],"CUL")["SD-PM"]
        ctx.fields["SD-PM"] = ("CUL",i,j)
    OBS = {
        "26SP":pd.read_csv(RUN/"calibration_observations.csv").fillna(""),
        "25SP":pd.read_csv(RUN/"locked_validation_observations.csv").fillna(""),
    }
    # Fruit-N is a conditional diagnostic, outside this timing and range grid.
    OBS["25SP"] = OBS["25SP"][~OBS["25SP"].variable.eq("FRUIT_N_PCT")].copy()


def fast_compare(work, obs):
    out = obs.copy()
    frames = {n:read_native(work/(n+".OUT")) for n in ("PlantGro","PlantN","FreshWt","SoilWat")}
    stages = pd.read_csv(work/"Evaluate.OUT",sep=r"\s+",skiprows=2)
    anthesis = read_anthesis(work/"Evaluate.OUT")
    cols = {"LAID":("PlantGro","LAID"),"LWAD":("PlantGro","LWAD"),
            "SWAD":("PlantGro","SWAD"),"CHTD":("PlantGro","CHTD"),
            "CHFPW":("FreshWt","CHFPW"),"CHPDT":("FreshWt","CHPDT"),
            "HFPOW":("FreshWt","HFPOW"),"HPODW":("FreshWt","HPODW"),
            "LEAF_N_PCT":("PlantN","LN%D"),"STEM_N_PCT":("PlantN","SN%D")}
    signed = {"W_FRESH_CONTRAST","N_ADJACENT_FRESH_CONTRAST"}
    for var, q in out.groupby("variable"):
        keys = list(zip(q.trno,q.date))
        if var=="ADAP":
            values = q.trno.map(anthesis).to_numpy()
        elif var=="VWC":
            values = np.zeros(len(q))
            for weights, sub in q.groupby("dssat_layer_weights"):
                parts = [(int(k),float(v)) for k,v in (s.split(":") for s in weights.split(";"))]
                assert abs(sum(w for _,w in parts)-1)<1e-6
                sim = frames["SoilWat"].loc[list(zip(sub.trno,sub.date)),[f"SW{i+1}D" for i,_ in parts]]
                assert sim.ge(0).all().all() and sim.le(1).all().all()
                values[q.index.get_indexer(sub.index)] = sim.to_numpy() @ np.array([w for _,w in parts])
        elif var in signed:
            lo = list(zip(q.paired_trno.astype(int),q.date))
            values = frames["FreshWt"].loc[keys,"CHFPW"].to_numpy()-frames["FreshWt"].loc[lo,"CHFPW"].to_numpy()
        else:
            file,col = cols[var]
            values = frames[file].loc[keys,col].to_numpy()
        if not np.isfinite(values).all() or (var not in signed and (values<0).any()):
            raise ValueError(f"Invalid {var} output")
        out.loc[q.index,"simulated"] = values
    return out, stages


def run_case(task):
    row, season = task
    label = row["case"]+"_"+season
    record = OUT/"records"/(label+".json")
    if record.exists():
        return trial.read(record)
    result = dict(case=row["case"],season=season,status="ok")
    with TemporaryDirectory(prefix=label+"_",dir=OUT/"scratch") as tmp:
        work = Path(tmp)
        try:
            trial.simulate(RUN,work,CTX[season],row["vector"])
            q, stages = fast_compare(work,OBS[season])
            if row["group"]=="reference":
                ref = extract(work,OBS[season])
                np.testing.assert_allclose(q.simulated,ref.simulated,rtol=1e-12)
            if season=="26SP":
                c = encode(q)
                result["phi"] = float(c.phi_contribution.sum())
                result["family_phi"] = c.groupby("family").phi_contribution.sum().to_dict()
            for var in ("ADAP","LAID","SWAD","HPODW","CHFPW","CHPDT"):
                sub = q[q.variable.eq(var)]
                if var in ("CHFPW","CHPDT"):
                    sub = sub.sort_values("date").groupby("trno").tail(1)
                residual = sub.simulated-sub.observed
                result[var] = dict(observed=float(sub.observed.mean()),simulated=float(sub.simulated.mean()),
                                   bias=float(residual.mean()),rmse=float(np.sqrt(np.mean(residual**2))))
            for var in ("PD1PS","PDFPS","MDAPS"):
                v = stages.loc[stages[var].ge(0),var]
                result[var] = dict(defined=len(v),mean=float(v.mean()) if len(v) else None)
            harvest = q[q.variable.eq("HPODW")].sort_values("date")
            first = harvest[harvest.simulated.gt(0)].groupby("trno").date.first()
            result["first_positive_harvest"] = first.value_counts().to_dict()
            result["first_positive_harvest_n"] = len(first)
            result["harvest_dry_pairs"] = harvest[["trno","date","observed","simulated"]].to_dict("records")
        except Exception as exc:
            result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            evidence = OUT/"failed"/label
            evidence.mkdir(parents=True,exist_ok=True)
            for p in work.iterdir():
                if p.name in {"model.log","ERROR.OUT","Evaluate.OUT","PlantGro.OUT","FreshWt.OUT",*trial.native.GENOTYPE}:
                    shutil.copy2(p,evidence/p.name)
    trial.native.write(record,result)
    return result


def main(extend=False):
    OUT.mkdir(exist_ok=True)
    for name in ("records","scratch"):
        (OUT/name).mkdir(exist_ok=True)
    design = trial.read(RUN/"design.json")
    assert trial.read(RUN/"sealed_design.json")["sha256"]==trial.native.sha(RUN/"design.json")
    for path,digest in design["source_hashes"].items():
        assert trial.native.sha(Path(path))==digest,path
    selection = trial.read(RUN/"selection.json")
    assert selection["parameters_sha256"]==trial.native.sha(RUN/"best_calibration_parameters.csv")
    b = pd.read_csv(design["frozen_bounds"]).rename(columns={"name":"registry_name","native_name":"name"})
    v = pd.read_csv(RUN/"best_calibration_parameters.csv").set_index("name").value.to_dict()
    rows, anchor = build_grid(b,v,extend)
    prefix = "extension_" if extend else ""
    setup = dict(trial=trial.ID, cases=rows, low_xfpht_anchor=anchor,
                 source_design_sha256=trial.native.sha(RUN/"design.json"),
                 selected_parameters_sha256=selection["parameters_sha256"])
    path = OUT/f"{prefix}grid_design.json"
    if path.exists():
        assert trial.read(path)==setup
    else:
        trial.native.write(path,setup)
    tasks = [(row,s) for row in rows for s in ("26SP","25SP")]
    count = 0
    with ProcessPoolExecutor(max_workers=6,initializer=init_worker) as pool:
        for i,result in enumerate(pool.map(run_case,tasks),1):
            count += result["status"]=="ok"
            trial.native.write(OUT/f"{prefix}status.json",dict(status="running",complete=i,total=len(tasks),valid=count))
    records = [trial.read(OUT/"records"/f"{row['case']}_{s}.json") for row,s in tasks]
    base = records[0]
    assert base["status"]=="ok" and np.isclose(base["phi"],selection["phi"],rtol=1e-10)
    rows_by_case = {row["case"]:row for row in rows}
    flat = []
    for r in records:
        d = rows_by_case[r["case"]]
        item = {k:r.get(k) for k in ("case","season","status","error","phi","first_positive_harvest_n")}
        item.update(group=d["group"],baseline=d["baseline"],changes=json.dumps(d["changes"]))
        for key,value in r.items():
            if key in ("ADAP","LAID","SWAD","HPODW","CHFPW","CHPDT","PD1PS","PDFPS","MDAPS","family_phi"):
                item.update({f"{key}_{k}":v for k,v in value.items()})
        flat.append(item)
    pd.DataFrame(flat).to_csv(OUT/f"{prefix}grid_results.csv",index=False)
    trial.native.write(OUT/f"{prefix}status.json",dict(status="completed",complete=len(tasks),total=len(tasks),valid=count,
                      cases=len(rows),low_xfpht_anchor=anchor))


if __name__=="__main__":
    import argparse
    cli = argparse.ArgumentParser()
    cli.add_argument("--extend",action="store_true")
    main(cli.parse_args().extend)
