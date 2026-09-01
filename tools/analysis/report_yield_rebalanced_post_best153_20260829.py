"""Build deterministic and ensemble diagnostics for formal best member 153."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.analysis.analyze_formal_armab_rrmse_26spn_results_20260828 as analysis
from src.calibration.nitrogen_response import derive_filex_water_n_mapping


RUN = ROOT / "workspace/runs/e02_formal_yield_rebalanced_post_official_200x6_20260829"
CASE = "e02_formal_yield_rebalanced_post_200x6_20260829"
DET = RUN / "best_member_153_two_season_deterministic_20260829"
BASELINE_DET = ROOT / (
    "workspace/runs/e02_formal_armab_rrmse_26spncal_official_200x6_20260828/"
    "best_member_103_two_season_deterministic_20260828"
)
OUT = RUN / "result_summary_20260829"


def deterministic_summary(det_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mapping_path = det_root / "two_season_water_n_mapping_from_filex.csv"
    if not mapping_path.is_file():
        mappings = []
        for season, treatments in (("25SP", [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]),
                                   ("26SP", list(range(1, 13)))):
            mappings.append(derive_filex_water_n_mapping(
                det_root / "_seasons" / season / f"XXQL{'25' if season == '25SP' else '26'}01.TMX",
                season_id=season,
                treatments=treatments,
            ))
        pd.concat(mappings, ignore_index=True).to_csv(mapping_path, index=False)
    original = analysis.DET
    analysis.DET = det_root
    try:
        role, terminal = analysis.role_metrics()
        response = analysis.response_metrics()
    finally:
        analysis.DET = original
    return role, terminal, response


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    analysis.RUN, analysis.CASE, analysis.DET = RUN, CASE, DET
    role, terminal, response = deterministic_summary(DET)
    baseline_role, baseline_terminal, baseline_response = deterministic_summary(BASELINE_DET)
    convergence, iteration, member, phi = analysis.convergence()
    boundary, boundary_summary = analysis.boundary_pressure(iteration, member)
    contributions = analysis.objective_contributions(iteration, member)

    role.to_csv(OUT / "metrics_by_season_role_variable.csv", index=False)
    terminal.to_csv(OUT / "terminal_yield_metrics_by_season_role.csv", index=False)
    response.to_csv(OUT / "water_nitrogen_response_metrics.csv", index=False)
    convergence.to_csv(OUT / "phi_convergence_summary.csv", index=False)
    boundary.to_csv(OUT / "best_member_and_ensemble_boundary_pressure.csv", index=False)
    boundary_summary.to_csv(OUT / "boundary_pressure_summary.csv", index=False)
    contributions.to_csv(OUT / "best_member_phi_by_observation_group.csv", index=False)

    comparison = role.merge(
        baseline_role,
        on=["season", "role", "kind", "variable"],
        suffixes=("_current", "_baseline103"),
    )
    for metric in ("rrmse_pct", "bias", "nse", "d_index", "r2"):
        comparison[f"delta_{metric}"] = (
            comparison[f"{metric}_current"] - comparison[f"{metric}_baseline103"]
        )
    comparison.to_csv(OUT / "comparison_to_previous_member103.csv", index=False)

    terminal_comparison = terminal.merge(
        baseline_terminal,
        on=["season", "role", "variable"],
        suffixes=("_current", "_baseline103"),
    )
    for metric in ("rrmse_pct", "bias", "nse", "d_index", "r2"):
        terminal_comparison[f"delta_{metric}"] = (
            terminal_comparison[f"{metric}_current"]
            - terminal_comparison[f"{metric}_baseline103"]
        )
    terminal_comparison.to_csv(OUT / "terminal_comparison_to_previous_member103.csv", index=False)

    response_comparison = response.merge(
        baseline_response,
        on=["season", "contrast", "stratum"],
        suffixes=("_current", "_baseline103"),
    )
    for metric in ("rrmse_pct", "bias", "nse", "d_index", "r2"):
        response_comparison[f"delta_{metric}"] = (
            response_comparison[f"{metric}_current"]
            - response_comparison[f"{metric}_baseline103"]
        )
    response_comparison.to_csv(OUT / "response_comparison_to_previous_member103.csv", index=False)

    gate = json.loads((RUN / "candidate_audit_20260829/candidate_selection.json").read_text(encoding="utf-8"))
    payload = {
        **gate,
        "engineering_quality": json.loads(
            (RUN / "ies_quality/ies_run_quality.json").read_text(encoding="utf-8")
        )["status"],
        "deterministic_replay_status": "success_22_of_22",
        "active_parameters": int(boundary_summary.iloc[0]["active_parameters"]),
        "best_member_near_boundary_count_2pct": int(
            boundary_summary.iloc[0]["best_member_near_boundary_count_2pct"]
        ),
        "final_ensemble_boundary_pressure_count_ge_20pct": int(
            boundary_summary.iloc[0]["parameters_with_final_ensemble_boundary_fraction_ge_0_20"]
        ),
        "top10_groups_phi_fraction": float(contributions.head(10)["phi_fraction"].sum()),
    }
    (OUT / "result_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\nAll-treatment metrics:\n", role.loc[role.role.eq("all22")].to_string(index=False))
    print("\nTerminal calibration metrics:\n", terminal.loc[terminal.role.eq("calibration")].to_string(index=False))
    print("\nResponse metrics:\n", response.to_string(index=False))
    print("\nNear-boundary parameters:\n", boundary.loc[
        boundary["best_member_near_boundary_2pct"], ["parameter", "value", "lower", "upper"]
    ].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
