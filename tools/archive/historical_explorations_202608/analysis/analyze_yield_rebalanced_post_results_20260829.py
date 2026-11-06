"""Audit all IES iterations and rank candidates for the yield-rebalanced run.

The hard acceptance rule is evaluated on calibration-treatment terminal dry
yield before Phi is used for ranking.  This intentionally avoids treating the
PEST++ ``acceptance_threshold_pct`` metadata as an optimizer constraint.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "workspace/runs/e02_formal_yield_rebalanced_post_official_200x6_20260829"
CASE = "e02_formal_yield_rebalanced_post_200x6_20260829"
OUT = RUN / "candidate_audit_20260829"


def _metrics(observed: np.ndarray, simulated: np.ndarray) -> dict[str, float]:
    ok = np.isfinite(observed) & np.isfinite(simulated) & (observed > -90) & (simulated > -90)
    observed, simulated = observed[ok], simulated[ok]
    if not len(observed):
        return {"n": 0, "rmse": np.nan, "rrmse_pct": np.nan, "bias": np.nan,
                "pbias_pct": np.nan, "nse": np.nan}
    error = simulated - observed
    rmse = float(np.sqrt(np.mean(error ** 2)))
    mean_abs = float(np.mean(np.abs(observed)))
    sst = float(np.sum((observed - observed.mean()) ** 2))
    return {
        "n": int(len(observed)),
        "rmse": rmse,
        "rrmse_pct": 100.0 * rmse / mean_abs if mean_abs else np.nan,
        "bias": float(np.mean(error)),
        "pbias_pct": 100.0 * float(np.sum(error)) / float(np.sum(observed))
        if float(np.sum(observed)) else np.nan,
        "nse": 1.0 - float(np.sum(error ** 2)) / sst if sst > 0 else np.nan,
    }


def _subset_metrics(registry: pd.DataFrame, simulations: pd.Series, mask: pd.Series) -> dict[str, float]:
    sub = registry.loc[mask]
    observed = pd.to_numeric(sub["raw_obsval"], errors="coerce").to_numpy(float)
    simulated = np.array([simulations.get(name.lower(), np.nan) for name in sub["obsnme"]], dtype=float)
    return _metrics(observed, simulated)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    registry = pd.read_csv(RUN / f"{CASE}_observation_registry.csv")
    phi = pd.read_csv(RUN / f"{CASE}.phi.actual.csv").set_index("iteration")
    member_columns = [column for column in phi.columns if str(column).isdigit()]
    rows: list[dict[str, float | int | str | bool]] = []

    for iteration in range(7):
        obs_path = RUN / f"{CASE}.{iteration}.obs.csv"
        if not obs_path.is_file():
            continue
        ensemble = pd.read_csv(obs_path)
        ensemble["real_name"] = ensemble["real_name"].astype(str).str.replace(r"\.0$", "", regex=True)
        ensemble = ensemble.set_index("real_name")
        for member in member_columns:
            if member not in ensemble.index:
                continue
            simulations = ensemble.loc[member]
            record: dict[str, float | int | str | bool] = {
                "iteration": iteration,
                "member": member,
                "phi": float(phi.loc[iteration, member]),
            }
            for season in ("25SP", "26SP"):
                season_mask = registry["season_id"].eq(season)
                terminal_mask = season_mask & registry["rrmse_lambda"].notna()
                lai_mask = season_mask & registry["obgnme"].str.contains("LAIDM", regex=False) & registry["weight"].gt(0)
                increment_mask = season_mask & registry["obgnme"].str.contains("HPODWM", regex=False) & registry["weight"].gt(0)
                n_response_mask = season_mask & registry["obgnme"].str.contains("NRESPM", regex=False) & registry["weight"].gt(0)
                w_response_mask = season_mask & registry["obgnme"].str.contains("WRESPM", regex=False) & registry["weight"].gt(0)
                for label, mask in (
                    ("terminal", terminal_mask),
                    ("lai", lai_mask),
                    ("dry_increment", increment_mask),
                    ("n_response", n_response_mask),
                    ("w_response", w_response_mask),
                ):
                    for metric, value in _subset_metrics(registry, simulations, mask).items():
                        record[f"{season.lower()}_{label}_{metric}"] = value
            record["terminal_gate_pass"] = bool(
                record["25sp_terminal_rrmse_pct"] <= 25.0
                and record["26sp_terminal_rrmse_pct"] <= 25.0
            )
            record["terminal_bias_gate_pass"] = bool(
                abs(record["25sp_terminal_pbias_pct"]) <= 15.0
                and abs(record["26sp_terminal_pbias_pct"]) <= 15.0
            )
            record["terminal_max_rrmse_pct"] = max(
                record["25sp_terminal_rrmse_pct"], record["26sp_terminal_rrmse_pct"]
            )
            rows.append(record)

    audit = pd.DataFrame(rows)
    audit["selection_rank"] = audit.sort_values(
        ["terminal_gate_pass", "terminal_bias_gate_pass", "terminal_max_rrmse_pct", "phi"],
        ascending=[False, False, True, True],
    ).index.to_series().rank(method="first").astype(int)
    ranked = audit.sort_values(
        ["terminal_gate_pass", "terminal_bias_gate_pass", "terminal_max_rrmse_pct", "phi"],
        ascending=[False, False, True, True],
    ).reset_index(drop=True)
    ranked["selection_rank"] = np.arange(1, len(ranked) + 1)
    ranked.to_csv(OUT / "all_iteration_candidate_metrics.csv", index=False)
    ranked.head(30).to_csv(OUT / "top30_candidate_metrics.csv", index=False)

    convergence = []
    for iteration, group in audit.groupby("iteration"):
        convergence.append({
            "iteration": int(iteration),
            "n_members": int(len(group)),
            "phi_min": float(group["phi"].min()),
            "phi_median": float(group["phi"].median()),
            "terminal_gate_pass_count": int(group["terminal_gate_pass"].sum()),
            "terminal_bias_gate_pass_count": int(group["terminal_bias_gate_pass"].sum()),
            "terminal_both_gates_pass_count": int((group["terminal_gate_pass"] & group["terminal_bias_gate_pass"]).sum()),
            "best_terminal_max_rrmse_pct": float(group["terminal_max_rrmse_pct"].min()),
        })
    pd.DataFrame(convergence).to_csv(OUT / "iteration_gate_summary.csv", index=False)

    gate_eligible = audit.loc[audit["terminal_gate_pass"] & audit["terminal_bias_gate_pass"]]
    if not gate_eligible.empty:
        best = gate_eligible.sort_values("phi").iloc[0]
        fallback_rule = "lowest Phi among candidates passing both terminal RRMSE and PBIAS gates"
    else:
        best = audit.sort_values("phi").iloc[0]
        fallback_rule = "no candidate passed both gates; lowest Phi retained as diagnostic best"
    payload = {
        "selected_iteration": int(best["iteration"]),
        "selected_member": str(best["member"]),
        "selected_phi": float(best["phi"]),
        "terminal_gate_pass": bool(best["terminal_gate_pass"]),
        "terminal_bias_gate_pass": bool(best["terminal_bias_gate_pass"]),
        "25sp_terminal_rrmse_pct": float(best["25sp_terminal_rrmse_pct"]),
        "26sp_terminal_rrmse_pct": float(best["26sp_terminal_rrmse_pct"]),
        "25sp_terminal_pbias_pct": float(best["25sp_terminal_pbias_pct"]),
        "26sp_terminal_pbias_pct": float(best["26sp_terminal_pbias_pct"]),
        "gate_pass_candidates": int(audit["terminal_gate_pass"].sum()),
        "both_gates_pass_candidates": int((audit["terminal_gate_pass"] & audit["terminal_bias_gate_pass"]).sum()),
        "global_lowest_phi": float(audit["phi"].min()),
        "global_lowest_phi_iteration": int(audit.loc[audit["phi"].idxmin(), "iteration"]),
        "global_lowest_phi_member": str(audit.loc[audit["phi"].idxmin(), "member"]),
        "selection_rule": fallback_rule,
    }
    (OUT / "candidate_selection.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\nTop candidates:\n", ranked.head(12).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
