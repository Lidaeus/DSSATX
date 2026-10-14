#!/usr/bin/env python3
"""Cross-Season Phenotype Evaluation Engine for Official vs Custom (Stage R4 & Enhanced) DSSAT.

Evaluates DSSAT simulations across calibration (26SP) and validation/testing sets (25SP, 25FA).
Strictly isolated in subprojects/critical_n/.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from subprojects.critical_n.adapters.pest_cnc_exporter import export_pest_cnc
from subprojects.critical_n.scripts.build_and_verify_dssat import (
    PRODUCTION_EXE,
    check_production_safety,
)

BIN_CNC = CRITICAL_N_DIR / "bin" / "dscsm048_cnc.exe"
BIN_VANILLA = CRITICAL_N_DIR / "bin" / "dscsm048_vanilla.exe"

SEASONS_INFO = {
    "26SP": {
        "source_dir": PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/selected_deterministic/_model",
        "experiment_code": "XXQL2601",
        "batch_file": "DSSBatch.v48",
        "tmt_meta_file": PROJECT_ROOT / "configs/figures/treatment_metadata_xxql2601.csv",
        "role": "calibration",
    },
    "25SP": {
        "source_dir": PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/evaluation/25SP",
        "experiment_code": "XXQL2501",
        "batch_file": "DSSBatch.v48",
        "tmt_meta_file": PROJECT_ROOT / "configs/figures/treatment_metadata_xxql2501.csv",
        "role": "validation",
    },
    "25FA": {
        "source_dir": PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/evaluation/25FA",
        "experiment_code": "XXQL2502",
        "batch_file": "DSSBatch.v48",
        "tmt_meta_file": PROJECT_ROOT / "data/user/experiments/xxql2502_refreshed_20261010/treatment_metadata.csv",
        "role": "validation_and_diagnostic",
    },
}


def read_native_output(file_path: Path) -> pd.DataFrame:
    """Reads fixed-width DSSAT .OUT file indexed by (TRNO, DATE) where available."""
    from src.calibration import single_season_n as legacy
    return legacy.read_native(file_path)


def compute_metrics(obs: np.ndarray, sim: np.ndarray) -> dict[str, float]:
    """Compute RMSE, NRMSE, R2, NSE, Willmott d, MAE, MBE, bias_pct."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    obs = obs[mask]
    sim = sim[mask]
    n = len(obs)
    if n == 0:
        return {
            "n": 0, "rmse": np.nan, "nrmse": np.nan, "r2": np.nan,
            "nse": np.nan, "d": np.nan, "mae": np.nan, "mbe": np.nan, "bias_pct": np.nan,
            "obs_mean": np.nan, "sim_mean": np.nan,
        }

    diff = sim - obs
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    obs_mean = float(np.mean(obs))
    sim_mean = float(np.mean(sim))
    nrmse = float(100.0 * rmse / abs(obs_mean)) if abs(obs_mean) > 1e-9 else np.nan
    mae = float(np.mean(np.abs(diff)))
    mbe = float(np.mean(diff))
    bias_pct = float(100.0 * mbe / abs(obs_mean)) if abs(obs_mean) > 1e-9 else np.nan

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
        "n": n, "obs_mean": obs_mean, "sim_mean": sim_mean,
        "rmse": rmse, "nrmse": nrmse, "r2": r2, "nse": nse, "d": d,
        "mae": mae, "mbe": mbe, "bias_pct": bias_pct,
    }


class CrossSeasonSandbox:
    """Isolated execution sandbox for a single season under specific binary & parameters."""

    def __init__(
        self,
        sandbox_dir: Path,
        season_id: str,
        binary_path: Path,
    ):
        self.sandbox_dir = sandbox_dir.resolve()
        self.season_id = season_id
        self.binary_path = binary_path.resolve()
        self.season_info = SEASONS_INFO[season_id]
        self.source_dir = self.season_info["source_dir"].resolve()
        assert self.binary_path.exists(), f"Binary not found: {self.binary_path}"
        assert self.source_dir.exists(), f"Source dir not found: {self.source_dir}"

    def prepare(self) -> None:
        """Copies necessary input files into sandbox."""
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        exp = self.season_info["experiment_code"]
        copy_patterns = [
            "DSSAT48.INH", "DSSAT48.INP", "DSSATPRO.v48", "DSSBatch.v48",
            "SOIL.SOL", "SOIL.SOL.base",
            "TMGRO048.CUL", "TMGRO048.CUL.base",
            "TMGRO048.ECO", "TMGRO048.ECO.base",
            "TMGRO048.SPE", "TMGRO048.SPE.base",
            f"{exp}.TMA", f"{exp}.TMT", f"{exp}.TMX", "XXTW2403.WTH",
            "parameters.csv",
        ]
        for fn in copy_patterns:
            src_f = self.source_dir / fn
            if src_f.exists():
                shutil.copy(src_f, self.sandbox_dir / fn)

        # Ensure .base files exist
        for base_name in ["SOIL.SOL.base", "TMGRO048.CUL.base", "TMGRO048.ECO.base", "TMGRO048.SPE.base"]:
            dest = self.sandbox_dir / base_name
            if not dest.exists():
                stem = base_name[:-5]
                src = self.source_dir / stem
                if src.exists():
                    shutil.copy(src, dest)

        # Place binary in sandbox as DSCSM048.EXE
        shutil.copy(self.binary_path, self.sandbox_dir / "DSCSM048.EXE")

    def run_simulation(
        self,
        params: dict[str, float],
        timeout_sec: int = 180,
    ) -> dict[str, Any]:
        """Injects candidate parameters and runs DSCSM048.EXE."""
        from src.dssat import run_dssat as runner
        from src.dssat.forward_joint import inject_phosphorus
        from src.dssat.forward_water_n import inject_environment

        # Write parameters.csv
        param_df = pd.DataFrame([{"name": k, "value": v} for k, v in params.items()])
        param_csv_path = self.sandbox_dir / "parameters.csv"
        param_df.to_csv(param_csv_path, index=False)

        # Injection
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
            inject_environment(self.sandbox_dir, params)
        finally:
            os.chdir(orig_cwd)

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
                f"DSSAT simulation failed in sandbox {self.sandbox_dir} (code {res.returncode}): {res.stderr}"
            )

        # Export PestCNC if custom CNC binary
        if "cnc" in str(self.binary_path).lower():
            tmt_file = self.season_info["tmt_meta_file"]
            try:
                export_pest_cnc(
                    run_dir=self.sandbox_dir,
                    include_r_tol=True,
                    treatment_n_levels=tmt_file if tmt_file.exists() else None,
                )
            except Exception:
                pass

        return {
            "returncode": res.returncode,
            "elapsed_sec": elapsed,
            "stdout_tail": res.stdout[-200:] if res.stdout else "",
        }

    def extract_observations(
        self,
        comparison_catalog: pd.DataFrame,
    ) -> pd.DataFrame:
        """Extracts observations for this season from the model output."""
        from src.calibration import single_season_n as legacy
        season_cat = comparison_catalog[comparison_catalog["season_id"] == self.season_id].copy()
        if len(season_cat) == 0:
            return pd.DataFrame()

        # Split specials (ADAP, WB100_INTERVAL) vs standard outputs
        standard_cat = season_cat[~season_cat["variable"].isin(["ADAP", "WB100_INTERVAL"])].copy()
        records = []
        if len(standard_cat) > 0:
            extracted_df = legacy.extract_evaluation_observations(self.sandbox_dir, standard_cat.drop(columns=["simulated"], errors="ignore"))
            records = extracted_df.to_dict("records")

        # Handle WB100_INTERVAL if present
        wb_cat = season_cat[season_cat["variable"] == "WB100_INTERVAL"].copy()
        if len(wb_cat) > 0:
            soilwat_path = self.sandbox_dir / "SoilWat.OUT"
            if soilwat_path.exists():
                from src.calibration import water_n_joint as parent
                soil = legacy.read_native(soilwat_path)
                lines = soilwat_path.read_text().splitlines()
                layerline = next((x for x in lines if "0-5" in x or "0-10" in x), None)
                if layerline:
                    layers = [tuple(map(int, x)) for x in re.findall(r"(\d+)-(\d+)", layerline)]
                else:
                    layers = [(0, 5), (5, 15), (15, 30), (30, 45), (45, 60), (60, 80), (80, 100)]

                for row in wb_cat.to_dict("records"):
                    trno = int(row["trno"])
                    # Look up interval start and end
                    start = row.get("interval_start", "2025-04-10" if self.season_id == "25SP" else "2026-04-10")
                    end = row["date"]
                    try:
                        sim_wb = parent.water_balance100(soil, trno, start, end, layers)
                        records.append({**row, "simulated": sim_wb, "comparison_status": "matched"})
                    except Exception:
                        records.append({**row, "simulated": np.nan, "comparison_status": "unmatched"})

        # Handle ADAP if present
        adap_cat = season_cat[season_cat["variable"] == "ADAP"].copy()
        if len(adap_cat) > 0:
            eval_path = self.sandbox_dir / "Evaluate.OUT"
            run_adap_map: dict[int, float] = {}
            trno_adap_map: dict[int, float] = {}
            if eval_path.is_file():
                header = None
                for line in eval_path.read_text(encoding="latin-1", errors="ignore").splitlines():
                    line_str = line.strip()
                    if line_str.startswith("@RUN"):
                        header = [c.lstrip("@") for c in line_str.split()]
                    elif header and line_str and line_str.split()[0].isdigit():
                        parts = line_str.split()
                        if len(parts) >= len(header):
                            row_dict = dict(zip(header, parts))
                            try:
                                r_num = int(row_dict.get("RUN", parts[0]))
                                t_num = int(row_dict.get("TN", row_dict.get("TRNO", r_num)))
                                val_str = row_dict.get("ADAPS", row_dict.get("ADAP"))
                                if val_str is not None:
                                    val = float(val_str)
                                    if val > 0:
                                        run_adap_map[r_num] = val
                                        trno_adap_map[t_num] = val
                            except (ValueError, KeyError):
                                pass

            for row in adap_cat.to_dict("records"):
                trno = int(row["trno"]) if "trno" in row and pd.notna(row["trno"]) else None
                run = int(row["run"]) if "run" in row and pd.notna(row["run"]) else None
                sim_val = np.nan
                if run is not None and run in run_adap_map:
                    sim_val = run_adap_map[run]
                elif trno is not None and trno in trno_adap_map:
                    sim_val = trno_adap_map[trno]
                elif run is not None and run in trno_adap_map:
                    sim_val = trno_adap_map[run]
                elif trno is not None and trno in run_adap_map:
                    sim_val = run_adap_map[trno]

                if np.isfinite(sim_val):
                    records.append({**row, "simulated": sim_val, "comparison_status": "matched"})
                else:
                    records.append({**row, "simulated": np.nan, "comparison_status": "missing"})

        res_df = pd.DataFrame(records)
        res_df["residual"] = res_df["simulated"] - res_df["observed"]
        return res_df


def run_full_cross_season_evaluation(
    config_id: str,
    binary_path: Path,
    param_dict: dict[str, float],
    comparison_catalog_path: Path,
    output_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Runs cross-season evaluation across 26SP, 25SP, and 25FA.

    Returns:
    - (all_pairs_df, metrics_summary_df)
    """
    check_production_safety()
    comp_cat = pd.read_csv(comparison_catalog_path)
    all_pairs = []
    
    out_dir = output_root / config_id
    out_dir.mkdir(parents=True, exist_ok=True)

    for season_id in ["26SP", "25SP", "25FA"]:
        season_sb_dir = out_dir / season_id
        print(f"  --> Running {config_id} on {season_id} in {season_sb_dir.name}...")
        sb = CrossSeasonSandbox(season_sb_dir, season_id, binary_path)
        sb.prepare()
        sb.run_simulation(param_dict)
        pairs_season = sb.extract_observations(comp_cat)
        all_pairs.append(pairs_season)

    all_pairs_df = pd.concat(all_pairs, ignore_index=True)
    all_pairs_df.to_csv(out_dir / "cross_season_comparison_pairs.csv", index=False)

    # Compute metrics summary
    metrics_rows = []
    for (season_id, role, var), grp in all_pairs_df.groupby(["season_id", "dataset_role", "variable"], sort=False):
        obs = grp["observed"].to_numpy(dtype=float)
        sim = grp["simulated"].to_numpy(dtype=float)
        m = compute_metrics(obs, sim)
        unit = grp["unit"].iloc[0] if "unit" in grp else ""
        metrics_rows.append({
            "config_id": config_id,
            "season_id": season_id,
            "dataset_role": role,
            "variable": var,
            "unit": unit,
            **m,
        })

    metrics_df = pd.DataFrame(metrics_rows)
    metrics_df.to_csv(out_dir / "cross_season_metrics_summary.csv", index=False)
    return all_pairs_df, metrics_df


if __name__ == "__main__":
    print("Testing cross-season evaluator module import & basic initialization...")
    check_production_safety()
    print("Cross-season evaluator ready.")
