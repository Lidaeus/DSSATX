"""Build and export posterior parameter distribution and conditional prediction uncertainty suites for C31.

Calibration run: workspace/runs/full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927
1. Parameter Posterior Distribution & Diagnostics:
   - Computes posterior diagnostics and samples for core parameters from Prior (iter0) and Posterior (iter6).
   - Computes Spearman rank correlation matrix across 142 retained members.
   - Detects functional equifinality candidate pairs and computes deterministic prediction distances.
   - Exports frozen data bundle into paper/paper_data/ensemble/ with paper_data_manifest.json.
2. Conditional Prediction Uncertainty Suite:
   - Runs deterministic forward DSSAT replays for all 142 retained members across 23 treatments (25SP: 11 trt, 26SP: 12 trt).
   - Exports frozen conditional prediction bundle into paper/paper_data/conditional/ with paper_data_manifest.json.
3. R Publication Figure Rendering:
   - Renders posterior figures: FigS5a (posterior density), FigS5b (posterior contraction), FigS6 (Spearman structure), FigS7 (candidate prediction distance).
   - Renders conditional uncertainty figures: FigCondPerf (1:1 prediction interval), diagnostic_conditional_residual_by_treatment (residual forest), Fig4Cond (representative ribbons), FigS4Cond (all-treatment ribbons).
4. Synchronizes all rendered figures into paper/03_Figures/ and updates figure_manifest.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path("D:/Tomato_Cal")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
    deterministic_joint_compare,
)
from src.reporting.equifinality import (
    load_posterior_ensemble,
    detect_functional_equifinality,
    _load_phi,
)
from src.reporting.posterior_summary import select_candidate_pairs
from src.reporting.export_conditional_predictions import export_conditional_predictions
from src.dssat.run_dssat import prepare_run_directory

RUN_DIR = ROOT / "workspace/runs/full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927"
CASE_PREFIX = "full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927"
FINAL_ITERATION = 6
BOUNDS_CSV = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_full_gen_final_calib_scheme1_tb1_200x6_20260927.csv"
DESIGN_PATH = ROOT / "configs/runs/full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927_design.json"
METADATA_PATH = ROOT / "configs/figures/treatment_metadata_two_season_20260922.csv"
OFFICIAL_DSSAT = Path("C:/DSSAT48/DSCSM048.EXE")
RSCRIPT = Path(r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe")
PUB_NOTE = "User authorized clean C31 champion figures on 2026-09-27; scientific status unchanged."

PAPER_DATA_DIR = ROOT / "paper/paper_data"
FIGURES_RENDER_DIR = ROOT / "paper/figures"
FIGURES_03_DIR = ROOT / "paper/03_Figures"

CORE_PARAMETERS = [
    # Phenology
    "TB1", "EM-FL", "FL-SH", "FL-SD",
    # Canopy & Photosynthesis
    "LFMAX", "KCAN", "SLAVR", "SIZLF",
    # Reproductive Sink-Source & Harvest
    "PODUR", "SFDUR", "XFRT", "XMAGE",
    # Water Hydraulics & Drought
    "RWUMX", "DSWBAR",
    # Nitrogen Uptake & Mobilization
    "RTNO3", "NVSMOB",
]

SIGMA_EFF_MAP = {
    "LAID": 2.07,
    "LWAD": 158.43,
    "SWAD": 206.40,
    "DRY_INC": 252.59,
    "DRY_CUM": 252.59,
    "HWAM": 52.44,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# =========================================================================
# Phase 1: Build Posterior Ensemble Data Bundle
# =========================================================================
def build_posterior_data_bundle():
    print("=" * 80)
    print("PHASE 1: Building Parameter Posterior & Equifinality Bundle for C31")
    print("=" * 80)
    out_dir = PAPER_DATA_DIR / "ensemble"
    out_dir.mkdir(parents=True, exist_ok=True)

    prior_df = pd.read_csv(RUN_DIR / f"{CASE_PREFIX}.0.par.csv")
    post_df = pd.read_csv(RUN_DIR / f"{CASE_PREFIX}.{FINAL_ITERATION}.par.csv")
    # Boundary hits must use the domain actually consumed by this run.
    pst_block = (RUN_DIR / f"{CASE_PREFIX}.pst").read_text(encoding="utf-8-sig").split("* parameter data")[1].split("*")[0]
    bounds_lookup = {
        fields[0].upper(): (fields[1], float(fields[4]), float(fields[5]))
        for line in pst_block.splitlines() if len(fields := line.split()) >= 7
    }

    col_prior_map = {c.upper(): c for c in prior_df.columns if c != "real_name"}
    col_post_map = {c.upper(): c for c in post_df.columns if c != "real_name"}

    diag_rows = []
    sample_rows = []

    for param in CORE_PARAMETERS:
        c_pr = col_prior_map.get(param)
        c_po = col_post_map.get(param)
        if not c_pr or not c_po:
            print(f"Warning: parameter {param} not found in columns")
            continue

        pr_vals = prior_df[c_pr].dropna()
        po_vals = post_df[c_po].dropna()
        if pr_vals.nunique() < 2 or po_vals.nunique() < 2:
            raise ValueError(f"Selected diagnostic parameter {param} is constant; select an active parameter")

        transform, lb, ub = bounds_lookup[param]
        if transform == "fixed" or not lb < ub:
            raise ValueError(f"Selected diagnostic parameter {param} is fixed in the actual PST")
        rng = ub - lb if (np.isfinite(lb) and np.isfinite(ub)) else 1.0
        tol = max(1e-10, 1e-4 * rng)

        pr_iqr = float(pr_vals.quantile(0.75) - pr_vals.quantile(0.25))
        po_iqr = float(po_vals.quantile(0.75) - po_vals.quantile(0.25))
        shrink = float(1.0 - po_iqr / pr_iqr) if pr_iqr > 0 else 0.0

        frac_lb = float(np.mean(np.abs(po_vals - lb) <= tol))
        frac_ub = float(np.mean(np.abs(po_vals - ub) <= tol))

        diag_rows.append({
            "run_id": CASE_PREFIX,
            "data_status": "tooling_demo",
            "parameter": param,
            "prior_q05": float(pr_vals.quantile(0.05)),
            "prior_q95": float(pr_vals.quantile(0.95)),
            "prior_median": float(pr_vals.median()),
            "posterior_q05": float(po_vals.quantile(0.05)),
            "posterior_q95": float(po_vals.quantile(0.95)),
            "posterior_median": float(po_vals.median()),
            "iqr_shrinkage": shrink,
            "frac_near_lower": frac_lb,
            "frac_near_upper": frac_ub,
            "lower": lb, "upper": ub,
            "boundary_basis": "actual_20260927_pst", "boundary_tolerance": tol,
            "prior_n": len(pr_vals), "posterior_n": len(po_vals),
            "posterior_n_unique": int(po_vals.nunique()),
        })

        for member, v in zip(post_df.loc[po_vals.index, "real_name"], po_vals):
            sample_rows.append({
                "run_id": CASE_PREFIX,
                "data_status": "tooling_demo",
                "parameter": param,
                "realization": str(member), "iteration": FINAL_ITERATION,
                "is_base": str(member).lower() == "base",
                "value": float(v),
            })

    diag_path = out_dir / "posterior_diagnostics.csv"
    pd.DataFrame(diag_rows).to_csv(diag_path, index=False, encoding="utf-8")
    print(f"  -> Generated {diag_path.name}")

    sample_path = out_dir / "posterior_samples.csv"
    pd.DataFrame(sample_rows).to_csv(sample_path, index=False, encoding="utf-8")
    print(f"  -> Generated {sample_path.name}")

    # Spearman Correlation Matrix
    rows = []
    for a in CORE_PARAMETERS:
        for b in CORE_PARAMETERS:
            ca = col_post_map.get(a)
            cb = col_post_map.get(b)
            if not ca or not cb:
                raise ValueError(f"Selected correlation parameter missing: {a}/{b}")
            r, _ = spearmanr(post_df[ca], post_df[cb])
            if not np.isfinite(r):
                raise ValueError(f"Undefined correlation for {a}/{b}; constant parameters must be excluded")
            rows.append({
                "run_id": CASE_PREFIX,
                "data_status": "tooling_demo",
                "parameter_a": a,
                "parameter_b": b,
                "spearman": float(r),
            })
    sp_path = out_dir / "spearman_correlation.csv"
    pd.DataFrame(rows).to_csv(sp_path, index=False, encoding="utf-8")
    print(f"  -> Generated {sp_path.name}")

    # Candidate pairs detection
    prior, posterior, bounds, active, all_cal = load_posterior_ensemble(RUN_DIR, CASE_PREFIX)
    phi = _load_phi(RUN_DIR, CASE_PREFIX)
    candidates = detect_functional_equifinality(posterior, phi, active, threshold_frac=0.15)
    selected_pairs = select_candidate_pairs(candidates, max_pairs=3)
    print("Selected 3 representative candidate pairs:")
    print(selected_pairs[["pair_id", "real_a", "real_b", "phi_a", "phi_b", "parameter_distance"]])

    # Simulate required representative realizations if needed
    needed_reals = set(selected_pairs["real_a"].tolist() + selected_pairs["real_b"].tolist())
    eval_cache_dir = ROOT / "scratch/eval_final_scheme1_candidates"
    eval_cache_dir.mkdir(parents=True, exist_ok=True)

    post_df_indexed = post_df.set_index("real_name") if "real_name" in post_df.columns else post_df

    for rid in needed_reals:
        r_folder = eval_cache_dir / f"cand_iter6_real{rid}"
        if not r_folder.exists() or not (r_folder / "all_35_yield.csv").exists():
            print(f"  Forward simulating representative candidate realization {rid}...")
            r_folder.mkdir(parents=True, exist_ok=True)
            p_row = post_df_indexed.loc[str(rid)]
            p_dict = p_row.to_dict()
            p_dict["slpf_25sp"] = 0.88
            p_dict["slpf_26sp"] = 0.89
            p_dict["sasc_ratio"] = 0.92
            pd.DataFrame({"name": list(p_dict.keys()), "value": list(p_dict.values())}).to_csv(r_folder / "params.csv", index=False)

            seasons = {
                "25SP": ROOT / "data/user/experiments/xxql2501_corrected_20260923",
                "26SP": ROOT / "data/user/experiments/xxql2601_corrected_20260923",
                "25FA": ROOT / "data/user/experiments/xxql2502_corrected_20260923",
            }
            for sname, sbundle in seasons.items():
                sdir = r_folder / sname
                sdir.mkdir(parents=True, exist_ok=True)
                for bf in ["TMGRO048.CUL.base", "TMGRO048.ECO.base", "TMGRO048.SPE.base"]:
                    shutil.copy2(ROOT / "data/templates/genotype" / bf, sdir / bf)
                for item in sbundle.glob("*"):
                    if item.is_file() and not item.name.endswith(".OUT"):
                        shutil.copy2(item, sdir / item.name)
                batch_dest = prepare_run_directory(sdir, ["--batch", str(sdir / "DSSBatch.v48"), "--input-dir", str(sdir)])
                cmd = [
                    sys.executable, "-m", "src.dssat.run_dssat",
                    "--param-csv", str((r_folder / "params.csv").resolve()),
                    "--batch", batch_dest.name,
                    "--harvest-var", "CHPDT",
                    "--input-dir", str(sdir.resolve()),
                ]
                env = dict(os.environ)
                env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
                subprocess.run(cmd, cwd=sdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)

    # Function to extract comparison records
    def _extract_records(rid: int) -> pd.DataFrame:
        r_folder = eval_cache_dir / f"cand_iter6_real{rid}"
        meta_df = pd.read_csv(ROOT / "configs/figures/treatment_metadata_xxql2501_2601_joint.csv")
        role_map = {(r["season_id"], int(r["treatment"])): r["dataset_role"] for _, r in meta_df.iterrows()}
        records = []
        for season_id in ["25SP", "26SP", "25FA"]:
            s_dir = r_folder / season_id
            b_dst = s_dir / "DSSBatch.v48"
            p_path = s_dir / f"{season_id}_deterministic_process_compare.csv"
            h_path = s_dir / f"{season_id}_deterministic_harvest_compare.csv"
            j_path = s_dir / f"{season_id}_deterministic_joint_compare.csv"
            if not (p_path.exists() and h_path.exists() and j_path.exists()):
                deterministic_harvest_compare(season_id, str(b_dst), run_dir=str(s_dir))
                deterministic_process_compare(season_id, str(b_dst), run_dir=str(s_dir))
                deterministic_joint_compare(season_id, str(b_dst), run_dir=str(s_dir))

            if p_path.exists():
                df_p = pd.read_csv(p_path)
                for _, row in df_p.iterrows():
                    tn = int(row["TN"])
                    role = "diagnostic" if season_id == "25FA" else role_map.get((season_id, tn), "validation")
                    date = float(row["DATE"])
                    for var in ["LAID", "LWAD", "SWAD"]:
                        sim_col = f"SIM_{var}"
                        if sim_col in row and np.isfinite(row[sim_col]):
                            records.append({
                                "season_id": season_id, "dataset_role": role, "treatment": tn,
                                "date": date, "harvest_number": 0, "variable": var, "simulated": float(row[sim_col]),
                            })
            if h_path.exists():
                df_h = pd.read_csv(h_path)
                for _, row in df_h.iterrows():
                    tn = int(row["TN"])
                    role = "diagnostic" if season_id == "25FA" else role_map.get((season_id, tn), "validation")
                    date = float(row["DATE"])
                    h_no = int(row.get("HNO", 0))
                    for var in ["DRY_INC", "DRY_CUM"]:
                        sim_col = f"SIM_{var}"
                        if sim_col in row and np.isfinite(row[sim_col]):
                            records.append({
                                "season_id": season_id, "dataset_role": role, "treatment": tn,
                                "date": date, "harvest_number": h_no, "variable": var, "simulated": float(row[sim_col]),
                            })
            if j_path.exists():
                df_j = pd.read_csv(j_path)
                for _, row in df_j.iterrows():
                    tn = int(row["TN"])
                    role = "diagnostic" if season_id == "25FA" else role_map.get((season_id, tn), "validation")
                    for var in ["HWAM"]:
                        sim_col = f"SIM_{var}"
                        if sim_col in row and np.isfinite(row[sim_col]):
                            records.append({
                                "season_id": season_id, "dataset_role": role, "treatment": tn,
                                "date": 99999.0, "harvest_number": 0, "variable": var, "simulated": float(row[sim_col]),
                            })
        return pd.DataFrame(records)

    pairs_rows = []
    pred_rows = []

    for _, row in selected_pairs.iterrows():
        pair_id = int(row["pair_id"])
        ra = int(row["real_a"])
        rb = int(row["real_b"])
        phi_a = float(row["phi_a"])
        phi_b = float(row["phi_b"])
        param_dist = float(row["parameter_distance"])

        df_a = _extract_records(ra)
        df_b = _extract_records(rb)

        merged = df_a.merge(
            df_b,
            on=["season_id", "dataset_role", "treatment", "date", "harvest_number", "variable"],
            suffixes=("_a", "_b"),
        )

        role_rms = {}
        for role in ["validation", "diagnostic"]:
            sub = merged[merged["dataset_role"] == role]
            rms_list = []
            for var, grp in sub.groupby("variable"):
                sig = SIGMA_EFF_MAP.get(var, 1.0)
                diff = grp["simulated_a"] - grp["simulated_b"]
                rms = math.sqrt(((diff / sig) ** 2).mean())
                rms_list.append(rms)
            role_rms[role] = float(np.mean(rms_list)) if rms_list else np.nan

        d_val = role_rms["validation"]
        d_diag = role_rms["diagnostic"]
        pred_dist = (d_val + d_diag) / 2.0
        classification = "prediction_similar" if max(d_val, d_diag) <= 1.0 else "prediction_divergent"

        pairs_rows.append({
            "run_id": CASE_PREFIX,
            "data_status": "tooling_demo",
            "pair_id": pair_id,
            "real_a": ra,
            "real_b": rb,
            "phi_a": phi_a,
            "phi_b": phi_b,
            "phi_total": (phi_a + phi_b) / 2.0,
            "parameter_distance": param_dist,
            "prediction_distance": pred_dist,
            "classification": classification,
        })
        pred_rows.append({
            "run_id": CASE_PREFIX,
            "data_status": "tooling_demo",
            "pair_id": pair_id,
            "real_a": ra,
            "real_b": rb,
            "phi_a": phi_a,
            "phi_b": phi_b,
            "parameter_distance": param_dist,
            "d_validation": d_val,
            "d_diagnostic": d_diag,
            "prediction_distance": pred_dist,
            "classification": classification,
        })
        print(f"  Pair {pair_id} (real_{ra} vs real_{rb}): param_dist={param_dist:.3f}, d_val={d_val:.4f}, d_diag={d_diag:.4f}, pred_dist={pred_dist:.4f}")

    pairs_path = out_dir / "candidate_pairs.csv"
    pd.DataFrame(pairs_rows).to_csv(pairs_path, index=False, encoding="utf-8")
    pred_path = out_dir / "candidate_pair_predictions.csv"
    pd.DataFrame(pred_rows).to_csv(pred_path, index=False, encoding="utf-8")

    # Manifest
    artifacts = []
    for fn in ["posterior_diagnostics.csv", "posterior_samples.csv", "spearman_correlation.csv", "candidate_pairs.csv", "candidate_pair_predictions.csv"]:
        artifacts.append({"path": fn, "sha256": sha256_file(out_dir / fn)})
    manifest = {
        "run_id": CASE_PREFIX,
        "bundle_type": "t4_posterior_equifinality",
        "data_status": "tooling_demo",
        "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifacts": artifacts,
    }
    (out_dir / "paper_data_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[Phase 1 Done] Saved posterior bundle to {out_dir}")


# =========================================================================
# Phase 2: Build Conditional Prediction Uncertainty Data Bundle
# =========================================================================
def build_conditional_data_bundle():
    print("\n" + "=" * 80)
    print("PHASE 2: Building Conditional Prediction Uncertainty Bundle for C31")
    print("=" * 80)
    out_dir = PAPER_DATA_DIR / "conditional"
    out_dir.mkdir(parents=True, exist_ok=True)

    export_conditional_predictions(
        run_dir=RUN_DIR,
        case=CASE_PREFIX,
        iteration=FINAL_ITERATION,
        calibration_design=DESIGN_PATH,
        season_bundles={
            "25SP": ROOT / "data/user/experiments/xxql2501_corrected_20260923",
            "26SP": ROOT / "data/user/experiments/xxql2601_corrected_20260923",
        },
        treatment_metadata_csv=METADATA_PATH,
        official_dssat=OFFICIAL_DSSAT,
        out_dir=out_dir,
        workers=6,
        member_limit=None,
        member_list=None,
        verify_members=3,
        allow_unvalidated_demo=True,
    )
    print(f"[Phase 2 Done] Saved conditional uncertainty bundle to {out_dir}")


# =========================================================================
# Phase 3: Render Publication Figures via R
# =========================================================================
def render_r_figures():
    print("\n" + "=" * 80)
    print("PHASE 3: Rendering R Figures for Ensemble and Conditional Suites")
    print("=" * 80)
    logs_dir = FIGURES_RENDER_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    tasks = [
        # Ensemble / Posterior Figures
        (
            "ensemble",
            PAPER_DATA_DIR / "ensemble",
            FIGURES_RENDER_DIR / "ensemble",
            [
                "--figure-ids",
                "figs5_posterior,figs6_spearman,figs7_equifinality",
            ],
        ),
        # Conditional Prediction Uncertainty Figures
        (
            "conditional",
            PAPER_DATA_DIR / "conditional",
            FIGURES_RENDER_DIR / "conditional",
            [
                "--figure-ids",
                "fig_model_performance_uncertainty,diagnostic_conditional_residual_by_treatment,fig4_dynamics_conditional,figs4_all_treatments_conditional",
                "--process-variables",
                "LAID,LWAD,SWAD",
            ],
        ),
    ]

    for name, src, dst, options in tasks:
        dst.mkdir(parents=True, exist_ok=True)
        command = [
            str(RSCRIPT),
            "paper/R/make_all.R",
            "--input-dir",
            str(src),
            "--out-dir",
            str(dst),
            *options,
            "--allow-unvalidated-demo",
            "--publication-label-note",
            PUB_NOTE,
        ]
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        env["LANG"] = "en_US"

        log_path = logs_dir / f"R_{name}.log"
        with log_path.open("w", encoding="utf-8") as f:
            proc = subprocess.run(command, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, env=env)
        print(f"[R Render] {name:15s} -> exit code {proc.returncode} (log: {log_path.name})")
        if proc.returncode != 0:
            print(log_path.read_text(encoding="utf-8", errors="ignore")[-1000:])
            raise RuntimeError(f"Rendering failed for {name}")

    print("[Phase 3 Done] All R figures rendered successfully!")


# =========================================================================
# Phase 4: Synchronize Figures and Update Root figure_manifest.json
# =========================================================================
def sync_and_manifest():
    print("\n" + "=" * 80)
    print("PHASE 4: Synchronizing Figures to paper/03_Figures/ and Updating Manifest")
    print("=" * 80)
    main_dir = FIGURES_03_DIR / "Main_Figures"
    supp_dir = FIGURES_03_DIR / "Supplementary_Figures"
    diag_dir = FIGURES_03_DIR / "Custom_Diagnostic_Figures"
    for d in [main_dir, supp_dir, diag_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Copy rendered ensemble figures
    ens_render = FIGURES_RENDER_DIR / "ensemble"
    for f in ens_render.glob("*"):
        if f.is_file():
            shutil.copy2(f, supp_dir / f.name)
            # Also maintain backward compatibility root copy
            shutil.copy2(f, FIGURES_03_DIR / f.name)

    # Copy rendered conditional figures
    cond_render = FIGURES_RENDER_DIR / "conditional"
    for f in cond_render.glob("*"):
        if f.is_file():
            fname = f.name
            if "model_performance_uncertainty" in fname:
                shutil.copy2(f, main_dir / fname)
            elif "residual" in fname:
                shutil.copy2(f, diag_dir / fname)
            else:
                shutil.copy2(f, supp_dir / fname)
            # Root copy
            shutil.copy2(f, FIGURES_03_DIR / fname)

    # Compile figure_manifest.json
    all_artifacts = []
    for f in sorted(FIGURES_03_DIR.glob("**/*")):
        if f.is_file() and f.name != "figure_manifest.json" and not f.name.endswith(".log"):
            rel_path = f.relative_to(FIGURES_03_DIR).as_posix()
            all_artifacts.append({
                "path": rel_path,
                "sha256": sha256_file(f),
                "size_bytes": f.stat().st_size,
            })

    root_manifest = {
        "schema_version": 2,
        "champion_id": "C31",
        "candidate_title": "C31: Scheme 1 Dual-Spring Precision Champion (TB1=9.20°C, Error-Minimizing)",
        "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "renderer": "R 4.5.2",
        "calibration_run_id": CASE_PREFIX,
        "publication_label_note": PUB_NOTE,
        "artifacts_count": len(all_artifacts),
        "artifacts": all_artifacts,
    }
    manifest_path = FIGURES_03_DIR / "figure_manifest.json"
    manifest_path.write_text(json.dumps(root_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[Phase 4 Done] Compiled {manifest_path.name} with {len(all_artifacts)} artifacts.")


def main():
    build_posterior_data_bundle()
    build_conditional_data_bundle()
    render_r_figures()
    sync_and_manifest()
    print("\n" + "=" * 80)
    print("ALL STEPS COMPLETED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    main()
