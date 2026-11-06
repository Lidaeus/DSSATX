"""Controlled 27-point nitrogen grid from the v46 best71 anchor.

Only RTNO3, FNPGN1 and FNPGN2 vary.  All other parameters, including water,
soil and source/sink parameters, remain the best71 deterministic vector.
"""

from __future__ import annotations

import hashlib
import json
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.profile_v46_best71_nitrogen_20260831 as profile
import tools.calibration.profile_n_parameters_determinstic as base

from src.common.input_manifest import verify_manifest_integrity

OUT = ROOT / "workspace/reports/e02_v46_best71_nitrogen_grid_20260831"
SCRATCH = OUT / "scratch_runs"
ANCHOR = profile.BASE / "best_member_71_params.csv"
DESIGN = profile.OUT / "design_all22.json"
BUNDLES = [
    ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830",
    ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830",
]
N_PAIRS = profile.N_PAIRS
W_PAIRS = {
    # Matches the formal all22 water-response contract: N0 and N3
    # strata only.  25SP uses W3-W1; 26SP uses W2-W1.
    "25SP": {"N0": (5, 13), "N3": (2, 10)},
    "26SP": {"N0": (11, 12), "N3": (2, 3)},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signed_metric(obs: pd.Series, sim: pd.Series) -> float:
    o = pd.to_numeric(obs, errors="coerce").to_numpy(float)
    s = pd.to_numeric(sim, errors="coerce").to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s)
    o, s = o[ok], s[ok]
    if len(o) < 2:
        return float("nan")
    sst = float(np.square(o - o.mean()).sum())
    return 1.0 - float(np.square(s - o).sum()) / sst if sst > 0 else float("nan")


def response_records(h: pd.DataFrame, season: str, pairs: dict[str, dict[str, tuple[int, int]]]) -> list[dict[str, object]]:
    terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1).set_index("TN")
    records = []
    for level, water_pairs in pairs.items():
        for water, (hi, lo) in water_pairs.items():
            if hi in terminal.index and lo in terminal.index:
                records.append({
                    "season": season, "level": level, "water": water,
                    "obs": float(terminal.loc[hi, "OBS_FRESH_CUM"] - terminal.loc[lo, "OBS_FRESH_CUM"]),
                    "sim": float(terminal.loc[hi, "SIM_FRESH_CUM"] - terminal.loc[lo, "SIM_FRESH_CUM"]),
                })
    return records


def water_records(h: pd.DataFrame, season: str) -> list[dict[str, object]]:
    terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1).set_index("TN")
    records = []
    for level, (hi, lo) in W_PAIRS[season].items():
        if hi in terminal.index and lo in terminal.index:
            records.append({
                "season": season, "level": level,
                "obs": float(terminal.loc[hi, "OBS_FRESH_CUM"] - terminal.loc[lo, "OBS_FRESH_CUM"]),
                "sim": float(terminal.loc[hi, "SIM_FRESH_CUM"] - terminal.loc[lo, "SIM_FRESH_CUM"]),
            })
    return records


def evaluate_case(case: str, changes: dict[str, float]) -> dict[str, object]:
    base._run_deterministic(changes, case)
    run = SCRATCH / case
    result: dict[str, object] = {"case": case, **{k: float(v) for k, v in changes.items()}, "status": "success"}
    n_records: list[dict[str, object]] = []
    w_records: list[dict[str, object]] = []
    for season in ("25SP", "26SP"):
        sdir = run / "_seasons" / season
        h = pd.read_csv(sdir / f"{season}_deterministic_harvest_compare.csv")
        p = pd.read_csv(sdir / f"{season}_deterministic_process_compare.csv")
        terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1)
        nrec = response_records(h, season, N_PAIRS[season])
        wrec = water_records(h, season)
        n_records.extend(nrec)
        w_records.extend(wrec)
        result[f"{season}_fresh_cum_nse"] = signed_metric(h["OBS_FRESH_CUM"], h["SIM_FRESH_CUM"])
        result[f"{season}_lai_nse"] = signed_metric(p["OBS_LAID"], p["SIM_LAID"])
        obs = terminal["OBS_FRESH_CUM"].to_numpy(float)
        sim = terminal["SIM_FRESH_CUM"].to_numpy(float)
        result[f"{season}_terminal_rrmse_pct"] = 100.0 * float(np.sqrt(np.mean(np.square(sim - obs)))) / float(np.mean(np.abs(obs)))
        result[f"{season}_terminal_pbias_pct"] = 100.0 * float(np.sum(sim - obs)) / float(np.sum(obs))
        result[f"{season}_n_mean_abs_error"] = float(np.mean([abs(float(x["sim"]) - float(x["obs"])) for x in nrec]))
        result[f"{season}_n_direction_pass"] = bool(
            all(np.mean([float(x["sim"]) for x in nrec if x["level"] == level]) > 0 for level in ("N1", "N2"))
        )
        result[f"{season}_w_response_nse"] = signed_metric(
            pd.Series([x["obs"] for x in wrec]), pd.Series([x["sim"] for x in wrec])
        )
    result["n_records_json"] = json.dumps(n_records, ensure_ascii=False)
    result["w_records_json"] = json.dumps(w_records, ensure_ascii=False)
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for bundle in BUNDLES:
        verify_manifest_integrity(bundle)
    if not ANCHOR.is_file() or not DESIGN.is_file():
        raise FileNotFoundError(f"missing anchor/design: {ANCHOR}, {DESIGN}")
    base.BASE_PARAMS_PATH = ANCHOR
    base.BASE_DESIGN_PATH = DESIGN
    base.SCRATCH_DIR = SCRATCH
    base.OUT_DIR = OUT

    rows: list[dict[str, object]] = []
    rows.append(evaluate_case("baseline_best71", {}))
    for rtno3, fn1, fn2 in product((0.025, 0.032, 0.040), (0.90, 1.00, 1.10), (4.15, 4.35, 4.50)):
        changes = {"RTNO3": rtno3, "FNPGN1": fn1, "FNPGN2": fn2}
        case = f"rtno3_{rtno3:.3f}_fnpgn1_{fn1:.2f}_fnpgn2_{fn2:.2f}"
        rows.append(evaluate_case(case, changes))
        pd.DataFrame(rows).to_csv(OUT / "grid_results.csv", index=False, encoding="utf-8-sig")
        print(f"[{len(rows):02d}/28] {case}", flush=True)

    df = pd.DataFrame(rows)
    baseline = df.iloc[0]
    for season in ("25SP", "26SP"):
        df[f"{season}_n_error_reduction_pct"] = 100.0 * (float(baseline[f"{season}_n_mean_abs_error"]) - df[f"{season}_n_mean_abs_error"].astype(float)) / float(baseline[f"{season}_n_mean_abs_error"])
    base_records = {(
        rec["season"], rec["level"], rec["water"]): abs(float(rec["sim"]) - float(rec["obs"]))
        for rec in json.loads(baseline["n_records_json"])
    }
    improvements = []
    for _, row in df.iterrows():
        improvements.append(sum(
            abs(float(rec["sim"]) - float(rec["obs"])) < base_records[(rec["season"], rec["level"], rec["water"])]
            for rec in json.loads(row["n_records_json"])
            if (rec["season"], rec["level"], rec["water"]) in base_records
        ))
    df["n_response_layers_improved_vs_baseline"] = improvements
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
    )
    df["grid_gate_pass"] = (
        df["25SP_n_direction_pass"].astype(bool)
        & df["26SP_n_error_reduction_pct"].astype(float).ge(30.0)
        & df["n_response_layers_improved_vs_baseline"].astype(int).ge(3)
        & df["yield_guard_pass"]
        & df["protected_fit_pass"]
    )
    df.to_csv(OUT / "grid_results.csv", index=False, encoding="utf-8-sig")
    manifest = {
        "grid_id": "e02_v46_best71_nitrogen_grid_20260831",
        "anchor": str(ANCHOR), "anchor_sha256": sha256(ANCHOR),
        "design": str(DESIGN), "design_sha256": sha256(DESIGN),
        "bundle_manifests": {bundle.name: sha256(bundle / "input_manifest.json") for bundle in BUNDLES},
        "points": 27, "fixed_scope": "best71 except RTNO3/FNPGN1/FNPGN2",
        "gate": "25SP N1/N2 means positive; 26SP N error reduction >=30%; >=3 layers; yield/LAI/W protected",
    }
    (OUT / "grid_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(df[["case", "25SP_n_mean_abs_error", "26SP_n_mean_abs_error", "26SP_n_error_reduction_pct", "n_response_layers_improved_vs_baseline", "grid_gate_pass"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
