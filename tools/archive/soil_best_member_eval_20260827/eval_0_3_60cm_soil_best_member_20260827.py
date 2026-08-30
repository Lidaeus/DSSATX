"""Evaluate Stage S5 Best Member with 0-3cm, 3-60cm Two-Layer Soil across 25SP, 26SP, and 25FA (34 treatments)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools/analysis") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools/analysis"))

from render_arm_d_best17_diagnostics_20260820 import (
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)

CAND_PARAMS = ROOT / "workspace/runs/e02_from_scratch_s5_soil_fertility_expanded_200reals_20260827/candidates/cand1_lowest_phi_params.csv"
CASE_NAME = "e02_eval_0_3_60cm_soil_all34_20260827"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
OUT_FIG_DIR = ROOT / "figture" / "e02_0_3_60cm_soil_diagnostics_20260827"
MAPPING_CSV = ROOT / "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv"
REG_CSV = ROOT / "workspace/runs/e02_from_scratch_s5_soil_fertility_expanded_200reals_20260827/e02_s5_soil200_observation_registry.csv"

if RUN_DIR.exists():
    shutil.rmtree(RUN_DIR)
RUN_DIR.mkdir(parents=True, exist_ok=True)
OUT_FIG_DIR.mkdir(parents=True, exist_ok=True)

# 0-3cm, 3-60cm Two-Layer Soil Profile Layer Definition
SOIL_0_3_60CM_LAYERS = """@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
     3     1  .150  .320  .450 1.000  0.23  1.45  0.70  35.0  30.0   -99  0.05   8.0   -99   -99   -99
    60     1  .150  .320  .450  .900  0.23  1.50  0.65  35.0  30.0   -99  0.05   8.0   -99   -99   -99
    80     4  .157  .330  .460  .250  0.24  1.50  0.18  35.0  30.0   -99   -99   -99   -99   -99   -99
   100     5  .166  .340  .510  .150  0.24  1.49  0.10  35.0  30.0   -99   -99   -99   -99   -99   -99
   140     6  .173  .305  .400  .080  0.24  1.53  0.07  35.0  30.0   -99   -99   -99   -99   -99   -99
   180     6  .176  .290  .350  .030  0.24  1.55  0.05  35.0  30.0   -99   -99   -99   -99   -99   -99"""


def patch_soil_sol_to_0_3_60cm(src_soil: Path, dst_soil: Path) -> None:
    """Replace IBTM910017 layers with 0-3cm and 3-60cm structure."""
    text = src_soil.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    new_lines = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("*IBTM910017"):
            new_lines.append(l)
            i += 1
            while i < len(lines) and not lines[i].startswith("@  SLB"):
                new_lines.append(lines[i])
                i += 1
            new_lines.append(SOIL_0_3_60CM_LAYERS)
            # Skip old layer lines until next profile
            while i < len(lines) and not lines[i].startswith("*IBPP910015"):
                i += 1
        else:
            new_lines.append(l)
            i += 1
    dst_soil.write_text("\n".join(new_lines), encoding="utf-8")


# 1. Create custom bundle copies with 0-3cm & 3-60cm soil
BUNDLE_ROOT = RUN_DIR / "_bundles"
BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)

SEASON_MAP = {
    "25SP": ("XXQL2501", ROOT / "data/user/experiments/xxql2501_from_scratch_10L_B_20260826", [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]),
    "26SP": ("XXQL2601", ROOT / "data/user/experiments/xxql2601_from_scratch_10L_B_20260826", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]),
    "25FA": ("XXQL2502", ROOT / "data/user/experiments/xxfa_from_scratch_10L_B_20260826", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]),
}

season_bundles = {}
for s, (excode, orig_bundle, tmts) in SEASON_MAP.items():
    b_dir = BUNDLE_ROOT / s
    if b_dir.exists():
        shutil.rmtree(b_dir)
    shutil.copytree(orig_bundle, b_dir)
    # Patch SOIL.SOL to 0-3cm & 3-60cm
    patch_soil_sol_to_0_3_60cm(orig_bundle / "SOIL.SOL", b_dir / "SOIL.SOL")
    season_bundles[s] = b_dir

# 2. Build multi-season forward design
design_dict = {
    "schema_version": 1,
    "design_id": CASE_NAME,
    "cultivar_identity": "TM0008",
    "shared_parameter_scope": "0-3cm & 3-60cm Two-Layer Soil Evaluation with Stage S5 Best Parameters",
    "bounds_id": "eggplant_e02_s5_soil_fertility_expanded_bounds_20260827",
    "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
    "group_policy": "configs/runs/e02_from_scratch_group_policy_20260826.csv",
    "harvest_dry_objective": {
        "enabled": True,
        "mode": "increment_plus_terminal",
        "variable": "CHPDT",
    },
    "process_state_objective": {
        "enabled": True,
        "mode": "signed_difference_plus_terminal",
        "variables": ["LAID", "LWAD", "SWAD"]
    },
    "seasons": [
        {
            "season_id": s,
            "experiment_code": excode,
            "bundle_path": str(season_bundles[s]),
            "role": "calibration",
            "treatments": tmts
        }
        for s, (excode, _, tmts) in SEASON_MAP.items()
    ]
}

design_path = RUN_DIR / "joint_design_0_3_60cm.json"
with open(design_path, "w", encoding="utf-8") as f:
    json.dump(design_dict, f, indent=2)

# 3. Run multi-season simulation
env = os.environ.copy()
env["PYTHONPATH"] = str(ROOT)
cmd_run = [
    sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
    "--design", str(design_path),
    "--param-csv", str(CAND_PARAMS),
    "--prefix", "eval_0_3_60cm",
    "--harvest-var", "CHPDT",
    "--keep-nitrogen-outputs",
]
print("Running deterministic simulation for 0-3cm & 3-60cm soil across 34 treatments...")
subprocess.run(cmd_run, cwd=str(RUN_DIR), env=env, check=True)

# 4. Compute metrics across all 3 seasons
metric_rows = []

for s in ["25SP", "26SP", "25FA"]:
    sdir = RUN_DIR / "_seasons" / s
    h_df = build_season_harvest_compare(sdir, s)
    p_df = build_season_process_compare(sdir, s)

    for v in ["DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"]:
        obs_c, sim_c = f"OBS_{v}", f"SIM_{v}"
        if obs_c in h_df.columns and sim_c in h_df.columns:
            m = compute_metrics(h_df[obs_c].to_numpy(float), h_df[sim_c].to_numpy(float))
            m.update({"season": s, "variable": v, "n": len(h_df), "soil_profile": "0-3cm_3-60cm_two_layer"})
            metric_rows.append(m)

    for v in ["LAID", "LWAD", "SWAD", "CHTD"]:
        obs_c, sim_c = f"OBS_{v}", f"SIM_{v}"
        if obs_c in p_df.columns and sim_c in p_df.columns:
            m = compute_metrics(p_df[obs_c].to_numpy(float), p_df[sim_c].to_numpy(float))
            m.update({"season": s, "variable": v, "n": len(p_df), "soil_profile": "0-3cm_3-60cm_two_layer"})
            metric_rows.append(m)

df_metrics = pd.DataFrame(metric_rows)
out_csv = ROOT / "workspace/reports/e02_from_scratch_10L_B_20260826/e02_0_3_60cm_soil_evaluation_metrics.csv"
df_metrics.to_csv(out_csv, index=False)
print(f"\nSaved 0-3cm & 3-60cm soil evaluation metrics -> {out_csv}")

# 5. Render diagnostic plots
cmd_plot = [
    sys.executable, str(ROOT / "tools/calibration/plot_dynamics.py"),
    "--det-root", str(RUN_DIR),
    "--out-root", str(OUT_FIG_DIR),
    "--seasons", "25SP,26SP,25FA",
    "--include-all-treatments",
    "--mapping-csv", str(MAPPING_CSV)
]
if REG_CSV.exists():
    cmd_plot.extend(["--registry-csv", str(REG_CSV)])

print(f"\nRendering 0-3cm & 3-60cm diagnostics via plot_dynamics.py -> {OUT_FIG_DIR}...")
subprocess.run(cmd_plot, cwd=str(ROOT), check=True)
print("0-3cm & 3-60cm soil evaluation complete!")
