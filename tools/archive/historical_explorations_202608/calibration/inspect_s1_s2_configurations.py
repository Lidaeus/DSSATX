import json
import pandas as pd
from pathlib import Path

root = Path("D:/Tomato_Cal")

# S1
s1_json = json.loads((root / "configs/runs/e02_from_scratch_10L_B_s1_canopy_0_4_60cm_20260827.json").read_text(encoding="utf-8"))
s1_bounds = pd.read_csv(root / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_s1_canopy_0_4_60cm_bounds_20260827.csv")
s1_weights = pd.read_csv(root / "workspace/runs/e02_from_scratch_s1_canopy_0_4_60cm_20260827/e02_s1_canopy_group_weight_audit.csv")

# S2
s2_json = json.loads((root / "configs/runs/e02_from_scratch_10L_B_s2_yield_0_4_60cm_20260827.json").read_text(encoding="utf-8"))
s2_bounds = pd.read_csv(root / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_s2_yield_0_4_60cm_bounds_20260827.csv")
s2_weights = pd.read_csv(root / "workspace/runs/e02_from_scratch_s2_yield_0_4_60cm_20260827/e02_s2_yield_group_weight_audit.csv")

print("=== 1. STAGE S1 (Canopy Pre-calibration) ===")
print(f"Ensemble Size: {s1_json['pest_ies']['num_reals']}, Iterations: {s1_json['pest_ies']['noptmax']}, Seed: {s1_json['pest_ies']['random_seed']}")
print(f"Calibration Seasons: {[s['season_id'] for s in s1_json['seasons'] if s['role']=='calibration']}")
print(f"Validation Seasons: {[s['season_id'] for s in s1_json['seasons'] if s['role']=='validation']}")
print(f"Objectives Config: Process State={s1_json['process_state_objective']['enabled']}, Harvest Dry={s1_json['harvest_dry_objective']['enabled']}, N-Resp={s1_json['nitrogen_response_objective']['enabled']}, W-Resp={s1_json['water_response_objective']['enabled']}")

act1 = s1_bounds[s1_bounds["status"] == "active"]
print(f"\nActive Parameters (n = {len(act1)}):")
for idx, r in act1.iterrows():
    pname = r["name"]
    pargp = r["pargp"]
    pfile = r["file"]
    init_v = float(r["init"])
    low_v = float(r["lower"])
    up_v = float(r["upper"])
    print(f"  {pname:12s} | init: {init_v:8.4f} | lower: {low_v:8.4f} | upper: {up_v:8.4f} | group: {pargp:18s} | file: {pfile}")

print(f"\nS1 Observation Groups & Weights (Total Groups = {len(s1_weights)}):")
print(s1_weights[["group", "season_id", "variable_family", "phi_budget", "n_obs", "mean_weight", "note"]].to_string(index=False))

print("\n" + "="*80 + "\n")

print("=== 2. STAGE S2 (Yield Pre-calibration) ===")
print(f"Ensemble Size: {s2_json['pest_ies']['num_reals']}, Iterations: {s2_json['pest_ies']['noptmax']}, Seed: {s2_json['pest_ies']['random_seed']}")
print(f"Calibration Seasons: {[s['season_id'] for s in s2_json['seasons'] if s['role']=='calibration']}")
print(f"Validation Seasons: {[s['season_id'] for s in s2_json['seasons'] if s['role']=='validation']}")
print(f"Objectives Config: Process State={s2_json['process_state_objective']['enabled']}, Harvest Dry={s2_json['harvest_dry_objective']['enabled']}, N-Resp={s2_json['nitrogen_response_objective']['enabled']}, W-Resp={s2_json['water_response_objective']['enabled']}")

act2 = s2_bounds[s2_bounds["status"] == "active"]
print(f"\nActive Parameters (n = {len(act2)}):")
for idx, r in act2.iterrows():
    pname = r["name"]
    pargp = r["pargp"]
    pfile = r["file"]
    init_v = float(r["init"])
    low_v = float(r["lower"])
    up_v = float(r["upper"])
    print(f"  {pname:12s} | init: {init_v:8.4f} | lower: {low_v:8.4f} | upper: {up_v:8.4f} | group: {pargp:18s} | file: {pfile}")

print(f"\nS2 Observation Groups & Weights (Total Groups = {len(s2_weights)}):")
print(s2_weights[["group", "season_id", "variable_family", "phi_budget", "n_obs", "mean_weight", "note"]].to_string(index=False))
