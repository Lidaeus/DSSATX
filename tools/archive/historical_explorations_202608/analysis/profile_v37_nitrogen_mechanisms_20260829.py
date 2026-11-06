"""Deterministic P0 profiles for the v37 nitrogen-response follow-up.

The anchor is explicitly iteration 3, realization 137 from v37.  No candidate
selector is consulted.  Each case changes only the named nitrogen parameter(s)
and replays all 22 spring treatments with the official DSSAT executable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUN = ROOT / "workspace/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829"
ANCHOR = RUN / "best_member_137_two_season_deterministic_20260829"
BASE_PARAMS = ANCHOR / "best_member_137_params.csv"
BASE_DESIGN = ANCHOR / "design.json"
OUT = ROOT / "workspace/reports/e02_v37_n_response_multiarm_execution_20260829/p0_profiles"
MAPPING = ROOT / "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv"

PROFILES = {
    "NSTFAC": [0.30, 0.42, 0.55, 0.70],
    "RTNO3": [0.025, 0.035, 0.041, 0.046, 0.050],
    "NMOBMX": [0.25, 0.35, 0.45, 0.544, 0.60],
    "PROLFI": [0.21, 0.23, 0.25, 0.27],
}
FNPGN_GRID = list(product([0.45, 0.55, 0.70], [3.25, 3.55, 3.95]))
TREATMENTS = {"25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14], "26SP": list(range(1, 13))}
CALIBRATION = {"25SP": [2, 5, 10, 13], "26SP": [1, 3, 9, 12]}
N_PAIRS = {
    "25SP": {"W3": (2, 5), "W1": (10, 13)},
    "26SP": {"W3": (1, 9), "W1": (3, 12)},
}
W_PAIRS = {
    "25SP": {"N3": (2, 10), "N0": (5, 13)},
    "26SP": {"N3": (1, 3), "N0": (9, 12)},
}


def metric(obs: pd.Series, sim: pd.Series) -> dict[str, float]:
    valid = obs.notna() & sim.notna() & obs.gt(-90) & sim.gt(-90)
    o = obs.loc[valid].to_numpy(float)
    s = sim.loc[valid].to_numpy(float)
    if not len(o):
        return {"n": 0, "nse": np.nan, "rrmse_pct": np.nan, "pbias_pct": np.nan}
    error = s - o
    sst = float(np.square(o - o.mean()).sum())
    return {
        "n": int(len(o)),
        "nse": 1.0 - float(np.square(error).sum()) / sst if sst > 0 else np.nan,
        "rrmse_pct": 100.0 * float(np.sqrt(np.square(error).mean())) / float(np.mean(np.abs(o))),
        "pbias_pct": 100.0 * float(error.sum()) / float(o.sum()),
    }


def response_frame(harvest: pd.DataFrame, high_tn: int, low_tn: int) -> pd.DataFrame:
    columns = ["HNO", "OBS_FRESH_CUM", "SIM_FRESH_CUM"]
    high = harvest.loc[harvest["TN"].eq(high_tn), columns].rename(
        columns={"OBS_FRESH_CUM": "obs_high", "SIM_FRESH_CUM": "sim_high"}
    )
    low = harvest.loc[harvest["TN"].eq(low_tn), columns].rename(
        columns={"OBS_FRESH_CUM": "obs_low", "SIM_FRESH_CUM": "sim_low"}
    )
    joined = high.merge(low, on="HNO", how="inner", validate="one_to_one").sort_values("HNO")
    joined["observed"] = joined["obs_high"] - joined["obs_low"]
    joined["simulated"] = joined["sim_high"] - joined["sim_low"]
    return joined


def analyze(case_dir: Path, case_id: str, parameter: str, value: str) -> dict[str, object]:
    from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare

    result: dict[str, object] = {"case_id": case_id, "parameter": parameter, "value": value}
    for season in ("25SP", "26SP"):
        season_dir = case_dir / "_seasons" / season
        filex = next(season_dir.glob("*.TMX"))
        batch = season_dir / "analysis_batch.v48"
        batch.write_text(
            "\n".join(f"{filex.resolve()} {tn} 1 0 0 0" for tn in TREATMENTS[season]) + "\n",
            encoding="utf-8",
        )
        deterministic_harvest_compare(season, str(batch), run_dir=str(season_dir))
        deterministic_process_compare(season, str(batch), var_names=["LAID", "LWAD", "SWAD"], run_dir=str(season_dir))
        harvest = pd.read_csv(season_dir / f"{season}_deterministic_harvest_compare.csv")
        process_df = pd.read_csv(season_dir / f"{season}_deterministic_process_compare.csv")

        cumulative = metric(harvest["OBS_FRESH_CUM"], harvest["SIM_FRESH_CUM"])
        lai = metric(process_df["OBS_LAID"], process_df["SIM_LAID"])
        result[f"{season}_fresh_cum_nse"] = cumulative["nse"]
        result[f"{season}_lai_nse"] = lai["nse"]

        terminal = harvest.sort_values(["TN", "HNO"]).groupby("TN", as_index=False).tail(1)
        terminal_cal = terminal.loc[terminal["TN"].isin(CALIBRATION[season])]
        terminal_metric = metric(terminal_cal["OBS_FRESH_CUM"], terminal_cal["SIM_FRESH_CUM"])
        result[f"{season}_cal_terminal_rrmse_pct"] = terminal_metric["rrmse_pct"]
        result[f"{season}_cal_terminal_pbias_pct"] = terminal_metric["pbias_pct"]

        for water, (high, low) in N_PAIRS[season].items():
            frame = response_frame(harvest, high, low)
            m = metric(frame["observed"], frame["simulated"])
            result[f"{season}_nresp_{water}_nse"] = m["nse"]
            result[f"{season}_nresp_{water}_terminal_obs"] = float(frame.iloc[-1]["observed"])
            result[f"{season}_nresp_{water}_terminal_sim"] = float(frame.iloc[-1]["simulated"])
            result[f"{season}_nresp_{water}_terminal_abs_error"] = float(
                abs(frame.iloc[-1]["simulated"] - frame.iloc[-1]["observed"])
            )

        for nitrogen, (high, low) in W_PAIRS[season].items():
            frame = response_frame(harvest, high, low)
            result[f"{season}_wresp_{nitrogen}_nse"] = metric(frame["observed"], frame["simulated"])["nse"]
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    params = pd.read_csv(BASE_PARAMS)
    params["name"] = params["name"].astype(str).str.upper()
    base_values = dict(zip(params["name"], pd.to_numeric(params["value"])))

    design = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))
    design.update(
        {
            "design_id": "e02_v37_nitrogen_p0_profiles_20260829",
            "purpose": "explicit iteration-3 member-137 nitrogen mechanism profiles; all 22 treatments",
            "custom_dssat_executable": str(ROOT / "DSCSM048.EXE"),
        }
    )
    design_path = OUT / "design.json"
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    experiments: list[tuple[str, str, str, dict[str, float]]] = [
        ("baseline_i3_m137", "BASELINE", "member137_iteration3", {})
    ]
    for parameter, values in PROFILES.items():
        for value in values:
            token = str(value).replace(".", "p")
            experiments.append((f"{parameter.lower()}_{token}", parameter, str(value), {parameter: value}))
    for first, second in FNPGN_GRID:
        case_id = f"fnpgn1_{str(first).replace('.', 'p')}_fnpgn2_{str(second).replace('.', 'p')}"
        experiments.append((case_id, "FNPGN1xFNPGN2", f"{first}|{second}", {"FNPGN1": first, "FNPGN2": second}))
    pd.DataFrame(
        [{"case_id": case, "parameter": parameter, "value": value, **changes}
         for case, parameter, value, changes in experiments]
    ).to_csv(OUT / "profile_plan.csv", index=False)

    rows: list[dict[str, object]] = []
    for index, (case_id, parameter, value, changes) in enumerate(experiments, start=1):
        case_dir = OUT / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        candidate = dict(base_values)
        candidate.update(changes)
        param_csv = case_dir / "params.csv"
        pd.DataFrame([{"name": name, "value": val} for name, val in candidate.items()]).to_csv(param_csv, index=False)
        status = case_dir / "multiseason_run_status.json"
        if not status.is_file():
            command = [
                sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                "--design", str(design_path), "--param-csv", str(param_csv),
                "--prefix", case_id, "--harvest-var", "CHFPW", "--keep-nitrogen-outputs",
            ]
            completed = subprocess.run(command, cwd=case_dir, capture_output=True, text=True)
            (case_dir / "run.stdout.log").write_text(completed.stdout, encoding="utf-8")
            (case_dir / "run.stderr.log").write_text(completed.stderr, encoding="utf-8")
            if completed.returncode != 0:
                rows.append({"case_id": case_id, "parameter": parameter, "value": value,
                             "status": "failed", "returncode": completed.returncode})
                pd.DataFrame(rows).to_csv(OUT / "profile_results.csv", index=False)
                print(f"[{index:02d}/{len(experiments):02d}] {case_id}: failed", flush=True)
                continue
        try:
            row = analyze(case_dir, case_id, parameter, value)
            row["status"] = "success"
        except Exception as exc:
            row = {"case_id": case_id, "parameter": parameter, "value": value,
                   "status": "analysis_failed", "error": repr(exc)}
        rows.append(row)
        pd.DataFrame(rows).to_csv(OUT / "profile_results.csv", index=False)
        print(f"[{index:02d}/{len(experiments):02d}] {case_id}: {row['status']}", flush=True)

    results = pd.DataFrame(rows)
    successful = results.loc[results["status"].eq("success")].copy()
    if successful.empty:
        return 1
    baseline = successful.loc[successful["parameter"].eq("BASELINE")].iloc[0]
    nse_cols = [column for column in successful if "_nresp_" in column and column.endswith("_nse")]
    n_abs_cols = [column for column in successful if column.endswith("_nresp_W3_terminal_abs_error") or column.endswith("_nresp_W1_terminal_abs_error")]
    w_cols = [column for column in successful if "_wresp_" in column and column.endswith("_nse")]
    successful["nresp_layers_improved"] = successful[nse_cols].gt(baseline[nse_cols]).sum(axis=1)
    successful["nresp_mean_delta"] = successful[nse_cols].sub(baseline[nse_cols]).mean(axis=1)
    successful["nresp_worst_delta"] = successful[nse_cols].sub(baseline[nse_cols]).min(axis=1)
    successful["nresp_terminal_abs_error_reduction_pct"] = 100.0 * (
        float(baseline[n_abs_cols].sum()) - successful[n_abs_cols].sum(axis=1)
    ) / float(baseline[n_abs_cols].sum())
    successful["wresp_worst_delta"] = successful[w_cols].sub(baseline[w_cols]).min(axis=1)
    successful["25SP_terminal_signs_positive"] = (
        successful["25SP_nresp_W3_terminal_sim"].gt(0)
        & successful["25SP_nresp_W1_terminal_sim"].gt(0)
    )
    successful["profile_screen_pass"] = (
        successful["nresp_layers_improved"].ge(3)
        & successful["nresp_worst_delta"].ge(-0.5)
        & successful["wresp_worst_delta"].ge(-0.3)
        & successful["25SP_fresh_cum_nse"].ge(float(baseline["25SP_fresh_cum_nse"]) - 0.03)
        & successful["26SP_fresh_cum_nse"].ge(float(baseline["26SP_fresh_cum_nse"]) - 0.03)
        & successful["25SP_lai_nse"].ge(float(baseline["25SP_lai_nse"]) - 0.03)
        & successful["26SP_lai_nse"].ge(float(baseline["26SP_lai_nse"]) - 0.03)
    )
    successful.sort_values(
        ["profile_screen_pass", "nresp_layers_improved", "nresp_mean_delta"],
        ascending=[False, False, False],
    ).to_csv(OUT / "profile_scorecard.csv", index=False)
    return 0 if len(successful) == len(experiments) else 1


if __name__ == "__main__":
    raise SystemExit(main())
