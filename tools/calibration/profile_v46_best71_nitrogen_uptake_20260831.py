"""Deterministic screen of the remaining nitrogen-uptake pathway.

The prior screen found RTNO3 and FNPGN to be weak but non-zero channels and
found NSTFAC/NREXP/NRMIN invariant in the official executable.  This screen
tests the complementary nitrate/ammonium and root-extension terms while
holding every other best71 parameter and the two bundles fixed.
"""
from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.profile_n_parameters_determinstic as runner
import tools.calibration.profile_v46_best71_nitrogen_20260831 as metrics

ANCHOR = ROOT / "workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/best_member_71_deterministic_20260831"
OUT = ROOT / "workspace/reports/e02_v46_best71_nitrogen_uptake_profile_20260831"
SCRATCH = OUT / "scratch_runs"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    runner.BASE_PARAMS_PATH = ANCHOR / "best_member_71_params.csv"
    runner.OUT_DIR = OUT
    runner.SCRATCH_DIR = SCRATCH
    runner.BASE_DESIGN_PATH = OUT / "design_uptake_profile.json"
    metrics.SCRATCH = SCRATCH

    design = json.loads((ROOT / "configs/runs/e02_formal_v46_step20_custom26sp_20260831_200x4.json").read_text(encoding="utf-8"))
    for season in design["seasons"]:
        season["treatments"] = {
            "25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
            "26SP": list(range(1, 13)),
        }[season["season_id"]]
    design["design_id"] = "e02_v46_best71_nitrogen_uptake_profile_20260831"
    design["purpose"] = "Deterministic profile of RTNH4/RTEXF/PORMIN and nitrate-ammonium uptake interaction"
    design["diagnostic_only"] = {"25SP": [], "26SP": []}
    runner.BASE_DESIGN_PATH.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    experiments: list[tuple[str, str, str, dict[str, float]]] = [("baseline", "BASELINE", "best71", {})]
    for v in [0.008, 0.020, 0.033734, 0.050]:
        experiments.append((f"rtnh4_{v:.6f}", "RTNH4", f"{v:.6f}", {"RTNH4": v}))
    for v in [0.080, 0.150, 0.21421, 0.300]:
        experiments.append((f"rtexf_{v:.5f}", "RTEXF", f"{v:.5f}", {"RTEXF": v}))
    for v in [0.010, 0.020, 0.050, 0.100]:
        experiments.append((f"pormin_{v:.3f}", "PORMIN", f"{v:.3f}", {"PORMIN": v}))
    for no3, nh4 in product([0.025, 0.033036, 0.045], [0.015, 0.033734, 0.050]):
        experiments.append((
            f"rtno3_{no3:.6f}_rtnh4_{nh4:.6f}", "RTNO3_RTNH4",
            f"{no3:.6f}|{nh4:.6f}", {"RTNO3": no3, "RTNH4": nh4},
        ))

    rows: list[dict[str, object]] = []
    for idx, (case, family, setting, changes) in enumerate(experiments, 1):
        result_file = SCRATCH / case / "profile_result.json"
        if result_file.is_file():
            row = json.loads(result_file.read_text(encoding="utf-8"))
        else:
            result = runner._run_deterministic(changes, case)
            if not result:
                row = {"case": case, "family": family, "setting": setting, "status": "failed"}
            else:
                result.update(metrics._terminal_n12(case))
                row = {"case": case, "family": family, "setting": setting, **result}
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        row.update({"case": case, "family": family, "setting": setting})
        rows.append(row)
        pd.DataFrame(rows).to_csv(OUT / "uptake_profile_results.csv", index=False)
        print(f"[{idx:02d}/{len(experiments):02d}] {case}", flush=True)

    df = pd.DataFrame(rows)
    if df.empty or "n12_mean_abs_error" not in df:
        return 1
    baseline = df.loc[df.case.eq("baseline")].iloc[0]
    df["n_response_error_delta_vs_baseline"] = df["n12_mean_abs_error"] - float(baseline["n12_mean_abs_error"])
    df["protected_fit_pass"] = (
        df["25SP_LAI_NSE"].ge(float(baseline["25SP_LAI_NSE"]) - 0.05)
        & df["26SP_LAI_NSE"].ge(float(baseline["26SP_LAI_NSE"]) - 0.05)
        & df["25SP_FRESH_NSE"].ge(float(baseline["25SP_FRESH_NSE"]) - 0.05)
        & df["26SP_FRESH_NSE"].ge(float(baseline["26SP_FRESH_NSE"]) - 0.05)
    )
    df["screen_pass"] = df["n12_direction_pass"] & df["protected_fit_pass"]
    df.sort_values(["screen_pass", "n_response_error_delta_vs_baseline"], ascending=[False, True]).to_csv(
        OUT / "uptake_profile_scorecard.csv", index=False
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
