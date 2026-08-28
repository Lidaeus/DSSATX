"""Multi-arm exploratory calibration experiment for diagnosing and resolving Low-Nitrogen (N0) underperformance.

Arms (50 realizations x 3 iterations):
1. Arm A (crop_n_sensitivity): Crop N mobilization & stress tolerance parameters (NMOBMX, NVSMOB, NSTFAC, LNREF).
2. Arm B (soil_n_supply): Greenhouse soil nitrogen mineralization factor (SOIL_SLNF active: 1.05-1.40).
3. Arm C (stratified_objective): Stratified N0 vs N3 harvest yield objective weighting (50% N0 : 50% N3).
4. Arm D (combined_synergy): Synergy of Arm A (crop) + Arm B (soil) + Arm C (objective).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.build_pest import _write_observation_noise_ensemble
from src.calibration.initial_ensemble import generate_lhs_ensemble, write_ensemble_csv
from src.calibration.nitrogen_response import derive_filex_water_n_mapping
import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation

N_REALS = 50
NOPTMAX = 3
AGENTS = 6
SEED = 20260820

SOURCE_CASE = "e02_v18_srgf_phi_budget_official_200x6_20260820"
SOURCE_REALIZATION = "54"

BASE_FROZEN_PATH = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v18_srgf_phi_budget_20260820.csv"


def _source_anchor() -> dict[str, float]:
    source = ROOT / "workspace/runs" / SOURCE_CASE / f"{SOURCE_CASE}.6.par.csv"
    if not source.exists():
        return {}
    frame = pd.read_csv(source)
    real_col = frame.columns[0]
    row = frame.loc[
        frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(SOURCE_REALIZATION)
    ]
    if len(row) != 1:
        return {}
    return {
        str(key).lower(): float(value)
        for key, value in row.iloc[0].items()
        if key != real_col and pd.notna(value)
    }


def build_arm(arm_id: str, arm_desc: str, param_adjustments: dict, is_stratified: bool) -> tuple[Path, str]:
    case_name = f"e02_arm_{arm_id}_50x3_20260820"
    bounds_id = f"eggplant_e02_arm_{arm_id}_20260820"
    run_dir = ROOT / "workspace/runs" / case_name
    design_path = ROOT / "configs/runs" / f"{case_name}.json"
    proposal_csv = ROOT / "data/parameter_registry/bounds_proposals" / f"{bounds_id}.csv"
    frozen_csv = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{bounds_id}.csv"

    print(f"\n=======================================================")
    print(f"  Building Arm [{arm_id.upper()}]: {arm_desc}")
    print(f"=======================================================")

    # 1. Create parameter proposal & frozen bounds
    frame = pd.read_csv(BASE_FROZEN_PATH, encoding="utf-8-sig")
    existing_names = set(frame["name"].str.lower())
    for pname, adj in param_adjustments.items():
        if pname in existing_names:
            idx = frame[frame["name"].str.lower() == pname].index[0]
            for k, v in adj.items():
                if k in frame.columns:
                    frame.at[idx, k] = v
        else:
            new_row = {col: "" for col in frame.columns}
            new_row["name"] = pname
            new_row.update(adj)
            frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    proposal_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(proposal_csv, index=False, encoding="utf-8-sig")
    if frozen_csv.exists():
        os.remove(frozen_csv)
    meta_path = frozen_csv.parent / f"{bounds_id}.yaml"
    if meta_path.exists():
        os.remove(meta_path)

    cmd = [
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal_csv), "--crop", "eggplant",
        "--bounds-id", bounds_id, "--notes", f"Exploratory Arm {arm_id}: {arm_desc}"
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)

    # 2. Design JSON
    design_content = {
        "schema_version": 1,
        "design_id": case_name,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": f"Exploratory Arm {arm_id}: {arm_desc}",
        "bounds_id": bounds_id,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Fixed corrected FileX with 5cm topdressing depth and 10-layer soil inputs",
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {
            "enabled": True, "mode": "increment_plus_terminal",
            "variable": "CHPDT", "process_lambda_per_season": 300.0, "terminal_lambda_per_season": 200.0
        },
        "process_state_objective": {
            "enabled": True, "mode": "signed_difference_plus_terminal", "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasonal_parameterization": None,
        "seasons": [
            {
                "season_id": "25SP", "experiment_code": "XXQL2501",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v2_20260819"),
                "role": "calibration", "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP", "experiment_code": "XXQL2601",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v2_20260819"),
                "role": "calibration", "treatments": [2, 11, 3, 12]
            }
        ],
        "formal_contract": {
            "arm_id": arm_id, "n_reals": N_REALS, "noptmax": NOPTMAX, "is_stratified": is_stratified
        }
    }
    design_path.parent.mkdir(parents=True, exist_ok=True)
    design_path.write_text(json.dumps(design_content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 3. Base PST Build
    if run_dir.exists():
        shutil.rmtree(run_dir)
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    subprocess.run(
        [
            sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
            "--variant", "official", "--case", case_name, "--design", str(design_path),
            "--bounds-id", bounds_id, "--noptmax", str(NOPTMAX),
            "--ies-num-reals", str(N_REALS), "--random-seed", str(SEED),
        ],
        cwd=ROOT, env=env, check=True,
    )

    # 4. Sync PST Parameter Bounds
    pst_path = run_dir / f"{case_name}.pst"
    audit_path = run_dir / f"{case_name}.weights.audit.csv"
    registry_path = run_dir / f"{case_name}_observation_registry.csv"
    pst = pyemu.Pst(str(pst_path))
    frozen = pd.read_csv(frozen_csv, encoding="utf-8-sig")
    frozen["name"] = frozen["name"].astype(str).str.lower()
    frozen = frozen.set_index("name")
    
    for name in pst.parameter_data.index:
        if name in frozen.index:
            status = str(frozen.at[name, "status"]).lower()
            if status == "fixed":
                pst.parameter_data.at[name, "partrans"] = "fixed"
                pst.parameter_data.at[name, "parval1"] = float(frozen.at[name, "init"])
                pst.parameter_data.at[name, "parlbnd"] = float(frozen.at[name, "lower"])
                pst.parameter_data.at[name, "parubnd"] = float(frozen.at[name, "upper"])
            else:
                value = float(frozen.at[name, "init"])
                lower = float(frozen.at[name, "lower"])
                upper = float(frozen.at[name, "upper"])
                pst.parameter_data.at[name, "partrans"] = "none"
                pst.parameter_data.at[name, "parlbnd"] = lower
                pst.parameter_data.at[name, "parubnd"] = upper
                pst.parameter_data.at[name, "parval1"] = min(max(value, lower), upper)

    # 5. Apply Weights (Standard Phi Budget vs Stratified N0/N3 Budget)
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    registry.index = registry["obsnme"].astype(str).str.lower()
    audit.index = audit["obsnme"].astype(str).str.lower()

    # Harvest dry weighting
    dry = registry[registry["sim_token"].astype(str).isin(["CHPDTS_T", "CHPDTS"])].copy()
    
    # N mapping for stratification
    n0_treatments = {"25SP": [5, 13], "26SP": [11, 12]}
    n3_treatments = {"25SP": [2, 10], "26SP": [2, 3]}

    for season, rows in dry.groupby("season_id", sort=True):
        if not is_stratified:
            # Baseline: Season-level unified SST
            for tok, bgt, grp_name in [("CHPDTS_T", 300.0, "dry_proc_nse"), ("CHPDTS", 200.0, "dry_term_nse")]:
                sub = rows[rows["sim_token"] == tok]
                if len(sub) > 0:
                    vals = pd.to_numeric(sub["raw_obsval"], errors="raise").to_numpy(float)
                    sst = float(np.square(vals - vals.mean()).sum())
                    w = float(math.sqrt(bgt / sst))
                    sig = float(math.sqrt(sst / len(sub)))
                    for n in sub.index:
                        v = float(sub.loc[n, "raw_obsval"])
                        pst.observation_data.loc[n, ["obsval", "weight", "obgnme"]] = [v, w, grp_name]
                        for t in (registry, audit):
                            t.loc[n, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [v, w, sig, "phi_budget", "raw", grp_name.upper()]
                            t.loc[n, "group_multiplier"] = w * sig
        else:
            # Stratified: Split N0 (50% budget) and N3 (50% budget)
            for tok, bgt_tot, grp_name in [("CHPDTS_T", 300.0, "dry_proc_nse"), ("CHPDTS", 200.0, "dry_term_nse")]:
                sub = rows[rows["sim_token"] == tok]
                for n_tag, tnts, bgt in [("n0", n0_treatments[str(season)], bgt_tot * 0.5), ("n3", n3_treatments[str(season)], bgt_tot * 0.5)]:
                    n_sub = sub[sub["treatment"].isin(tnts)]
                    if len(n_sub) > 0:
                        vals = pd.to_numeric(n_sub["raw_obsval"], errors="raise").to_numpy(float)
                        sst = float(np.square(vals - vals.mean()).sum())
                        if sst <= 0:
                            sst = float(np.square(vals).sum()) or 1.0
                        w = float(math.sqrt(bgt / sst))
                        sig = float(math.sqrt(sst / len(n_sub)))
                        for n in n_sub.index:
                            v = float(n_sub.loc[n, "raw_obsval"])
                            pst.observation_data.loc[n, ["obsval", "weight", "obgnme"]] = [v, w, f"{grp_name}_{n_tag}"]
                            for t in (registry, audit):
                                t.loc[n, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [v, w, sig, "stratified_n_budget", "raw", f"{grp_name.upper()}_{n_tag.upper()}"]
                                t.loc[n, "group_multiplier"] = w * sig

    # Process states (LAID, LWAD, SWAD)
    for var, budget, toks in [("LAID", 150.0, ["LAIDS_T", "LAIDS", "LAIDM_T", "LAIDM"]),
                              ("LWAD", 150.0, ["LWADS_T", "LWADS", "LWADM_T", "LWADM"]),
                              ("SWAD", 150.0, ["SWADS_T", "SWADS", "SWADM_T", "SWADM"])]:
        v_rows = registry[registry["sim_token"].astype(str).isin(toks)].copy()
        for season, rows in v_rows.groupby("season_id", sort=True):
            vals = pd.to_numeric(rows["raw_obsval"], errors="raise").to_numpy(float)
            sst = float(np.square(vals - vals.mean()).sum())
            if sst > 0:
                w = float(math.sqrt(budget / sst))
                sig = float(math.sqrt(sst / len(rows)))
                for n in rows.index:
                    v = float(rows.loc[n, "raw_obsval"])
                    pst.observation_data.loc[n, ["obsval", "weight", "obgnme"]] = [v, w, f"proc_{var.lower()}"]
                    for t in (registry, audit):
                        t.loc[n, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [v, w, sig, "phi_budget", "raw", f"PROC_{var}"]
                        t.loc[n, "group_multiplier"] = w * sig

    # Zero out exclusions (CHTD, WRESP, NRESP)
    zero_obs = pst.observation_data[
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("CHTD") |
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("WRESP") |
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("NRESP")
    ].index
    pst.observation_data.loc[zero_obs, "weight"] = 0.0

    pst.control_data.noptmax = NOPTMAX
    pst.pestpp_options.update({
        "ies_num_reals": N_REALS,
        "rand_seed": SEED,
        "ies_parameter_ensemble": f"{case_name}.0.par.csv",
        "ies_observation_ensemble": f"{case_name}.observation_ensemble.csv",
        "ies_include_base": "false",
    })
    pst.write(str(pst_path))
    registry.reset_index(drop=True).to_csv(registry_path, index=False, encoding="utf-8-sig")
    audit.reset_index(drop=True).to_csv(audit_path, index=False, encoding="utf-8-sig")

    params_path = run_dir / f"{case_name}_params.csv"
    params = pd.read_csv(params_path)
    lookup = pst.parameter_data["parval1"].to_dict()
    params["value"] = params.apply(lambda r: lookup.get(str(r["name"]).lower(), r["value"]), axis=1)
    params.to_csv(params_path, index=False)

    # 6. Ensemble Generation
    par = pst.parameter_data
    ensemble_bounds = pd.DataFrame({
        "name": par.index,
        "init": par.parval1,
        "lower": par.parlbnd,
        "upper": par.parubnd,
        "status": np.where(par.partrans.astype(str).str.lower().eq("fixed"), "fixed", "active"),
    })
    ensemble = generate_lhs_ensemble(N_REALS, ensemble_bounds, SEED, method="sobol")
    anchor = _source_anchor()
    real_col = ensemble.columns[0]
    first = ensemble.index[0]
    for name in ensemble.columns[1:]:
        key = str(name).lower()
        if key in anchor:
            lower = float(par.at[key, "parlbnd"])
            upper = float(par.at[key, "parubnd"])
            ensemble.at[first, name] = min(max(anchor[key], lower), upper)
    ensemble.at[first, real_col] = f"anchor_member{SOURCE_REALIZATION}"
    ensemble_path = run_dir / f"{case_name}.0.par.csv"
    write_ensemble_csv(ensemble, ensemble_path)

    _write_observation_noise_ensemble(pst_path, audit_path, run_dir, case_name, N_REALS, SEED)

    print(f"Task built: {case_name} in {run_dir}")
    return run_dir, case_name


def run_and_evaluate_arm(run_dir: Path, case_name: str, arm_id: str, arm_name: str) -> dict:
    """Run parallel IES for arm and execute deterministic replay & metrics evaluation."""
    print(f"\n[Running Parallel IES for {case_name}]...")
    cmd = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir), "--case", case_name,
        "--mode", "ies", "--n-agents", str(AGENTS), "--wait"
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)

    # Find best member
    phi_csv = run_dir / f"{case_name}.phi.actual.csv"
    df_phi = pd.read_csv(phi_csv)
    last_row = df_phi.iloc[-1]
    members = [c for c in df_phi.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
    best_mem = None
    min_phi = float("inf")
    for m in members:
        val = float(last_row[m])
        if val < min_phi:
            min_phi = val
            best_mem = m

    print(f"[{arm_id.upper()}] Best Member #{best_mem} with Phi: {min_phi:.2f}")

    # Replay deterministic
    det_root = run_dir / f"deterministic_best_{best_mem}"
    det_root.mkdir(parents=True, exist_ok=True)
    out_root = ROOT / f"figture/exploratory_arms/{case_name}_best{best_mem}"
    out_root.mkdir(parents=True, exist_ok=True)

    evaluation.CASE = case_name
    evaluation.RUN_DIR = run_dir
    evaluation.BEST_MEMBER = best_mem
    evaluation.SOURCE_ITERATION = NOPTMAX
    evaluation.BEST_PHI = min_phi
    evaluation.CALIBRATION_STATE = "engineering_validated"
    evaluation.ARTIFACT_TYPE = f"arm_{arm_id}_diagnostics"
    evaluation.HARVEST_OBJECTIVE = f"Exploratory Arm {arm_id}: {arm_name}"
    evaluation.SOIL_INJECTION_DESCRIPTION = "10-layer soil profile"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.OBS_REGISTRY = run_dir / f"{case_name}_observation_registry.csv"
    evaluation.OUT_ROOT = out_root
    evaluation.DET_ROOT = det_root
    evaluation.SEASONS = [
        {"season_id": "25SP", "excode": "XXQL2501", "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14], "bundle": ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v2_20260819"},
        {"season_id": "26SP", "excode": "XXQL2601", "treatments": list(range(1, 13)), "bundle": ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v2_20260819"},
    ]
    evaluation.SEASON_IDS = ["25SP", "26SP"]
    evaluation.COLORS = {"25SP": "#2878B5", "26SP": "#2A9D55"}
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None

    mapping_csv = det_root / "two_season_water_n_mapping_from_filex.csv"
    mappings = [
        derive_filex_water_n_mapping(season["bundle"] / f"{season['excode']}.TMX", season_id=season["season_id"], treatments=season["treatments"])
        for season in evaluation.SEASONS
    ]
    pd.concat(mappings, ignore_index=True).to_csv(mapping_csv, index=False, encoding="utf-8-sig")
    evaluation.PLOT_MAPPING_CSV = mapping_csv
    evaluation.EXTRA_LIMITATIONS = []
    evaluation.main()

    for name in ("metrics_by_season_variable.csv", "organ_n_compare.csv"):
        src_file = det_root / name
        if src_file.is_file():
            shutil.copy2(src_file, out_root / name)

    # Extract score metrics
    metrics_path = det_root / "metrics_by_season_variable.csv"
    all_metrics = pd.read_csv(metrics_path) if metrics_path.exists() else pd.DataFrame()
    
    # Parse N0 vs N3 yield from PestHarvest
    map_df = pd.read_csv(mapping_csv)
    p_harv = det_root / "PestHarvest.OUT"
    n0_diff_25, n3_diff_25, n0_diff_26, n3_diff_26 = np.nan, np.nan, np.nan, np.nan
    if p_harv.exists():
        reg_df = pd.read_csv(run_dir / f"{case_name}_observation_registry.csv")
        h_reg = reg_df[reg_df["sim_token"].astype(str).str.contains("CHPDT")].copy()
        h_lines = p_harv.read_text().splitlines()
        p_map = {}
        for l in h_lines:
            m = re.match(r"RUN\s+(\d+)\s+TN\s+(\d+)\s+HNO\s+(\d+)\s+DATE\s+(\d+)\s+(.*)", l)
            if m:
                r, tn, hno, date, rest = m.groups()
                toks = re.findall(r"@([A-Za-z0-9_]+)@\s+([0-9\.\-]+)", rest)
                for tok, val in toks:
                    s_id = "25SP" if int(r) <= 4 else "26SP"
                    p_map[f"{s_id}_{tok}_R{r}_H{hno}".lower()] = float(val)
        h_reg["simval"] = h_reg["obsnme"].str.lower().map(p_map)
        h_reg["error"] = h_reg["simval"] - h_reg["raw_obsval"]
        map_df["treatment"] = map_df["treatment"].astype(int)
        h_reg = h_reg.merge(map_df[["season_id", "treatment", "water_level", "nitrogen_level"]].drop_duplicates(), on=["season_id", "treatment"], how="left")
        
        # Terminal dry errors
        term = h_reg[h_reg["sim_token"] == "CHPDTS"]
        n0_25 = term[(term["season_id"] == "25SP") & (term["nitrogen_level"] == "N0")]
        n3_25 = term[(term["season_id"] == "25SP") & (term["nitrogen_level"] == "N3")]
        n0_26 = term[(term["season_id"] == "26SP") & (term["nitrogen_level"] == "N0")]
        n3_26 = term[(term["season_id"] == "26SP") & (term["nitrogen_level"] == "N3")]
        
        n0_diff_25 = float(n0_25["error"].mean()) if not n0_25.empty else np.nan
        n3_diff_25 = float(n3_25["error"].mean()) if not n3_25.empty else np.nan
        n0_diff_26 = float(n0_26["error"].mean()) if not n0_26.empty else np.nan
        n3_diff_26 = float(n3_26["error"].mean()) if not n3_26.empty else np.nan

    plantgro_25 = det_root / "_seasons/25SP/PlantGro.OUT"
    plantgro_26 = det_root / "_seasons/26SP/PlantGro.OUT"
    
    def parse_max_lai(pg_path, tnts):
        if not pg_path.exists():
            return np.nan
        text = pg_path.read_text()
        runs = re.split(r'\*RUN\s+(\d+)', text)
        max_lais = []
        for i in range(1, len(runs), 2):
            run_body = runs[i+1]
            m_tn = re.search(r'TREATMENT\s+(\d+)', run_body)
            tn = int(m_tn.group(1)) if m_tn else int(runs[i])
            if tn in tnts:
                lines = run_body.splitlines()
                h = [j for j, l in enumerate(lines) if l.startswith('@YEAR')]
                if h:
                    cols = lines[h[0]][1:].split()
                    d = [l.split() for l in lines[h[0]+1:] if l.strip() and not l.startswith('@') and not l.startswith('!') and not l.startswith('*')]
                    df = pd.DataFrame(d, columns=cols)
                    if 'LAID' in df.columns:
                        max_lais.append(pd.to_numeric(df['LAID'], errors='coerce').max())
        return float(np.mean(max_lais)) if max_lais else np.nan

    lai_25_n0 = parse_max_lai(plantgro_25, [5, 13])
    lai_26_n0 = parse_max_lai(plantgro_26, [11, 12])
    
    # Extract DRY_CUM metrics
    dry_25 = all_metrics[(all_metrics['season'] == '25SP') & (all_metrics['variable'] == 'DRY_CUM')]
    dry_26 = all_metrics[(all_metrics['season'] == '26SP') & (all_metrics['variable'] == 'DRY_CUM')]

    score = {
        "arm_id": arm_id,
        "arm_name": arm_name,
        "case": case_name,
        "best_member": best_mem,
        "min_phi": min_phi,
        "25SP_dry_nse": float(dry_25["nse"].values[0]) if not dry_25.empty else np.nan,
        "25SP_dry_bias": float(dry_25["bias"].values[0]) if not dry_25.empty else np.nan,
        "25SP_dry_d_index": float(dry_25["d_index"].values[0]) if not dry_25.empty else np.nan,
        "26SP_dry_nse": float(dry_26["nse"].values[0]) if not dry_26.empty else np.nan,
        "26SP_dry_bias": float(dry_26["bias"].values[0]) if not dry_26.empty else np.nan,
        "26SP_dry_d_index": float(dry_26["d_index"].values[0]) if not dry_26.empty else np.nan,
        "25SP_N0_term_bias": n0_diff_25,
        "25SP_N3_term_bias": n3_diff_25,
        "26SP_N0_term_bias": n0_diff_26,
        "26SP_N3_term_bias": n3_diff_26,
        "25SP_N0_max_lai": lai_25_n0,
        "26SP_N0_max_lai": lai_26_n0,
    }
    return score


def main() -> int:
    arms = [
        {
            "id": "a_crop_n_sensitivity",
            "name": "Arm A: 作物生理耐低氮机制臂 (Crop N Sensitivity)",
            "params": {
                "nmobmx": {"init": 0.200, "lower": 0.100, "upper": 0.280, "status": "active"},
                "nvsmob": {"init": 0.350, "lower": 0.200, "upper": 0.450, "status": "active"},
                "nstfac": {"init": 0.400, "lower": 0.200, "upper": 0.600, "status": "active"},
                "lnref": {"init": 3.200, "lower": 2.800, "upper": 3.600, "status": "active"},
                "nslope": {"init": 0.180, "lower": 0.100, "upper": 0.250, "status": "active"},
            },
            "stratified": False
        },
        {
            "id": "b_soil_n_supply",
            "name": "Arm B: 土壤温室矿化供氮机制臂 (Soil N Supply & SLNF)",
            "params": {
                "soil_slnf": {"init": 1.200, "lower": 1.050, "upper": 1.400, "status": "active", "pargp": "SOIL_Chemical", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both"},
                "rtno3": {"init": 0.045, "lower": 0.010, "upper": 0.050, "status": "active"},
                "rtnh4": {"init": 0.045, "lower": 0.010, "upper": 0.050, "status": "active"},
            },
            "stratified": False
        },
        {
            "id": "c_stratified_objective",
            "name": "Arm C: 目标函数 N0/N3 分层等权优化臂 (Stratified Objective)",
            "params": {},
            "stratified": True
        },
        {
            "id": "d_combined_synergy",
            "name": "Arm D: 全要素协同组合臂 (Combined Synergy A+B+C)",
            "params": {
                "nmobmx": {"init": 0.200, "lower": 0.100, "upper": 0.280, "status": "active"},
                "nvsmob": {"init": 0.350, "lower": 0.200, "upper": 0.450, "status": "active"},
                "nstfac": {"init": 0.400, "lower": 0.200, "upper": 0.600, "status": "active"},
                "lnref": {"init": 3.200, "lower": 2.800, "upper": 3.600, "status": "active"},
                "nslope": {"init": 0.180, "lower": 0.100, "upper": 0.250, "status": "active"},
                "soil_slnf": {"init": 1.200, "lower": 1.050, "upper": 1.400, "status": "active", "pargp": "SOIL_Chemical", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both"},
                "rtno3": {"init": 0.045, "lower": 0.010, "upper": 0.050, "status": "active"},
                "rtnh4": {"init": 0.045, "lower": 0.010, "upper": 0.050, "status": "active"},
            },
            "stratified": True
        },
    ]

    scores = []
    for arm in arms:
        run_dir, case_name = build_arm(arm["id"], arm["name"], arm["params"], arm["stratified"])
        score = run_and_evaluate_arm(run_dir, case_name, arm["id"], arm["name"])
        scores.append(score)

    # Compile Cross-Arm Scorecard
    scorecard_df = pd.DataFrame(scores)
    out_dir = ROOT / "figture/exploratory_arms"
    out_dir.mkdir(parents=True, exist_ok=True)
    scorecard_path = out_dir / "multi_arm_decision_scorecard.csv"
    scorecard_df.to_csv(scorecard_path, index=False, encoding="utf-8-sig")

    print("\n" + "="*80)
    print("        CROSS-ARM EXPLORATORY DECISION SCORECARD (四臂横向对比决策矩阵)")
    print("="*80)
    print(scorecard_df.to_string(index=False))
    print("="*80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
