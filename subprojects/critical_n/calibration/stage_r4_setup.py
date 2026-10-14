"""Stage R4: PEST++ Multi-Objective Joint Calibration & Diagnostic Comparison.

Implements core specifications for Stage R4:
1. Model Engine: Sandbox execution using custom binary subprojects/critical_n/bin/dscsm048_cnc.exe
   with allometric demand dilution (DEMAND_CNC), cumulative fruit N tracking (CHPDTN in FreshWt/CROPGRO),
   safe buffer mobilization (MOBIL_CNC), and senescence decoupling (SENES_CNC).
2. Parameter Space Purification & Bottleneck Release:
   - Purify 5 Fortran ghost parameters: PROLFG, PROSTG, PRORTG, PROSHI, PROSHG -> status: fixed.
   - Release physical bottlenecks:
     * SENPOR_LATE upper bound relaxed to 0.28~0.32 (0.300)
     * RWUMX lower bound relaxed to 0.006
     * RTNO3 lower bound relaxed to 0.003
     * FRSTMF upper bound relaxed to 0.95
     * FL-LF maintained in physiological range [140.0, 220.0]
   - Strictly freeze exogenous invariants: CNC_A=4.85, CNC_B=0.38, CNC_W0=1.00, CNC_NC_INF=1.70%.
   - Active parameter count: exactly 61 parameters.
3. Objective Reformulation & CNC Soft Constraint:
   - Sparse phenological r_tol soft constraints across 12 treatments (48 targets, target=0.0).
   - Rebalanced phi budget: 76% terminal yield dominance, HPODW reduced to 2.0%, SWAD reduced to 1.5%.
   - Pseudo-Huber loss with delta=0.15 on dynamic growth variables.
4. Isolated Sandbox Execution:
   - Strictly sandboxed in subprojects/critical_n/runs/stage_r4_calibration/.
   - Production C:\\DSSAT48\\DSCSM048.EXE remains pristine and untouched.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from subprojects.critical_n.adapters.instruction_generator import (
    CNCObservationTarget,
    make_obs_name,
)
from subprojects.critical_n.adapters.pest_cnc_exporter import (
    PEST_CNC_FILENAME,
    export_pest_cnc,
)
from subprojects.critical_n.calibration.bounds_protocol import (
    CNC_FROZEN_INVARIANTS,
    CNC_PHYSICAL_BOUNDS,
    validate_no_active_cnc_params,
)
from subprojects.critical_n.calibration.cnc_builder import (
    build_cnc_observation_targets,
    resolve_treatment_n_levels,
)
from subprojects.critical_n.core.dilution_curve import (
    DEFAULT_CNC_A,
    DEFAULT_CNC_B,
    DEFAULT_CNC_NC_INF,
    DEFAULT_CNC_W0,
)
from subprojects.critical_n.core.objective_penalty import (
    PHYSIOLOGICAL_NNI_INTERVALS,
    pseudo_huber_loss,
    tolerance_relaxation_operator,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"
BIN_CNC = CRITICAL_N_DIR / "bin" / "dscsm048_cnc.exe"
BIN_VANILLA = CRITICAL_N_DIR / "bin" / "dscsm048_vanilla.exe"

# 5 Fortran ghost parameters that are purged (set to fixed)
STAGE_R4_GHOST_PARAMETERS: set[str] = {
    "PROLFG",
    "PROSTG",
    "PRORTG",
    "PROSHI",
    "PROSHG",
}

# The 61 active parameter identities for Stage R4
STAGE_R4_ACTIVE_PARAMETERS: list[str] = [
    "ATOP",
    "CMOBMX",
    "DSWBAR",
    "EM-FL",
    "EM-V1",
    "FINREF",
    "FL-LF",
    "FL-SD",
    "FL-SH",
    "FNPGN1",
    "FNPGN2",
    "FRLFF",
    "FRSTMF",
    "ICMP",
    "KCAN",
    "KEP",
    "LFMAX",
    "LNGSH",
    "LNREF",
    "NMOBMX",
    "NRCVR",
    "NSLOPE",
    "NSTFAC",
    "NVSMOB",
    "PGEFF",
    "PM06",
    "PODUR",
    "PORPT",
    "PROLFF",
    "PROLFI",
    "PRORTF",
    "PRORTI",
    "PROSTF",
    "PROSTI",
    "RHGHT",
    "RTNH4",
    "RTNO3",
    "RWDTH",
    "RWUMX",
    "SENDAY",
    "SENMAX_LATE",
    "SENPOR_LATE",
    "SENRT2",
    "SENRTE",
    "SFDUR",
    "SIZLF",
    "SLAVR",
    "SOIL_SLDR",
    "SWBAR_REC",
    "TB1",
    "TB2",
    "TCMP",
    "TM1",
    "TM2",
    "TO11",
    "TO12",
    "TRIFL",
    "VSSINK",
    "XFRT",
    "XMAGE",
    "YSWBAR_MID",
]

# Physical bottleneck releases and invariants
STAGE_R4_BOUND_ADJUSTMENTS: dict[str, dict[str, Any]] = {
    "SENPOR_LATE": {
        "lower": 0.170,
        "upper": 0.300,  # Relaxed from 0.260 to 0.300 (in range 0.28~0.32)
        "status": "active",
        "reason": "Stage R4: Upper bound relaxed to 0.300 to curb late-season overshooting",
    },
    "RWUMX": {
        "lower": 0.006,  # Relaxed from 0.009 to 0.006
        "upper": 0.018,
        "status": "active",
        "reason": "Stage R4: Lower bound relaxed to 0.006 to release water uptake bottleneck",
    },
    "RTNO3": {
        "lower": 0.003,  # Confirmed lower bound 0.003
        "upper": 0.015,
        "status": "active",
        "reason": "Stage R4: Lower bound maintained at 0.003",
    },
    "FRSTMF": {
        "lower": 0.720,
        "upper": 0.950,  # Relaxed from 0.860 to 0.950
        "status": "active",
        "reason": "Stage R4: Upper bound relaxed to 0.950 to allow optimal stem allocation",
    },
    "FL-LF": {
        "lower": 140.0,  # Protected physiological range, avoids destructive [50, 65]
        "upper": 220.0,
        "status": "active",
        "reason": "Stage R4: Maintained in physiological range [140.0, 220.0] avoiding dwarfism",
    },
    # 5 Ghost parameters fixed
    "PROLFG": {
        "init": 0.253461,
        "lower": 0.253461,
        "upper": 0.253461,
        "status": "fixed",
        "reason": "Stage R4: Ghost parameter purged, fixed at candidate center",
    },
    "PROSTG": {
        "init": 0.136445,
        "lower": 0.136445,
        "upper": 0.136445,
        "status": "fixed",
        "reason": "Stage R4: Ghost parameter purged, fixed at candidate center",
    },
    "PRORTG": {
        "init": 0.115542,
        "lower": 0.115542,
        "upper": 0.115542,
        "status": "fixed",
        "reason": "Stage R4: Ghost parameter purged, fixed at candidate center",
    },
    "PROSHI": {
        "init": 0.125000,
        "lower": 0.125000,
        "upper": 0.125000,
        "status": "fixed",
        "reason": "Stage R4: Ghost parameter purged, fixed at candidate center",
    },
    "PROSHG": {
        "init": 0.124968,
        "lower": 0.124968,
        "upper": 0.124968,
        "status": "fixed",
        "reason": "Stage R4: Ghost parameter purged, fixed at candidate center",
    },
}

# Rebalanced objective policy contract (17 families, total budget = 100.0)
STAGE_R4_OBJECTIVE_POLICY: list[dict[str, Any]] = [
    {
        "variable": "CHPDT",
        "family": "FINAL_DRY_YIELD",
        "phi_budget": 38.0,
        "n_targets": 12,
        "loss": "quadratic",
        "delta": None,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "CHFPW",
        "family": "FINAL_FRESH_YIELD",
        "phi_budget": 38.0,
        "n_targets": 12,
        "loss": "quadratic",
        "delta": None,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "CHPDT",
        "family": "HARVEST_DRY_CUMULATIVE_EARLY",
        "phi_budget": 1.0,
        "n_targets": 48,
        "loss": "pseudo_huber",
        "delta": 0.15,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "HPODW",
        "family": "HARVEST_DRY_EVENT",
        "phi_budget": 2.0,  # Downweighted from 5.0
        "n_targets": 60,
        "loss": "pseudo_huber",
        "delta": 0.15,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "LAID",
        "family": "CANOPY_LAI",
        "phi_budget": 2.5,
        "n_targets": 48,
        "loss": "pseudo_huber",
        "delta": 0.15,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "LWAD",
        "family": "LEAF_DRY_MASS",
        "phi_budget": 1.5,
        "n_targets": 48,
        "loss": "pseudo_huber",
        "delta": 0.15,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "SWAD",
        "family": "STEM_DRY_MASS",
        "phi_budget": 1.5,  # Downweighted from 3.0
        "n_targets": 48,
        "loss": "pseudo_huber",
        "delta": 0.15,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "CHTD",
        "family": "HEIGHT",
        "phi_budget": 1.0,
        "n_targets": 48,
        "loss": "pseudo_huber",
        "delta": 0.15,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "LEAF_N_PCT",
        "family": "LEAF_N_CONCENTRATION",
        "phi_budget": 1.5,
        "n_targets": 48,
        "loss": "pseudo_huber",
        "delta": 0.15,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "STEM_N_PCT",
        "family": "STEM_N_CONCENTRATION",
        "phi_budget": 1.5,
        "n_targets": 48,
        "loss": "pseudo_huber",
        "delta": 0.15,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "FRUIT_N_PCT",
        "family": "FRUIT_N_CONCENTRATION",
        "phi_budget": 1.0,
        "n_targets": 36,
        "loss": "pseudo_huber",
        "delta": 0.15,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "ADAP",
        "family": "ANTHESIS",
        "phi_budget": 1.0,
        "n_targets": 12,
        "loss": "quadratic",
        "delta": None,
        "scale_policy": "fixed_2_days",
        "approved": True,
    },
    {
        "variable": "VWC",
        "family": "SOIL_WATER",
        "phi_budget": 3.0,
        "n_targets": 180,
        "loss": "quadratic",
        "delta": None,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "WB100_INTERVAL",
        "family": "WATER_BALANCE_100CM",
        "phi_budget": 1.5,
        "n_targets": 24,
        "loss": "quadratic",
        "delta": None,
        "scale_policy": "frozen_calibration_family_mean",
        "approved": True,
    },
    {
        "variable": "W_FRESH_CONTRAST",
        "family": "W_SIGNED_CONTRAST",
        "phi_budget": 1.5,
        "n_targets": 8,
        "loss": "quadratic",
        "delta": None,
        "scale_policy": "frozen_terminal_fresh_yield_mean",
        "approved": True,
    },
    {
        "variable": "N_ADJACENT_FRESH_CONTRAST",
        "family": "N_ADJACENT_SIGNED_CONTRAST",
        "phi_budget": 1.5,
        "n_targets": 9,
        "loss": "quadratic",
        "delta": None,
        "scale_policy": "frozen_terminal_fresh_yield_mean",
        "approved": True,
    },
    {
        "variable": "R_TOL",
        "family": "CNC_NNI_PENALTY",
        "phi_budget": 2.0,  # CNC NNI soft constraint budget
        "n_targets": 48,
        "loss": "pseudo_huber",
        "delta": 0.15,
        "scale_policy": "fixed_unit_scale",
        "approved": True,
    },
]


def create_stage_r4_bounds(
    base_bounds_path_or_df: Union[str, Path, pd.DataFrame]
) -> pd.DataFrame:
    """Create purified, bottleneck-released parameter bounds table for Stage R4.

    Enforces:
    1. Exactly 61 active parameters (purges the 5 ghost parameters).
    2. SENPOR_LATE upper bound relaxed to 0.300.
    3. RWUMX lower bound relaxed to 0.006.
    4. RTNO3 lower bound relaxed to 0.003.
    5. FRSTMF upper bound relaxed to 0.950.
    6. FL-LF maintained in [140.0, 220.0].
    7. Exogenous CNC invariants strictly fixed.
    """
    if isinstance(base_bounds_path_or_df, (str, Path)):
        df = pd.read_csv(base_bounds_path_or_df).copy()
    else:
        df = base_bounds_path_or_df.copy()

    df["name"] = df["name"].astype(str).str.strip().str.upper()

    # Apply adjustments
    for p_name, adj in STAGE_R4_BOUND_ADJUSTMENTS.items():
        mask = df["name"] == p_name
        if mask.any():
            for k, v in adj.items():
                if k in df.columns:
                    df.loc[mask, k] = v
        else:
            # If not in base dataframe, append as new row
            row = {
                "name": p_name,
                "init": adj.get("init", adj.get("lower", 0.0)),
                "lower": adj.get("lower", 0.0),
                "upper": adj.get("upper", 1.0),
                "status": adj.get("status", "fixed"),
                "pargp": "StageR4_Adjusted",
                "location": "SPE",
                "file": "TMGRO048.SPE.base",
                "cultivar": "TM0008",
                "ecotype": "TM0001",
                "mode": "eggplant_stage2",
            }
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)

    # Ensure CNC frozen invariants are present and strictly fixed
    from subprojects.critical_n.calibration.bounds_protocol import create_frozen_cnc_records
    cnc_records = create_frozen_cnc_records()
    for rec in cnc_records:
        rec_name = str(rec["name"]).upper()
        mask = df["name"] == rec_name
        if mask.any():
            df.loc[mask, "status"] = "fixed"
            df.loc[mask, "init"] = rec["init"]
            df.loc[mask, "lower"] = rec["lower"]
            df.loc[mask, "upper"] = rec["upper"]
        else:
            df = pd.concat([df, pd.DataFrame([rec])], ignore_index=True)

    # Validate invariant protocol: no active CNC parameter
    validate_no_active_cnc_params(df)

    # Validate active parameter count
    active_params = df[df["status"] == "active"]["name"].tolist()
    if set(active_params) != set(STAGE_R4_ACTIVE_PARAMETERS):
        missing = set(STAGE_R4_ACTIVE_PARAMETERS) - set(active_params)
        unexpected = set(active_params) - set(STAGE_R4_ACTIVE_PARAMETERS)
        raise ValueError(
            f"Stage R4 active parameter mismatch! Missing: {missing}, Unexpected: {unexpected}"
        )

    return df


def create_stage_r4_objective_catalog(
    base_observations_path_or_df: Union[str, Path, pd.DataFrame],
    treatment_metadata_path_or_df: Union[str, Path, pd.DataFrame],
    cnc_run_dir: Optional[Union[str, Path]] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Construct the rebalanced 737-observation catalog and 17-family policy catalog.

    Combines the 689 base direct observations with 48 sparse phenological CNC r_tol targets.
    """
    if isinstance(base_observations_path_or_df, (str, Path)):
        base_obs = pd.read_csv(base_observations_path_or_df).copy()
    else:
        base_obs = base_observations_path_or_df.copy()

    if isinstance(treatment_metadata_path_or_df, (str, Path)):
        tmt_meta = pd.read_csv(treatment_metadata_path_or_df).copy()
    else:
        tmt_meta = treatment_metadata_path_or_df.copy()

    policy_df = pd.DataFrame(STAGE_R4_OBJECTIVE_POLICY)

    # Verify total budget
    assert math.isclose(policy_df["phi_budget"].sum(), 100.0, rel_tol=1e-5), "Budget sum != 100.0"

    # Map policy to base observations
    policy_by_family = policy_df.set_index("family").to_dict(orient="index")

    updated_obs_rows = []
    for _, row in base_obs.iterrows():
        fam = row["family"]
        pol = policy_by_family.get(fam, {})
        r_dict = row.to_dict()
        if pol:
            r_dict["phi_budget"] = pol["phi_budget"]
            r_dict["loss"] = pol["loss"]
            if pol.get("delta") is not None:
                r_dict["huber_delta"] = pol["delta"]
            # Recalculate final_weight = sqrt(phi_budget / n_targets)
            n_tgt = pol["n_targets"]
            r_dict["final_weight"] = math.sqrt(pol["phi_budget"] / n_tgt)
        updated_obs_rows.append(r_dict)

    # Generate 48 sparse phenological CNC targets
    # 4 DAS dates per treatment: DAS 38, 68, 98, 128 (spaced across season)
    n_map = dict(zip(tmt_meta["treatment"].astype(int), tmt_meta["nitrogen_level"].astype(str)))
    cnc_das_anchors = [38, 68, 98, 128]
    cnc_pol = policy_by_family["CNC_NNI_PENALTY"]
    cnc_weight = math.sqrt(cnc_pol["phi_budget"] / 48)  # sqrt(2.0 / 48) ~ 0.204124

    for trt in range(1, 13):
        for das in cnc_das_anchors:
            obs_nme = f"cnc_t{trt}_d{das}"
            cnc_row = {
                "season_id": "26SP",
                "trno": trt,
                "date": f"2026-DAS-{das:03d}",
                "variable": "R_TOL",
                "unit": "dimensionless",
                "observed": 0.0,
                "replicate_sd": 0.05,
                "n_rep": 1.0,
                "n_samples": 1.0,
                "n_eff": 1.0,
                "sigma_source": "physiological_tolerance_projection",
                "dataset_role": "calibration",
                "status": "approved_r4_cnc_soft_constraint",
                "source_file": "PestCNC.OUT",
                "family": "CNC_NNI_PENALTY",
                "phi_budget": cnc_pol["phi_budget"],
                "final_weight": cnc_weight,
                "obsnme": obs_nme,
                "fit_scale": 1.0,
                "fit_metric": "pseudo_huber_residual",
                "fit_scale_source": "unit_scale",
                "scale_policy": "fixed_unit_scale",
                "loss": "pseudo_huber",
                "huber_delta": 0.15,
                "pest_obsval": 0.0,
            }
            updated_obs_rows.append(cnc_row)

    combined_obs_df = pd.DataFrame(updated_obs_rows)
    assert len(combined_obs_df) == 737, f"Expected 737 targets (689 base + 48 CNC), got {len(combined_obs_df)}"
    return combined_obs_df, policy_df


def loss_residual(r: np.ndarray, kind: str, delta: float = 0.15) -> np.ndarray:
    """Evaluate loss transformed residual vector."""
    r = np.asarray(r, dtype=float)
    if kind == "quadratic":
        return r
    if kind == "pseudo_huber":
        if delta <= 0:
            raise ValueError(f"Pseudo-Huber delta must be positive, got {delta}")
        return r * np.sqrt(2.0 / (np.hypot(1.0, r / delta) + 1.0))
    raise ValueError(f"Unsupported loss function: {kind}")


def encode_stage_r4_objective(compared: pd.DataFrame) -> pd.DataFrame:
    """Encode simulated and observed values into weighted objective contributions."""
    comp = compared.copy()
    comp["normalized_raw_residual"] = (
        comp["simulated"] - comp["observed"]
    ) / pd.to_numeric(comp["fit_scale"])
    comp["pest_output"] = np.nan

    for fam, q in comp.groupby("family", sort=False):
        loss_kind = q["loss"].iloc[0]
        delta_val = float(q["huber_delta"].iloc[0]) if "huber_delta" in q and pd.notna(q["huber_delta"].iloc[0]) else 0.15
        comp.loc[q.index, "pest_output"] = loss_residual(
            comp.loc[q.index, "normalized_raw_residual"].to_numpy(),
            loss_kind,
            delta=delta_val,
        )

    if not np.isfinite(comp["pest_output"]).all():
        raise ValueError("Non-finite values encountered in objective encoding!")

    comp["phi_contribution"] = np.square(comp["pest_output"] * comp["final_weight"])
    return comp


def compute_comprehensive_metrics(obs: np.ndarray, sim: np.ndarray) -> dict[str, float]:
    """Compute comprehensive performance metrics (RMSE, NRMSE%, R2, NSE, d, MBE)."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    obs = obs[mask]
    sim = sim[mask]
    n = len(obs)
    if n == 0:
        return {
            "n": 0,
            "rmse": np.nan,
            "nrmse": np.nan,
            "r2": np.nan,
            "nse": np.nan,
            "d": np.nan,
            "mae": np.nan,
            "mbe": np.nan,
        }

    diff = sim - obs
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    obs_mean = float(np.mean(obs))
    nrmse = (
        float(100.0 * rmse / abs(obs_mean)) if abs(obs_mean) > 1e-9 else np.nan
    )
    mae = float(np.mean(np.abs(diff)))
    mbe = float(np.mean(diff))

    if np.std(obs) > 1e-9 and np.std(sim) > 1e-9:
        r = float(np.corrcoef(obs, sim)[0, 1])
        r2 = r ** 2
    else:
        r2 = np.nan

    ss_tot = float(np.sum((obs - obs_mean) ** 2))
    ss_res = float(np.sum(diff ** 2))
    nse = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-9 else np.nan

    d_denom = float(np.sum((np.abs(sim - obs_mean) + np.abs(obs - obs_mean)) ** 2))
    d = float(1.0 - ss_res / d_denom) if d_denom > 1e-9 else np.nan

    return {
        "n": n,
        "rmse": rmse,
        "nrmse": nrmse,
        "r2": r2,
        "nse": nse,
        "d": d,
        "mae": mae,
        "mbe": mbe,
    }


def parse_dssat_out_file(file_path: Path) -> dict[int, list[dict[str, str]]]:
    """Parses multi-treatment DSSAT output file into {trt_no: [records]}."""
    if not file_path.exists():
        return {}

    lines = file_path.read_text(encoding="latin-1", errors="ignore").splitlines()
    data_by_trt: dict[int, list[dict[str, str]]] = {}
    current_trt = None
    headers: list[str] = []

    for line in lines:
        sline = line.strip()
        if not sline:
            continue
        if sline.startswith("*RUN"):
            parts = sline.split()
            try:
                current_trt = int(parts[1])
                data_by_trt[current_trt] = []
            except (ValueError, IndexError):
                current_trt = None
            headers = []
            continue
        if sline.startswith("@"):
            headers = [h.strip() for h in sline[1:].split()]
            continue
        if sline.startswith("*") or sline.startswith("!"):
            continue
        if current_trt is not None and headers:
            values = sline.split()
            if len(values) >= len(headers):
                rec = {headers[i]: values[i] for i in range(len(headers))}
                data_by_trt[current_trt].append(rec)
            elif len(values) > 0:
                rec = {headers[i]: values[i] for i in range(len(values))}
                data_by_trt[current_trt].append(rec)

    return data_by_trt


def inject_critical_nitrogen(
    spe_file: Union[str, Path],
    params: Mapping[str, float],
) -> None:
    """Inject dynamic CNC_A, CNC_B, CNC_W0, CNC_NC_INF into TMGRO048.SPE."""
    spe_path = Path(spe_file)
    if not spe_path.is_file():
        return
    cnc_keys = ["CNC_A", "CNC_B", "CNC_W0", "CNC_NC_INF"]
    if not any(k in params for k in cnc_keys):
        return

    a_val = float(params.get("CNC_A", 4.85))
    b_val = float(params.get("CNC_B", 0.38))
    w0_val = float(params.get("CNC_W0", 1.00))
    inf_val = float(params.get("CNC_NC_INF", 1.70))

    content = spe_path.read_text(encoding="latin-1")
    lines = content.splitlines()

    crit_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("!*CRITICAL NITROGEN DILUTION"):
            crit_idx = i
            break

    data_line = f"{a_val:6.2f}{b_val:6.2f}{w0_val:6.2f}{inf_val:6.2f}               CNC_A,CNC_B,CNC_W0,CNC_NC_INF"

    if crit_idx != -1:
        replaced = False
        for j in range(crit_idx + 1, min(crit_idx + 6, len(lines))):
            s = lines[j].strip()
            if s.startswith("!") or s.startswith("@") or not s:
                continue
            lines[j] = data_line
            replaced = True
            break
        if not replaced:
            lines.insert(crit_idx + 2, data_line)
    else:
        lines.append("")
        lines.append("!*CRITICAL NITROGEN DILUTION PARAMETERS")
        lines.append("@ CNC_A  CNC_B CNC_W0 CNC_NC_INF")
        lines.append(data_line)

    spe_path.write_text("\n".join(lines) + "\n", encoding="latin-1")


class StageR4Sandbox:
    """Isolated execution sandbox for Stage R4 DSSAT simulations."""

    def __init__(
        self,
        sandbox_dir: Union[str, Path],
        binary_path: Union[str, Path] = BIN_CNC,
        model_source_dir: Optional[Union[str, Path]] = None,
    ):
        self.sandbox_dir = Path(sandbox_dir).resolve()
        self.binary_path = Path(binary_path).resolve()
        self.model_source_dir = (
            Path(model_source_dir).resolve()
            if model_source_dir
            else PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/selected_deterministic/_model"
        )
        assert self.binary_path.exists(), f"Binary not found: {self.binary_path}"
        assert self.model_source_dir.exists(), f"Model source not found: {self.model_source_dir}"

    def prepare(self) -> None:
        """Initialize clean sandboxed run directory with all necessary files."""
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        copy_files = [
            "DSSAT48.INH",
            "DSSAT48.INP",
            "DSSATPRO.v48",
            "DSSBatch.v48",
            "SOIL.SOL",
            "SOIL.SOL.base",
            "TMGRO048.CUL",
            "TMGRO048.CUL.base",
            "TMGRO048.ECO",
            "TMGRO048.ECO.base",
            "TMGRO048.SPE",
            "TMGRO048.SPE.base",
            "XXQL2601.TMA",
            "XXQL2601.TMT",
            "XXQL2601.TMX",
            "XXTW2403.WTH",
            "parameters.csv",
        ]
        for fn in copy_files:
            src_f = self.model_source_dir / fn
            if src_f.exists():
                shutil.copy(src_f, self.sandbox_dir / fn)

        # Place binary inside sandbox as DSCSM048.EXE
        shutil.copy(self.binary_path, self.sandbox_dir / "DSCSM048.EXE")

    def run_simulation(
        self,
        params: dict[str, float],
        timeout_sec: int = 180,
    ) -> dict[str, Any]:
        """Update model files with candidate parameters and execute DSSAT."""
        from src.dssat import run_dssat as runner
        from src.dssat.forward_joint import inject_phosphorus
        from src.dssat.forward_water_n import inject_environment

        # Save parameters.csv
        param_df = pd.DataFrame(
            [{"name": k, "value": v} for k, v in params.items()]
        )
        param_csv_path = self.sandbox_dir / "parameters.csv"
        param_df.to_csv(param_csv_path, index=False)

        # Inject parameters into genotype and environment files
        orig_cwd = os.getcwd()
        try:
            os.chdir(self.sandbox_dir)
            runner.PARAM_CSV = "parameters.csv"
            runner.BATCH_FILE = "DSSBatch.v48"
            runner.DSSAT_MODEL = "CRGRO048"
            runner.HARVEST_VAR = "CHPDT"
            runner.KEEP_SOIL_WATER = True
            runner.KEEP_NITROGEN_OUTPUTS = True

            runner.update_cul_file(param_csv_path="parameters.csv", target_cultivar="TM0008")
            ecotype = runner._infer_ecotype_from_cul(runner.CUL_FILE, "TM0008") or "TM0001"
            runner.update_eco_file(param_csv_path="parameters.csv", target_ecotype=ecotype)
            runner.update_spe_file(param_csv_path="parameters.csv")
            inject_phosphorus(runner.SPE_FILE, params)
            inject_critical_nitrogen(runner.SPE_FILE, params)
            inject_environment(self.sandbox_dir, params)
        finally:
            os.chdir(orig_cwd)

        # Execute DSCSM048.EXE
        t0 = time.time()
        cmd = [str(self.sandbox_dir / "DSCSM048.EXE"), "CRGRO048", "B", "DSSBatch.v48"]
        res = subprocess.run(
            cmd,
            cwd=self.sandbox_dir,
            input="\n" * 8,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        elapsed = time.time() - t0

        if res.returncode != 0:
            raise RuntimeError(
                f"DSSAT simulation failed in sandbox {self.sandbox_dir}: {res.stderr}"
            )

        # Generate PestCNC.OUT with R_TOL column
        tmt_meta_file = PROJECT_ROOT / "configs/figures/treatment_metadata_xxql2601.csv"
        export_pest_cnc(
            run_dir=self.sandbox_dir,
            include_r_tol=True,
            treatment_n_levels=tmt_meta_file,
        )

        return {
            "returncode": res.returncode,
            "elapsed_sec": elapsed,
            "stdout_tail": res.stdout[-200:] if res.stdout else "",
        }

    def extract_stage_r4_observations(
        self,
        target_catalog: pd.DataFrame,
    ) -> pd.DataFrame:
        """Extract simulated predictions for all 737 targets using canonical DSSAT extractors."""
        from src.calibration import water_n_joint

        # 1. Base empirical observations (689 targets)
        base_targets = target_catalog[target_catalog["family"] != "CNC_NNI_PENALTY"].copy()
        base_comp = water_n_joint.extract_observations(self.sandbox_dir, base_targets)

        # 2. CNC NNI tolerance soft constraint targets (48 targets)
        cnc_targets = target_catalog[target_catalog["family"] == "CNC_NNI_PENALTY"].copy()
        tmt_meta_file = PROJECT_ROOT / "configs/figures/treatment_metadata_xxql2601.csv"
        tmt_meta = pd.read_csv(tmt_meta_file)
        n_map = dict(zip(tmt_meta["treatment"].astype(int), tmt_meta["nitrogen_level"].astype(str)))

        cnc_map: dict[tuple[int, int], float] = {}
        cnc_path = self.sandbox_dir / "PestCNC.OUT"
        if cnc_path.exists():
            for line in cnc_path.read_text(encoding="latin-1", errors="ignore").splitlines():
                if line.startswith("*") or line.startswith("@") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 9:
                    try:
                        c_trt = int(parts[1])
                        c_das = int(parts[4])
                        c_nni = float(parts[8])
                        cnc_map[(c_trt, c_das)] = c_nni
                    except (ValueError, IndexError):
                        pass

        cnc_results = []
        for row in cnc_targets.to_dict("records"):
            trt = int(row["trno"])
            obs_nme = row["obsnme"]
            match = re.search(r"d(\d+)", obs_nme)
            das = int(match.group(1)) if match else 38
            sim_nni = cnc_map.get((trt, das), -99.0)
            n_lvl = n_map.get(trt, "N2")
            lo, hi = PHYSIOLOGICAL_NNI_INTERVALS.get(n_lvl, (0.85, 1.15))
            if sim_nni > 0.0:
                sim_val = tolerance_relaxation_operator(sim_nni, lo, hi)
            else:
                sim_val = 999.0
            cnc_results.append({**row, "simulated": sim_val})

        compared_df = pd.concat([base_comp, pd.DataFrame(cnc_results)], ignore_index=True)
        return encode_stage_r4_objective(compared_df)


def run_stage_r4_calibration_search(
    sandbox: StageR4Sandbox,
    base_params: dict[str, float],
    bounds_df: pd.DataFrame,
    target_catalog: pd.DataFrame,
    max_evals: int = 40,
) -> tuple[dict[str, float], pd.DataFrame, float]:
    """Execute Stage R4 joint multi-objective calibration search.

    Starts from prior best representative solution local_00023, explores the relaxed
    domain (SENPOR_LATE up to 0.30, FRSTMF up to 0.95, RWUMX/RTNO3 relaxed, 5 ghost params fixed),
    and finds the solution minimizing total Phi while eliminating LAI overshooting
    and preserving yield fit.
    """
    bounds_map = bounds_df.set_index("name").to_dict(orient="index")
    current_params = copy.deepcopy(base_params)

    # 1. Enforce ghost parameter purification
    for gp in STAGE_R4_GHOST_PARAMETERS:
        if gp in bounds_map:
            current_params[gp] = bounds_map[gp]["init"]

    # 2. Evaluate starting solution
    comp = sandbox.extract_stage_r4_observations(target_catalog)
    best_phi = float(comp["phi_contribution"].sum())
    lai_init = comp[comp["family"] == "CANOPY_LAI"]
    final_lai_init = float(lai_init[lai_init["date"] == "2026-07-17"]["simulated"].mean()) if len(lai_init) else 3.10
    best_score = best_phi + 15.0 * max(0.0, final_lai_init - 2.65) ** 2
    best_params = copy.deepcopy(current_params)
    best_comp = comp.copy()

    # Define candidate parameter tweaks for physiological bottleneck release
    # Test physiological gradient of SENPOR_LATE (0.28 -> 0.31), FRSTMF, RWUMX, FL-LF
    candidates: list[dict[str, float]] = []

    # Systematically explore SENPOR_LATE relaxation in [0.28, 0.32] domain
    # prioritizing 0.295 and 0.285 to eliminate LAI overshooting while preserving yield
    for s_late in [0.295, 0.285, 0.300, 0.310]:
        for fl_lf in [192.3, 185.0, 175.0]:
            for frstmf in [0.890, 0.920, 0.860]:
                for rwumx in [0.011, 0.008, 0.013]:
                    p = copy.deepcopy(current_params)
                    p["SENPOR_LATE"] = s_late
                    p["FL-LF"] = fl_lf
                    p["FRSTMF"] = frstmf
                    p["RWUMX"] = rwumx
                    # Ensure FRSTMF + FRLFF <= 0.995
                    if p["FRSTMF"] + p.get("FRLFF", 0.118) > 0.995:
                        p["FRLFF"] = 0.995 - p["FRSTMF"]
                    candidates.append(p)

    eval_count = 0
    for cand in candidates:
        if eval_count >= max_evals:
            break
        eval_count += 1
        try:
            sandbox.run_simulation(cand)
            comp_cand = sandbox.extract_stage_r4_observations(target_catalog)
            phi_cand = float(comp_cand["phi_contribution"].sum())

            # Yield check: ensure terminal yield CHFPW is well-behaved
            fresh_yield_comp = comp_cand[comp_cand["family"] == "FINAL_FRESH_YIELD"]
            nrmse_yield = float(
                100.0
                * np.sqrt(np.mean((fresh_yield_comp["simulated"] - fresh_yield_comp["observed"]) ** 2))
                / fresh_yield_comp["observed"].mean()
            )

            # LAI check: harvest LAI overshooting penalty
            lai_comp = comp_cand[comp_cand["family"] == "CANOPY_LAI"]
            final_lai_sim = float(lai_comp[lai_comp["date"] == "2026-07-17"]["simulated"].mean()) if len(lai_comp) else 2.65
            score_cand = phi_cand + 15.0 * max(0.0, final_lai_sim - 2.65) ** 2

            # Acceptance criteria: lower multi-objective composite score and yield NRMSE < 9.5%
            if score_cand < best_score and nrmse_yield < 9.5:
                best_score = score_cand
                best_phi = phi_cand
                best_params = copy.deepcopy(cand)
                best_comp = comp_cand.copy()
        except Exception:
            continue

    # Enforce all parameter identities from bounds table (including locked invariants and ghost params)
    for p_name, b_row in bounds_map.items():
        if p_name not in best_params:
            best_params[p_name] = float(b_row.get("init", b_row.get("lower", 0.0)))
        elif b_row.get("status") == "fixed":
            best_params[p_name] = float(b_row["init"])

    return best_params, best_comp, best_phi
