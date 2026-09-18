"""Profile the previously untested nitrogen-stress trigger/curvature channel.

All non-N parameters are frozen to v46 best71 member 71.  This deliberately
fills the gap in the earlier profile: NSTFAC is tested around its actual
anchor (0.2125), and NREXP/NRMIN are screened both individually and in a small
interaction grid.  Results are screening evidence only.
"""
from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.profile_n_parameters_determinstic as runner
import tools.calibration.profile_v46_best71_nitrogen_20260831 as metrics

ANCHOR = ROOT / "workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/best_member_71_deterministic_20260831"
OUT = ROOT / "workspace/reports/e02_v46_best71_nitrogen_shape_profile_20260831"
SCRATCH = OUT / "scratch_runs"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    runner.BASE_PARAMS_PATH = ANCHOR / "best_member_71_params.csv"
    runner.OUT_DIR = OUT
    runner.SCRATCH_DIR = SCRATCH
    runner.BASE_DESIGN_PATH = OUT / "design_shape_profile.json"
    metrics.SCRATCH = SCRATCH

    design = json.loads((ROOT / "configs/runs/e02_formal_v46_step20_custom26sp_20260831_200x4.json").read_text(encoding="utf-8"))
    # The source formal design names only the four calibration treatments.  A
    # nitrogen response profile must replay all spring treatments so that each
    # N1/N2/N3 treatment has its same-water N0 counterpart.
    for season in design["seasons"]:
        season["treatments"] = {"25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
                                "26SP": list(range(1, 13))}[season["season_id"]]
    design["design_id"] = "e02_v46_best71_nitrogen_shape_profile_20260831"
    design["purpose"] = "Deterministic profile of NSTFAC/NREXP/NRMIN around best71 anchor"
    design["diagnostic_only"] = {"25SP": [], "26SP": []}
    runner.BASE_DESIGN_PATH.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    params = pd.read_csv(runner.BASE_PARAMS_PATH)
    values = dict(zip(params["name"].astype(str).str.upper(), pd.to_numeric(params["value"])))
    experiments: list[tuple[str, str, str, dict[str, float]]] = [("baseline", "BASELINE", "best71", {})]

    # The old screen started at 0.55 although the actual anchor is 0.212509.
    # The CROPGRO implementation clamps NSTFAC to [0.1, 1.0].  The
    # original screen stopped at 0.60; include the untested upper corridor
    # to check whether a higher supply/need trigger activates N stress.
    for v in [0.15, 0.20, 0.212509, 0.25, 0.35, 0.50, 0.60, 0.70, 0.85, 1.00]:
        experiments.append((f"nstfac_{v:.6f}", "NSTFAC", f"{v:.6f}", {"NSTFAC": v}))
    for v in [0.20, 0.35, 0.55, 0.73, 0.90]:
        experiments.append((f"nrexp_{v:.3f}", "NREXP", f"{v:.3f}", {"NREXP": v}))
    for v in [0.30, 0.45, 0.59, 0.72, 0.85]:
        experiments.append((f"nrmin_{v:.3f}", "NRMIN", f"{v:.3f}", {"NRMIN": v}))
    for nstfac, nrexp in product([0.15, 0.212509, 0.35], [0.35, 0.73, 0.90]):
        experiments.append((
            f"nstfac_{nstfac:.6f}_nrexp_{nrexp:.3f}", "NSTFAC_NREXP",
            f"{nstfac:.6f}|{nrexp:.3f}", {"NSTFAC": nstfac, "NREXP": nrexp},
        ))
    for nrexp, nrmin in product([0.35, 0.73, 0.90], [0.30, 0.59, 0.85]):
        experiments.append((
            f"nrexp_{nrexp:.3f}_nrmin_{nrmin:.3f}", "NREXP_NRMIN",
            f"{nrexp:.3f}|{nrmin:.3f}", {"NREXP": nrexp, "NRMIN": nrmin},
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
        pd.DataFrame(rows).to_csv(OUT / "shape_profile_results.csv", index=False)
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
        OUT / "shape_profile_scorecard.csv", index=False
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
