"""Fair deterministic comparison of v6 and corrected-data v7 best members."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.reporting import diagnostic_three_season_best_member as base
from tools.reporting import diagnostic_v6_three_season_best_member as diag


SEASONS = [
    {
        "season_id": "25SP", "experiment_code": "XXQL2501",
        "bundle_path": "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
        "bundle_manifest_sha256": "f0c59a5e48127b62d77da13f1e5db154ac3b13f03b496b3586ee7514192e39fe",
        "role": "calibration", "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
    },
    {
        "season_id": "25FA", "experiment_code": "XXQL2502",
        "bundle_path": "data/user/experiments/xxql2502_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        "bundle_manifest_sha256": "0d37048d027ad08f3c5cdb87e6302974b63643864c6afd909517a741885b5897",
        "role": "calibration", "treatments": list(range(1, 13)),
    },
    {
        "season_id": "26SP", "experiment_code": "XXQL2601",
        "bundle_path": "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        "bundle_manifest_sha256": "365e0afc8e33be2ef6413a5420ec905211f7deb276f852f97723f4ce3dd1d24a",
        "role": "calibration", "treatments": [1, 3, 4, 6, 7, 9, 10, 12],
    },
]


CASES = {
    "v6_best82": (
        ROOT / "workspace/runs/e02_joint62_m1_offsets_plantn_slpf_150x5_20260729_v6"
        / "e02_joint62_m1_offsets_plantn_slpf_150x5_20260729_v6.5.par.csv",
        "82",
    ),
    "v7_best78": (
        ROOT / "workspace/runs/e02_joint62_moisturefix_touchrelax_harvest250_150x5_20260729"
        / "e02_joint62_moisturefix_touchrelax_harvest250_150x5_20260729.5.par.csv",
        "78",
    ),
}


def main() -> int:
    out = ROOT / "workspace/diagnostics/e02_v6_v7_corrected_data_best_comparison_20260729"
    out.mkdir(parents=True, exist_ok=True)
    design = json.loads(
        (ROOT / "configs/runs/eggplant_e02_joint62_25sp_25fa_autumn_offsets_moisturefix_touchrelax_v6_20260729.json")
        .read_text(encoding="utf-8")
    )
    design["design_id"] = "diagnostic_v6_v7_corrected_data_comparison"
    design["seasons"] = SEASONS
    design_path = out / "diagnostic_design.json"
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diag.SEASONS = SEASONS

    all_metrics = []
    for case, (ensemble, member) in CASES.items():
        case_dir = out / case
        case_dir.mkdir(exist_ok=True)
        params = case_dir / f"{case}_parameters.csv"
        base._export_member(ensemble, member, params)
        subprocess.run([
            sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
            "--design", str(design_path), "--param-csv", str(params),
            "--prefix", case, "--harvest-var", "CHPDT", "--keep-nitrogen-outputs",
        ], cwd=case_dir, check=True)
        comparison, trajectory = base._collect(case_dir, case, SEASONS)
        comparison = diag.add_plant_n(comparison, case_dir)
        comparison.to_csv(case_dir / "comparison_original_scale.csv", index=False)
        trajectory.to_csv(case_dir / "simulation_trajectory.csv", index=False)
        metric = diag.metrics(comparison, case_dir)
        metric.insert(0, "case", case)
        all_metrics.append(metric)

    combined = pd.concat(all_metrics, ignore_index=True)
    combined.to_csv(out / "metrics_by_case_season_variable.csv", index=False)
    wide = combined.pivot(index=["season", "variable"], columns="case",
                          values=["rrmse_pct", "nse", "r2", "bias"]).reset_index()
    wide.columns = ["_".join(str(x) for x in col if x) for col in wide.columns]
    for metric in ("rrmse_pct", "nse", "r2"):
        wide[f"delta_{metric}_v7_minus_v6"] = (
            wide[f"{metric}_v7_best78"] - wide[f"{metric}_v6_best82"]
        )
    wide.to_csv(out / "v7_minus_v6_metric_deltas.csv", index=False)
    print(wide.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
