"""Deterministic all-22 replay and post-run gate for the v46 N-yield arms.

The IES launcher intentionally stops before the scientific gate.  This script
selects the minimum-Phi member from the final IES iteration for each arm,
replays all 10 25SP and 12 26SP treatments with the same arm design, and
records the deterministic harvest/process metrics plus the mean (N2-N0,
N1-N0) nitrogen-response gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
# Analysis scripts are often launched from a replay directory; make the
# repository importable independently of the caller's working directory.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REPORT = ROOT / "workspace/reports/e02_v46_corrected_yield_multiarm_20260830"
OUT = REPORT / "deterministic_all22"
MAP = ROOT / "configs/runs/e02_mapping_25sp_w3w1_26sp_w2w1_n2n0_20260830.csv"
TREATMENTS = {"25SP": list(range(2, 15)), "26SP": list(range(1, 13))}
# The experiment has no TN=1,6,7,8 in 25SP and no TN=13,14 in 26SP.
TREATMENTS["25SP"] = [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]


def _metric(obs: pd.Series, sim: pd.Series, signed: bool = False) -> dict[str, float]:
    o = pd.to_numeric(obs, errors="coerce").to_numpy(float)
    s = pd.to_numeric(sim, errors="coerce").to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s)
    if not signed:
        ok &= (o > -90) & (s > -90)
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


def _response(h: pd.DataFrame, high: int, low: int) -> pd.DataFrame:
    cols = ["HNO", "OBS_FRESH_CUM", "SIM_FRESH_CUM"]
    hi = h.loc[h.TN.eq(high), cols].rename(columns={"OBS_FRESH_CUM": "obs_hi", "SIM_FRESH_CUM": "sim_hi"})
    lo = h.loc[h.TN.eq(low), cols].rename(columns={"OBS_FRESH_CUM": "obs_lo", "SIM_FRESH_CUM": "sim_lo"})
    out = hi.merge(lo, on="HNO", validate="one_to_one")
    out["observed"] = out.obs_hi - out.obs_lo
    out["simulated"] = out.sim_hi - out.sim_lo
    return out.sort_values("HNO")


def _gate(h: pd.DataFrame, season: str) -> dict[str, object]:
    mapping = pd.read_csv(MAP)
    mapping = mapping.loc[mapping.season_id.eq(season)].copy()
    terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1)
    terminal = terminal.merge(mapping[["treatment", "water_level", "nitrogen_level"]], left_on="TN", right_on="treatment", how="inner")
    recs = []
    for water, m in terminal.groupby("water_level"):
        by_n = {str(x): float(y) for x, y in zip(m.nitrogen_level, m.SIM_FRESH_CUM)}
        by_no = {str(x): float(y) for x, y in zip(m.nitrogen_level, m.OBS_FRESH_CUM)}
        if not {"N0", "N1", "N2"}.issubset(by_n):
            continue
        recs.append({
            "water": water,
            "obs_n2_n0": by_no["N2"] - by_no["N0"],
            "sim_n2_n0": by_n["N2"] - by_n["N0"],
            "obs_n1_n0": by_no["N1"] - by_no["N0"],
            "sim_n1_n0": by_n["N1"] - by_n["N0"],
        })
    if not recs:
        return {"n_strata": 0, "mean_abs_error": np.nan, "direction_pass": False}
    frame = pd.DataFrame(recs)
    obs = np.r_[frame.obs_n2_n0.to_numpy(float), frame.obs_n1_n0.to_numpy(float)]
    sim = np.r_[frame.sim_n2_n0.to_numpy(float), frame.sim_n1_n0.to_numpy(float)]
    return {
        "n_strata": int(len(frame)),
        "mean_observed": float(obs.mean()),
        "mean_simulated": float(sim.mean()),
        "mean_abs_error": float(np.abs(sim - obs).mean()),
        "mean_nse": _metric(pd.Series(obs), pd.Series(sim), signed=True)["nse"],
        "direction_pass": bool(np.all(frame[["sim_n2_n0", "sim_n1_n0"]].to_numpy(float) > 0)),
        "records": recs,
    }


def _replay(arm: str, arm_run: Path, member: str) -> Path:
    design_path = next((ROOT / "configs/runs").glob(f"e02_v46_arm_{arm}_*20260830.json"))
    design = json.loads(design_path.read_text(encoding="utf-8"))
    for season in design["seasons"]:
        season["treatments"] = TREATMENTS[season["season_id"]]
    design["diagnostic_only"] = {"25SP": [], "26SP": []}
    design["design_id"] = f"e02_v46_arm_{arm}_all22_deterministic_20260830"
    design["purpose"] = "postrun deterministic all-22 replay"
    case = f"e02_v46_arm_{arm}_20260830"
    par_file = arm_run / f"{case}.3.par.csv"
    par = pd.read_csv(par_file)
    par["real_name"] = par["real_name"].astype(str).str.replace(r"\.0$", "", regex=True)
    vals = par.set_index("real_name").loc[member]
    params = {str(k).upper(): float(v) for k, v in vals.items() if k != "real_name"}
    out = OUT / f"arm_{arm}_member_{member}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "design.json").write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    param_path = out / "params.csv"
    pd.DataFrame([{"name": k, "value": v} for k, v in params.items()]).to_csv(param_path, index=False)
    status = out / "multiseason_run_status.json"
    if not status.is_file():
        cmd = [sys.executable, str(ROOT / "src/calibration/run_multiseason.py"), "--design", str(out / "design.json"), "--param-csv", str(param_path), "--prefix", f"arm_{arm}_member_{member}", "--harvest-var", "CHFPW"]
        proc = subprocess.run(cmd, cwd=out, capture_output=True, text=True)
        (out / "run.stdout.log").write_text(proc.stdout, encoding="utf-8")
        (out / "run.stderr.log").write_text(proc.stderr, encoding="utf-8")
        if proc.returncode:
            raise RuntimeError(f"{arm} member {member} replay failed: {proc.returncode}")
    return out


def _analyze(out: Path, arm: str, member: str) -> dict[str, object]:
    from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare

    row: dict[str, object] = {"arm": arm, "member": member, "status": "success"}
    for season in ("25SP", "26SP"):
        sdir = out / "_seasons" / season
        filex = next(sdir.glob("*.TMX"))
        batch = sdir / "all22_analysis_batch.v48"
        batch.write_text("\n".join(f"{filex.resolve()} {tn} 1 0 0 0" for tn in TREATMENTS[season]) + "\n", encoding="utf-8")
        deterministic_harvest_compare(season, str(batch), run_dir=str(sdir))
        deterministic_process_compare(season, str(batch), var_names=["LAID", "LWAD", "SWAD"], run_dir=str(sdir))
        h = pd.read_csv(sdir / f"{season}_deterministic_harvest_compare.csv")
        p = pd.read_csv(sdir / f"{season}_deterministic_process_compare.csv")
        terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1)
        hm = _metric(terminal.OBS_FRESH_CUM, terminal.SIM_FRESH_CUM)
        cm = _metric(h.OBS_FRESH_CUM, h.SIM_FRESH_CUM)
        lm = _metric(p.OBS_LAID, p.SIM_LAID)
        row[f"{season}_terminal_rrmse_pct"] = hm["rrmse_pct"]
        row[f"{season}_terminal_pbias_pct"] = hm["pbias_pct"]
        row[f"{season}_fresh_cum_nse"] = cm["nse"]
        row[f"{season}_lai_nse"] = lm["nse"]
        gate = _gate(h, season)
        row[f"{season}_n_gate_mean_abs_error"] = gate["mean_abs_error"]
        row[f"{season}_n_gate_mean_nse"] = gate["mean_nse"]
        row[f"{season}_n_gate_direction_pass"] = gate["direction_pass"]
        row[f"{season}_n_gate_records"] = json.dumps(gate.get("records", []), ensure_ascii=False)
    row["gate_pass"] = bool(
        all(row.get(f"{s}_n_gate_direction_pass", False) for s in ("25SP", "26SP"))
        and all(float(row[f"{s}_terminal_rrmse_pct"]) <= 25.0 for s in ("25SP", "26SP"))
        and all(abs(float(row[f"{s}_terminal_pbias_pct"])) <= 15.0 for s in ("25SP", "26SP"))
        and all(float(row[f"{s}_fresh_cum_nse"]) >= 0.75 for s in ("25SP", "26SP"))
        and all(float(row[f"{s}_lai_nse"]) >= 0.60 for s in ("25SP", "26SP"))
    )
    return row


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for arm in ("c", "d", "e"):
        arm_run = next(ROOT.joinpath("workspace/runs").glob(f"e02_v46_arm_{arm}_*60x3_20260830"))
        phi = pd.read_csv(next(arm_run.glob("*.phi.actual.csv")))
        last = phi.loc[phi.iteration.eq(phi.iteration.max())]
        cols = [c for c in phi.columns if c.isdigit()]
        vals = pd.to_numeric(last.iloc[0][cols], errors="coerce")
        member = str(vals.idxmin())
        replay = _replay(arm, arm_run, member)
        rows.append(_analyze(replay, arm, member))
        pd.DataFrame(rows).to_csv(OUT / "all22_metrics.csv", index=False)
        print(f"{arm}: member {member} complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
