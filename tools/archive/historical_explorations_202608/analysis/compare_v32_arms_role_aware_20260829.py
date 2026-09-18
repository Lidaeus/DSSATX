"""Re-score recent v32 arms using the approved calibration/validation roles."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "workspace/reports/e02_v33_formal_design_review_20260829"
RUNS = {
    "post153": ("e02_formal_yield_rebalanced_post_official_200x6_20260829",
                "best_member_153_two_season_deterministic_20260829", 153),
    "v32_A": ("e02_multiarm_v32_arma_60x4_20260829",
              "best_member_9_two_season_deterministic_20260829", 9),
    "v32_B": ("e02_multiarm_v32_armb_60x4_20260829",
              "best_member_29_two_season_deterministic_20260829", 29),
    "v32_C": ("e02_multiarm_v32_armc_60x4_20260829",
              "best_member_5_two_season_deterministic_20260829", 5),
    "v32_D": ("e02_multiarm_v32_armd_60x4_20260829",
              "best_member_52_two_season_deterministic_20260829", 52),
    "champion41": ("e02_formal_final_champion_200x6_20260829",
                   "best_member_41_two_season_deterministic_20260829", 41),
}
CALIBRATION = {"25SP": {2, 5, 10, 13}, "26SP": {1, 3, 9, 12}}


def metric(obs: pd.Series, sim: pd.Series) -> dict[str, float]:
    valid = obs.notna() & sim.notna() & obs.gt(-90) & sim.gt(-90)
    o = obs.loc[valid].to_numpy(float)
    s = sim.loc[valid].to_numpy(float)
    residual = s - o
    sst = np.square(o - o.mean()).sum()
    return {
        "n": len(o),
        "rrmse_pct": 100 * np.sqrt(np.square(residual).mean()) / o.mean(),
        "pbias_pct": 100 * residual.sum() / o.sum(),
        "nse": 1 - np.square(residual).sum() / sst if sst > 0 else np.nan,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    parameter_rows = []
    for label, (run_id, det_name, member) in RUNS.items():
        det = ROOT / "workspace/runs" / run_id / det_name
        param_path = next(det.glob(f"best_member_{member}_params.csv"))
        params = pd.read_csv(param_path)
        params["name"] = params["name"].str.upper()
        for parameter in ["PGEFF", "TRIFL", "SFDUR", "WTFSD", "PARMAX", "PHTMAX",
                          "XFRMAX", "PORPT", "NRMIN", "NREXP", "RTNO3", "NMOBMX",
                          "NSTFAC", "CMOBMX", "LFMAX", "SLAVR", "SLAREF"]:
            selected = params.loc[params["name"].eq(parameter), "value"]
            if not selected.empty:
                parameter_rows.append({"candidate": label, "parameter": parameter,
                                       "value": float(selected.iloc[0])})
        row: dict[str, float | str] = {"candidate": label, "run_id": run_id, "member": member}
        for season in ("25SP", "26SP"):
            sdir = det / "_seasons" / season
            harvest = pd.read_csv(sdir / f"{season}_deterministic_harvest_compare.csv")
            process = pd.read_csv(sdir / f"{season}_deterministic_process_compare.csv")
            terminal = harvest.sort_values(["TN", "HNO"]).groupby("TN", as_index=False).tail(1)
            for role, treatments in (("cal", CALIBRATION[season]),
                                     ("val", set(terminal["TN"]) - CALIBRATION[season]),
                                     ("all", set(terminal["TN"]))):
                t = terminal.loc[terminal["TN"].isin(treatments)]
                tm = metric(t["OBS_DRY_CUM"], t["SIM_DRY_CUM"])
                row[f"{season}_{role}_terminal_rrmse_pct"] = tm["rrmse_pct"]
                row[f"{season}_{role}_terminal_pbias_pct"] = tm["pbias_pct"]
                h = harvest.loc[harvest["TN"].isin(treatments)]
                hm = metric(h["OBS_DRY_CUM"], h["SIM_DRY_CUM"])
                row[f"{season}_{role}_dry_cum_nse"] = hm["nse"]
                p = process.loc[process["TN"].isin(treatments)]
                for variable in ("LAID", "LWAD", "SWAD"):
                    pm = metric(p[f"OBS_{variable}"], p[f"SIM_{variable}"])
                    row[f"{season}_{role}_{variable.lower()}_nse"] = pm["nse"]
            if season == "26SP":
                for role, treatments in (("cal", CALIBRATION[season]),
                                         ("val", set(harvest["TN"]) - CALIBRATION[season])):
                    h3 = harvest.loc[harvest["TN"].isin(treatments) & harvest["HNO"].eq(3)]
                    row[f"26SP_{role}_h3_increment_bias"] = float(
                        (h3["SIM_DRY_INC"] - h3["OBS_DRY_INC"]).mean()
                    )
        rows.append(row)

    scorecard = pd.DataFrame(rows)
    scorecard.to_csv(OUT / "role_aware_candidate_scorecard.csv", index=False)
    parameters = pd.DataFrame(parameter_rows)
    parameters.to_csv(OUT / "candidate_parameter_values.csv", index=False)
    print(scorecard[[
        "candidate", "25SP_cal_terminal_rrmse_pct", "25SP_val_terminal_rrmse_pct",
        "26SP_cal_terminal_rrmse_pct", "26SP_val_terminal_rrmse_pct",
        "25SP_val_laid_nse", "26SP_val_laid_nse", "26SP_val_dry_cum_nse",
        "26SP_cal_h3_increment_bias", "26SP_val_h3_increment_bias",
    ]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
