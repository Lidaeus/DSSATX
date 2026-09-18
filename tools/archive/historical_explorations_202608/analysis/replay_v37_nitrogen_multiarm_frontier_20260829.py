"""Deterministically replay the strongest N-response candidate from each arm.

The candidates are selected from the final IES iteration by maximum 26SP
N-response absolute-error reduction among members improving >=3 response
layers.  All 22 spring treatments are replayed with the official DSSAT build.
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

ANALYSIS = ROOT / "workspace/reports/e02_v37_n_response_multiarm_execution_20260829/postrun_analysis"
OUT = ANALYSIS / "deterministic_frontier_replays_fullanchor"
BASE_DESIGN = ROOT / "workspace/reports/e02_v37_n_response_multiarm_execution_20260829/p0_profiles/design.json"
BASE_PARAMS = (
    ROOT / "workspace/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829"
    / "best_member_137_two_season_deterministic_20260829/best_member_137_params.csv"
)
BASE_REPLAY = (
    ROOT / "workspace/reports/e02_v37_n_response_multiarm_execution_20260829"
    / "p0_profiles/baseline_i3_m137"
)
TREATMENTS = {"25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14], "26SP": list(range(1, 13))}
CALIBRATION = {"25SP": {2, 5, 10, 13}, "26SP": {1, 3, 9, 12}}
N_PAIRS = {"25SP": {"W3": (2, 5), "W1": (10, 13)}, "26SP": {"W3": (1, 9), "W1": (3, 12)}}
W_PAIRS = {"25SP": {"N3": (2, 10), "N0": (5, 13)}, "26SP": {"N3": (1, 3), "N0": (9, 12)}}


def metric(obs: pd.Series, sim: pd.Series, *, signed_response: bool = False) -> dict[str, float]:
    o = pd.to_numeric(obs, errors="coerce").to_numpy(float)
    s = pd.to_numeric(sim, errors="coerce").to_numpy(float)
    valid = np.isfinite(o) & np.isfinite(s)
    if not signed_response:
        valid &= (o > -90) & (s > -90)
    o, s = o[valid], s[valid]
    residual = s - o
    sst = float(np.square(o - o.mean()).sum())
    return {
        "n": len(o), "nse": 1 - float(np.square(residual).sum()) / sst if sst > 0 else np.nan,
        "rrmse_pct": 100 * float(np.sqrt(np.square(residual).mean())) / float(np.mean(np.abs(o))),
        "pbias_pct": 100 * float(residual.sum()) / float(o.sum()),
        "sae": float(np.abs(residual).sum()),
    }


def response_frame(harvest: pd.DataFrame, high: int, low: int) -> pd.DataFrame:
    columns = ["HNO", "OBS_FRESH_CUM", "SIM_FRESH_CUM"]
    h = harvest.loc[harvest["TN"].eq(high), columns].rename(
        columns={"OBS_FRESH_CUM": "obs_high", "SIM_FRESH_CUM": "sim_high"})
    l = harvest.loc[harvest["TN"].eq(low), columns].rename(
        columns={"OBS_FRESH_CUM": "obs_low", "SIM_FRESH_CUM": "sim_low"})
    joined = h.merge(l, on="HNO", validate="one_to_one").sort_values("HNO")
    joined["observed"] = joined["obs_high"] - joined["obs_low"]
    joined["simulated"] = joined["sim_high"] - joined["sim_low"]
    return joined


def analyze(case_dir: Path, arm: str, member: str) -> dict[str, object]:
    from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare

    result: dict[str, object] = {"arm": arm, "member": member}
    for season in ("25SP", "26SP"):
        season_dir = case_dir / "_seasons" / season
        filex = next(season_dir.glob("*.TMX"))
        batch = season_dir / "analysis_batch.v48"
        batch.write_text("\n".join(f"{filex.resolve()} {tn} 1 0 0 0" for tn in TREATMENTS[season]) + "\n",
                         encoding="utf-8")
        deterministic_harvest_compare(season, str(batch), run_dir=str(season_dir))
        deterministic_process_compare(season, str(batch), var_names=["LAID", "LWAD", "SWAD"], run_dir=str(season_dir))
        harvest = pd.read_csv(season_dir / f"{season}_deterministic_harvest_compare.csv")
        process = pd.read_csv(season_dir / f"{season}_deterministic_process_compare.csv")
        terminal = harvest.sort_values(["TN", "HNO"]).groupby("TN", as_index=False).tail(1)
        for role, treatments in (
            ("cal", CALIBRATION[season]),
            ("val", set(TREATMENTS[season]) - CALIBRATION[season]),
            ("all", set(TREATMENTS[season])),
        ):
            h = harvest.loc[harvest["TN"].isin(treatments)]
            t = terminal.loc[terminal["TN"].isin(treatments)]
            p = process.loc[process["TN"].isin(treatments)]
            result[f"{season}_{role}_fresh_cum_nse"] = metric(h["OBS_FRESH_CUM"], h["SIM_FRESH_CUM"])["nse"]
            tm = metric(t["OBS_FRESH_CUM"], t["SIM_FRESH_CUM"])
            result[f"{season}_{role}_terminal_rrmse_pct"] = tm["rrmse_pct"]
            result[f"{season}_{role}_terminal_pbias_pct"] = tm["pbias_pct"]
            result[f"{season}_{role}_lai_nse"] = metric(p["OBS_LAID"], p["SIM_LAID"])["nse"]
        for water, pair in N_PAIRS[season].items():
            frame = response_frame(harvest, *pair)
            m = metric(frame["observed"], frame["simulated"], signed_response=True)
            result[f"{season}_nresp_{water}_nse"] = m["nse"]
            result[f"{season}_nresp_{water}_sae"] = m["sae"]
            result[f"{season}_nresp_{water}_terminal_sim"] = float(frame.iloc[-1]["simulated"])
        for nitrogen, pair in W_PAIRS[season].items():
            frame = response_frame(harvest, *pair)
            result[f"{season}_wresp_{nitrogen}_nse"] = metric(
                frame["observed"], frame["simulated"], signed_response=True
            )["nse"]
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    audit = pd.read_csv(ANALYSIS / "all_iteration_candidate_metrics.csv")
    final = audit.loc[audit["iteration"].eq(3) & audit["nresp_layers_improved"].ge(3)].copy()
    frontier = final.sort_values("26SP_nresp_abs_error_reduction_pct", ascending=False).groupby("arm", as_index=False).head(1)
    design = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))
    design.update({"design_id": "e02_v37_nmulti_frontier_all22_replay_20260829",
                   "purpose": "independent all-22-treatment validation of final-iteration nitrogen-arm frontiers",
                   "custom_dssat_executable": str(ROOT / "DSCSM048.EXE")})
    design_path = OUT / "design.json"
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    anchor = pd.read_csv(BASE_PARAMS)
    anchor["name"] = anchor["name"].astype(str).str.upper()
    anchor_values = dict(zip(anchor["name"], pd.to_numeric(anchor["value"])))
    baseline_row = analyze(BASE_REPLAY, "BASE", "137")
    baseline_row["status"] = "success"
    rows = [baseline_row]
    for _, candidate in frontier.sort_values("arm").iterrows():
        arm, member = str(candidate["arm"]), str(candidate["member"])
        run = ROOT / f"workspace/runs/e02_v37_nmulti_arm_{arm.lower()}_60x3_20260829"
        case = f"e02_v37_nmulti_arm_{arm.lower()}_20260829"
        par = pd.read_csv(run / f"{case}.3.par.csv")
        par["real_name"] = par["real_name"].astype(str).str.replace(r"\.0$", "", regex=True)
        values = par.set_index("real_name").loc[member]
        case_dir = OUT / f"arm_{arm.lower()}_member_{member}"
        case_dir.mkdir(parents=True, exist_ok=True)
        params = case_dir / "params.csv"
        complete = dict(anchor_values)
        complete.update({str(name).upper(): float(value) for name, value in values.items()})
        pd.DataFrame([{"name": name, "value": value} for name, value in complete.items()]).to_csv(params, index=False)
        if not (case_dir / "multiseason_run_status.json").is_file():
            command = [sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                       "--design", str(design_path), "--param-csv", str(params),
                       "--prefix", f"arm_{arm.lower()}_member_{member}", "--harvest-var", "CHFPW"]
            completed = subprocess.run(command, cwd=case_dir, capture_output=True, text=True)
            (case_dir / "run.stdout.log").write_text(completed.stdout, encoding="utf-8")
            (case_dir / "run.stderr.log").write_text(completed.stderr, encoding="utf-8")
            if completed.returncode:
                rows.append({"arm": arm, "member": member, "status": "failed", "returncode": completed.returncode})
                continue
        row = analyze(case_dir, arm, member)
        row["status"] = "success"
        rows.append(row)
        pd.DataFrame(rows).to_csv(OUT / "all22_frontier_metrics.csv", index=False)
        print(f"{arm} member {member}: success", flush=True)
    frontier.to_csv(OUT / "frontier_selection.csv", index=False)
    return 0 if all(row["status"] == "success" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
