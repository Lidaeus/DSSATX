"""Generate full 22-treatment diagnostic plots for Fixed Arm A (Mem #71) and Fixed Arm B (Mem #9).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation
from src.calibration.nitrogen_response import derive_filex_water_n_mapping


def generate_suite_for_arm(run_dir_name: str, case_name: str, member_id: str, bundle_prefix: str, out_name: str):
    print(f"\n=======================================================")
    print(f"Generating full diagnostic plot suite for {out_name}...")
    print(f"=======================================================")
    
    det_root = ROOT / f"workspace/runs/plot_eval_{out_name}"
    out_root = ROOT / f"figture/{out_name}"
    
    evaluation.RUN_DIR = ROOT / f"workspace/runs/{run_dir_name}"
    evaluation.DET_ROOT = det_root
    evaluation.OUT_ROOT = out_root
    evaluation.BEST_MEMBER = str(member_id)
    evaluation.FIGURE_DIR = out_root
    evaluation.TABLE_DIR = out_root
    evaluation.CASE = case_name
    
    evaluation.SEASONS = [
        {
            "season_id": "25SP",
            "excode": "XXQL2501",
            "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
            "bundle": ROOT / f"data/user/experiments/xxql2501_{bundle_prefix}",
        },
        {
            "season_id": "26SP",
            "excode": "XXQL2601",
            "treatments": list(range(1, 13)),
            "bundle": ROOT / f"data/user/experiments/xxql2601_{bundle_prefix}",
        },
    ]
    evaluation.SEASON_IDS = [item["season_id"] for item in evaluation.SEASONS]
    evaluation.COLORS = {"25SP": "#2878B5", "26SP": "#2A9D55"}
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None

    if det_root.exists():
        shutil.rmtree(det_root)
    det_root.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)

    # Extract param row from PEST output
    par_file = ROOT / f"workspace/runs/{run_dir_name}/{case_name}.5.par.csv"
    par_df = pd.read_csv(par_file)
    r_col = [c for c in par_df.columns if c in ['real_name', 'realization']][0]
    best_row = par_df[par_df[r_col].astype(str) == str(member_id)].iloc[0]
    param_cols = [c for c in par_df.columns if c not in ['real_name', 'realization', 'iteration']]
    dest_params = det_root / f"best_member_{member_id}_params.csv"
    pd.DataFrame([{'name': p.upper(), 'value': float(best_row[p])} for p in param_cols]).to_csv(dest_params, index=False)
    
    evaluation._export_member = lambda out_csv: len(pd.read_csv(dest_params))

    mapping_csv = evaluation.DET_ROOT / "two_season_water_n_mapping_from_filex.csv"
    mappings = [
        derive_filex_water_n_mapping(
            season["bundle"] / f"{season['excode']}.TMX",
            season_id=season["season_id"],
            treatments=season["treatments"],
        )
        for season in evaluation.SEASONS
    ]
    pd.concat(mappings, ignore_index=True).to_csv(mapping_csv, index=False, encoding="utf-8-sig")
    evaluation.PLOT_MAPPING_CSV = mapping_csv
    evaluation.EXTRA_LIMITATIONS = [
        f"Evaluation of {out_name} (Member #{member_id}) on 0-4cm and 4-60cm soil scheme with fixed parameter engine.",
        "Evaluates 22 treatments (25SP TN 2-5, 9-14; 26SP TN 1-12).",
    ]

    rc = int(evaluation.main() or 0)
    print(f"Generated full suite for {out_name}: exit code {rc}, out_dir: {out_root}")

if __name__ == "__main__":
    # Arm A Fixed
    generate_suite_for_arm(
        run_dir_name="e02_arm_a_fixed_pgeff_20260828",
        case_name="e02_arm_a",
        member_id="71",
        bundle_prefix="from_scratch_0_4_60cm_20260827",
        out_name="e02_arm_a_fixed_pgeff_best71_0_4_60cm_20260828"
    )
    # Arm B Fixed
    generate_suite_for_arm(
        run_dir_name="e02_arm_b_clean_measuredn_fixed_pgeff_20260828",
        case_name="e02_arm_b",
        member_id="9",
        bundle_prefix="clean_measuredn_0_4_60cm_20260828",
        out_name="e02_arm_b_fixed_clean_measuredn_best9_0_4_60cm_20260828"
    )
