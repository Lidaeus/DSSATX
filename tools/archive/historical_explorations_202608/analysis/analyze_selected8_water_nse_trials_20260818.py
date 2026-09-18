"""Evaluate selected-eight water NSE trial arms and apply advancement gates."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "workspace" / "runs"
CASES = {
    "A": "e02_selected8_water_A_baseline_static_80x4_20260818",
    "B": "e02_selected8_water_B_wresp_nse_lam0p5_80x4_20260818_retry1",
    "C": "e02_selected8_water_C_wresp_nse_lam1p0_80x4_20260818_retry1",
}
OUT = ROOT / "workspace" / "reports" / "selected8_water_nse_trials_20260818"


def nse(obs: np.ndarray, sim: np.ndarray) -> float:
    sst = float(np.square(obs - obs.mean()).sum())
    return float(1.0 - np.square(sim - obs).sum() / sst) if sst > 0 else float("nan")


def _metrics(arm: str, case: str) -> pd.DataFrame:
    run = RUNS / case
    obs_path = run / f"{case}.4.obs.csv"
    if not obs_path.exists():
        raise FileNotFoundError(f"trial arm {arm} is not complete: {obs_path}")
    sims = pd.read_csv(obs_path)
    real_col = sims.columns[0]
    registry = pd.read_csv(run / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    registry["key"] = registry["obsnme"].astype(str).str.lower()
    mapping_path = ROOT / "configs" / "runs" / "e02_selected8_water_n_mapping_20260818.csv"
    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")
    mapping["season_id"] = mapping["season_id"].astype(str)
    mapping["treatment"] = pd.to_numeric(mapping["treatment"], errors="raise").astype(int)
    registry["treatment"] = pd.to_numeric(registry["treatment"], errors="coerce").astype("Int64")
    registry = registry.merge(
        mapping[["season_id", "treatment", "nitrogen_level"]],
        on=["season_id", "treatment"], how="left", validate="many_to_one",
    )
    pst = pyemu.Pst(str(run / f"{case}.pst"))
    weights = pst.observation_data["weight"].astype(float)
    observed_all = pst.observation_data["obsval"].astype(float)
    out: list[dict[str, object]] = []
    for _, sim_row in sims.iterrows():
        realization = str(sim_row[real_col]).removesuffix(".0")
        sim_values = pd.Series({str(col).lower(): sim_row[col] for col in sims.columns[1:]})
        shared = observed_all.index.intersection(sim_values.index)
        residual = sim_values.loc[shared].astype(float) - observed_all.loc[shared]
        phi = float(np.square(residual * weights.loc[shared]).sum())
        metrics: dict[str, float] = {"phi": phi}
        dry = registry.loc[registry["obgnme"].astype(str).str.upper().eq("DRYNSE")]
        for season, group in dry.groupby("season_id"):
            keys = group["key"].tolist()
            metrics[f"dry_nse_{season}"] = nse(
                group["raw_obsval"].astype(float).to_numpy(), sim_values.loc[keys].astype(float).to_numpy()
            )
            terminal = group.assign(hno=group["obsnme"].str.extract(r"_H(\d+)$")[0].astype(int))
            terminal = terminal.loc[terminal["hno"].eq(terminal.groupby("treatment")["hno"].transform("max"))]
            tkeys = terminal["key"].tolist(); tobs = terminal["raw_obsval"].astype(float).to_numpy()
            metrics[f"terminal_pbias_{season}"] = float(100.0 * (sim_values.loc[tkeys].astype(float).to_numpy().sum() - tobs.sum()) / tobs.sum())
        water = registry.loc[registry["obgnme"].astype(str).str.upper().str.contains("WRESP")]
        for (season, nitrogen), group in water.groupby(["season_id", "nitrogen_level"]):
            keys = group["key"].tolist()
            metrics[f"w_nse_{season}_{nitrogen}"] = nse(
                group["raw_obsval"].astype(float).to_numpy(), sim_values.loc[keys].astype(float).to_numpy()
            )
        water_values = [value for name, value in metrics.items() if name.startswith("w_nse_")]
        metrics["w_nse_mean4"] = float(np.mean(water_values))
        out.append({"arm": arm, "case": case, "realization": realization, **metrics})
    return pd.DataFrame(out)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    metrics = pd.concat([_metrics(arm, case) for arm, case in CASES.items()], ignore_index=True)
    metrics.to_csv(OUT / "member_metrics.csv", index=False, encoding="utf-8-sig")
    baseline = metrics.loc[metrics["arm"].eq("A")].sort_values("phi").iloc[0]
    references = {season: float(baseline[f"dry_nse_{season}"]) for season in ("25SP", "26SP")}
    pbias_refs = {season: abs(float(baseline[f"terminal_pbias_{season}"])) for season in ("25SP", "26SP")}
    selections: list[dict[str, object]] = []
    for arm, group in metrics.groupby("arm", sort=True):
        group = group.copy()
        group["dry_gate"] = True
        group["scale_gate"] = True
        for season in ("25SP", "26SP"):
            group["dry_gate"] &= group[f"dry_nse_{season}"].ge(references[season] - 0.03)
            group["scale_gate"] &= group[f"terminal_pbias_{season}"].abs().le(pbias_refs[season] + 5.0)
        eligible = group.loc[group["dry_gate"] & group["scale_gate"]].copy()
        if arm == "A":
            chosen = group.sort_values("phi").iloc[0]
        elif eligible.empty:
            chosen = group.sort_values("w_nse_mean4", ascending=False).iloc[0]
        else:
            phi_cutoff = float(eligible["phi"].quantile(0.20))
            pool = eligible.loc[eligible["phi"].le(phi_cutoff)]
            chosen = pool.sort_values(["w_nse_mean4", "phi"], ascending=[False, True]).iloc[0]
        selections.append({
            **chosen.to_dict(), "eligible_count": int(len(eligible)),
            "advances": bool(arm != "A" and chosen["dry_gate"] and chosen["scale_gate"] and chosen["w_nse_mean4"] > baseline["w_nse_mean4"]),
        })
    selected = pd.DataFrame(selections)
    selected.to_csv(OUT / "arm_selection_summary.csv", index=False, encoding="utf-8-sig")
    recommendation = selected.sort_values(["advances", "w_nse_mean4"], ascending=[False, False]).iloc[0]
    report = {
        "baseline_reference": baseline.to_dict(),
        "gate": {
            "dry_cumulative_nse": "each season >= baseline best-Phi minus 0.03",
            "terminal_scale": "absolute PBIAS no more than 5 percentage points worse than baseline best-Phi",
            "selection": "within eligible lowest-phi 20%, maximize mean of four season x N water-response NSE values",
        },
        "recommended_arm": str(recommendation["arm"]),
        "recommended_realization": str(recommendation["realization"]),
        "advances": bool(recommendation["advances"]),
    }
    (OUT / "analysis_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=float) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
