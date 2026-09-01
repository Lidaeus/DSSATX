"""Three-season diagnostics for the v6 joint62 best member.

This is deliberately a run-diagnostics product.  All figures are prefixed
``diagnostic_`` and are not publication Fig/FigS artifacts.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.reporting import diagnostic_three_season_best_member as base  # noqa: E402


SEASONS = [
    {
        "season_id": "25SP",
        "experiment_code": "XXQL2501",
        "bundle_path": "data/user/experiments/xxql2501_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        "bundle_manifest_sha256": "808d8127e65d03ba0315519ff87254841c0bc510b36a79736cad7e9ccebdbb42",
        "role": "calibration",
        "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
    },
    {
        "season_id": "25FA",
        "experiment_code": "XXQL2502",
        "bundle_path": "data/user/experiments/xxql2502_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        "bundle_manifest_sha256": "0d37048d027ad08f3c5cdb87e6302974b63643864c6afd909517a741885b5897",
        "role": "calibration",
        "treatments": list(range(1, 13)),
    },
    {
        "season_id": "26SP",
        "experiment_code": "XXQL2601",
        "bundle_path": "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        "bundle_manifest_sha256": "365e0afc8e33be2ef6413a5420ec905211f7deb276f852f97723f4ce3dd1d24a",
        "role": "calibration",
        "treatments": [1, 3, 4, 6, 7, 9, 10, 12],
    },
]

COLORS = {"25SP": "#2878B5", "25FA": "#D95F02", "26SP": "#2A9D55"}
VARIABLES = [
    "DRY_CUM", "DRY_INC", "LAID", "LWAD", "SWAD", "CHTD",
    "SNAM", "LNAM", "LAIX", "ADAP",
]
LABELS = {
    "DRY_CUM": "Cumulative dry harvest",
    "DRY_INC": "Incremental dry harvest",
    "LAID": "LAI",
    "LWAD": "Leaf dry mass",
    "SWAD": "Stem dry mass",
    "CHTD": "Plant height",
    "SNAM": "Stem N mass",
    "LNAM": "Leaf N mass",
    "LAIX": "Maximum LAI",
    "ADAP": "Anthesis timing",
}
YLAB = {"CHTD": "m", "LAID": "m² m⁻²", "LAIX": "m² m⁻²",
        "SNAM": "kg N ha⁻¹", "LNAM": "kg N ha⁻¹",
        "LWAD": "kg ha⁻¹", "SWAD": "kg ha⁻¹",
        "DRY_CUM": "kg ha⁻¹", "DRY_INC": "kg ha⁻¹", "ADAP": "d"}


def write_design(path: Path) -> None:
    source = json.loads((ROOT / "configs/runs/eggplant_e02_joint62_25sp_25fa_autumn_offsets_plantn_slpf_v5_20260729.json").read_text(encoding="utf-8"))
    source["design_id"] = "diagnostic_v6_three_season_best82_20260729"
    source["shared_parameter_scope"] = "v6 joint62 best member; seven 25FA offsets; 26SP uses shared reference vector"
    source["seasons"] = SEASONS
    source["t10_scheme"]["purpose"] = "Three-season deterministic diagnostics only; no re-calibration"
    source["t10_scheme"]["diagnostic_season"] = "26SP"
    path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def metrics(comparison: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    rows = []
    for keys, g in comparison.groupby(["season", "variable"], sort=False):
        y = g.observed.to_numpy(float); q = g.simulated.to_numpy(float)
        e = q - y
        den = float(np.sum((y - y.mean()) ** 2))
        rows.append({"season": keys[0], "variable": keys[1], "n": len(g),
                     "rmse": float(np.sqrt(np.mean(e**2))),
                     "rrmse_pct": float(100*np.sqrt(np.mean(e**2))/np.mean(np.abs(y))) if np.mean(np.abs(y)) else np.nan,
                     "nse": float(1-np.sum(e**2)/den) if den > 0 else np.nan,
                     "r2": float(np.corrcoef(y, q)[0, 1]**2) if len(g)>1 and np.std(y)>0 and np.std(q)>0 else np.nan,
                     "bias": float(e.mean())})
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "diagnostic_metrics_by_season_variable.csv", index=False)
    return out


def add_plant_n(comparison: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """Append SNAM/LNAM pairs from the retained PestTmtGrow outputs."""
    rows = []
    pattern = re.compile(
        r"RUN\s+(\d+)\s+TN\s+(\d+)\s+DATE\s+(\d+).*?"
        r"@SNAMS@\s+([-+0-9.]+).*?@LNAMS@\s+([-+0-9.]+)"
    )
    for season in SEASONS:
        if season["season_id"] == "26SP":
            continue
        sid = season["season_id"]
        sdir = out_dir / "_seasons" / sid
        entries = {int(e["run"]): int(e["tn"]) for e in base._parse_batch_entries(str(sdir / "DSSBatch.selected.v48"))}
        observed = base._read_tmt_process_obs(
            str(ROOT / season["bundle_path"] / f"{season['experiment_code']}.TMT"), ["SNAM", "LNAM"]
        )
        for line in (sdir / "PestTmtGrow.OUT").read_text(errors="ignore").splitlines():
            m = pattern.search(line)
            if not m:
                continue
            run, tn, date = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if entries.get(run) != tn:
                continue
            point = next((x for x in observed.get(tn, []) if int(x["DATE"]) == date), None)
            if point is None:
                continue
            for var, obs_key, idx in (("SNAM", "OBS_SNAM", 4), ("LNAM", "OBS_LNAM", 5)):
                if obs_key not in point or not np.isfinite(float(point[obs_key])):
                    continue
                sim = float(m.group(idx))
                if sim <= -98:
                    continue
                rows.append({
                    "run_id": "diagnostic_v6_best82_three_season",
                    "data_status": "engineering_validated_diagnostic",
                    "dataset_role": "calibration",
                    "season": sid,
                    "variable": var,
                    "variable_label": LABELS[var],
                    "unit": YLAB[var],
                    "treatment": str(tn),
                    "time": float(date % 1000),
                    "time_label": "Day of year",
                    "observed": float(point[obs_key]),
                    "simulated": sim,
                    "source_file": str((sdir / "PestTmtGrow.OUT").resolve()),
                    "date_code": float(date), "year": float(2000 + date // 1000),
                    "doy": float(date % 1000), "dap": np.nan,
                    "harvest_number": np.nan, "observed_sd": np.nan,
                    "observed_se": np.nan, "n_rep": np.nan,
                })
    if rows:
        comparison = pd.concat([comparison, pd.DataFrame(rows)], ignore_index=True)
    return comparison


def plot_grid(comparison: pd.DataFrame, out_dir: Path, residual: bool) -> Path:
    present = [v for v in VARIABLES if v in set(comparison.variable)]
    ncols = 5; nrows = math.ceil(len(present) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(16, 3.2*nrows), dpi=180, squeeze=False)
    axes = axes.ravel()
    for ax, var in zip(axes, present):
        g = comparison[comparison.variable.eq(var)].copy()
        for season, color in COLORS.items():
            p = g[g.season.eq(season)]
            if p.empty: continue
            if residual:
                ax.scatter(p.observed, p.simulated-p.observed, s=18, alpha=.72, color=color, label=season, edgecolor="white", linewidth=.25)
            else:
                ax.scatter(p.observed, p.simulated, s=18, alpha=.72, color=color, label=season, edgecolor="white", linewidth=.25)
        lo = float(min(g.observed.min(), g.simulated.min())); hi = float(max(g.observed.max(), g.simulated.max())); pad=max((hi-lo)*.05,1e-6)
        if residual: ax.axhline(0, ls="--", color="#333333", lw=.8)
        else: ax.plot([lo-pad,hi+pad],[lo-pad,hi+pad], ls="--", color="#333333", lw=.8); ax.set_xlim(lo-pad,hi+pad); ax.set_ylim(lo-pad,hi+pad)
        ax.set_title(LABELS[var]); ax.set_xlabel("Observed"); ax.set_ylabel("Residual" if residual else "Simulated")
        ax.grid(True, color="#E7E7E7", lw=.6); ax.spines[["top","right"]].set_visible(False)
    for ax in axes[len(present):]: ax.set_visible(False)
    handles, labels = axes[0].get_legend_handles_labels(); fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.5,.965), ncol=3, frameon=False)
    fig.suptitle("v6 best member residual diagnostics" if residual else "v6 best member observed vs simulated", y=1.015, fontsize=14)
    fig.tight_layout(rect=(0,0,1,.94))
    name = "diagnostic_v6_residuals_major_variables.png" if residual else "diagnostic_v6_observed_vs_simulated_major_variables.png"
    path=out_dir/name; fig.savefig(path,bbox_inches="tight"); plt.close(fig); return path


def plot_dynamics(comparison: pd.DataFrame, trajectory: pd.DataFrame, season: dict, variable: str, out_dir: Path) -> Path:
    sid=season["season_id"]; treatments=season["treatments"]; ncols=5 if len(treatments)>8 else 4; nrows=math.ceil(len(treatments)/ncols)
    fig, axes=plt.subplots(nrows,ncols,figsize=(3*ncols,2.6*nrows),dpi=180,squeeze=False,sharey=variable=="DRY_CUM"); axes=axes.ravel()
    sim_var="DRY_CUM" if variable=="DRY_CUM" else variable; allvals=[]
    for ax,tn in zip(axes,treatments):
        sim=trajectory[(trajectory.season.eq(sid))&(trajectory.variable.eq(sim_var))&(trajectory.treatment.astype(str).eq(str(tn)))].sort_values("time")
        obs=comparison[(comparison.season.eq(sid))&(comparison.variable.eq(variable))&(comparison.treatment.astype(str).eq(str(tn)))].sort_values("time")
        if not sim.empty: ax.plot(sim.time,sim.simulated,color="#345995",lw=1.35,label="DSSAT"); allvals.extend(sim.simulated.dropna().tolist())
        if not obs.empty: ax.scatter(obs.time,obs.observed,color="#D1495B",s=24,zorder=3,edgecolor="white",linewidth=.35,label="Observed"); allvals.extend(obs.observed.dropna().tolist())
        ax.set_title(f"TN{tn}"); ax.set_xlabel("DAP"); ax.set_ylabel(YLAB.get(variable,variable)); ax.grid(True,color="#E7E7E7",lw=.6); ax.spines[["top","right"]].set_visible(False)
    if variable=="DRY_CUM" and allvals:
        for ax in axes[:len(treatments)]: ax.set_ylim(0,max(max(allvals)*1.05,1.0))
    for ax in axes[len(treatments):]: ax.set_visible(False)
    handles, labels=axes[0].get_legend_handles_labels(); fig.legend(handles,labels,loc="lower center",bbox_to_anchor=(.5,.965),ncol=2,frameon=False)
    fig.suptitle(f"{sid}: {LABELS[variable]} dynamics",y=1.015,fontsize=14); fig.tight_layout(rect=(0,0,1,.94))
    path=out_dir/f"diagnostic_v6_{sid.lower()}_{'yield' if variable=='DRY_CUM' else 'lai'}_dynamics.png"; fig.savefig(path,bbox_inches="tight"); plt.close(fig); return path


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--run-dir",type=Path,required=True); ap.add_argument("--ensemble",type=Path,required=True); ap.add_argument("--member",default="82"); ap.add_argument("--out-dir",type=Path,required=True); ap.add_argument("--reuse-rerun",action="store_true"); args=ap.parse_args()
    out=args.out_dir.resolve(); out.mkdir(parents=True,exist_ok=True); design=out/"diagnostic_v6_three_season_design.json"; write_design(design)
    params=out/f"best_member_{args.member}_parameters.csv"; base._export_member(args.ensemble.resolve(),args.member,params)
    status=out/"multiseason_run_status.json"
    if not (args.reuse_rerun and status.exists()):
        cmd=[sys.executable,str(ROOT/"src/calibration/run_multiseason.py"),"--design",str(design),"--param-csv",str(params),"--prefix","diagnostic_v6_best82_three_season","--harvest-var","CHPDT","--keep-nitrogen-outputs"]
        subprocess.run(cmd,cwd=out,check=True)
    comparison,trajectory=base._collect(out,"diagnostic_v6_best82_three_season",SEASONS)
    comparison = add_plant_n(comparison, out)
    comparison.to_csv(out/"diagnostic_v6_comparison_original_scale.csv",index=False); trajectory.to_csv(out/"diagnostic_v6_simulation_trajectory.csv",index=False)
    m=metrics(comparison,out); figures=[plot_grid(comparison,out,False),plot_grid(comparison,out,True)]
    for s in SEASONS: figures.extend([plot_dynamics(comparison,trajectory,s,"DRY_CUM",out),plot_dynamics(comparison,trajectory,s,"LAID",out)])
    manifest={"artifact_type":"run_diagnostics","source_calibration":str(args.run_dir.resolve()),"source_ensemble":str(args.ensemble.resolve()),"best_member":str(args.member),"season_bundles":SEASONS,"residual_definition":"simulated - observed","figures":[x.name for x in figures],"note":"v6 62-parameter vector; seven autumn offsets applied only to 25FA; 26SP is external-season diagnostic."}
    (out/"diagnostic_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(m.to_string(index=False)); print(f"Diagnostics written to: {out}"); return 0


if __name__ == "__main__": raise SystemExit(main())
