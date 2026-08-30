"""Launch Script for v24 Calibration with Plug Root Weight PLWT=7.0g + 7-Layer Root-Zone Soil (80 reals x 5 iters x 6 agents).

Integrates:
1. Transplanting Plug Biomass (PLWT = 7.0 g/plant) with 8cm plug depth (PLDP=8, SPRL=8).
2. 7-Layer Tillage/Measurement Root-Zone Soil (SLB = 20, 40, 60, 80, 100, 140, 180) to eliminate thin-layer artificial leaching.
3. Hydraulic retention & Active Solute Foraging (SDUL, PORMIN, RTNO3, RTNH4, RWDTH, RTEXF).
4. Greenhouse Steady-State Mineralization (SOIL_SLNF [2.8, 3.6]).
5. Measured Leaf N ceiling & Senescence protection (LNREF [4.5, 5.6], SENRTE [0.3, 2.0], NRCVR [0.35, 0.55]).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CASE_NAME = "e02_v24_synergy_plwt7g_rootzone7l_80x5_20260822"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
BOUNDS_ID = "eggplant_e02_v24_synergy_plwt7g_rootzone7l_20260822"

N_REALS = 80
NOPTMAX = 5
N_AGENTS = 6
SEED = 20260822

EXP_25_7L = ROOT / "data/user/experiments/xxql2501_rootzone_7layer_20260822"
EXP_26_7L = ROOT / "data/user/experiments/xxql2601_rootzone_7layer_20260822"
BOUNDS_SRC = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v23_formal_full_synergy_20260821.csv"


def prepare_experiment_bundles():
    # Update PLWT to 7.0g in both bundles
    for p, sname, yr in [(EXP_25_7L, "XXQL2501", "25"), (EXP_26_7L, "XXQL2601", "26")]:
        tmx = p / f"{sname}.TMX"
        lines = tmx.read_text(encoding="utf-8").splitlines()
        new_lines = []
        for l in lines:
            if l.strip().startswith("2 ") and f"{yr}075" in l:
                # Exact fixed format with PLWT = 7.0g
                new_lines.append(f" 2 {yr}075   -99   2.7   2.7     T     R    90    90     8   7.0    60    25     1     8                        Eggplant")
            else:
                new_lines.append(l)
        tmx.write_text("\n".join(new_lines), encoding="utf-8")
        
        # Update manifest hashes
        manifest_path = p / "input_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["bundle_id"] = p.name
            for entry in manifest.get("files", []):
                fname = entry.get("relative_path") or entry.get("filename") or entry.get("name")
                if fname and (p / fname).exists():
                    data = (p / fname).read_bytes()
                    entry["sha256"] = hashlib.sha256(data).hexdigest()
                    entry["size_bytes"] = len(data)
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Experiment bundles updated with PLWT = 7.0g and manifests refreshed.")


def prepare_bounds_and_freeze():
    frame = pd.read_csv(BOUNDS_SRC, encoding="utf-8-sig")
    proposal_csv = ROOT / "data/parameter_registry/bounds_proposals" / f"{BOUNDS_ID}.csv"
    frozen_csv = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"
    proposal_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(proposal_csv, index=False, encoding="utf-8-sig")
    
    if frozen_csv.exists():
        os.remove(frozen_csv)
    meta_path = frozen_csv.parent / f"{BOUNDS_ID}.yaml"
    if meta_path.exists():
        os.remove(meta_path)
        
    subprocess.run([
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal_csv), "--crop", "eggplant",
        "--bounds-id", BOUNDS_ID, "--notes", "v24 Calibration with PLWT=7.0g and 7-layer Root-Zone Soil"
    ], cwd=ROOT, check=True)
    print(f"Frozen bounds prepared & registered: {BOUNDS_ID}")


def build_and_launch():
    prepare_experiment_bundles()
    prepare_bounds_and_freeze()
    
    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)
        
    design_path = ROOT / "configs/runs" / f"{CASE_NAME}.json"
    design_content = {
        "schema_version": 1,
        "design_id": CASE_NAME,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "v24 Calibration with PLWT=7.0g and 7-layer Root-Zone Soil",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Pure measured FileX IC values with 7-layer root-zone soil and PLWT=7.0g",
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {
            "enabled": True,
            "mode": "increment_plus_terminal",
            "variable": "CHPDT",
            "process_lambda_per_season": 200.0,
            "terminal_lambda_per_season": 300.0
        },
        "process_state_objective": {
            "enabled": True,
            "mode": "signed_difference_plus_terminal",
            "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasons": [
            {
                "season_id": "25SP",
                "experiment_code": "XXQL2501",
                "bundle_path": str(EXP_25_7L),
                "role": "calibration",
                "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP",
                "experiment_code": "XXQL2601",
                "bundle_path": str(EXP_26_7L),
                "role": "calibration",
                "treatments": [2, 11, 3, 12]
            }
        ],
        "pest_ies": {
            "num_reals": N_REALS,
            "noptmax": NOPTMAX,
            "par_sigma_range": 4.0,
            "lambda_mults": [0.1, 1.0, 10.0],
            "subreg": True,
            "subreg_how": "par_sigma_range"
        }
    }
    
    with open(design_path, "w", encoding="utf-8") as f:
        json.dump(design_content, f, indent=2)
        
    print(f"\n=======================================================")
    print(f"   Building v24 Medium Calibration with PLWT=7.0g: {CASE_NAME}")
    print(f"   Config: {N_REALS} reals x {NOPTMAX} iters x {N_AGENTS} agents")
    print(f"=======================================================")
    
    builder_cmd = [
        sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
        "--variant", "official",
        "--case", CASE_NAME,
        "--design", str(design_path),
        "--bounds-id", BOUNDS_ID,
        "--noptmax", str(NOPTMAX),
        "--ies-num-reals", str(N_REALS),
        "--random-seed", str(SEED)
    ]
    subprocess.run(builder_cmd, cwd=ROOT, check=True)
    
    cmd_parallel = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(RUN_DIR),
        "--case", CASE_NAME,
        "--mode", "ies",
        "--n-agents", str(N_AGENTS),
        "--wait"
    ]
    print(f"Launching {N_AGENTS}-Agent Parallel IES for {CASE_NAME}...")
    subprocess.run(cmd_parallel, cwd=ROOT, check=True)
    print(f"\nv24 PLWT=7.0g Medium Calibration completed successfully!")


if __name__ == "__main__":
    build_and_launch()
