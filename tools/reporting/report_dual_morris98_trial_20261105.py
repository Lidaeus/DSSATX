"""Reproduce the two-season trial review from frozen outputs."""
from pathlib import Path
import argparse
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration.sa98_joint40 import extract
from src.calibration.single_season_n import read_native
from src.common.input_manifest import verify_calibrated_input_bundle
from tools.calibration import run_dual_morris98_trial_20261105 as trial
from tools.calibration.run_dual_morris98_trial_20261105 import ID, read
from tools.reporting.report_sa98_joint40_20261031 import UNITS, metrics, render, sha, write
from tools.calibration import plot_dynamics as plots

RUN = ROOT / "workspace/runs" / ID
OUT = RUN / "result_review"
FIG = ROOT / "figture/dual_morris98_trial80x4_two_spring_suite_20261105"
NATIVE = {"26SP": RUN / "selected_deterministic", "25SP": RUN / "validation"}


def summarize(frame, keys):
    return pd.DataFrame([dict(zip(keys, group)) | metrics(q) for group, q in frame.groupby(keys)])


def native_pairs(design):
    data, metadata, sources = [], [], []
    for season, work in NATIVE.items():
        ds = design["datasets"][season]
        bundle = Path(ds["path"])
        assert verify_calibrated_input_bundle(bundle).manifest_sha256 == ds["manifest_sha256"]
        saved_dates = trial.DATES
        try:
            trial.DATES = design["anthesis_dates"]
            evidence = trial.observation_catalog(bundle, season).assign(role=ds["role"]).fillna("")
        finally:
            trial.DATES = saved_dates
        q = extract(work, evidence, strict=False)
        pg = read_native(work / "PlantGro.OUT").reset_index()
        q = q.merge(pg[["trno", "date", "DAP"]], on=["trno", "date"], how="left",
                    validate="many_to_one").rename(columns={"DAP": "dap"})
        q.loc[q.variable.eq("ADAP"), "dap"] = q.loc[q.variable.eq("ADAP"), "observed"]
        q["unit"] = q.variable.map(UNITS)
        assert q.unit.notna().all()
        m = pd.read_csv(bundle / "treatment_metadata.csv").assign(season_id=season, dataset_role=ds["role"])
        assert set(m.treatment) == set(ds["treatments"]) == set(q.trno)
        data.append(q)
        metadata.append(m)
        sources.extend(work / f"{f}.OUT" for f in ("PlantGro", "PlantN", "FreshWt", "Evaluate", "SoilWat"))
        sources.append(bundle / "input_manifest.json")
        sdir = OUT / "_seasons" / season
        sdir.mkdir(parents=True, exist_ok=True)
        q = q.assign(DATE=pd.to_datetime(q.date).dt.strftime("%y%j").astype(int))
        vars_by_kind = {"process": {"LAID": "LAID", "LWAD": "LWAD", "SWAD": "SWAD", "CHTD": "CHTD"},
                        "harvest": {"CHPDT": "DRY_CUM", "CHFPW": "FRESH_CUM", "HPODW": "DRY_INC", "HFPOW": "FRESH_INC"}}
        for kind, names in vars_by_kind.items():
            f = q[q.variable.isin(names)].assign(kind=lambda x:x.variable.map(names))
            assert f.comparison_status.eq("matched").all()
            wide = f.pivot(index=["trno", "DATE"], columns="kind", values="observed").add_prefix("OBS_").join(
                f.pivot(index=["trno", "DATE"], columns="kind", values="simulated").add_prefix("SIM_"))
            wide = wide.reset_index().rename(columns={"trno":"TN"}).sort_values(["TN","DATE"])
            if kind == "harvest":
                wide["HNO"] = wide.groupby("TN").cumcount()+1
            wide.to_csv(sdir / f"{season}_deterministic_{kind}_compare.csv", index=False)
    m = pd.concat(metadata, ignore_index=True)
    q = pd.concat(data, ignore_index=True).merge(
        m, left_on=["season_id","trno"], right_on=["season_id","treatment"], validate="many_to_one")
    assert not q.duplicated(["season_id","trno","date","variable","depth_label"]).any()
    return q, m, sources


def signed_response(terminal):
    rows = []
    for (season, var), q in terminal.groupby(["season_id", "variable"]):
        by = q.set_index(["water_level", "nitrogen_level"])
        water = sorted(q.water_level.unique())
        contrasts = [(f"{w}-W1", n, (w,n), ("W1",n), "water")
                     for w in water if w!="W1" for n in ("N0","N1","N2","N3")]
        contrasts.extend((f"N{i+1}-N{i}", w, (w,f"N{i+1}"), (w,f"N{i}"), "nitrogen")
                         for w in water for i in range(3))
        for contrast, context, hi, lo, process in contrasts:
            a, b = by.loc[hi], by.loc[lo]
            rows.append(dict(season_id=season, variable=var, process=process, contrast=contrast,
                             context=context, hi_trno=int(a.trno), lo_trno=int(b.trno),
                             observed=a.observed-b.observed, simulated=a.simulated-b.simulated,
                             comparison_status="matched"))
    return pd.DataFrame(rows)


def approved_gradient_response(terminal):
    evidence = pd.read_csv(RUN / "gradient_comparison.csv")
    fresh = terminal[terminal.variable.eq("CHFPW")].set_index(["season_id","trno"])
    for row in evidence.itertuples():
        hi, lo = fresh.loc[row.season_id,row.trno], fresh.loc[row.season_id,row.paired_trno]
        assert hi.date == lo.date == row.date and hi.role == lo.role == row.role
        if row.contrast == "W2-W1":
            assert (hi.water_level, lo.water_level) == ("W2", "W1")
            assert hi.nitrogen_level == lo.nitrogen_level == row.contrast_context
        else:
            assert row.contrast == "N2-N0" and (hi.nitrogen_level, lo.nitrogen_level) == ("N2", "N0")
            assert hi.water_level == lo.water_level == row.contrast_context
        np.testing.assert_allclose([row.observed, row.simulated],
            [hi.observed-lo.observed, hi.simulated-lo.simulated], rtol=0, atol=1e-9)
    assert not evidence.duplicated(["season_id","contrast","contrast_context"]).any()
    return evidence.rename(columns={"contrast_context":"context","trno":"hi_trno","paired_trno":"lo_trno"}).assign(
        variable="CHFPW", process=evidence.contrast.map({"W2-W1":"water","N2-N0":"nitrogen"}))


def audit_ies(design, selection):
    raw = pd.read_csv(RUN / "calibration_comparison.csv")
    assert len(raw)==design["target_count"]
    calibration = {s for s, ds in design["datasets"].items() if ds["role"] == "calibration"}
    assert raw.comparison_status.eq("matched").all() and set(raw.season_id) == calibration
    r = (raw.simulated-raw.observed)/raw.sigma_eff
    loss = r**2
    huber = raw.loss.eq("pseudo_huber")
    delta = raw.loc[huber,"huber_delta"]
    loss.loc[huber] = 2*delta**2*(np.hypot(1,r[huber]/delta)-1)
    np.testing.assert_allclose(loss*raw.final_weight**2, raw.phi_contribution, rtol=1e-10, atol=1e-11)
    phi = float((loss*raw.final_weight**2).sum())
    assert np.isclose(phi, selection["phi"], rtol=1e-12)
    if "phi_by_season" in selection:
        by_season = raw.groupby("season_id").phi_contribution.sum()
        np.testing.assert_allclose(by_season, by_season.index.map(selection["phi_by_season"]), rtol=1e-12)
        by_season.to_csv(OUT / "phi_by_season.csv")
    families = []
    keys = ["season_id", "family"] if len(calibration) > 1 else ["family"]
    for group, q in raw.groupby(keys):
        identity = dict(zip(keys, group))
        family = identity["family"]
        kind = "signed" if family.endswith("CONTRAST") else "raw"
        fam_phi = q.phi_contribution.sum()
        families.append(dict(**identity, variable=q.variable.iloc[0], phi=fam_phi,
                             phi_share_pct=100*fam_phi/phi, budget=(q.final_weight**2).sum(),
                             MBE=(q.simulated-q.observed).mean(),
                             **plots._metrics(q.observed,q.simulated,value_kind=kind)))
    pd.DataFrame(families).sort_values("phi",ascending=False).to_csv(OUT/"calibration_family_metrics.csv",index=False)
    bounds = pd.read_csv(design["frozen_bounds"])
    selected = pd.read_csv(RUN/"best_calibration_parameters.csv").set_index("name").value
    active = bounds[bounds.status.eq("active")].copy()
    active["selected"] = active.native_name.map(selected)
    active["position"] = (active.selected-active.lower)/(active.upper-active.lower)
    iterations, members, missing = [], [], []
    population = pd.read_csv(RUN/"joint/initial_ensemble.csv",index_col=0).index
    reported = pd.read_csv(RUN/"round_quality.csv").set_index("iteration")
    last_two = range(design["updates"]-1, design["updates"]+1)
    for i in range(design["updates"]+1):
        p = pd.read_csv(RUN/f"joint/joint.{i}.par.csv",index_col=0)
        o = pd.read_csv(RUN/f"joint/joint.{i}.obs.csv",index_col=0)
        assert o.index.is_unique and p.index.is_unique
        assert set(o.index).union(p.index).issubset(population)
        common = population.intersection(p.index).intersection(o.index)
        values = o.loc[common,raw.obsnme].to_numpy()
        valid = np.isfinite(values).all(axis=1) & np.isfinite(p.loc[common,active.pest_name]).all(axis=1)
        names = common[valid]
        ph = np.square(values[valid] * raw.final_weight.to_numpy()).sum(axis=1)
        minimum_retained = selection.get("minimum_retained")
        passed = (len(names) >= minimum_retained if minimum_retained is not None
                  else len(names)/len(population) >= .98)
        assert len(names)==reported.loc[i,"retained"] and passed==reported.loc[i,"passed"]
        iterations.append(dict(iteration=i,retained=len(ph),passed=passed,phi_min=ph.min(),phi_median=np.median(ph),
                               phi_mean=ph.mean(),phi_q25=np.quantile(ph,.25),phi_q75=np.quantile(ph,.75)))
        members.extend(dict(iteration=i,member=k,phi=v) for k,v in zip(names,ph))
        missing.extend(dict(iteration=i,member=k,parameter_present=k in p.index,observation_present=k in o.index)
                       for k in population.difference(names))
        if i in last_two:
            lower, upper = (active.set_index("pest_name")[k] for k in ("lower","upper"))
            pos = (p.loc[names,active.pest_name]-lower)/(upper-lower)
            active[f"r{i}_members"] = len(names)
            for key, test in {"near_lower":pos.le(.02), "near_upper":pos.ge(.98),
                              "severe_lower":pos.le(.005), "severe_upper":pos.ge(.995)}.items():
                active[f"r{i}_{key}"] = active.pest_name.map(test.mean())
            active[f"r{i}_median_position"] = active.pest_name.map(pos.median())
    rounds = pd.DataFrame(iterations)
    results = pd.DataFrame(members)
    eligible = results[results.iteration.isin(rounds.loc[rounds.passed,"iteration"])]
    best = eligible.sort_values(["phi","iteration","member"]).iloc[0]
    assert (best.iteration,best.member)==(selection["iteration"],selection["member"])
    assert np.isclose(phi,best.phi,rtol=1e-6)
    for side in ("lower","upper"):
        active[f"persistent_{side}"] = active[[f"r{i}_severe_{side}" for i in last_two]].ge(.2).all(axis=1)
    active["selected_near"] = active.position.le(.02) | active.position.ge(.98)
    active["selected_severe"] = active.position.le(.005) | active.position.ge(.995)
    rounds.to_csv(OUT/"iteration_statistics.csv",index=False)
    results.to_csv(OUT/"member_phi.csv",index=False)
    pd.DataFrame(missing,columns=["iteration","member","parameter_present","observation_present"]).to_csv(
        OUT/"missing_members_by_round.csv",index=False)
    final = results[results.iteration.eq(design["updates"])].member
    results[results.member.isin(final)].groupby("iteration").phi.agg(["count","min","median","mean"]).to_csv(
        OUT/"same_final_members_phi.csv")
    active.to_csv(OUT/"parameter_boundary_audit.csv",index=False)
    return rounds, active, phi, float(best.phi)


def review(validation_bundle=None):
    OUT.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)
    design, status, selection = [read(RUN/f"{n}.json") for n in ("design","pipeline_status","selection")]
    assert status["status"]=="completed"
    both_calibrated = all(ds["role"] == "calibration" for ds in design["datasets"].values())
    if both_calibrated:
        assert set(selection["calibration_seasons"]) == set(design["datasets"]) and selection["validation_seasons"] == []
        NATIVE.update({s: RUN / "selected_deterministic" / s for s in design["datasets"]})
    else:
        assert selection["validation_used"] is False
    assert read(RUN/"sealed_design.json")["sha256"]==sha(RUN/"design.json")
    assert selection["parameters_sha256"]==sha(RUN/"best_calibration_parameters.csv")
    assert sha(Path(design["frozen_bounds"]))==design["source_hashes"][design["frozen_bounds"]]
    if validation_bundle is not None:
        assert design["datasets"]["25SP"]["role"] == "validation" and not selection["validation_used"]
        bundle = verify_calibrated_input_bundle(validation_bundle)
        ds = design["datasets"]["25SP"]
        original_bundle = verify_calibrated_input_bundle(ds["path"])
        assert original_bundle.manifest_sha256 == ds["manifest_sha256"]
        provenance = read(validation_bundle / "source_provenance.json")
        assert provenance["baseline_manifest_sha256"] == ds["manifest_sha256"]
        ds.update(path=str(validation_bundle), bundle_id=bundle.bundle_id, manifest_sha256=bundle.manifest_sha256)
        status["diagnostic_footer"] = status.get("diagnostic_footer",
            f"trial | final {status['retained']}/{status['members']}") + " | updated 2025 leaf dry weight"
        status["validation_bundle_override"] = ds.copy()
    pairs, metadata, sources = native_pairs(design)
    diagnostics = "diagnostic_comparison.csv" if both_calibrated else "validation_comparison.csv"
    recorded = pd.read_csv(RUN/diagnostics).fillna("")
    keys = ["season_id","trno","date","variable","depth_label"]
    diagnostic_pairs = pairs if both_calibrated else pairs[pairs.season_id.eq("25SP")]
    check = diagnostic_pairs.merge(recorded,on=keys,validate="one_to_one",suffixes=("", "_saved"))
    assert len(check)==len(recorded)==len(diagnostic_pairs)
    assert check.comparison_status.eq(check.comparison_status_saved).all()
    np.testing.assert_allclose(pd.to_numeric(check.simulated,errors="coerce"),
                               pd.to_numeric(check.simulated_saved,errors="coerce"))
    if validation_bundle is not None:
        other = check[check.variable.ne("LWAD")]
        np.testing.assert_allclose(other.observed.astype(float), other.observed_saved.astype(float), rtol=0, atol=1e-10)
    raw = pd.read_csv(RUN/"calibration_comparison.csv").fillna("")
    base = raw[raw.paired_trno.eq("")]
    check = base.merge(pairs,on=keys,validate="one_to_one",suffixes=("", "_review"))
    assert len(check)==len(base)
    np.testing.assert_allclose(check.simulated,check.simulated_review)
    pairs.to_csv(OUT/"all_observed_simulated_pairs.csv",index=False)
    metadata.to_csv(OUT/"treatment_metadata.csv",index=False)
    variable = summarize(pairs, ["season_id","role","variable","unit"])
    variable.to_csv(OUT/"variable_metrics.csv",index=False)
    summarize(pairs[pairs.variable.eq("VWC")],["season_id","depth_label"]).to_csv(OUT/"soil_water_depth_metrics.csv",index=False)
    terminal = pairs[pairs.variable.isin(["CHFPW","CHPDT"])].sort_values("date").groupby(
        ["season_id","trno","variable"]).tail(1)
    terminal.to_csv(OUT/"terminal_yield_pairs.csv",index=False)
    tm = summarize(terminal,["season_id","role","variable","unit"])
    tm["relative_bias_pct"] = 100*tm.MBE/tm.mean_observed
    tm.to_csv(OUT/"terminal_yield_metrics.csv",index=False)
    approved_gradients = bool(design.get("gradients"))
    contrasts = approved_gradient_response(terminal) if approved_gradients else signed_response(terminal)
    contrasts.to_csv(OUT/"signed_water_nitrogen_response.csv",index=False)
    signed = []
    for key, q in contrasts.groupby(["season_id","variable","process"]):
        signed.append(dict(zip(("season_id","variable","process"),key)) | dict(
            sign_matches=int((np.sign(q.observed)==np.sign(q.simulated)).sum()),
            **plots._metrics(q.observed,q.simulated,value_kind="signed")))
    if approved_gradients and "W2" not in metadata.loc[metadata.season_id.eq("25SP"),"water_level"].values:
        signed.append(dict(season_id="25SP",variable="CHFPW",process="water",n=0))
    pd.DataFrame(signed).to_csv(OUT/"signed_response_metrics.csv",index=False)
    rounds, bounds, phi, best_phi = audit_ies(design,selection)
    sources.extend([RUN/f for f in ("design.json","calibration_comparison.csv",diagnostics,
                                    "selection.json","best_calibration_parameters.csv","joint/ies_quality/ies_run_quality.json")])
    if approved_gradients:
        sources.append(RUN / "gradient_comparison.csv")
    sources.extend(RUN/f"joint/joint.{i}.{suffix}.csv" for i in range(design["updates"]+1) for suffix in ("par","obs"))
    write(OUT/"review_summary.json",dict(status=status,selection=selection,phi_from_raw=phi,ensemble_phi=best_phi,
          phi_relative_error=abs(phi-best_phi)/phi,
          source_sha256={str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p): sha(p) for p in sources}))
    print(tm.to_string(index=False),flush=True)
    print(variable.to_string(index=False),flush=True)
    final_rounds = range(design["updates"] - 1, design["updates"] + 1)
    severe_columns = [f"r{i}_severe_{side}" for side in ("lower", "upper") for i in final_rounds]
    print(bounds.loc[bounds.selected_near | bounds.persistent_lower | bounds.persistent_upper,
                     ["native_name","lower","upper","selected","position",*severe_columns]].to_string(index=False),flush=True)
    return pairs, metadata, terminal, rounds, bounds, status


def render_trial(pairs, metadata, terminal, rounds, bounds, status, *, nitrogen_response=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import PercentFormatter
    from tools.calibration.plot_diagnostic_custom import NITROGEN_COLORS

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top":False, "axes.spines.right":False})
    blue, orange = "#176B87", "#BC582D"
    markers = {"W1":"^","W2":"s","W3":"o"}
    roles = {}
    for s in ("26SP", "25SP"):
        season_metadata = metadata.loc[metadata.season_id.eq(s), "dataset_role"]
        if season_metadata.empty:
            continue
        role, = season_metadata.unique()
        roles[s] = f"20{s[:2]} spring | {role}"

    def save(fig, file):
        fig.savefig(FIG/f"diagnostic_{file}.png", dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.8,4.6),layout="constrained")
    ax.fill_between(rounds.iteration, rounds.phi_q25, rounds.phi_q75,color=blue,alpha=.18,label="Middle 50%")
    ax.plot(rounds.iteration,rounds.phi_median,"o-",color=blue,label="Median")
    ax.plot(rounds.iteration,rounds.phi_min,"s-",color=orange,label="Minimum")
    rejected = rounds[~rounds.passed]
    if len(rejected):
        ax.scatter(rejected.iteration,rejected.phi_min,marker="x",color="#9F1239",s=85,zorder=5,
                   label="Retention gate missed")
    best_round = status["selected_iteration"]
    ax.scatter([best_round],[status["selected_phi"]],marker="*",color=blue,s=120,zorder=6,label="Selected")
    phi_label = status.get("phi_label", "Joint calibration Phi" if not metadata.dataset_role.eq("validation").any() else "2026 calibration Phi")
    ax.set(xlabel="IES update (retained / initial members)",ylabel=phi_label,xticks=rounds.iteration,
           xticklabels=[f"{r.iteration}\n{r.retained}/{status['members']}" for r in rounds.itertuples()],
           title="Calibration objective and member retention")
    ax.grid(axis="y",alpha=.25)
    ax.legend(frameon=False)
    save(fig,"phi_iterations")

    fig, axes = plt.subplots(2,len(roles),figsize=(4.25*len(roles),8.5),squeeze=False,layout="constrained")
    for row, (var,label) in enumerate([("CHFPW","Fresh yield"),("CHPDT","Dry yield")]):
        f = terminal[terminal.variable.eq(var)]
        lo, hi = f[["observed","simulated"]].min().min()/1000, f[["observed","simulated"]].max().max()/1000
        pad = .08*(hi-lo)
        for j, (season,role) in enumerate(roles.items()):
            ax = axes[row,j]
            q = f[f.season_id.eq(season)]
            ax.plot([lo-pad,hi+pad],[lo-pad,hi+pad],"--",color=".55",lw=1)
            for w, group in q.groupby("water_level"):
                ax.scatter(group.observed/1000,group.simulated/1000,marker=markers[w],
                           c=group.nitrogen_level.map(NITROGEN_COLORS),edgecolor="white",linewidth=.45,s=48)
            m = metrics(q)
            ax.set(xlim=(lo-pad,hi+pad),ylim=(lo-pad,hi+pad),aspect="equal",
                   xlabel=f"Observed {label.lower()} (t/ha)",ylabel=f"Simulated {label.lower()} (t/ha)",title=role)
            ax.text(.04,.96,f"n = {m['n']}   NRMSE = {m['RRMSE']:.1f}%\nNSE = {m['NSE']:.2f}",transform=ax.transAxes,va="top")
    fig.suptitle("Final harvest yield by treatment")
    water_legend = [Line2D([],[],marker=marker,color=".35",linestyle="none",label=w)
                    for w,marker in markers.items()]
    nitrogen_legend = [Line2D([],[],marker="o",color=NITROGEN_COLORS[n],linestyle="none",label=n)
                       for n in ("N0","N1","N2","N3")]
    fig.legend(handles=water_legend+nitrogen_legend,loc="outside lower center",ncols=7,frameon=False)
    save(fig,"terminal_yield")

    panels = [("ADAP","First flower (DAP)"),("CHTD","Height (m)"),("LEAF_N_PCT","Leaf N (% DM)"),
              ("STEM_N_PCT","Stem N (% DM)"),("VWC","Soil water (cm³/cm³)"),("FRUIT_N_PCT","Fruit N proxy (% DM)")]
    fig, axes = plt.subplots(2,3,figsize=(12,7.5),layout="constrained")
    for ax,(v,label) in zip(axes.flat,panels):
        q = pairs[pairs.variable.eq(v)]
        xy = q[["observed","simulated"]].apply(pd.to_numeric,errors="coerce")
        lo, hi = xy.min().min(),xy.max().max()
        pad = max(.01,.08*(hi-lo))
        ax.plot([lo-pad,hi+pad],[lo-pad,hi+pad],"--",color=".55",lw=1)
        for s,c,marker in (("26SP",blue,"o"),("25SP",orange,"^")):
            if s not in roles:
                continue
            match = q[q.season_id.eq(s)&q.comparison_status.eq("matched")]
            diagnostic = match.get("diagnostic_visit", pd.Series(False, index=match.index))
            fitted = match[~diagnostic]
            ax.scatter(fitted.observed,fitted.simulated,s=18,c=c,marker=marker,alpha=.67,label=roles[s])
            if diagnostic.any():
                ax.scatter(match.loc[diagnostic,"observed"],match.loc[diagnostic,"simulated"],
                           s=28,facecolors="none",edgecolors=c,marker=marker,label="Diagnostic visit")
        ax.set(xlim=(lo-pad,hi+pad),ylim=(lo-pad,hi+pad),aspect="equal",xlabel="Observed",ylabel="Simulated",title=label)
        if v=="FRUIT_N_PCT":
            coverage = []
            for s in roles:
                season = q[q.season_id.eq(s)]
                count = season.comparison_status.eq("matched").sum()
                coverage.append(f"{s} {count}/{len(season)}")
            ax.text(.97,.05,"Conditional diagnostic\nMatched "+", ".join(coverage),
                    transform=ax.transAxes,ha="right",va="bottom",fontsize=8)
        if q.get("diagnostic_visit", pd.Series(False, index=q.index)).any():
            ax.text(.03,.96,"Open markers: diagnostic visit",transform=ax.transAxes,va="top",fontsize=8)
    axes[0,0].legend(loc="upper left",frameon=False,fontsize=8)
    fig.suptitle("Phenology and water–nitrogen process diagnostics")
    save(fig,"phenology_water_nitrogen")

    # Show every parameter with an elevated tail concentration or a near-bound representative value.
    previous_round, final_round = rounds.iteration.iloc[-2:].astype(int)
    near = [f"r{i}_near_{side}" for i in (previous_round, final_round) for side in ("lower", "upper")]
    design_path = RUN / "design.json"
    plot_design = read(design_path) if design_path.is_file() else {}
    protein_constraint = plot_design.get("proshi_feasibility")
    include_constraint = bounds.native_name.eq("PROSHI") & bool(protein_constraint)
    focus = bounds[bounds.selected_near | bounds[near].max(axis=1).ge(.10) | include_constraint].copy()
    focus["peak"] = focus[near].max(axis=1)
    focus = focus.sort_values(["peak","native_name"],ascending=[False,True])
    fig, axes = plt.subplots(1,2,figsize=(10,max(4,.34*len(focus)+1.8)),sharey=True,layout="constrained")
    y = np.arange(len(focus))
    axes[0].axvspan(0,.02,color=orange,alpha=.15)
    axes[0].axvspan(.98,1,color=orange,alpha=.15)
    axes[0].scatter(focus.position,y,c=blue,s=32,zorder=3)
    labels = focus.native_name.tolist()
    if protein_constraint:
        protein_row = np.flatnonzero(focus.native_name.eq("PROSHI").to_numpy()).item()
        row = focus.iloc[protein_row]
        excluded = (protein_constraint["required_lower"]-row.lower)/(row.upper-row.lower)
        axes[0].barh(protein_row,excluded,height=.72,color=".82",zorder=1)
        labels[protein_row] = f"PROSHI (feasible ≥ {protein_constraint['required_lower']:g})"
    axes[0].set(yticks=y,yticklabels=labels,xlim=(-.03,1.03),xlabel="Position within bounds",
                title="Selected member")
    axes[0].xaxis.set_major_formatter(PercentFormatter(1))
    axes[0].invert_yaxis()
    ax = axes[1]
    for i, c, offset in [(previous_round,"#9EB5C1",-.14),(final_round,blue,.14)]:
        ax.barh(y+offset,-focus[f"r{i}_severe_lower"],height=.24,color=c,label=f"Update {i}")
        ax.barh(y+offset,focus[f"r{i}_severe_upper"],height=.24,color=c)
    ax.axvline(0,color=".5",lw=.8)
    for x in (-.2,.2):
        ax.axvline(x,color=orange,lw=.85,ls="--")
    ax.set(xlabel="Members near lower (−) or upper (+) bound",title="Within 0.5% of a bound")
    ax.xaxis.set_major_formatter(PercentFormatter(1,decimals=0))
    ax.legend(frameon=False)
    fig.suptitle("Parameter boundary diagnostics")
    save(fig,"parameter_bounds")

    approved_gradients = bool(plot_design.get("gradients"))
    if approved_gradients:
        gradient = pd.read_csv(OUT / "signed_water_nitrogen_response.csv")
        fig, axes = plt.subplots(2,2,figsize=(9.4,5.8),sharex=True,layout="constrained")
        for row, (season, role) in enumerate(roles.items()):
            for col, (contrast, title) in enumerate([("W2-W1","W2 − W1 by nitrogen level"),
                                                      ("N2-N0","N2 − N0 by water level")]):
                ax = axes[row,col]
                q = gradient[gradient.season_id.eq(season)&gradient.contrast.eq(contrast)].sort_values("context")
                ax.set_title(f"{role}\n{title}",fontsize=10,loc="left")
                ax.axvline(0,color=".55",lw=.9,ls="--")
                ax.grid(axis="x",alpha=.18)
                ax.set_axisbelow(True)
                if q.empty:
                    ax.set_yticks([])
                    ax.text(.5,.5,"W2 treatment unavailable",transform=ax.transAxes,ha="center",color=".35")
                    continue
                y = np.arange(len(q))
                observed, simulated = q.observed/1000, q.simulated/1000
                ax.hlines(y,np.minimum(observed,simulated),np.maximum(observed,simulated),color=".70",lw=1.4)
                ax.scatter(observed,y,s=38,facecolors="white",edgecolors=blue,zorder=3)
                ax.scatter(simulated,y,s=34,c=orange,marker="s",zorder=3)
                ax.set(yticks=y,yticklabels=q.context)
                ax.invert_yaxis()
        for ax in axes[-1]:
            ax.set_xlabel("Final fresh yield difference (t/ha)",fontsize=10)
        fig.suptitle("Water and nitrogen gradients")
        fig.legend(handles=[
            Line2D([],[],marker="o",markerfacecolor="white",markeredgecolor=blue,linestyle="none",label="Observed"),
            Line2D([],[],marker="s",color=orange,linestyle="none",label="Simulated"),
        ],loc="outside lower center",ncols=2,frameon=False)
        save(fig,"approved_yield_gradients")

    gate = "engineering gate passed" if status["all_rounds_passed"] else "engineering gate missed"
    trial_label = f"Trial {status['members']}x{status.get('updates', final_round)} / update {best_round} {status['selected_member']}"
    render(pairs,metadata,out=OUT,fig_dir=FIG,native_dirs=NATIVE,
           label=status.get("candidate_label", trial_label),
           footer=status.get("diagnostic_footer", f"trial | {gate} | final {status['retained']}/{status['members']}"),
           run_id=RUN.name,scientific_status=status["scientific_status"],engineering_status=status["engineering_status"],
           legacy_responses=not approved_gradients,nitrogen_response=nitrogen_response)
    manifest = read(FIG/"diagnostic_manifest.json")
    manifest["renderer_code_sha256"][str(Path(__file__).relative_to(ROOT))] = sha(Path(__file__))
    manifest["metrics_source_sha256"] = {p.name:sha(p) for p in sorted(OUT.glob("*.csv"))}
    if "validation_bundle_override" in status:
        manifest["validation_bundle_override"] = status["validation_bundle_override"]
    write(FIG/"diagnostic_manifest.json",manifest)


if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-only",action="store_true")
    parser.add_argument("--run-id",default=ID)
    parser.add_argument("--figure-dir",type=Path)
    parser.add_argument("--review-dir",type=Path)
    parser.add_argument("--validation-bundle",type=Path,help="Use a verified observation refresh for the 2025 validation season.")
    parser.add_argument("--nitrogen-response",action="store_true",help="Include the terminal fresh-yield response across nitrogen levels.")
    args = parser.parse_args()
    if args.run_id!=ID:
        RUN = ROOT/"workspace/runs"/args.run_id
        OUT = RUN/"result_review"
        NATIVE = {"26SP":RUN/"selected_deterministic","25SP":RUN/"validation"}
        FIG = ROOT/"figture"/args.run_id
    if args.figure_dir:
        FIG = args.figure_dir.resolve()
    if args.review_dir:
        OUT = args.review_dir.resolve()
    if args.validation_bundle and not (args.review_dir and args.figure_dir):
        parser.error("--validation-bundle requires separate --review-dir and --figure-dir paths")
    results = review(args.validation_bundle.resolve() if args.validation_bundle else None)
    if not args.data_only:
        render_trial(*results,nitrogen_response=args.nitrogen_response)
