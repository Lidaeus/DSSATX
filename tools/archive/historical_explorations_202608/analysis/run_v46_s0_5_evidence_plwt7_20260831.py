"""Deterministic test of the historically documented common 26SP PLWT=7 g.

This is an isolated evidence-follow-up to S0-4.  Only the 26SP planting
record is changed in a scratch bundle; formal bundles, observations and
frozen bounds remain untouched.  The 25SP bundle is copied unchanged.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARAMS = ROOT / "workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/best_member_71_deterministic_20260831/best_member_71_params.csv"
B25 = ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830"
B26 = ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830"
MAP = ROOT / "configs/runs/e02_mapping_25sp_w3w1_26sp_w2w1_n2n0_20260830.csv"
OUT = ROOT / "workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_5_evidence_plwt7"


def _edit_26sp_plwt(path: Path, value: float = 7.0) -> int:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    changed = 0
    for i, raw in enumerate(lines):
        if raw.lstrip().startswith("2 ") and "26075" in raw and len(raw) >= 70:
            lines[i] = raw[:58] + f"{value:6.1f}" + raw[64:]
            changed += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def _nse(obs: pd.Series, sim: pd.Series) -> float:
    o = pd.to_numeric(obs, errors="coerce").to_numpy(float)
    s = pd.to_numeric(sim, errors="coerce").to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s) & (o > -90) & (s > -90)
    o, s = o[ok], s[ok]
    den = float(np.square(o - o.mean()).sum())
    return float(1 - np.square(s - o).sum() / den) if len(o) and den > 0 else float("nan")


def _evaluate(rd: Path) -> pd.DataFrame:
    import src.reporting.analyze_results as ar
    rows = []
    meta = pd.read_csv(MAP)
    for season in ("25SP", "26SP"):
        sd = rd / "_seasons" / season
        ar.WORKSPACE = str(sd)
        ar.deterministic_process_compare(season, str(sd / "DSSBatch.v48"), var_names=["LAID", "LWAD", "SWAD", "CHTD"], run_dir=str(sd))
        ar.deterministic_harvest_compare(season, str(sd / "DSSBatch.v48"), run_dir=str(sd))
        p = pd.read_csv(sd / f"{season}_deterministic_process_compare.csv")
        h = pd.read_csv(sd / f"{season}_deterministic_harvest_compare.csv")
        terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1)
        first = h[h["HNO"].eq(1)]
        m = meta[meta.season_id.eq(season)].set_index("treatment")
        t = terminal.merge(m[["water_level", "nitrogen_level"]], left_on="TN", right_index=True, how="left")
        contrasts = []
        for water, g in t.groupby("water_level"):
            byn = g.set_index("nitrogen_level")
            if "N0" not in byn.index:
                continue
            for lev in ("N1", "N2", "N3"):
                if lev in byn.index:
                    contrasts.append(float((byn.loc[lev, "SIM_FRESH_CUM"] - byn.loc["N0", "SIM_FRESH_CUM"]) - (byn.loc[lev, "OBS_FRESH_CUM"] - byn.loc["N0", "OBS_FRESH_CUM"])))
        rrmse = 100 * float(np.sqrt(np.mean((terminal.SIM_FRESH_CUM - terminal.OBS_FRESH_CUM) ** 2))) / float(np.mean(np.abs(terminal.OBS_FRESH_CUM)))
        rows.append({
            "season": season,
            "first_fresh_sim_range": float(np.ptp(first.SIM_FRESH_CUM)) if len(first) else np.nan,
            "first_fresh_obs_range": float(np.ptp(first.OBS_FRESH_CUM)) if len(first) else np.nan,
            "terminal_fresh_rrmse_pct": rrmse,
            "fresh_cum_nse": _nse(h.OBS_FRESH_CUM, h.SIM_FRESH_CUM),
            "lai_nse": _nse(p.OBS_LAID, p.SIM_LAID),
            "n_response_mae": float(np.mean(np.abs(contrasts))) if contrasts else np.nan,
        })
    return pd.DataFrame(rows)


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    b25, b26 = OUT / "exp25", OUT / "exp26"
    shutil.copytree(B25, b25)
    shutil.copytree(B26, b26)
    changed = _edit_26sp_plwt(next(b26.glob("*.TMX")), 7.0)
    design = {
        "schema_version": 1, "design_id": "S0_5_evidence_plwt7_26sp", "cultivar_identity": "TM0008",
        "shared_parameter_scope": "best71_s0_5", "bounds_id": "best71_deterministic",
        "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
        "group_policy": "configs/runs/e02_group_policy_v40_formal_fresh_3x_yield.csv",
        "nitrogen_response_objective": {"enabled": False}, "water_response_objective": {"enabled": False},
        "harvest_fresh_objective": {"enabled": False}, "process_state_objective": {"enabled": False},
        "seasons": [
            {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(b25), "role": "calibration", "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]},
            {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(b26), "role": "calibration", "treatments": list(range(1, 13))},
        ],
    }
    dp = OUT / "joint_design.json"
    dp.write_text(json.dumps(design, indent=2), encoding="utf-8")
    cmd = [sys.executable, str(ROOT / "src/calibration/run_multiseason.py"), "--design", str(dp), "--param-csv", str(PARAMS), "--prefix", "s0_5", "--harvest-var", "CHFPW", "--keep-nitrogen-outputs"]
    subprocess.run(cmd, cwd=OUT, check=True, encoding="cp1252", errors="replace")
    score = _evaluate(OUT)
    score.to_csv(OUT / "s0_5_scorecard.csv", index=False, encoding="utf-8-sig")
    (OUT / "s0_5_manifest.json").write_text(json.dumps({"anchor": str(PARAMS), "formal_bundle_25": str(B25), "formal_bundle_26": str(B26), "changed_26sp_planting_rows": changed, "plwt_g": 7.0}, indent=2), encoding="utf-8")
    print(score.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
