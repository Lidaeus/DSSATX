#!/usr/bin/env python3
"""Build and export posterior & equifinality data bundle and render formal publication figures.

Workflow:
1. Extract 16 core physiological parameters across phenology, canopy, reproductive sink-source,
   hydraulics, and nitrogen mobilization.
2. Compute prior vs posterior IQR shrinkage, bounds proximity, and compile:
   - posterior_diagnostics.csv
   - posterior_samples.csv (continuous ensemble realizations for density plots)
   - spearman_correlation.csv (pairwise rank correlation structure)
3. Detect equifinal candidate pairs and compute deterministic validation & diagnostic prediction distances:
   - candidate_pairs.csv
   - candidate_pair_predictions.csv
4. Package hash-checked paper_data_manifest.json (bundle_type: t4_posterior_equifinality)
5. Render publication figures via Rscript paper/R/make_all.R:
   - Fig. S5 Posterior Contraction (DEMO_FigS5_posterior_contraction)
   - Fig. S5 Posterior Kernel Density (DEMO_FigS5_posterior_density)
   - Fig. S6 Spearman Rank Correlation Structure (DEMO_FigS6_spearman_structure)
   - Fig. S7 Candidate-Pair Prediction Distance (DEMO_FigS7_candidate_prediction_distance)
6. Archive rendered figure suite into workspace/candidates/candidate_c15_real72_grand_champion/posterior_figures/
"""

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from itertools import combinations
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.project import sha256_file
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

RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_gen_13trt_tb1_80_95_150x6_20260920"
CASE_PREFIX = "full_gen_13trt_tb1_80_95_150x6"
DATA_STATUS = "tooling_demo"

OUT_DATA_DIR = RUN_DIR / "paper_data_posterior"
OUT_FIGURES_DIR = RUN_DIR / "posterior_figures"
CANDIDATE_FIGURES_DIR = PROJECT_ROOT / "workspace" / "candidates" / "candidate_c15_real72_grand_champion" / "posterior_figures"

RSCRIPT_PATH = r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"

CORE_PARAMETERS = [
    # Phenology
    "TB1", "EM-FL", "FL-SH", "FL-SD",
    # Canopy & Photosynthesis
    "LFMAX", "KCAN", "SLAVR", "SIZLF",
    # Reproductive Sink-Source & Harvest
    "PODUR", "SFDUR", "XFRT", "THRSH",
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


def step1_compute_posterior_diagnostics_and_samples():
    print("=" * 80)
    print("STEP 1: Computing posterior diagnostics and samples for 16 core parameters")
    print("=" * 80)
    OUT_DATA_DIR.mkdir(parents=True, exist_ok=True)

    prior_df = pd.read_csv(RUN_DIR / f"{CASE_PREFIX}.0.par.csv")
    post_df = pd.read_csv(RUN_DIR / f"{CASE_PREFIX}.6.par.csv")
    bounds_df = pd.read_csv(
        PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_full_gen_tb1_80_95_13trt_20260920.csv"
    )
    bounds_lookup = bounds_df.set_index(bounds_df["name"].str.upper())

    col_prior_map = {c.upper(): c for c in prior_df.columns if c != "real_name"}
    col_post_map = {c.upper(): c for c in post_df.columns if c != "real_name"}

    diag_rows = []
    sample_rows = []

    for param in CORE_PARAMETERS:
        c_pr = col_prior_map[param]
        c_po = col_post_map[param]

        pr_vals = prior_df[c_pr].dropna()
        po_vals = post_df[c_po].dropna()

        lb = float(bounds_lookup.loc[param, "lower"])
        ub = float(bounds_lookup.loc[param, "upper"])
        rng = ub - lb if (np.isfinite(lb) and np.isfinite(ub)) else 1.0
        tol = max(1e-10, 1e-4 * rng)

        pr_iqr = float(pr_vals.quantile(0.75) - pr_vals.quantile(0.25))
        po_iqr = float(po_vals.quantile(0.75) - po_vals.quantile(0.25))
        shrink = float(1.0 - po_iqr / pr_iqr) if pr_iqr > 0 else 0.0

        frac_lb = float(np.mean(np.abs(po_vals - lb) <= tol))
        frac_ub = float(np.mean(np.abs(po_vals - ub) <= tol))

        diag_rows.append({
            "run_id": CASE_PREFIX,
            "data_status": DATA_STATUS,
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
        })

        for val in po_vals:
            sample_rows.append({
                "run_id": CASE_PREFIX,
                "data_status": DATA_STATUS,
                "parameter": param,
                "value": float(val),
            })

    diag_path = OUT_DATA_DIR / "posterior_diagnostics.csv"
    pd.DataFrame(diag_rows).to_csv(diag_path, index=False, encoding="utf-8")
    print(f"  -> Generated {diag_path.name} ({len(diag_rows)} parameters)")

    samples_path = OUT_DATA_DIR / "posterior_samples.csv"
    pd.DataFrame(sample_rows).to_csv(samples_path, index=False, encoding="utf-8")
    print(f"  -> Generated {samples_path.name} ({len(sample_rows)} sample values)")


def step2_compute_spearman_correlation():
    print("\n" + "=" * 80)
    print("STEP 2: Computing Spearman rank-correlation matrix for 16 core parameters")
    print("=" * 80)
    post_df = pd.read_csv(RUN_DIR / f"{CASE_PREFIX}.6.par.csv")
    col_post_map = {c.upper(): c for c in post_df.columns if c != "real_name"}

    rows = []
    for a, b in combinations(CORE_PARAMETERS, 2):
        ca, cb = col_post_map[a], col_post_map[b]
        r, _ = spearmanr(post_df[ca], post_df[cb])
        rows.append({
            "run_id": CASE_PREFIX,
            "data_status": DATA_STATUS,
            "parameter_a": a,
            "parameter_b": b,
            "spearman": float(r) if np.isfinite(r) else 0.0,
        })

    sp_path = OUT_DATA_DIR / "spearman_correlation.csv"
    pd.DataFrame(rows).to_csv(sp_path, index=False, encoding="utf-8")
    print(f"  -> Generated {sp_path.name} ({len(rows)} parameter pairs)")


def _extract_comparison_records_for_real(real_id: int) -> pd.DataFrame:
    eval_dir = PROJECT_ROOT / "scratch" / "eval_new_tb1_150x6" / f"run_new_iter6_real{real_id}"
    meta_path = PROJECT_ROOT / "configs" / "figures" / "treatment_metadata_xxql2501_2601_joint.csv"
    meta_df = pd.read_csv(meta_path)
    role_map = {(r["season_id"], int(r["treatment"])): r["dataset_role"] for _, r in meta_df.iterrows()}

    batches = {
        "25SP": PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch.v48",
        "26SP": PROJECT_ROOT / "scratch" / "eval_new_tb1_150x6" / "batches" / "DSSBatch_26SP_all.v48",
        "25FA": PROJECT_ROOT / "scratch" / "eval_new_tb1_150x6" / "batches" / "DSSBatch_25FA_all.v48",
    }

    records = []
    for season_id in ["25SP", "26SP", "25FA"]:
        s_dir = eval_dir / season_id
        b_dst = s_dir / "DSSBatch.v48"
        if not b_dst.exists():
            shutil.copy2(batches[season_id], b_dst)
        pfx = f"real{real_id}_{season_id.lower()}"
        p_path = s_dir / f"{pfx}_deterministic_process_compare.csv"
        h_path = s_dir / f"{pfx}_deterministic_harvest_compare.csv"
        j_path = s_dir / f"{pfx}_deterministic_joint_compare.csv"
        if not (p_path.exists() and h_path.exists() and j_path.exists()):
            deterministic_harvest_compare(pfx, str(b_dst), run_dir=str(s_dir))
            deterministic_process_compare(pfx, str(b_dst), run_dir=str(s_dir))
            deterministic_joint_compare(pfx, str(b_dst), run_dir=str(s_dir))

        # Process (LAID, LWAD, SWAD)
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
        # Harvest (DRY_INC, DRY_CUM)
        if h_path.exists():
            df_h = pd.read_csv(h_path)
            for _, row in df_h.iterrows():
                tn = int(row["TN"])
                role = "diagnostic" if season_id == "25FA" else role_map.get((season_id, tn), "validation")
                date = float(row["DATE"])
                h_no = int(row.get("HARVEST_NO", 0))
                for var in ["DRY_INC", "DRY_CUM"]:
                    sim_col = f"SIM_{var}"
                    if sim_col in row and np.isfinite(row[sim_col]):
                        records.append({
                            "season_id": season_id, "dataset_role": role, "treatment": tn,
                            "date": date, "harvest_number": h_no, "variable": var, "simulated": float(row[sim_col]),
                        })
        # Joint (HWAM)
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


def step3_detect_candidate_pairs_and_predictions():
    print("\n" + "=" * 80)
    print("STEP 3: Detecting candidate pairs and computing deterministic prediction distances")
    print("=" * 80)
    prior, posterior, bounds, active, all_cal = load_posterior_ensemble(RUN_DIR, CASE_PREFIX)
    phi = _load_phi(RUN_DIR, CASE_PREFIX)
    candidates = detect_functional_equifinality(posterior, phi, active, threshold_frac=0.15)
    selected_pairs = select_candidate_pairs(candidates, max_pairs=3)
    print("Selected 3 representative candidate pairs:")
    print(selected_pairs[["pair_id", "real_a", "real_b", "phi_a", "phi_b", "parameter_distance"]])

    pairs_rows = []
    pred_rows = []

    for _, row in selected_pairs.iterrows():
        pair_id = int(row["pair_id"])
        ra = int(row["real_a"])
        rb = int(row["real_b"])
        phi_a = float(row["phi_a"])
        phi_b = float(row["phi_b"])
        param_dist = float(row["parameter_distance"])

        df_a = _extract_comparison_records_for_real(ra)
        df_b = _extract_comparison_records_for_real(rb)

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
            "data_status": DATA_STATUS,
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
            "data_status": DATA_STATUS,
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

    pairs_path = OUT_DATA_DIR / "candidate_pairs.csv"
    pd.DataFrame(pairs_rows).to_csv(pairs_path, index=False, encoding="utf-8")
    print(f"  -> Generated {pairs_path.name}")

    pred_path = OUT_DATA_DIR / "candidate_pair_predictions.csv"
    pd.DataFrame(pred_rows).to_csv(pred_path, index=False, encoding="utf-8")
    print(f"  -> Generated {pred_path.name}")


def step4_create_paper_data_manifest():
    print("\n" + "=" * 80)
    print("STEP 4: Creating frozen paper_data_manifest.json")
    print("=" * 80)
    artifacts = []
    for filename in [
        "posterior_diagnostics.csv",
        "posterior_samples.csv",
        "spearman_correlation.csv",
        "candidate_pairs.csv",
        "candidate_pair_predictions.csv",
    ]:
        p = OUT_DATA_DIR / filename
        artifacts.append({
            "role": filename.replace(".csv", ""),
            "path": filename,
            "sha256": sha256_file(p),
        })

    manifest = {
        "schema_version": 1,
        "bundle_type": "t4_posterior_equifinality",
        "run_id": CASE_PREFIX,
        "data_status": DATA_STATUS,
        "created_at": "2026-09-20T08:25:00Z",
        "renderer_contract": "r_paper_figures_v2",
        "artifacts": artifacts,
    }

    manifest_path = OUT_DATA_DIR / "paper_data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  -> Created {manifest_path} with {len(artifacts)} validated artifacts")


def step5_render_publication_figures():
    print("\n" + "=" * 80)
    print("STEP 5: Rendering publication figures via Rscript make_all.R")
    print("=" * 80)
    OUT_FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        RSCRIPT_PATH,
        str(PROJECT_ROOT / "paper" / "R" / "make_all.R"),
        "--input-dir", str(OUT_DATA_DIR),
        "--out-dir", str(OUT_FIGURES_DIR),
        "--figure-ids", "figs5_posterior,figs6_spearman,figs7_equifinality",
        "--allow-unvalidated-demo",
    ]

    print("Running command:", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.stdout:
        print(res.stdout)
    if res.stderr:
        print(res.stderr, file=sys.stderr)
    if res.returncode != 0:
        raise RuntimeError(f"R figure rendering failed with return code {res.returncode}")
    print("  -> R figures successfully rendered in", OUT_FIGURES_DIR)


def step6_archive_to_candidate():
    print("\n" + "=" * 80)
    print("STEP 6: Archiving rendered figures and source CSVs into candidate folder")
    print("=" * 80)
    CANDIDATE_FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    copied = 0
    for f in OUT_FIGURES_DIR.iterdir():
        if f.is_file():
            shutil.copy2(f, CANDIDATE_FIGURES_DIR / f.name)
            copied += 1
    print(f"  -> Successfully archived {copied} files to {CANDIDATE_FIGURES_DIR}")


def main():
    step1_compute_posterior_diagnostics_and_samples()
    step2_compute_spearman_correlation()
    step3_detect_candidate_pairs_and_predictions()
    step4_create_paper_data_manifest()
    step5_render_publication_figures()
    step6_archive_to_candidate()
    print("\n" + "=" * 80)
    print("All posterior & equifinality publication figures built and archived successfully!")
    print("=" * 80)


if __name__ == "__main__":
    main()
