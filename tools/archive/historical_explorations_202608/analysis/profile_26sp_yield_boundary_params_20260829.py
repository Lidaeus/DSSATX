"""Deterministic one-at-a-time profiles for the 26SP late-yield deficit.

The experiment keeps member 153 fixed and perturbs only parameters selected by
either posterior boundary pressure or prior full-bounds yield sensitivity.  It
is diagnostic only: exploratory values do not change frozen calibration bounds.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUN = ROOT / "workspace/runs/e02_formal_yield_rebalanced_post_official_200x6_20260829"
ANCHOR = RUN / "best_member_153_two_season_deterministic_20260829"
OUT = RUN / "diagnosis_26sp_late_yield_20260829/boundary_parameter_profiles"
BASE_PARAMS = ANCHOR / "best_member_153_params.csv"
BASE_DESIGN = ANCHOR / "design.json"

PROFILES = {
    "PHTMAX": [50.0, 60.0, 75.0],
    "WTFSD": [0.40, 0.50],
    "SFDUR": [40.0, 45.0, 55.0],  # 55 is exploratory, not a frozen-bound change.
    "PARMAX": [38.0, 42.0, 45.0],
    "XFRMAX": [0.12, 0.16, 0.20],
    "PGEFF": [0.052, 0.056, 0.060],
    "TRIFL": [0.70, 0.74, 0.82, 0.86],
    "PORPT": [0.32, 0.35],
    "NRMIN": [0.50, 0.65, 0.90, 1.00],
    "NREXP": [0.30, 0.45, 0.80, 1.00],
    "RTNO3": [0.03, 0.04, 0.06, 0.08],
    "RTNH4": [0.008, 0.020, 0.040],
    "NMOBMX": [0.25, 0.32, 0.40],
}
TREATMENTS = {"25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14], "26SP": list(range(1, 13))}
CALIBRATION_TREATMENTS = {"25SP": [2, 5, 10, 13], "26SP": [1, 3, 9, 12]}


def _metric(observed: pd.Series, simulated: pd.Series) -> dict[str, float]:
    valid = observed.notna() & simulated.notna() & observed.gt(-90) & simulated.gt(-90)
    obs = observed.loc[valid].to_numpy(float)
    sim = simulated.loc[valid].to_numpy(float)
    if not len(obs):
        return {"n": 0, "nse": np.nan, "rrmse_pct": np.nan, "pbias_pct": np.nan}
    residual = sim - obs
    sst = np.square(obs - obs.mean()).sum()
    return {
        "n": int(len(obs)),
        "nse": float(1.0 - np.square(residual).sum() / sst) if sst > 0 else np.nan,
        "rrmse_pct": float(100.0 * np.sqrt(np.square(residual).mean()) / obs.mean()),
        "pbias_pct": float(100.0 * residual.sum() / obs.sum()),
    }


def _analyze(case_dir: Path, case_id: str, parameter: str, value: float) -> dict[str, float | str]:
    from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare

    result: dict[str, float | str] = {
        "case_id": case_id, "parameter": parameter, "value": value,
    }
    for season in ("25SP", "26SP"):
        season_dir = case_dir / "_seasons" / season
        batch = season_dir / "analysis_batch.v48"
        filex = next(season_dir.glob("*.TMX"))
        batch.write_text(
            "\n".join(f"{filex.resolve()} {tn} 1 0 0 0" for tn in TREATMENTS[season]) + "\n",
            encoding="utf-8",
        )
        deterministic_harvest_compare(season, str(batch), run_dir=str(season_dir))
        deterministic_process_compare(
            season, str(batch), var_names=["LAID", "LWAD", "SWAD"], run_dir=str(season_dir)
        )
        harvest = pd.read_csv(season_dir / f"{season}_deterministic_harvest_compare.csv")
        process = pd.read_csv(season_dir / f"{season}_deterministic_process_compare.csv")
        terminal = harvest.sort_values(["TN", "HNO"]).groupby("TN", as_index=False).tail(1)
        terminal_metric = _metric(terminal["OBS_DRY_CUM"], terminal["SIM_DRY_CUM"])
        terminal_cal = terminal.loc[terminal["TN"].isin(CALIBRATION_TREATMENTS[season])]
        terminal_val = terminal.loc[~terminal["TN"].isin(CALIBRATION_TREATMENTS[season])]
        terminal_cal_metric = _metric(terminal_cal["OBS_DRY_CUM"], terminal_cal["SIM_DRY_CUM"])
        terminal_val_metric = _metric(terminal_val["OBS_DRY_CUM"], terminal_val["SIM_DRY_CUM"])
        cumulative_metric = _metric(harvest["OBS_DRY_CUM"], harvest["SIM_DRY_CUM"])
        result[f"{season}_terminal_rrmse_pct"] = terminal_metric["rrmse_pct"]
        result[f"{season}_terminal_pbias_pct"] = terminal_metric["pbias_pct"]
        result[f"{season}_calibration_terminal_rrmse_pct"] = terminal_cal_metric["rrmse_pct"]
        result[f"{season}_calibration_terminal_pbias_pct"] = terminal_cal_metric["pbias_pct"]
        result[f"{season}_validation_terminal_rrmse_pct"] = terminal_val_metric["rrmse_pct"]
        result[f"{season}_validation_terminal_pbias_pct"] = terminal_val_metric["pbias_pct"]
        result[f"{season}_dry_cum_nse"] = cumulative_metric["nse"]
        for variable in ("LAID", "LWAD", "SWAD"):
            m = _metric(process[f"OBS_{variable}"], process[f"SIM_{variable}"])
            result[f"{season}_{variable.lower()}_nse"] = m["nse"]
        if season == "26SP":
            for harvest_number in (3, 5):
                selected = harvest.loc[harvest["HNO"].eq(harvest_number)]
                result[f"26SP_h{harvest_number}_obs_mean"] = float(selected["OBS_DRY_CUM"].mean())
                result[f"26SP_h{harvest_number}_sim_mean"] = float(selected["SIM_DRY_CUM"].mean())
                result[f"26SP_h{harvest_number}_bias_mean"] = float(
                    (selected["SIM_DRY_CUM"] - selected["OBS_DRY_CUM"]).mean()
                )
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    base = pd.read_csv(BASE_PARAMS)
    base["name"] = base["name"].astype(str).str.upper()
    base_values = dict(zip(base["name"], base["value"].astype(float)))
    design = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))
    design["purpose"] = "deterministic one-at-a-time boundary parameter profiles"
    design["design_id"] = "e02_26sp_late_yield_boundary_profiles_20260829"
    design_path = OUT / "design.json"
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    experiments: list[tuple[str, str, float]] = [("baseline", "BASELINE", np.nan)]
    for parameter, values in PROFILES.items():
        experiments.extend(
            (f"{parameter.lower()}_{str(value).replace('.', 'p')}", parameter, value)
            for value in values
        )
    pd.DataFrame(experiments, columns=["case_id", "parameter", "value"]).to_csv(
        OUT / "profile_plan.csv", index=False
    )

    rows = []
    for case_id, parameter, value in experiments:
        case_dir = OUT / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        values = dict(base_values)
        if parameter != "BASELINE":
            values[parameter] = value
        param_csv = case_dir / "params.csv"
        pd.DataFrame([{"name": name, "value": val} for name, val in values.items()]).to_csv(
            param_csv, index=False
        )
        status_path = case_dir / "multiseason_run_status.json"
        if not status_path.exists():
            command = [
                sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                "--design", str(design_path), "--param-csv", str(param_csv),
                "--prefix", case_id, "--harvest-var", "CHPDT",
            ]
            completed = subprocess.run(command, cwd=case_dir, capture_output=True, text=True)
            (case_dir / "run.stdout.log").write_text(completed.stdout, encoding="utf-8")
            (case_dir / "run.stderr.log").write_text(completed.stderr, encoding="utf-8")
            if completed.returncode != 0:
                rows.append({"case_id": case_id, "parameter": parameter, "value": value,
                             "status": "failed", "returncode": completed.returncode})
                continue
        try:
            row = _analyze(case_dir, case_id, parameter, value)
            row["status"] = "success"
            rows.append(row)
        except Exception as exc:  # retain all failures for audit instead of hiding them
            rows.append({"case_id": case_id, "parameter": parameter, "value": value,
                         "status": "analysis_failed", "error": repr(exc)})
        pd.DataFrame(rows).to_csv(OUT / "profile_results.csv", index=False)
        print(f"[{len(rows):02d}/{len(experiments):02d}] {case_id}: {rows[-1]['status']}", flush=True)

    results = pd.DataFrame(rows)
    successful = results.loc[results["status"].eq("success")].copy()
    if successful.empty:
        return 1
    baseline = successful.loc[successful["parameter"].eq("BASELINE")].iloc[0]
    metric_columns = [column for column in successful.columns if column not in {
        "case_id", "parameter", "value", "status", "returncode", "error"
    }]
    for column in metric_columns:
        successful[f"delta_{column}"] = successful[column] - baseline[column]
    successful.to_csv(OUT / "profile_results_with_baseline_deltas.csv", index=False)
    return 0 if len(successful) == len(experiments) else 1


if __name__ == "__main__":
    raise SystemExit(main())
