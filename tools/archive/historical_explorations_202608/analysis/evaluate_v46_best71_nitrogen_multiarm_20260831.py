"""Replay and gate the best members from the best71 nitrogen A--E arms."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.profile_v46_best71_nitrogen_20260831 as profile
import tools.calibration.profile_n_parameters_determinstic as base

RUN_ROOT = ROOT / "workspace/runs"
REPORT = ROOT / "workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831"
REPLAY = REPORT / "deterministic_replays"
TREATMENTS = {"25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14], "26SP": list(range(1, 13))}
N_PAIRS = profile.N_PAIRS
W_PAIRS = {
    # Matches the formal all22 water-response contract: N0 and N3
    # strata only.  25SP uses W3-W1; 26SP uses W2-W1.
    "25SP": {"N0": (5, 13), "N3": (2, 10)},
    "26SP": {"N0": (11, 12), "N3": (2, 3)},
}


def metric(obs: pd.Series, sim: pd.Series) -> dict[str, float]:
    o = pd.to_numeric(obs, errors="coerce").to_numpy(float)
    s = pd.to_numeric(sim, errors="coerce").to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s) & (o > -90) & (s > -90)
    o, s = o[ok], s[ok]
    if len(o) == 0:
        return {"n": 0, "nse": np.nan, "rrmse_pct": np.nan, "pbias_pct": np.nan}
    err = s - o
    sst = float(np.square(o - o.mean()).sum())
    return {
        "n": int(len(o)),
        "nse": 1.0 - float(np.square(err).sum()) / sst if sst > 0 else np.nan,
        "rrmse_pct": 100.0 * float(np.sqrt(np.square(err).mean())) / float(np.mean(np.abs(o))) if np.mean(np.abs(o)) else np.nan,
        "pbias_pct": 100.0 * float(err.sum()) / float(o.sum()) if o.sum() else np.nan,
    }


def response_metric(obs: pd.Series, sim: pd.Series) -> dict[str, float]:
    """Metric for signed response differences; negative values are valid."""
    o = pd.to_numeric(obs, errors="coerce").to_numpy(float)
    s = pd.to_numeric(sim, errors="coerce").to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s)
    o, s = o[ok], s[ok]
    if len(o) == 0:
        return {"n": 0, "nse": np.nan, "rrmse_pct": np.nan, "pbias_pct": np.nan}
    err = s - o
    sst = float(np.square(o - o.mean()).sum())
    return {
        "n": int(len(o)),
        "nse": 1.0 - float(np.square(err).sum()) / sst if sst > 0 else np.nan,
        "rrmse_pct": np.nan,
        "pbias_pct": np.nan,
    }


def n_gate(h: pd.DataFrame, season: str) -> dict[str, object]:
    terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1).set_index("TN")
    records: list[dict[str, object]] = []
    for level, pairs in N_PAIRS[season].items():
        for water, (hi, lo) in pairs.items():
            if hi not in terminal.index or lo not in terminal.index:
                continue
            records.append({
                "season": season, "level": level, "water": water,
                "obs": float(terminal.loc[hi, "OBS_FRESH_CUM"] - terminal.loc[lo, "OBS_FRESH_CUM"]),
                "sim": float(terminal.loc[hi, "SIM_FRESH_CUM"] - terminal.loc[lo, "SIM_FRESH_CUM"]),
            })
    if not records:
        return {"records": [], "mean_obs": np.nan, "mean_sim": np.nan,
                "mean_abs_error": np.nan, "n2_mean_sim": np.nan,
                "n1_mean_sim": np.nan, "direction_pass": False}
    frame = pd.DataFrame(records)
    means = frame.groupby("level")["sim"].mean().to_dict()
    return {
        "records": records,
        "mean_obs": float(frame["obs"].mean()),
        "mean_sim": float(frame["sim"].mean()),
        "mean_abs_error": float(np.abs(frame["sim"] - frame["obs"]).mean()),
        "n2_mean_sim": float(means.get("N2", np.nan)),
        "n1_mean_sim": float(means.get("N1", np.nan)),
        "direction_pass": bool(float(means.get("N2", np.nan)) > 0 and float(means.get("N1", np.nan)) > 0),
    }


def w_response(h: pd.DataFrame, season: str) -> dict[str, object]:
    terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1).set_index("TN")
    records: list[dict[str, object]] = []
    for level, (hi, lo) in W_PAIRS[season].items():
        if hi not in terminal.index or lo not in terminal.index:
            continue
        records.append({
            "season": season, "level": level,
            "obs": float(terminal.loc[hi, "OBS_FRESH_CUM"] - terminal.loc[lo, "OBS_FRESH_CUM"]),
            "sim": float(terminal.loc[hi, "SIM_FRESH_CUM"] - terminal.loc[lo, "SIM_FRESH_CUM"]),
        })
    if not records:
        return {"records": [], "nse": np.nan, "mean_abs_error": np.nan}
    frame = pd.DataFrame(records)
    m = response_metric(frame["obs"], frame["sim"])
    return {"records": records, "nse": m["nse"],
            "mean_abs_error": float(np.abs(frame["sim"] - frame["obs"]).mean())}


def choose_member(run_dir: Path, case: str) -> str:
    phi = pd.read_csv(run_dir / f"{case}.phi.actual.csv")
    last = phi.loc[phi["iteration"].eq(phi["iteration"].max())].iloc[0]
    cols = [c for c in phi.columns if str(c).isdigit()]
    values = pd.to_numeric(last[cols], errors="coerce")
    if values.isna().all():
        raise RuntimeError(f"{case}: no finite final-iteration Phi values")
    return str(values.idxmin())


def replay_arm(arm: str, row: pd.Series) -> dict[str, object]:
    case = f"e02_v46_best71_n_{arm}_20260831"
    run_id = f"e02_v46_best71_n_{arm}_{row['label']}_60x3_20260831"
    run_dir = RUN_ROOT / run_id
    member = choose_member(run_dir, case)
    par = pd.read_csv(run_dir / f"{case}.3.par.csv")
    par["real_name"] = par["real_name"].astype(str).str.replace(r"\.0$", "", regex=True)
    if member not in set(par["real_name"]):
        raise RuntimeError(f"{case}: member {member} absent from final parameter ensemble")
    vals = par.set_index("real_name").loc[member]
    params = {str(k).upper(): float(v) for k, v in vals.items() if k != "real_name"}

    replay_id = f"arm_{arm}_member_{member}"
    base.SCRATCH_DIR = REPLAY
    base.BASE_PARAMS_PATH = profile.BASE / "best_member_71_params.csv"
    base.BASE_DESIGN_PATH = profile.OUT / "design_all22.json"
    REPLAY.mkdir(parents=True, exist_ok=True)
    base._run_deterministic(params, replay_id)
    out = REPLAY / replay_id

    result: dict[str, object] = {"arm": arm, "label": str(row["label"]), "member": member,
                                 "run_id": run_id, "status": "success"}
    for season in ("25SP", "26SP"):
        sdir = out / "_seasons" / season
        h = pd.read_csv(sdir / f"{season}_deterministic_harvest_compare.csv")
        p = pd.read_csv(sdir / f"{season}_deterministic_process_compare.csv")
        terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1)
        hm = metric(terminal["OBS_FRESH_CUM"], terminal["SIM_FRESH_CUM"])
        cm = metric(h["OBS_FRESH_CUM"], h["SIM_FRESH_CUM"])
        lm = metric(p["OBS_LAID"], p["SIM_LAID"])
        ng = n_gate(h, season)
        wg = w_response(h, season)
        result.update({
            f"{season}_terminal_rrmse_pct": hm["rrmse_pct"],
            f"{season}_terminal_pbias_pct": hm["pbias_pct"],
            f"{season}_fresh_cum_nse": cm["nse"],
            f"{season}_lai_nse": lm["nse"],
            f"{season}_n_mean_obs": ng["mean_obs"],
            f"{season}_n_mean_sim": ng["mean_sim"],
            f"{season}_n_mean_abs_error": ng["mean_abs_error"],
            f"{season}_n2_mean_sim": ng["n2_mean_sim"],
            f"{season}_n1_mean_sim": ng["n1_mean_sim"],
            f"{season}_n_direction_pass": ng["direction_pass"],
            f"{season}_n_records_json": json.dumps(ng["records"], ensure_ascii=False),
            f"{season}_w_response_nse": wg["nse"],
            f"{season}_w_response_mean_abs_error": wg["mean_abs_error"],
            f"{season}_w_records_json": json.dumps(wg["records"], ensure_ascii=False),
        })
    result["engineering_pass"] = bool((run_dir / "run_status.json").is_file())
    return result


def main() -> int:
    manifest = pd.read_csv(REPORT / "arm_configuration_manifest.csv", encoding="utf-8-sig")
    rows = []
    for _, row in manifest.sort_values("arm").iterrows():
        arm = str(row["arm"])
        item = replay_arm(arm, row)
        rows.append(item)
    df = pd.DataFrame(rows)
    if df.empty:
        return 1
    baseline = df.loc[df["arm"].eq("a")].iloc[0]
    base_records = {}
    for season in ("25SP", "26SP"):
        for rec in json.loads(baseline[f"{season}_n_records_json"]):
            base_records[(season, rec["level"], rec["water"])] = abs(float(rec["sim"]) - float(rec["obs"]))
    reductions = []
    for _, row in df.iterrows():
        improvements = 0
        for season in ("25SP", "26SP"):
            for rec in json.loads(row[f"{season}_n_records_json"]):
                key = (season, rec["level"], rec["water"])
                if key in base_records and abs(float(rec["sim"]) - float(rec["obs"])) < base_records[key]:
                    improvements += 1
        reductions.append(improvements)
    df["n_response_layers_improved_vs_A"] = reductions
    df["25SP_n_error_reduction_pct_vs_A"] = 100.0 * (float(baseline["25SP_n_mean_abs_error"]) - df["25SP_n_mean_abs_error"].astype(float)) / float(baseline["25SP_n_mean_abs_error"])
    df["26SP_n_error_reduction_pct_vs_A"] = 100.0 * (float(baseline["26SP_n_mean_abs_error"]) - df["26SP_n_mean_abs_error"].astype(float)) / float(baseline["26SP_n_mean_abs_error"])
    df["n_gate_pass"] = (
        df["25SP_n_direction_pass"].astype(bool)
        & (df["26SP_n_error_reduction_pct_vs_A"] >= 30.0)
        & (df["n_response_layers_improved_vs_A"] >= 3)
    )
    df["yield_guard_pass"] = (
        df["25SP_terminal_rrmse_pct"].astype(float).le(25.0)
        & df["26SP_terminal_rrmse_pct"].astype(float).le(25.0)
    )
    df["protected_fit_pass"] = (
        df["25SP_fresh_cum_nse"].astype(float).ge(float(baseline["25SP_fresh_cum_nse"]) - 0.05)
        & df["26SP_fresh_cum_nse"].astype(float).ge(float(baseline["26SP_fresh_cum_nse"]) - 0.05)
        & df["25SP_lai_nse"].astype(float).ge(float(baseline["25SP_lai_nse"]) - 0.05)
        & df["26SP_lai_nse"].astype(float).ge(float(baseline["26SP_lai_nse"]) - 0.05)
        & df["25SP_w_response_nse"].astype(float).ge(float(baseline["25SP_w_response_nse"]) - 0.05)
        & df["26SP_w_response_nse"].astype(float).ge(float(baseline["26SP_w_response_nse"]) - 0.05)
        & df["25SP_terminal_pbias_pct"].astype(float).abs().le(abs(float(baseline["25SP_terminal_pbias_pct"])) + 5.0)
        & df["26SP_terminal_pbias_pct"].astype(float).abs().le(abs(float(baseline["26SP_terminal_pbias_pct"])) + 5.0)
    )
    df["promotion_pass"] = df["engineering_pass"].astype(bool) & df["n_gate_pass"] & df["yield_guard_pass"] & df["protected_fit_pass"]
    df.to_csv(REPORT / "deterministic_candidate_metrics.csv", index=False, encoding="utf-8-sig")
    for _, row in df.iterrows():
        print(f"{row['arm']}: member {row['member']} replayed; promotion_pass={row['promotion_pass']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
