"""Rerun and report the best final IES member for the four 0805 N-response builds.

The calibration outputs identify the final member by minimum finite phi.  This
script exports that member, reruns the 25SP six-treatment design with the
variant-specific DSSAT executable/SPE, and writes deterministic harvest/process
comparisons plus a compact yield/metric manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CASE_PREFIX = "e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260805_"
BUNDLE = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"
MAPPING = ROOT / "configs/runs/e02_v2_25sp_water_n_mapping_corrected_20260805.csv"
VARIANTS = {
    "a3_0805": ("windows/windows_a3_20260805/dscsm048_a3.exe", "windows/windows_a3_20260805/Genotype/TMGRO048.SPE"),
    "a4_0805": ("windows/windows_a4_20260805/dscsm048_a4.exe", "windows/windows_a4_20260805/Genotype/TMGRO048.SPE"),
    "a3_nr_zp_0805": ("windows/windows_a3_nr_zp_20260805/dscsm048_a3_nr_zp.exe", "windows/windows_a3_nr_zp_20260805/Genotype/TMGRO048.SPE"),
    "a4_nr_zp_0805": ("windows/windows_a4_nr_zp_20260805/dscsm048_a4_nr_zp.exe", "windows/windows_a4_nr_zp_20260805/Genotype/TMGRO048.SPE"),
}
TREATMENTS = [13, 12, 11, 5, 4, 3]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def best_member(run_dir: Path, case: str) -> tuple[str, float]:
    phi = pd.read_csv(run_dir / f"{case}.phi.actual.csv")
    final = phi.iloc[-1]
    # phi.actual has metadata columns followed by numeric realization columns
    # and a trailing base value.  Restrict to integer-named realizations.
    candidates = {}
    for col, val in final.items():
        if not re.fullmatch(r"\d+(?:\.0)?", str(col)):
            continue
        try:
            x = float(val)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):
            candidates[str(col).split(".")[0]] = x
    if not candidates:
        raise RuntimeError(f"no finite final realization phi in {run_dir}")
    member, value = min(candidates.items(), key=lambda kv: kv[1])
    return member, float(value)


def export_member(run_dir: Path, case: str, member: str, out_csv: Path) -> int:
    source = run_dir / f"{case}.4.par.csv"
    frame = pd.read_csv(source)
    real_col = "real_name" if "real_name" in frame.columns else frame.columns[0]
    mask = frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(member)
    if int(mask.sum()) != 1:
        raise RuntimeError(f"member {member} occurs {int(mask.sum())} times in {source}")
    row = frame.loc[mask].iloc[0]
    records = []
    for col in frame.columns:
        if col == real_col:
            continue
        value = float(row[col])
        if not math.isfinite(value):
            raise RuntimeError(f"non-finite best-member parameter {col}={value}")
        records.append({"name": str(col).upper(), "value": value})
    pd.DataFrame(records).to_csv(out_csv, index=False)
    return len(records)


def write_design(run_dir: Path, det_dir: Path, exe: Path, spe: Path) -> Path:
    payload = json.loads((run_dir / "six_treatment_design.json").read_text(encoding="utf-8"))
    payload["purpose"] = "best final member deterministic 25SP rerun"
    payload["custom_dssat_executable"] = str(exe.resolve())
    payload["custom_spe"] = str(spe.resolve())
    path = det_dir / "six_treatment_design.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_deterministic(det_dir: Path, design: Path, params: Path, case: str) -> None:
    cmd = [
        sys.executable,
        str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design),
        "--param-csv", str(params),
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
        "--prefix", "best_member_deterministic",
    ]
    transform_config = ROOT / f"workspace/runs/{case}/{case}.observation_transforms.json"
    if transform_config.is_file():
        cmd.extend(["--observation-transform-config", str(transform_config.resolve())])
    subprocess.run(cmd, cwd=det_dir, env=os.environ.copy(), check=True)


def compare_outputs(det_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare

    season_dir = det_dir / "_seasons" / "25SP"
    filex = season_dir / "XXQL2501.TMX"
    batch = season_dir / "analysis_batch.v48"
    batch.write_text("\n".join(f"{filex.resolve()} {tn} 1 0 0 0" for tn in TREATMENTS) + "\n", encoding="utf-8")
    deterministic_process_compare("best_member_deterministic", str(batch), var_names=["L#SD", "LAID", "LWAD", "SWAD", "CHTD"], run_dir=str(season_dir))
    deterministic_harvest_compare("best_member_deterministic", str(batch), run_dir=str(season_dir))
    harvest = pd.read_csv(season_dir / "best_member_deterministic_deterministic_harvest_compare.csv")
    process = pd.read_csv(season_dir / "best_member_deterministic_deterministic_process_compare.csv")
    return harvest, process


def metric(y: pd.Series, p: pd.Series) -> dict[str, float | int | None]:
    ok = np.isfinite(pd.to_numeric(y, errors="coerce")) & np.isfinite(pd.to_numeric(p, errors="coerce"))
    yv = pd.to_numeric(y, errors="coerce")[ok].to_numpy(float)
    pv = pd.to_numeric(p, errors="coerce")[ok].to_numpy(float)
    if not len(yv):
        return {"n": 0, "rmse": None, "mae": None, "bias": None, "nse": None, "d_index": None, "r2": None}
    err = pv - yv
    den = float(np.sum((yv - np.mean(yv)) ** 2))
    dden = float(np.sum((np.abs(pv - np.mean(yv)) + np.abs(yv - np.mean(yv))) ** 2))
    r2 = float(np.corrcoef(yv, pv)[0, 1] ** 2) if len(yv) > 1 and np.std(yv) > 0 and np.std(pv) > 0 else None
    return {
        "n": int(len(yv)), "rmse": float(np.sqrt(np.mean(err**2))),
        "mae": float(np.mean(np.abs(err))), "bias": float(np.mean(err)),
        "nse": float(1 - np.sum(err**2) / den) if den > 0 else None,
        "d_index": float(1 - np.sum(err**2) / dden) if dden > 0 else None, "r2": r2,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=sorted(VARIANTS), action="append")
    ap.add_argument("--reuse-rerun", action="store_true")
    ap.add_argument("--case-prefix", default=CASE_PREFIX)
    ap.add_argument("--report-out", type=Path, default=ROOT / "workspace/runs/n_response_variants_20260805_best_member_report.json")
    args = ap.parse_args()
    selected = args.variant or list(VARIANTS)
    mapping = pd.read_csv(MAPPING)
    all_payloads = []
    for variant in selected:
        case = args.case_prefix + variant
        run_dir = ROOT / "workspace/runs" / case
        exe = (ROOT / VARIANTS[variant][0]).resolve()
        spe = (ROOT / VARIANTS[variant][1]).resolve()
        member, phi = best_member(run_dir, case)
        det_dir = run_dir / f"best_member_{member}_deterministic_20260805"
        det_dir.mkdir(parents=True, exist_ok=True)
        params = det_dir / f"best_member_{member}_parameters.csv"
        n_params = export_member(run_dir, case, member, params)
        design = write_design(run_dir, det_dir, exe, spe)
        env = os.environ.copy()
        env.update({
            "DSSAT_CUSTOM_EXE": str(exe),
            "DSSAT_SPE_BASE": str(spe),
            "DSSAT_SOIL_BASE": str((BUNDLE / "SOIL.SOL").resolve()),
            "DSSAT_KEEP_RUNS": "1",
        })
        old_env = os.environ.copy()
        os.environ.update(env)
        try:
            status = det_dir / "multiseason_run_status.json"
            if not (args.reuse_rerun and status.is_file()):
                run_deterministic(det_dir, design, params, case)
            harvest, process = compare_outputs(det_dir)
        finally:
            os.environ.clear(); os.environ.update(old_env)

        # Last simulated cumulative dry/fresh yield at each observed harvest.
        yields = []
        for tn, group in harvest.groupby("TN", sort=True):
            group = group.sort_values("DATE")
            row = group.iloc[-1]
            m = mapping[mapping["treatment"].eq(int(tn))]
            label = "TN" + str(int(tn))
            if not m.empty:
                label = f"{m.iloc[0]['water_level']}{m.iloc[0]['nitrogen_level']}"
            yields.append({"treatment": int(tn), "label": label, "last_date": int(row["DATE"]), "sim_dry_cum": float(row["SIM_DRY_CUM"]), "sim_fresh_cum": float(row["SIM_FRESH_CUM"]), "obs_dry_cum": float(row["OBS_DRY_CUM"]), "obs_fresh_cum": float(row["OBS_FRESH_CUM"])})
        yields_df = pd.DataFrame(yields).sort_values("treatment")
        yields_df.to_csv(det_dir / "best_member_yields_by_treatment.csv", index=False)
        metrics = {
            "harvest_dry_cum": metric(harvest["OBS_DRY_CUM"], harvest["SIM_DRY_CUM"]),
            "harvest_fresh_cum": metric(harvest["OBS_FRESH_CUM"], harvest["SIM_FRESH_CUM"]),
        }
        pd.DataFrame([{ "scope": k, **v } for k, v in metrics.items()]).to_csv(det_dir / "best_member_deterministic_metrics.csv", index=False)
        payload = {"variant": variant, "case": case, "best_member": member, "best_phi": phi, "parameter_count": n_params, "exe": str(exe), "exe_sha256": sha256(exe), "spe": str(spe), "spe_sha256": sha256(spe), "deterministic_dir": str(det_dir), "metrics": metrics, "yields": yields}
        (det_dir / "best_member_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        all_payloads.append(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    args.report_out.resolve().write_text(json.dumps(all_payloads, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
