"""Re-run the locked SASC70 trial representative with 25SP SASC/SAOC=0.55."""
from dataclasses import replace
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration.sa98_joint40 import extract
from src.common.input_manifest import verify_calibrated_input_bundle
from tools.calibration import plot_dynamics as plots
from tools.calibration.plot_diagnostic_custom import NITROGEN_COLORS
from tools.calibration.restart_dual_morris98_trial_sasc70_20261105 import RUN, trial
from tools.reporting.report_sa98_joint40_20261031 import UNITS, metrics
from tools.reporting.scan_25sp_sasc_20261105 import write_sasc

OUT = RUN/"validation_25sp_sasc55_20261106"
FIG = ROOT/"figture/validation_25sp_sasc55_20261106"
RATIO = .55


def model_run():
    d = trial.read(RUN/"design.json")
    assert trial.read(RUN/"sealed_design.json")["sha256"]==trial.native.sha(RUN/"design.json")
    for file, digest in d["source_hashes"].items():
        assert trial.native.sha(Path(file))==digest, file
    assert d["SLPF"]["25SP"]==.90 and d["SASC_ratio_by_season"]["25SP"]==.70
    selection = trial.read(RUN/"selection.json")
    param_path = RUN/"best_calibration_parameters.csv"
    assert selection["parameters_sha256"]==trial.native.sha(param_path)
    bounds = pd.read_csv(d["frozen_bounds"]).rename(columns={"name":"registry_name","native_name":"name"})
    values = trial.values_for(bounds,pd.read_csv(param_path).set_index("name").value.to_dict())
    ctx = trial.contexts(RUN,d,bounds,("25SP",))["25SP"]
    bundle = Path(d["datasets"]["25SP"]["path"])
    assert verify_calibrated_input_bundle(bundle).manifest_sha256==d["datasets"]["25SP"]["manifest_sha256"]
    payload = OUT/"inputs"
    shutil.copytree(ctx.payload,payload)
    proof = OUT/"sasc70_reconstructed.tmx"
    write_sasc(bundle/ctx.filex,proof,.70)
    assert proof.read_bytes()==(ctx.payload/ctx.filex).read_bytes()
    layers = write_sasc(bundle/ctx.filex,payload/ctx.filex,RATIO)
    pd.DataFrame(layers).assign(SASC_ratio=RATIO).to_csv(OUT/"sasc_layer_audit.csv",index=False)
    native = OUT/"model"
    native.mkdir()
    trial.simulate(RUN,native,replace(ctx,payload=payload),values)
    assert trial.native.sha(native/"SOIL.SOL")==trial.native.sha(ctx.payload/"SOIL.SOL")
    for genotype in trial.native.GENOTYPE:
        assert (native/genotype).read_bytes()==(RUN/"validation"/genotype).read_bytes()
    obs = pd.read_csv(RUN/"locked_validation_observations.csv").fillna("")
    q = extract(native,obs,strict=False)
    m = pd.read_csv(bundle/"treatment_metadata.csv").rename(columns={"treatment":"trno"})
    previous = pd.read_csv(RUN/"validation_comparison.csv").fillna("")
    keys = ["trno","date","variable","depth_label"]
    pairs = q.merge(previous[keys+["observed","simulated","comparison_status"]],on=keys,
                    suffixes=("","_070"),validate="one_to_one")
    assert len(pairs)==len(obs)==len(previous)
    np.testing.assert_allclose(pairs.observed,pairs.observed_070,rtol=0,atol=1e-10)
    pairs = pairs.merge(m,on="trno",validate="many_to_one")
    pairs.to_csv(OUT/"paired_validation.csv",index=False)
    files = (RUN/"design.json",param_path,RUN/"validation_comparison.csv",bundle/"input_manifest.json",
             payload/ctx.filex,native/"SOIL.SOL",native/"Evaluate.OUT",native/"PlantGro.OUT",
             native/"PlantN.OUT",native/"FreshWt.OUT",native/"SoilWat.OUT")
    trial.native.write(OUT/"run_audit.json",dict(selection=selection,SLPF=.90,SASC_ratio=RATIO,
        baseline_SASC_ratio=.70,role="validation_diagnostic",layers=len(layers),
        source_sha256={str(p):trial.native.sha(p) for p in files}))
    return pairs,m,native


def summarize(q):
    rows = []
    for v, g in q.groupby("variable"):
        for ratio in (.55,.70):
            f = g if ratio==.55 else g.assign(simulated=g.simulated_070,comparison_status=g.comparison_status_070)
            rows.append(dict(variable=v,SASC_ratio=ratio,unit=UNITS[v],**metrics(f)))
    return pd.DataFrame(rows)


def figures(pairs,meta,native,terminal,vm):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    FIG.mkdir(exist_ok=True)
    plotmeta = meta.rename(columns={"trno":"treatment"}).assign(season_id="25SP")
    plotmeta.to_csv(OUT/"treatment_metadata.csv",index=False)
    plots.MAPPING_CSV = str(OUT/"treatment_metadata.csv")
    plots._INCLUDE_ALL_TREATMENTS = True
    plots._ALL_TREATMENT_IDS = {"25SP":set(meta.trno)}
    plots.SEASON_LABELS["25SP"] = "2025 Spring (cross-season evaluation)"
    pg,fw = plots._read_plantgro(str(native)),plots._read_freshwt(str(native))
    pg["CHTD"] = pd.to_numeric(pg["CHTD"],errors="raise")
    common = dict(plantgro=pg,freshwt=fw,ref_year=2025)
    for kind, names in (("process",{"LAID":"LAID","LWAD":"LWAD","SWAD":"SWAD","CHTD":"CHTD"}),
                        ("harvest",{"CHPDT":"DRY_CUM","CHFPW":"FRESH_CUM","HPODW":"DRY_INC","HFPOW":"FRESH_INC"})):
        q = pairs[pairs.variable.isin(names)].copy()
        q["DATE"] = pd.to_datetime(q.date).dt.strftime("%y%j").astype(int)
        q["key"] = q.variable.map(names)
        wide = q.pivot(index=["trno","DATE"],columns="key",values="observed").add_prefix("OBS_").join(
            q.pivot(index=["trno","DATE"],columns="key",values="simulated").add_prefix("SIM_"))
        wide = wide.reset_index().rename(columns={"trno":"TN"}).sort_values(["TN","DATE"])
        if kind=="harvest":
            wide["HNO"] = wide.groupby("TN").cumcount()+1
            for var,k,label in (("DRY_CUM","cum_dry","Dry"),("FRESH_CUM","cum_fresh","Fresh")):
                plots._plot_dynamics_single_season(common|dict(compare=wide),"25SP",var,k,
                    str(FIG/f"diagnostic_{k}.png"),None,f"{label} yield (kg/ha)",
                    f"SASC/SAOC 0.55 | cumulative {label.lower()} harvest",harvest_curve="native")
            plots._increment_plot({"25SP":common|dict(compare=wide)},str(FIG/"diagnostic_dry_harvest_events.png"))
        else:
            for var in ("LAID","LWAD","SWAD","CHTD"):
                plots._plot_dynamics_single_season(common|dict(compare=wide),"25SP",var,"process",
                    str(FIG/f"diagnostic_timeseries_{var}.png"),None,f"{var} ({UNITS[var]})",
                    f"SASC/SAOC 0.55 | {var}")

    fig, axes = plt.subplots(1,2,figsize=(9,5),layout="constrained")
    markers = {"W1":"^","W3":"o"}
    for ax,(var,label) in zip(axes,[("CHFPW","Fresh"),("CHPDT","Dry")]):
        q = terminal[terminal.variable.eq(var)]
        values = q[["observed","simulated","simulated_070"]].to_numpy()/1000
        low,high = values.min(),values.max()
        pad = (high-low)*.08
        ax.plot([low-pad,high+pad],[low-pad,high+pad],"--",color=".55",lw=1)
        for w,g in q.groupby("water_level"):
            x,y,z = g.observed/1000,g.simulated/1000,g.simulated_070/1000
            colors = g.nitrogen_level.map(NITROGEN_COLORS)
            ax.vlines(x,z,y,color=".62",lw=1)
            ax.scatter(x,z,marker=markers[w],facecolors="none",edgecolors=colors,s=40)
            ax.scatter(x,y,marker=markers[w],c=colors,s=40)
        ax.set(xlim=(low-pad,high+pad),ylim=(low-pad,high+pad),aspect="equal",title=f"{label} yield",
               xlabel="Observed (t/ha)",ylabel="Simulated (t/ha)")
    handles = [Line2D([],[],marker="o",color=".3",markerfacecolor="none",linestyle="none",label="0.70"),
               Line2D([],[],marker="o",color=".3",linestyle="none",label="0.55")]
    handles += [Line2D([],[],marker="o",color=NITROGEN_COLORS[n],linestyle="none",label=n) for n in ("N0","N1","N2","N3")]
    handles += [Line2D([],[],marker=marker,color=".3",linestyle="none",label=w) for w,marker in markers.items()]
    fig.legend(handles=handles,loc="outside lower center",ncols=4,frameon=False)
    fig.suptitle("2025 spring | last harvest per treatment")
    fig.savefig(FIG/"diagnostic_terminal_yield.png",dpi=200)
    plt.close(fig)

    q = vm.pivot(index="variable",columns="SASC_ratio",values="RRMSE")
    q = q.drop(index=["ADAP","FRUIT_N_PCT"]).dropna()
    labels = {"CHFPW":"Cumulative fresh yield","CHPDT":"Cumulative dry yield","HFPOW":"Fresh harvest by event",
              "HPODW":"Dry harvest by event","CHTD":"Height","LAID":"LAI","LWAD":"Leaf dry mass","SWAD":"Stem dry mass",
              "LEAF_N_PCT":"Leaf N","STEM_N_PCT":"Stem N","VWC":"Soil water"}
    q = q.rename(index=labels)
    fig, ax = plt.subplots(figsize=(8,5),layout="constrained")
    y = np.arange(len(q))
    ax.hlines(y,q[.70],q[.55],color=".75")
    ax.scatter(q[.70],y,facecolors="none",edgecolors="#176B87",label="0.70")
    ax.scatter(q[.55],y,color="#176B87",label="0.55")
    ax.set(yticks=y,yticklabels=q.index,xlabel="NRMSE (%)",title="2025 spring | process fit")
    ax.legend(frameon=False)
    fig.savefig(FIG/"diagnostic_process_nrmse.png",dpi=200)
    plt.close(fig)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-only",action="store_true")
    args = parser.parse_args()
    if args.render_only:
        pairs = pd.read_csv(OUT/"paired_validation.csv")
        meta = pairs[["trno","water_level","nitrogen_level","treatment_label"]].drop_duplicates()
        native = OUT/"model"
    else:
        OUT.mkdir()
        pairs,meta,native = model_run()
    term = pairs[pairs.variable.isin(("CHFPW","CHPDT"))].sort_values("date").groupby(["trno","variable"]).tail(1)
    vm,tm = summarize(pairs),summarize(term)
    vm.to_csv(OUT/"variable_metrics.csv",index=False)
    tm.to_csv(OUT/"terminal_yield_metrics.csv",index=False)
    term.to_csv(OUT/"terminal_yield_pairs.csv",index=False)
    figures(pairs,meta,native,term,vm)
    trial.native.write(FIG/"diagnostic_manifest.json",dict(run=str(OUT),SASC_ratio=RATIO,
        source_sha256={p:trial.native.sha(OUT/p) for p in ("paired_validation.csv","variable_metrics.csv","terminal_yield_pairs.csv")},
        figures_sha256={p.name:trial.native.sha(p) for p in sorted(FIG.glob("diagnostic_*.png"))}))
    print(tm.to_string(index=False))
    print(vm.to_string(index=False))


if __name__=="__main__":
    main()
