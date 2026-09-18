"""Prepare a posterior-guided E02 V2 rerun without SOIL_WATER in Phi.

The prior formal run is used only as a starting posterior/bound reference.  The
rerun retains the canopy, biomass, organ-N, harvest-dry and N-response targets;
SOIL_WATER is diagnostic-only so soil-water residuals cannot steer Phi.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BASE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v2_formal25sp_nreleased_20260802.csv"
POSTERIOR = ROOT / "workspace/runs/e02_v2_formal25sp_nreleased_200x5_20260802/e02_v2_formal25sp_nreleased_200x5_20260802.5.par.csv"
PROPOSAL = ROOT / "data/parameter_registry/bounds_proposals/eggplant/eggplant_e02_v2_formal25sp_nosoilwater_20260802.csv"
FROZEN = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v2_formal25sp_nosoilwater_20260802.csv"
POLICY = ROOT / "configs/runs/e02_v2_canopy_yield_nresponse_nosoilwater_policy_20260802.csv"
BASE_POLICY = ROOT / "configs/runs/e02_v2_canopy_yield_nresponse_policy_20260802.csv"
DESIGN = ROOT / "configs/runs/eggplant_e02_v2_formal25sp_nosoilwater_20260802.json"
BOUND_ID = "eggplant_e02_v2_formal25sp_nosoilwater_20260802"


def main() -> None:
    bounds = pd.read_csv(BASE_BOUNDS)
    posterior = pd.read_csv(POSTERIOR)
    pcols = {str(c).lower(): c for c in posterior.columns}

    # Targeted changes are deliberately small.  NSTFAC is capped to avoid the
    # observed N-response cliff; NMOBMX is released below its former floor so
    # organ-N remobilisation is not forced to compensate at the boundary.
    actions = {
        "NSTFAC": (0.50, 0.90, "Cap upper tail after 12.5% upper touch; reduce N-response cliff while retaining stress sensitivity"),
        "NMOBMX": (0.005, 0.40, "Release lower floor after 63% lower touch; retain organ-N remobilisation identifiability"),
        "SLAVR": (280.0, 320.0, "Release upper edge after posterior concentration near upper bound; support underpredicted LAI"),
        "RTNH4": (0.0025, 0.05, "Small lower release after lower-side accumulation; keep uptake process-safe"),
        "XFINT": (0.12, 0.40, "Retain IPDMND-safe harvest interval envelope; no expansion despite upper touch"),
    }

    for i, row in bounds.iterrows():
        name = str(row["name"])
        if name in actions:
            lo, hi, note = actions[name]
            bounds.loc[i, "lower"] = lo
            bounds.loc[i, "upper"] = hi
            bounds.loc[i, "init"] = min(max(float(row["init"]), lo), hi)
            bounds.loc[i, "review_note"] = note
        elif str(row.get("status", "")).lower() == "active" and name.lower() in pcols:
            # For non-targeted parameters, retain the frozen bounds.  This
            # avoids manufacturing precision from a run whose soil-water
            # residuals were part of Phi.
            bounds.loc[i, "review_note"] = "Retained from V2 formal bounds; SOIL_WATER removed from Phi"

    bounds.to_csv(PROPOSAL, index=False)

    policy = pd.read_csv(BASE_POLICY)
    mask = policy["group"].astype(str).str.upper().eq("SOIL_WATER")
    if not mask.any():
        raise RuntimeError("SOIL_WATER row not found in observation policy")
    policy.loc[mask, "phi_role"] = "diagnostic_only"
    policy.loc[mask, "note"] = "Removed from Phi in posterior-guided rerun; retained for diagnostic reporting"
    policy.to_csv(POLICY, index=False)

    manifest = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801/input_manifest.json"
    design = {
        "schema_version": 1,
        "design_id": "eggplant_e02_v2_formal25sp_nosoilwater_20260802",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "V2 posterior-guided canopy/yield/N-response plus organ-N and soil parameters",
        "observation_policy": "configs/runs/e02_v2_canopy_yield_nresponse_nosoilwater_policy_20260802.csv",
        "group_policy": "configs/runs/t10_water_n_response_group_policy_harvestdry250_v1.csv",
        "initial_condition_policy": "25SP layer-mean IC valid bundle; TRNO9/TRNO14 excluded",
        "nitrogen_response_objective": {
            "enabled": True,
            "mapping_csv": "configs/runs/e02_v2_25sp_water_n_mapping_20260802.csv",
            "source_variable": "CHPDT",
            "contrast": "ln1p_Nk_minus_ln1p_N0",
            "response_target": "observed_shape",
            "levels": ["N1", "N2", "N3"],
            "sigma_floor": 0.1,
            "budget_rule": "0.75 static N_RESPONSE budget within 25SP",
        },
        "seasonal_parameterization": None,
        "seasons": [{
            "season_id": "25SP",
            "experiment_code": "XXQL2501",
            "bundle_path": "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801",
            "bundle_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "role": "calibration",
            "treatments": [2, 3, 4, 5, 10, 11, 12, 13],
        }],
        "formal": {"n_reals": 200, "noptmax": 5, "initial_ensemble_method": "sobol"},
        "diagnostic_single_season": True,
        "soil_water_phi": "disabled",
        "posterior_reference": "e02_v2_formal25sp_nreleased_200x5_20260802/.5.par.csv",
    }
    DESIGN.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not FROZEN.exists():
        subprocess.run([
            sys.executable, str(ROOT / "tools/freeze_bounds.py"),
            "--proposal", str(PROPOSAL), "--crop", "eggplant",
            "--bounds-id", BOUND_ID,
            "--notes", "Posterior-guided 25SP E02 V2 rerun with SOIL_WATER removed from Phi",
            "--operator", "Codex",
        ], cwd=ROOT, check=True)

    frozen = pd.read_csv(FROZEN)
    print(json.dumps({
        "bounds_id": BOUND_ID,
        "active_parameters": int((frozen["status"].astype(str).str.lower() == "active").sum()),
        "policy": str(POLICY),
        "soil_water_phi": str(policy.loc[mask, "phi_role"].iloc[0]),
        "design": str(DESIGN),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
